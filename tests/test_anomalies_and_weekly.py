from datetime import date, timedelta
from decimal import Decimal

from finops.anomalies import detect_anomalies
from finops.cli import main
from finops.models import CostRecord
from finops.sample_client import EC2_COMPUTE
from finops.sources import build_source, run_collection
from finops.weekly_report import build_weekly_report

TODAY = date(2026, 11, 5)


def series(values: list[float], service: str = "S", account: str = "a") -> list[CostRecord]:
    start = TODAY - timedelta(days=len(values))
    return [CostRecord(start + timedelta(days=i), service, Decimal(str(v)), "USD", False, account)
            for i, v in enumerate(values)]


def test_flat_series_has_no_anomalies():
    assert detect_anomalies(series([10.0] * 40)) == []


def test_noise_is_not_an_anomaly():
    noisy = [10 + (i % 3 - 1) * 0.4 for i in range(40)]  # 9,6 / 10 / 10,4
    assert detect_anomalies(series(noisy)) == []


def test_single_spike_is_detected_with_impact():
    values = [10.0] * 30 + [40.0] + [10.0] * 5
    (event,) = detect_anomalies(series(values))
    assert event.start == event.end
    assert event.impact == Decimal("30.00")
    assert event.severity == "alta"


def test_consecutive_days_become_one_event():
    values = [10.0] * 30 + [30.0, 32.0, 31.0] + [10.0] * 5
    (event,) = detect_anomalies(series(values))
    assert len(event.days) == 3
    assert event.peak.amount == 32.0


def test_small_absolute_change_is_ignored():
    # 0,01 -> 0,05 é 5x, mas só 4 centavos: não merece alerta
    values = [0.01] * 30 + [0.05] + [0.01] * 3
    assert detect_anomalies(series(values)) == []


def test_drop_is_not_an_anomaly():
    values = [10.0] * 30 + [0.0] * 3
    assert detect_anomalies(series(values)) == []


def test_series_are_independent_per_account_and_service():
    records = series([10.0] * 30 + [50.0], "EC2", "prod") + series([10.0] * 31, "EC2", "dev")
    (event,) = detect_anomalies(records)
    assert (event.account, event.service) == ("prod", "EC2")


def test_sample_data_finds_exactly_the_planted_spike():
    result = run_collection(build_source("exemplo", TODAY), TODAY, 90)
    events = detect_anomalies(result.records)
    assert len(events) == 1
    assert (events[0].account, events[0].service) == ("producao", EC2_COMPUTE)
    assert events[0].start == TODAY - timedelta(days=12)
    assert events[0].end == TODAY - timedelta(days=10)


def test_weekly_report_sections():
    result = run_collection(build_source("exemplo", TODAY), TODAY, 90)
    md = build_weekly_report(result.records, today=TODAY, source="teste",
                             anomalies=detect_anomalies(result.records), recommendations=[],
                             forecast_amount=Decimal("100"))
    for section in ("# Relatório semanal", "## Resumo", "## Maiores serviços da semana", "## Anomalias",
                    "## Maiores oportunidades de economia"):
        assert section in md
    assert "producao" in md


def test_weekly_report_empty_account():
    md = build_weekly_report([], today=TODAY, source="vazia", anomalies=[], recommendations=[],
                             forecast_amount=None)
    assert "Nenhum custo na semana." in md
    assert "Nenhuma anomalia detectada" in md
    assert "indisponível" in md


def test_cli_anomalies_and_report(capsys, tmp_path):
    assert main(["anomalias"], today=TODAY) == 0
    assert "Amazon Elastic Compute Cloud - Compute" in capsys.readouterr().out

    out_file = tmp_path / "relatorio.md"
    assert main(["relatorio", "--saida", str(out_file)], today=TODAY) == 0
    assert out_file.read_text(encoding="utf-8").startswith("# Relatório semanal")
