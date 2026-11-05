"""Inventário de recursos que geram custo (EC2, EBS, snapshots, IPs elásticos).

Usa só chamadas de leitura (Describe*/GetMetricData), cobertas pela role
FinOpsReadOnly. As chamadas Describe do EC2 não têm custo.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

REQUIRED_TAGS = ("Project", "Environment")
CPU_LOOKBACK_DAYS = 14
_STOP_TIME = re.compile(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)")


def _tags(raw: list[dict[str, str]] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in raw or []}


def parse_stop_time(reason: str | None) -> datetime | None:
    """Extrai a data de 'User initiated (2026-10-01 12:00:00 GMT)'."""
    match = _STOP_TIME.search(reason or "")
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


@dataclass(frozen=True)
class Volume:
    id: str
    region: str
    size_gb: int
    volume_type: str
    state: str  # "in-use" | "available" | ...
    created: datetime
    instance_id: str | None = None
    iops: int | None = None
    throughput: int | None = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Address:
    allocation_id: str
    public_ip: str
    region: str
    association_id: str | None = None
    instance_id: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Snapshot:
    id: str
    region: str
    size_gb: int
    created: datetime
    volume_id: str | None = None
    description: str = ""
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Instance:
    id: str
    region: str
    instance_type: str
    state: str  # "running" | "stopped" | ...
    launched: datetime
    stopped_since: datetime | None = None
    volume_ids: tuple[str, ...] = ()
    cpu_avg: float | None = None  # média de CPU (%) nos últimos 14 dias
    cpu_max: float | None = None  # maior média horária (%) nos últimos 14 dias
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class Inventory:
    account: str
    volumes: list[Volume] = field(default_factory=list)
    addresses: list[Address] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)
    instances: list[Instance] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    blocked_regions: list[str] = field(default_factory=list)  # negadas por SCP da organização
    errors: list[str] = field(default_factory=list)

    def merge(self, other: Inventory) -> None:
        self.volumes += other.volumes
        self.addresses += other.addresses
        self.snapshots += other.snapshots
        self.instances += other.instances
        self.regions += other.regions
        self.blocked_regions += other.blocked_regions
        self.errors += other.errors

    @property
    def resource_count(self) -> int:
        return len(self.volumes) + len(self.addresses) + len(self.snapshots) + len(self.instances)


def _paginate(client: Any, operation: str, key: str, **params: Any) -> list[dict]:
    items: list[dict] = []
    for page in client.get_paginator(operation).paginate(**params):
        items.extend(page.get(key, []))
    return items


def _cpu_stats(cloudwatch: Any, instance_ids: list[str], now: datetime) -> dict[str, tuple[float, float]]:
    """Média e máximo das médias horárias de CPU de cada instância (até 500 por chamada)."""
    stats: dict[str, tuple[float, float]] = {}
    for start in range(0, len(instance_ids), 500):
        batch = instance_ids[start : start + 500]
        queries = [
            {
                "Id": f"cpu{index}",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": "CPUUtilization",
                        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
                    },
                    "Period": 3600,
                    "Stat": "Average",
                },
                "ReturnData": True,
            }
            for index, instance_id in enumerate(batch)
        ]
        response = cloudwatch.get_metric_data(
            MetricDataQueries=queries,
            StartTime=now - timedelta(days=CPU_LOOKBACK_DAYS),
            EndTime=now,
        )
        for result in response.get("MetricDataResults", []):
            values = result.get("Values", [])
            if values:
                instance_id = batch[int(result["Id"][3:])]
                stats[instance_id] = (sum(values) / len(values), max(values))
    return stats


def collect_region(ec2: Any, cloudwatch: Any, region: str, account: str, now: datetime) -> Inventory:
    inventory = Inventory(account=account, regions=[region])

    for raw in _paginate(ec2, "describe_volumes", "Volumes"):
        attachments = raw.get("Attachments") or []
        inventory.volumes.append(
            Volume(
                id=raw["VolumeId"],
                region=region,
                size_gb=raw["Size"],
                volume_type=raw["VolumeType"],
                state=raw["State"],
                created=raw["CreateTime"],
                instance_id=attachments[0]["InstanceId"] if attachments else None,
                iops=raw.get("Iops"),
                throughput=raw.get("Throughput"),
                tags=_tags(raw.get("Tags")),
            )
        )

    for raw in ec2.describe_addresses().get("Addresses", []):
        inventory.addresses.append(
            Address(
                allocation_id=raw.get("AllocationId", raw["PublicIp"]),
                public_ip=raw["PublicIp"],
                region=region,
                association_id=raw.get("AssociationId"),
                instance_id=raw.get("InstanceId"),
                tags=_tags(raw.get("Tags")),
            )
        )

    for raw in _paginate(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"]):
        inventory.snapshots.append(
            Snapshot(
                id=raw["SnapshotId"],
                region=region,
                size_gb=raw["VolumeSize"],
                created=raw["StartTime"],
                volume_id=raw.get("VolumeId"),
                description=raw.get("Description", ""),
                tags=_tags(raw.get("Tags")),
            )
        )

    raw_instances = [i for r in _paginate(ec2, "describe_instances", "Reservations") for i in r.get("Instances", [])]
    running = [i["InstanceId"] for i in raw_instances if i["State"]["Name"] == "running"]
    cpu = _cpu_stats(cloudwatch, running, now) if running else {}
    for raw in raw_instances:
        state = raw["State"]["Name"]
        if state in ("terminated", "shutting-down"):
            continue
        avg_max = cpu.get(raw["InstanceId"])
        inventory.instances.append(
            Instance(
                id=raw["InstanceId"],
                region=region,
                instance_type=raw["InstanceType"],
                state=state,
                launched=raw["LaunchTime"],
                stopped_since=parse_stop_time(raw.get("StateTransitionReason")) if state == "stopped" else None,
                volume_ids=tuple(m["Ebs"]["VolumeId"] for m in raw.get("BlockDeviceMappings", []) if "Ebs" in m),
                cpu_avg=avg_max[0] if avg_max else None,
                cpu_max=avg_max[1] if avg_max else None,
                tags=_tags(raw.get("Tags")),
            )
        )
    return inventory


def enabled_regions(session: Any) -> list[str]:
    ec2 = session.client("ec2", region_name="us-east-1")
    return sorted(r["RegionName"] for r in ec2.describe_regions()["Regions"])


def collect_inventory(
    session: Any,
    account: str,
    regions: list[str] | None = None,
    max_workers: int = 8,
) -> Inventory:
    """Inventário de todas as regiões (ou só das informadas), em paralelo."""
    now = datetime.now(UTC)
    regions = regions or enabled_regions(session)
    # Sessões boto3 não são thread-safe; os clientes são. Criamos os clientes antes de paralelizar.
    clients = {r: (session.client("ec2", region_name=r), session.client("cloudwatch", region_name=r)) for r in regions}

    def scan(region: str) -> Inventory:
        ec2, cloudwatch = clients[region]
        try:
            return collect_region(ec2, cloudwatch, region, account, now)
        except Exception as error:  # noqa: BLE001 - uma região com problema não derruba as outras
            message = str(error).splitlines()[0]
            if is_scp_denial(message):
                return Inventory(account=account, blocked_regions=[region])
            return Inventory(account=account, errors=[f"{region}: {message}"])

    result = Inventory(account=account)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for partial in pool.map(scan, regions):
            result.merge(partial)
    result.regions.sort()
    result.blocked_regions.sort()
    return result


def is_scp_denial(message: str) -> bool:
    """Negação explícita por Service Control Policy: a organização proibiu a região/ação."""
    return "explicit deny in a service control policy" in message
