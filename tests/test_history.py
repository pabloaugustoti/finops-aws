from datetime import date
from decimal import Decimal

from finops.cli import render_history
from finops.history import HistoryStore
from finops.models import CostRecord
from finops.sources import build_source, run_collection

TODAY = date(2026, 11, 5)


def rec(day: str, amount: str, account: str = "a", estimated: bool = False) -> CostRecord:
    return CostRecord(date.fromisoformat(day), "S3", Decimal(amount), "USD", estimated, account)


def test_save_upserts_and_groups_by_month():
    with HistoryStore(":memory:") as store:
        store.save([rec("2026-09-30", "10"), rec("2026-10-01", "5"), rec("2026-10-02", "5", estimated=True)])
        store.save([rec("2026-10-02", "7")])  # o dado mais recente substitui o anterior
        months = store.monthly()
        assert [(m.month, m.amount, m.estimated) for m in months] == [
            ("2026-09", Decimal("10.0"), False),
            ("2026-10", Decimal("12.0"), False),
        ]
        assert store.coverage().rows == 3


def test_monthly_filters_accounts():
    with HistoryStore(":memory:") as store:
        store.save([rec("2026-10-01", "5", "a"), rec("2026-10-01", "9", "b")])
        assert store.monthly(["b"])[0].amount == Decimal("9.0")


def test_sample_collection_fills_history(tmp_path):
    result = run_collection(build_source("exemplo", TODAY), TODAY, 90)
    with HistoryStore(tmp_path / "h.sqlite") as store:
        store.save(result.records)
        months = store.monthly()
    assert len(months) >= 3
    assert months[-1].estimated
    assert "▲" in "\n".join(render_history(months)) or "▼" in "\n".join(render_history(months))
