"""Monta e formata o resumo de custos."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from finops.models import CostRecord

ZERO = Decimal("0")
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


@dataclass(frozen=True)
class CostSummary:
    start: date
    end: date  # exclusivo
    total: Decimal
    by_service: list[tuple[str, Decimal]]
    by_account: list[tuple[str, Decimal]]
    daily: list[tuple[date, Decimal]]
    month_to_date: Decimal
    month_forecast: Decimal | None
    has_estimated: bool

    @property
    def days(self) -> int:
        return (self.end - self.start).days


def _ranked(totals: dict[str, Decimal]) -> list[tuple[str, Decimal]]:
    return sorted(((k, v) for k, v in totals.items() if v > ZERO), key=lambda item: item[1], reverse=True)


def build_summary(
    records: list[CostRecord], *, today: date, days: int, forecast_amount: Decimal | None
) -> CostSummary:
    """`forecast_amount` é a previsão de hoje até o fim do mês (soma de todas as contas)."""
    start = today - timedelta(days=days)
    month_start = today.replace(day=1)
    window = [r for r in records if start <= r.day < today]

    by_service: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_account: dict[str, Decimal] = defaultdict(lambda: ZERO)
    daily: dict[date, Decimal] = {start + timedelta(days=i): ZERO for i in range(days)}
    for record in window:
        by_service[record.service] += record.amount
        by_account[record.account] += record.amount
        daily[record.day] += record.amount

    month_to_date = sum((r.amount for r in records if month_start <= r.day < today), ZERO)
    return CostSummary(
        start=start,
        end=today,
        total=sum(by_service.values(), ZERO),
        by_service=_ranked(by_service),
        by_account=_ranked(by_account),
        daily=sorted(daily.items()),
        month_to_date=month_to_date,
        month_forecast=month_to_date + forecast_amount if forecast_amount is not None else None,
        has_estimated=any(r.estimated for r in window),
    )


def fmt_usd(value: Decimal) -> str:
    """Formata no padrão brasileiro: US$ 1.234,56."""
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"US$ {text}"


def sparkline(values: list[Decimal]) -> str:
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        return SPARK_BLOCKS[0] * len(values)
    scale = len(SPARK_BLOCKS) - 1
    return "".join(SPARK_BLOCKS[int((v - low) / (high - low) * scale)] for v in values)


def _ranking_lines(items: list[tuple[str, Decimal]], total: Decimal) -> list[str]:
    width = max((len(name) for name, _ in items), default=0)
    lines = []
    for name, amount in items:
        share = amount / total if total else ZERO
        bar = "█" * max(1, round(share * 20))
        percent = f"{share * 100:.1f}%".replace(".", ",")
        lines.append(f"  {name:<{width}}  {fmt_usd(amount):>14}  {percent:>6}  {bar}")
    return lines


def render_text(
    summary: CostSummary,
    *,
    source: str,
    top: int = 10,
    warnings: list[str] | None = None,
    forecast_is_partial: bool = False,
) -> str:
    last_day = summary.end - timedelta(days=1)
    lines = [
        f"FinOps AWS: resumo de custos (fonte: {source})",
        f"Período: {summary.start.isoformat()} a {last_day.isoformat()} ({summary.days} dias)",
        "",
        f"  Total no período ........ {fmt_usd(summary.total)}",
        f"  Média diária ............ {fmt_usd(summary.total / summary.days)}",
        f"  Mês atual até ontem ..... {fmt_usd(summary.month_to_date)}",
    ]
    if summary.month_forecast is not None:
        partial = " (parcial: algumas contas sem previsão)" if forecast_is_partial else ""
        lines.append(f"  Previsão de fechamento .. {fmt_usd(summary.month_forecast)}{partial}")
    else:
        lines.append("  Previsão de fechamento .. indisponível (histórico insuficiente)")
    if summary.has_estimated:
        lines.append("  * valores do mês corrente são estimados até a fatura fechar")

    if len(summary.by_account) > 1:
        lines += ["", "Por conta:"] + _ranking_lines(summary.by_account, summary.total)

    lines += ["", "Top serviços:"]
    if not summary.by_service:
        lines.append("  (nenhum custo no período)")
    lines += _ranking_lines(summary.by_service[:top], summary.total)

    recent = summary.daily[-14:]
    lines += ["", f"Custo diário (últimos {len(recent)} dias):  {sparkline([a for _, a in recent])}"]
    peak_day, peak_amount = max(summary.daily, key=lambda item: item[1])
    if peak_amount > ZERO:
        lines.append(f"  Dia mais caro: {peak_day.isoformat()} com {fmt_usd(peak_amount)}")
    if warnings:
        lines += ["", "⚠ Contas com problema (não entraram nos totais):"]
        lines += [f"  - {w}" for w in warnings]
    return "\n".join(lines)


def export_csv(records: list[CostRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dia", "conta", "servico", "custo", "moeda", "estimado"])
        for r in sorted(records, key=lambda r: (r.day, r.account, r.service)):
            writer.writerow([r.day.isoformat(), r.account, r.service, str(r.amount), r.unit, r.estimated])
