from datetime import date
from decimal import Decimal

import boto3
from botocore.stub import Stubber

from finops.budgets import Budget, fetch_budgets
from finops.cli import main
from finops.cost_explorer import CostExplorer
from finops.models import UNTAGGED
from finops.sources import build_source, load_budgets, run_collection, run_tags
from finops.web.api import budgets_payload, tags_payload

TODAY = date(2026, 11, 5)
D = Decimal


# ---------- orçamentos ----------


def budget(actual: str, forecast: str | None, limit: str = "100") -> Budget:
    return Budget("a", "b", D(limit), D(actual), D(forecast) if forecast else None)


def test_budget_status_levels():
    assert budget("10", "50").status == "ok"
    assert budget("10", "90").status == "atenção"  # previsão >= 85%
    assert budget("86", None).status == "atenção"  # gasto >= 85%
    assert budget("10", "120").status == "vai estourar"
    assert budget("100", "130").status == "estourado"


def test_budget_ratios():
    b = budget("25", "80")
    assert b.used == D("0.25")
    assert b.forecast_ratio == D("0.8")
    assert budget("1", None).forecast_ratio is None


class FakeSession:
    def __init__(self, clients):
        self.clients = clients

    def client(self, service, region_name=None):
        return self.clients[service]


def test_fetch_budgets_parses_api_and_skips_non_cost():
    kwargs = {"region_name": "us-east-1", "aws_access_key_id": "teste", "aws_secret_access_key": "teste"}
    sts, budgets_client = boto3.client("sts", **kwargs), boto3.client("budgets", **kwargs)
    with Stubber(sts) as sts_stub, Stubber(budgets_client) as budgets_stub:
        sts_stub.add_response(
            "get_caller_identity",
            {"Account": "111111111111", "Arn": "arn:aws:sts::111111111111:assumed-role/X/y", "UserId": "AROAX:y"},
        )
        budgets_stub.add_response(
            "describe_budgets",
            {
                "Budgets": [
                    {
                        "BudgetName": "mensal",
                        "BudgetType": "COST",
                        "TimeUnit": "MONTHLY",
                        "BudgetLimit": {"Amount": "5.0", "Unit": "USD"},
                        "CalculatedSpend": {
                            "ActualSpend": {"Amount": "1.5", "Unit": "USD"},
                            "ForecastedSpend": {"Amount": "4.6", "Unit": "USD"},
                        },
                    },
                    {
                        "BudgetName": "uso",
                        "BudgetType": "USAGE",
                        "TimeUnit": "MONTHLY",
                        "BudgetLimit": {"Amount": "10", "Unit": "GB"},
                    },
                ]
            },
            {"AccountId": "111111111111"},
        )
        result = fetch_budgets(FakeSession({"sts": sts, "budgets": budgets_client}), "lab")
    assert [b.name for b in result] == ["mensal"]
    assert result[0].actual == D("1.5")
    assert result[0].status == "atenção"  # previsão 4,6 de 5 = 92%


def test_sample_budgets_cover_all_statuses():
    result = load_budgets("exemplo", TODAY)
    assert {b.status for b in result.budgets} == {"ok", "atenção", "vai estourar"}
    payload = budgets_payload(result)
    assert payload["itens"][0]["situacao"] == "vai estourar"  # maior previsão primeiro


# ---------- custo por tag ----------


def test_costs_by_tag_maps_empty_value_to_untagged():
    client = boto3.client("ce", region_name="us-east-1", aws_access_key_id="teste", aws_secret_access_key="teste")
    with Stubber(client) as stub:
        stub.add_response(
            "get_cost_and_usage",
            {
                "ResultsByTime": [
                    {
                        "TimePeriod": {"Start": "2026-10-01", "End": "2026-11-01"},
                        "Groups": [
                            {"Keys": ["Project$loja"], "Metrics": {"UnblendedCost": {"Amount": "7", "Unit": "USD"}}},
                            {"Keys": ["Project$"], "Metrics": {"UnblendedCost": {"Amount": "3", "Unit": "USD"}}},
                        ],
                    }
                ]
            },
        )
        costs = CostExplorer(client, account="lab").costs_by_tag(date(2026, 10, 1), date(2026, 11, 1), "Project")
    assert {c.value: c.amount for c in costs} == {"loja": D("7"), UNTAGGED: D("3")}


def test_sample_tags_add_up_to_total_cost():
    source = build_source("exemplo", TODAY)
    tags = run_tags(source, TODAY, 30, "Project")
    window_start = date.fromordinal(TODAY.toordinal() - 30)
    total = sum(r.amount for r in run_collection(source, TODAY, 30).records if window_start <= r.day < TODAY)
    assert abs(sum(c.amount for c in tags.costs) - total) < D("0.05")


def test_tags_payload_coverage_and_account_filter():
    result = run_tags(build_source("exemplo", TODAY), TODAY, 30, "Environment")
    payload = tags_payload(result)
    assert 0.8 < payload["cobertura"] < 0.85
    dados = tags_payload(result, selected=["dados"])
    assert {v["nome"] for v in dados["valores"]} == {"producao", UNTAGGED}
    assert round(dados["cobertura"], 2) == 0.9


def test_cli_budgets_and_tags(capsys):
    assert main(["orcamentos"], today=TODAY) == 0
    out = capsys.readouterr().out
    assert "vai estourar" in out
    assert "dev-mensal" in out

    assert main(["tags", "--chave", "Project"], today=TODAY) == 0
    out = capsys.readouterr().out
    assert "Cobertura de tags: 82,4%" in out
