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


def build_summary(records: list[CostRecord], *, today: date, days: int, forecast_amount: Decimal | None) -> CostSummary:
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


def fmt_pct(ratio: float | Decimal, decimals: int = 1) -> str:
    """Formata no padrão brasileiro: 0.672 -> 67,2%."""
    return f"{float(ratio) * 100:.{decimals}f}%".replace(".", ",")


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


SEVERITY_LABEL = {"alta": "ALTA ", "media": "MÉDIA", "baixa": "BAIXA"}


def render_recommendations(recs: list, *, source: str, inventories: list, detail_limit: int = 30) -> str:
    """Relatório de texto das recomendações (lista já ordenada por economia)."""
    from finops.recommendations import savings_by_rule, total_savings

    savings = [r for r in recs if r.monthly_savings is not None]
    governance = [r for r in recs if r.monthly_savings is None]
    total = total_savings(recs)
    resources = sum(i.resource_count for i in inventories)
    regions = sorted({r for i in inventories for r in i.regions})

    lines = [
        f"FinOps AWS: recomendações (fonte: {source})",
        f"Inventário: {resources} recurso(s) em {len(inventories)} conta(s) e {len(regions)} região(ões)",
        "",
        f"  Economia potencial ...... {fmt_usd(total)}/mês ({fmt_usd(total * 12)}/ano)",
        f"  Oportunidades ........... {len(savings)} de economia + {len(governance)} de governança (tags)",
    ]
    if savings:
        lines += ["", "Por tipo:"]
        width = max(len(t) for t, _, _ in savings_by_rule(savings))
        for title, count, amount in savings_by_rule(savings):
            lines.append(f"  {title:<{width}}  {count:>3}x  {fmt_usd(amount):>14}/mês")

        lines += ["", "Maiores economias:"]
        for r in savings[:detail_limit]:
            lines.append(
                f"  [{SEVERITY_LABEL[r.severity]}] {fmt_usd(r.monthly_savings):>12}/mês  "
                f"{r.account} · {r.region} · {r.resource_id}"
            )
            lines.append(f"           {r.title}: {r.detail}")
            lines.append(f"           → {r.action}")
        if len(savings) > detail_limit:
            lines.append(f"  ... e mais {len(savings) - detail_limit} (use --csv para ver todas)")
    elif not governance:
        lines += ["", "Nenhum desperdício encontrado. 🎉"]

    if governance:
        lines += ["", f"Governança: {len(governance)} recurso(s) sem as tags Project/Environment"]
        for r in governance[:5]:
            lines.append(f"  - {r.account} · {r.region} · {r.resource_id}: {r.detail}")
        if len(governance) > 5:
            lines.append(f"  ... e mais {len(governance) - 5}")

    for inv in inventories:
        if inv.blocked_regions:
            lines += [
                "",
                f"ℹ {inv.account}: {len(inv.blocked_regions)} região(ões) bloqueadas por SCP da organização "
                f"(ignoradas): {', '.join(inv.blocked_regions)}",
            ]
    errors = [f"{i.account}: {e}" for i in inventories for e in i.errors]
    if errors:
        lines += ["", "⚠ Problemas na coleta:"] + [f"  - {e}" for e in errors]
    return "\n".join(lines)


def export_recommendations_csv(recs: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["severidade", "economia_mensal_usd", "regra", "titulo", "conta", "regiao", "recurso", "detalhe", "acao"]
        )
        for r in recs:
            savings = "" if r.monthly_savings is None else str(r.monthly_savings.quantize(ZERO_CENTS))
            writer.writerow(
                [r.severity, savings, r.rule, r.title, r.account, r.region, r.resource_id, r.detail, r.action]
            )


ZERO_CENTS = Decimal("0.01")


def export_csv(records: list[CostRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dia", "conta", "servico", "custo", "moeda", "estimado"])
        for r in sorted(records, key=lambda r: (r.day, r.account, r.service)):
            writer.writerow([r.day.isoformat(), r.account, r.service, str(r.amount), r.unit, r.estimated])
