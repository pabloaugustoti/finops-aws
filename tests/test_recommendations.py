from datetime import UTC, datetime, timedelta
from decimal import Decimal

import boto3
import pytest
from botocore.stub import ANY, Stubber

from finops import pricing
from finops.cli import main
from finops.inventory import Address, Instance, Inventory, Snapshot, Volume, collect_region, parse_stop_time
from finops.recommendations import (
    analyze,
    rule_gp2_to_gp3,
    rule_idle_elastic_ip,
    rule_idle_instance,
    rule_missing_tags,
    rule_old_snapshot,
    rule_stopped_instance,
    rule_unattached_volume,
    savings_by_rule,
    total_savings,
)
from finops.sample_inventory import sample_inventory

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
TAGS = {"Project": "p", "Environment": "e"}
R = "us-east-1"


def ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


# ---------- preços ----------


def test_gp2_to_gp3_savings_small_volume():
    assert pricing.volume_monthly_cost("gp2", 100) == Decimal("10.00")
    assert pricing.gp3_equivalent_cost(100) == Decimal("8.00")


def test_large_gp2_needs_extra_iops_on_gp3():
    # gp2 de 2.000 GB entrega 6.000 IOPS; o gp3 precisa pagar 3.000 IOPS extras
    assert pricing.gp3_equivalent_cost(2000) == Decimal("160.00") + 3000 * pricing.GP3_IOPS_MONTH


def test_io1_includes_provisioned_iops():
    assert pricing.volume_monthly_cost("io1", 100, iops=1000) == Decimal("12.5") + Decimal("65")


# ---------- regras ----------


def test_gp2_rule_skips_unattached_and_long_stopped():
    inv = Inventory(
        "a",
        volumes=[
            Volume("vol-ok", R, 100, "gp2", "in-use", ago(10), "i-run"),
            Volume("vol-solto", R, 100, "gp2", "available", ago(10)),
            Volume("vol-parado", R, 100, "gp2", "in-use", ago(10), "i-stop"),
            Volume("vol-gp3", R, 100, "gp3", "in-use", ago(10), "i-run"),
        ],
        instances=[
            Instance("i-run", R, "t3.micro", "running", ago(30)),
            Instance("i-stop", R, "t3.micro", "stopped", ago(90), stopped_since=ago(30)),
        ],
    )
    recs = rule_gp2_to_gp3(inv, NOW)
    assert [r.resource_id for r in recs] == ["vol-ok"]
    assert recs[0].monthly_savings == Decimal("2.00")


def test_unattached_volume_severity_by_age():
    inv = Inventory(
        "a",
        volumes=[
            Volume("vol-velho", R, 10, "gp3", "available", ago(60)),
            Volume("vol-novo", R, 10, "gp3", "available", ago(2)),
        ],
    )
    severities = {r.resource_id: r.severity for r in rule_unattached_volume(inv, NOW)}
    assert severities == {"vol-velho": "alta", "vol-novo": "media"}


def test_idle_elastic_ip():
    inv = Inventory("a", addresses=[Address("eip-1", "1.1.1.1", R), Address("eip-2", "2.2.2.2", R, "assoc")])
    recs = rule_idle_elastic_ip(inv, NOW)
    assert [r.resource_id for r in recs] == ["eip-1"]
    assert recs[0].monthly_savings == Decimal("3.650")


def test_old_snapshot_orphan_and_shared_estimate():
    inv = Inventory(
        "a",
        volumes=[Volume("vol-1", R, 100, "gp3", "in-use", ago(300), "i-1")],
        snapshots=[
            Snapshot("snap-orfao", R, 100, ago(200), "vol-apagado"),
            Snapshot("snap-a", R, 100, ago(100), "vol-1"),
            Snapshot("snap-b", R, 100, ago(10), "vol-1"),  # recente: não é recomendado
        ],
    )
    recs = {r.resource_id: r for r in rule_old_snapshot(inv, NOW)}
    assert set(recs) == {"snap-orfao", "snap-a"}
    assert recs["snap-orfao"].severity == "media"
    assert recs["snap-orfao"].monthly_savings == Decimal("5.00")
    assert recs["snap-a"].monthly_savings == Decimal("1.000")  # 20% de 100 GB x 0,05


def test_stopped_instance_counts_attached_volumes():
    inv = Inventory(
        "a",
        instances=[
            Instance("i-velha", R, "t3.medium", "stopped", ago(200), stopped_since=ago(40), volume_ids=("vol-1",)),
            Instance("i-recente", R, "t3.medium", "stopped", ago(200), stopped_since=ago(2)),
        ],
        volumes=[Volume("vol-1", R, 50, "gp2", "in-use", ago(200), "i-velha")],
    )
    recs = rule_stopped_instance(inv, NOW)
    assert [r.resource_id for r in recs] == ["i-velha"]
    assert recs[0].monthly_savings == Decimal("5.00")


def test_idle_instance_thresholds():
    inv = Inventory(
        "a",
        instances=[
            Instance("i-ociosa", R, "m5.large", "running", ago(60), cpu_avg=1.0, cpu_max=4.0),
            Instance("i-pico", R, "m5.large", "running", ago(60), cpu_avg=1.0, cpu_max=50.0),
            Instance("i-nova", R, "m5.large", "running", ago(3), cpu_avg=1.0, cpu_max=2.0),
            Instance("i-sem-metrica", R, "m5.large", "running", ago(60)),
            Instance("i-tipo-raro", R, "x9.mega", "running", ago(60), cpu_avg=1.0, cpu_max=2.0),
        ],
    )
    recs = {r.resource_id: r for r in rule_idle_instance(inv, NOW)}
    assert set(recs) == {"i-ociosa", "i-tipo-raro"}
    assert recs["i-ociosa"].monthly_savings == Decimal("0.096") * 730 / 2
    assert recs["i-tipo-raro"].monthly_savings is None


def test_missing_tags_is_governance():
    inv = Inventory(
        "a",
        volumes=[
            Volume("vol-ok", R, 1, "gp3", "in-use", ago(1), tags=TAGS),
            Volume("vol-meia", R, 1, "gp3", "in-use", ago(1), tags={"Project": "p"}),
        ],
    )
    recs = rule_missing_tags(inv, NOW)
    assert [r.resource_id for r in recs] == ["vol-meia"]
    assert recs[0].category == "governança"
    assert "Environment" in recs[0].detail


def test_analyze_orders_by_savings_and_governance_last():
    recs = analyze([sample_inventory("producao", NOW)], NOW)
    savings = [r.monthly_savings for r in recs if r.monthly_savings is not None]
    assert savings == sorted(savings, reverse=True)
    first_governance = next(i for i, r in enumerate(recs) if r.monthly_savings is None)
    assert all(r.monthly_savings is None for r in recs[first_governance:])


def test_sample_inventory_triggers_every_rule():
    inventories = [sample_inventory(a, NOW) for a in ("producao", "desenvolvimento", "dados")]
    rules = {r.rule for r in analyze(inventories, NOW)}
    assert rules == {
        "ebs-gp2-para-gp3",
        "ebs-volume-solto",
        "eip-ocioso",
        "snapshot-antigo",
        "instancia-parada",
        "instancia-ociosa",
        "sem-tags",
    }
    recs = analyze(inventories, NOW)
    assert total_savings(recs) == sum(a for _, _, a in savings_by_rule([r for r in recs if r.monthly_savings]))


def test_empty_inventory_has_no_recommendations():
    assert analyze([Inventory("vazia")], NOW) == []


# ---------- coleta via API ----------


def test_scp_denied_region_is_reported_as_blocked_not_error():
    from finops.inventory import collect_inventory

    class DenyingClient:
        def get_paginator(self, _):
            raise Exception(
                "An error occurred (UnauthorizedOperation) ... with an explicit deny in a "
                "service control policy: arn:aws:organizations::1:policy/x"
            )

    class FakeSession:
        def client(self, service, region_name=None):
            return DenyingClient()

    inv = collect_inventory(FakeSession(), "conta", regions=["eu-west-1", "ap-south-1"])
    assert inv.blocked_regions == ["ap-south-1", "eu-west-1"]
    assert inv.errors == []


def test_parse_stop_time():
    assert parse_stop_time("User initiated (2026-10-01 12:30:00 GMT)") == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
    assert parse_stop_time("") is None


def test_collect_region_parses_api_responses():
    kwargs = {"region_name": R, "aws_access_key_id": "teste", "aws_secret_access_key": "teste"}
    ec2, cloudwatch = boto3.client("ec2", **kwargs), boto3.client("cloudwatch", **kwargs)
    with Stubber(ec2) as ec2_stub, Stubber(cloudwatch) as cw_stub:
        ec2_stub.add_response(
            "describe_volumes",
            {
                "Volumes": [
                    {
                        "VolumeId": "vol-1",
                        "Size": 100,
                        "VolumeType": "gp2",
                        "State": "in-use",
                        "CreateTime": ago(10),
                        "Iops": 300,
                        "Attachments": [{"InstanceId": "i-1"}],
                        "Tags": [{"Key": "Project", "Value": "p"}],
                    }
                ]
            },
            {},
        )
        ec2_stub.add_response(
            "describe_addresses",
            {
                "Addresses": [
                    {"AllocationId": "eipalloc-1", "PublicIp": "1.2.3.4"},
                ]
            },
            {},
        )
        ec2_stub.add_response(
            "describe_snapshots",
            {
                "Snapshots": [
                    {
                        "SnapshotId": "snap-1",
                        "VolumeSize": 100,
                        "StartTime": ago(200),
                        "VolumeId": "vol-x",
                    }
                ]
            },
            {"OwnerIds": ["self"]},
        )
        ec2_stub.add_response(
            "describe_instances",
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-1",
                                "InstanceType": "m5.large",
                                "State": {"Name": "running"},
                                "LaunchTime": ago(60),
                                "BlockDeviceMappings": [{"Ebs": {"VolumeId": "vol-1"}}],
                            },
                            {
                                "InstanceId": "i-2",
                                "InstanceType": "t3.micro",
                                "State": {"Name": "stopped"},
                                "LaunchTime": ago(90),
                                "StateTransitionReason": "User initiated (2026-09-01 08:00:00 GMT)",
                            },
                            {
                                "InstanceId": "i-3",
                                "InstanceType": "t3.micro",
                                "State": {"Name": "terminated"},
                                "LaunchTime": ago(5),
                            },
                        ]
                    }
                ]
            },
            {},
        )
        cw_stub.add_response(
            "get_metric_data",
            {
                "MetricDataResults": [
                    {"Id": "cpu0", "Values": [1.0, 2.0, 3.0]},
                ]
            },
            {"MetricDataQueries": ANY, "StartTime": ANY, "EndTime": ANY},
        )

        inv = collect_region(ec2, cloudwatch, R, "conta", NOW)

    assert inv.volumes[0].instance_id == "i-1"
    assert inv.volumes[0].tags == {"Project": "p"}
    assert inv.addresses[0].association_id is None
    assert inv.snapshots[0].volume_id == "vol-x"
    assert [i.id for i in inv.instances] == ["i-1", "i-2"]  # terminada é ignorada
    assert inv.instances[0].cpu_avg == pytest.approx(2.0)
    assert inv.instances[0].cpu_max == 3.0
    assert inv.instances[1].stopped_since == datetime(2026, 9, 1, 8, tzinfo=UTC)

    rules = {r.rule for r in analyze([inv], NOW)}
    assert {"eip-ocioso", "snapshot-antigo", "instancia-ociosa", "instancia-parada"} <= rules


def test_cli_recommendations(capsys, tmp_path):
    csv_path = tmp_path / "recs.csv"
    assert main(["recomendacoes", "--csv", str(csv_path)]) == 0
    out = capsys.readouterr().out
    assert "Economia potencial" in out
    assert "Por tipo:" in out
    assert csv_path.read_text(encoding="utf-8").startswith("severidade,economia_mensal_usd")
