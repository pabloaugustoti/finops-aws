from datetime import date, timedelta
from decimal import Decimal

import pytest

pd = pytest.importorskip("pandas")

from finops.dashboard.data import (  # noqa: E402
    OTHER,
    daily_by_service,
    kpis,
    month_projection,
    records_frame,
    service_order,
    totals_by,
)
from finops.models import CostRecord  # noqa: E402
from finops.sources import build_source, collection_window, run_collection  # noqa: E402

TODAY = date(2026, 11, 4)


def rec(day: date, service: str, amount: str, account: str = "a") -> CostRecord:
    return CostRecord(day, service, Decimal(amount), "USD", False, account)


def test_records_frame_empty_has_columns():
    df = records_frame([])
    assert list(df.columns) == ["dia", "conta", "servico", "custo", "estimado"]
    assert df.empty


def test_service_order_folds_tail_into_other():
    records = [rec(TODAY - timedelta(days=1), f"S{i}", str(10 - i)) for i in range(8)]
    order = service_order(records_frame(records), top=3)
    assert order == ["S0", "S1", "S2", OTHER]


def test_daily_by_service_fills_missing_days_and_groups_other():
    records = [
        rec(TODAY - timedelta(days=1), "EC2", "5"),
        rec(TODAY - timedelta(days=1), "Pequeno", "1"),
        rec(TODAY - timedelta(days=3), "EC2", "2"),
    ]
    df = records_frame(records)
    daily = daily_by_service(df, ["EC2", OTHER], TODAY, days=3)
    assert len(daily) == 3 * 2  # 3 dias x 2 grupos, inclusive o dia sem custo
    assert daily["custo"].sum() == pytest.approx(8.0)
    other = daily[(daily["servico"] == OTHER)]["custo"].sum()
    assert other == pytest.approx(1.0)


def test_totals_by_share():
    df = records_frame([rec(TODAY, "A", "3", "x"), rec(TODAY, "B", "1", "y")])
    table = totals_by(df, "conta")
    assert list(table["conta"]) == ["x", "y"]
    assert table["participacao"].tolist() == pytest.approx([0.75, 0.25])


def test_kpis_week_change():
    records = [rec(TODAY - timedelta(days=d), "A", "2" if d <= 7 else "1") for d in range(1, 15)]
    k = kpis(records_frame(records), TODAY, days=14, forecast_amount=10.0)
    assert k.last_7 == pytest.approx(14.0)
    assert k.previous_7 == pytest.approx(7.0)
    assert k.week_change == pytest.approx(1.0)
    assert k.month_to_date == pytest.approx(6.0)  # dias 1, 2 e 3 de novembro
    assert k.month_forecast == pytest.approx(16.0)


def test_month_projection_ends_at_month_end():
    records = [rec(date(2026, 11, d), "A", "1") for d in (1, 2, 3)]
    projection = month_projection(records_frame(records), TODAY, forecast_amount=27.0)
    real = projection[projection["serie"] == "Real"]
    forecast = projection[projection["serie"] == "Previsão"]
    assert real["custo"].tolist() == [1.0, 2.0, 3.0]
    assert forecast["dia"].iloc[-1] == pd.Timestamp(2026, 11, 30)
    assert forecast["custo"].iloc[-1] == pytest.approx(30.0)


def test_month_projection_without_forecast():
    projection = month_projection(records_frame([]), TODAY, forecast_amount=None)
    assert set(projection["serie"]) == {"Real"}


def test_collection_window_covers_month_start():
    window = collection_window(date(2026, 11, 20), days=7)
    assert window.start == date(2026, 11, 1)
    assert window.forecast_end == date(2026, 12, 1)


def test_sample_source_end_to_end():
    source = build_source("exemplo", TODAY)
    assert not source.paid
    result = run_collection(source, TODAY, 30)
    assert {r.account for r in result.records} == {"producao", "desenvolvimento", "dados"}
    assert result.api_calls == 0 or not source.paid


def test_unknown_source():
    with pytest.raises(ValueError):
        build_source("nada", TODAY)
