from datetime import date, timedelta
from decimal import Decimal

from finops.cli import main
from finops.cost_explorer import CostExplorer
from finops.models import CostRecord, Forecast
from finops.report import build_summary, fmt_usd, sparkline
from finops.sample_client import EC2_COMPUTE, SERVICES, SampleCostExplorerClient

TODAY = date(2026, 11, 4)


def test_sample_data_is_deterministic():
    a = SampleCostExplorerClient(TODAY).daily_cost(date(2026, 10, 20), "AWS Lambda")
    b = SampleCostExplorerClient(TODAY).daily_cost(date(2026, 10, 20), "AWS Lambda")
    assert a == b


def test_sample_data_has_ec2_spike():
    client = SampleCostExplorerClient(TODAY)
    spike = client.daily_cost(TODAY - timedelta(days=11), EC2_COMPUTE)
    normal = client.daily_cost(TODAY - timedelta(days=4), EC2_COMPUTE)
    assert spike > normal * 2


def test_sample_client_never_returns_future_days():
    explorer = CostExplorer(SampleCostExplorerClient(TODAY))
    records = explorer.costs_by_service(TODAY - timedelta(days=3), TODAY + timedelta(days=10))
    assert max(r.day for r in records) == TODAY - timedelta(days=1)
    assert len(records) == 3 * len(SERVICES)


def test_monthly_granularity_matches_daily_sum():
    explorer = CostExplorer(SampleCostExplorerClient(TODAY))
    start, end = date(2026, 9, 15), date(2026, 11, 1)
    daily = sum(r.amount for r in explorer.costs_by_service(start, end, "DAILY"))
    monthly = explorer.costs_by_service(start, end, "MONTHLY")
    assert {r.day for r in monthly} == {date(2026, 9, 15), date(2026, 10, 1)}
    assert sum(r.amount for r in monthly) == daily


def test_build_summary_totals():
    records = [
        CostRecord(date(2026, 10, 31), "A", Decimal("10"), "USD", False),
        CostRecord(date(2026, 11, 1), "A", Decimal("5"), "USD", True),
        CostRecord(date(2026, 11, 3), "B", Decimal("20"), "USD", True),
        CostRecord(date(2026, 10, 1), "C", Decimal("99"), "USD", False),  # fora da janela de 7 dias
    ]
    forecast = Forecast(TODAY, date(2026, 12, 1), Decimal("100"), "USD")
    summary = build_summary(records, today=TODAY, days=7, forecast=forecast)

    assert summary.total == Decimal("35")
    assert summary.by_service == [("B", Decimal("20")), ("A", Decimal("15"))]
    assert summary.month_to_date == Decimal("25")
    assert summary.month_forecast == Decimal("125")
    assert len(summary.daily) == 7
    assert summary.has_estimated


def test_build_summary_empty_account():
    summary = build_summary([], today=TODAY, days=30, forecast=None)
    assert summary.total == 0
    assert summary.by_service == []
    assert summary.month_forecast is None


def test_fmt_usd_brazilian_format():
    assert fmt_usd(Decimal("1234.5")) == "US$ 1.234,50"
    assert fmt_usd(Decimal("0")) == "US$ 0,00"


def test_sparkline():
    assert sparkline([Decimal(1), Decimal(1)]) == "▁▁"
    assert sparkline([Decimal(0), Decimal(10)]) == "▁█"


def test_cli_sample_summary(capsys, tmp_path):
    csv_path = tmp_path / "custos.csv"
    assert main(["resumo", "--fonte", "exemplo", "--dias", "30", "--csv", str(csv_path)], today=TODAY) == 0
    out = capsys.readouterr().out
    assert "Top serviços" in out
    assert EC2_COMPUTE in out
    assert "Previsão de fechamento .. US$" in out
    assert csv_path.read_text(encoding="utf-8").startswith("dia,servico,custo")


def test_cli_rejects_invalid_days(capsys):
    assert main(["resumo", "--dias", "0"], today=TODAY) == 2
