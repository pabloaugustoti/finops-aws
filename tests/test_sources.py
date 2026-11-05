from datetime import date

import pytest

from finops.sources import build_source, collection_window, run_collection

TODAY = date(2026, 11, 4)


def test_collection_window_covers_month_start():
    window = collection_window(date(2026, 11, 20), days=7)
    assert window.start == date(2026, 11, 1)
    assert window.forecast_end == date(2026, 12, 1)


def test_collection_window_longer_than_month():
    window = collection_window(TODAY, days=30)
    assert window.start == date(2026, 10, 5)
    assert window.end == TODAY


def test_sample_source_end_to_end():
    source = build_source("exemplo", TODAY)
    assert not source.paid
    result = run_collection(source, TODAY, 30)
    assert {r.account for r in result.records} == {"producao", "desenvolvimento", "dados"}
    # o contador registra as chamadas ao cliente (3 contas x custos + previsão); como a
    # fonte não é paga, a CLI e a interface não mostram custo de API
    assert result.api_calls == 6


def test_unknown_source():
    with pytest.raises(ValueError, match="fonte desconhecida"):
        build_source("nada", TODAY)
