from datetime import date, timedelta
from decimal import Decimal

import boto3
import pytest
from botocore.stub import Stubber

from finops.accounts import Account, ConfigError, load_accounts
from finops.aws_session import assume_role_session
from finops.cache import JsonCache
from finops.collector import collect
from finops.models import CostRecord
from finops.report import build_summary, render_text
from finops.sample_client import SampleCostExplorerClient

TODAY = date(2026, 11, 4)
NEXT_MONTH = date(2026, 12, 1)


# ---------- configuração ----------

def _write(tmp_path, text: str):
    path = tmp_path / "accounts.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_accounts(tmp_path):
    path = _write(tmp_path, """
[hub]
profile = "finops-lab"

[[accounts]]
name = "lab"
account_id = "111111111111"

[[accounts]]
name = "prod"
account_id = "222222222222"
role_name = "OutraRole"
external_id = "segredo"
""")
    config = load_accounts(path)
    assert config.hub_profile == "finops-lab"
    assert [a.name for a in config.accounts] == ["lab", "prod"]
    assert config.accounts[0].role_arn == "arn:aws:iam::111111111111:role/FinOpsReadOnly"
    assert config.accounts[1].external_id == "segredo"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[[accounts]]\nname="a"\naccount_id="111111111111"', "hub"),
        ('[hub]\nprofile="p"', "nenhuma conta"),
        ('[hub]\nprofile="p"\n[[accounts]]\nname="a"\naccount_id="123"', "12 dígitos"),
        ('[hub]\nprofile="p"\n[[accounts]]\nname="a"\naccount_id="111111111111"\n'
         '[[accounts]]\nname="a"\naccount_id="222222222222"', "mais de uma vez"),
        ("isto não é toml = = =", "TOML inválido"),
    ],
)
def test_invalid_config(tmp_path, body, message):
    with pytest.raises(ConfigError, match=message):
        load_accounts(_write(tmp_path, body))


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError, match="não encontrado"):
        load_accounts(tmp_path / "nao-existe.toml")


# ---------- AssumeRole ----------

def test_assume_role_sends_external_id_and_returns_temporary_session():
    sts = boto3.client("sts", region_name="us-east-1", aws_access_key_id="teste", aws_secret_access_key="teste")
    account = Account(name="prod", account_id="222222222222", external_id="segredo")
    with Stubber(sts) as stubber:
        stubber.add_response(
            "assume_role",
            {"Credentials": {
                "AccessKeyId": "ASIATESTE0000000000", "SecretAccessKey": "s" * 40,
                "SessionToken": "token", "Expiration": "2026-11-04T12:00:00Z",
            }},
            {"RoleArn": account.role_arn, "RoleSessionName": "finops-coletor",
             "DurationSeconds": 3600, "ExternalId": "segredo"},
        )
        session = assume_role_session(sts, account)
    credentials = session.get_credentials()
    assert credentials.access_key == "ASIATESTE0000000000"
    assert credentials.token == "token"


# ---------- coleta multi-conta ----------

def _sample_factory(name: str):
    if name == "quebrada":
        raise PermissionError("role FinOpsReadOnly não encontrada")
    scale = {"a": 1.0, "b": 0.5}[name]
    return SampleCostExplorerClient(today=TODAY, scale=scale, spike=False)


def test_collect_labels_records_by_account():
    result = collect(["a", "b"], _sample_factory, start=TODAY - timedelta(days=7), end=TODAY,
                     forecast_end=NEXT_MONTH)
    assert {r.account for r in result.records} == {"a", "b"}
    total_a = sum(r.amount for r in result.records if r.account == "a")
    total_b = sum(r.amount for r in result.records if r.account == "b")
    assert total_b < total_a
    assert result.forecast_amount is not None
    assert result.errors == []


def test_one_broken_account_does_not_stop_the_others():
    result = collect(["a", "quebrada"], _sample_factory, start=TODAY - timedelta(days=7), end=TODAY,
                     forecast_end=NEXT_MONTH)
    assert {r.account for r in result.records} == {"a"}
    assert len(result.errors) == 1
    assert result.errors[0].startswith("quebrada: PermissionError")


def test_cache_is_separated_per_account(tmp_path):
    cache = JsonCache(tmp_path)
    collect(["a", "b"], _sample_factory, start=TODAY - timedelta(days=3), end=TODAY,
            forecast_end=NEXT_MONTH, cache=cache)
    # 2 contas x (custos + previsão) = 4 respostas distintas no cache
    assert len(list(tmp_path.glob("*.json"))) == 4


def test_summary_and_report_by_account():
    records = [
        CostRecord(date(2026, 11, 2), "EC2", Decimal("30"), "USD", True, account="prod"),
        CostRecord(date(2026, 11, 2), "EC2", Decimal("10"), "USD", True, account="dev"),
        CostRecord(date(2026, 11, 3), "S3", Decimal("5"), "USD", True, account="dev"),
    ]
    summary = build_summary(records, today=TODAY, days=7, forecast_amount=None)
    assert summary.by_account == [("prod", Decimal("30")), ("dev", Decimal("15"))]

    text = render_text(summary, source="teste", warnings=["x: AccessDenied"])
    assert "Por conta:" in text
    assert "Contas com problema" in text and "x: AccessDenied" in text
