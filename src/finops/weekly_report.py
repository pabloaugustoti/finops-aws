"""Relatório semanal em Markdown: pronto para e-mail, Slack, issue do GitHub ou wiki.

Junta as três visões do projeto: custos (semana × semana anterior),
anomalias e as maiores oportunidades de economia.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from finops.anomalies import AnomalyEvent
from finops.models import CostRecord
from finops.recommendations import Recommendation, total_savings
from finops.report import fmt_usd

ZERO = Decimal("0")


def _sum_between(records: list[CostRecord], start: date, end: date) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in records:
        if start <= r.day < end:
            totals[r.service] += r.amount
    return totals


def _change(current: Decimal, previous: Decimal) -> str:
    if previous <= 0:
        return "novo" if current > 0 else "—"
    pct = (current / previous - 1) * 100
    arrow = "🔺" if pct > 5 else ("🔻" if pct < -5 else "➖")
    return f"{arrow} {pct:+.1f}%".replace(".", ",")


def build_weekly_report(
    records: list[CostRecord],
    *,
    today: date,
    source: str,
    anomalies: list[AnomalyEvent],
    recommendations: list[Recommendation],
    forecast_amount: Decimal | None,
    top: int = 5,
) -> str:
    week_start, prev_start = today - timedelta(days=7), today - timedelta(days=14)
    this_week = _sum_between(records, week_start, today)
    last_week = _sum_between(records, prev_start, week_start)
    total, previous = sum(this_week.values(), ZERO), sum(last_week.values(), ZERO)
    month_start = today.replace(day=1)
    mtd = sum((r.amount for r in records if month_start <= r.day < today), ZERO)

    last_day = today - timedelta(days=1)
    lines = [
        f"# Relatório semanal de custos AWS: {week_start.strftime('%d/%m')} a {last_day.strftime('%d/%m/%Y')}",
        "",
        f"_Fonte: {source}. Valores do mês corrente são estimados até a fatura fechar._",
        "",
        "## Resumo",
        "",
        "| Indicador | Valor |",
        "|---|---|",
        f"| Custo da semana | **{fmt_usd(total)}** ({_change(total, previous)} vs. semana anterior) |",
        f"| Semana anterior | {fmt_usd(previous)} |",
        f"| Mês até ontem | {fmt_usd(mtd)} |",
        f"| Previsão de fechamento do mês | "
        f"{fmt_usd(mtd + forecast_amount) if forecast_amount is not None else 'indisponível'} |",
        f"| Anomalias nos últimos 30 dias | {len(anomalies)} |",
        f"| Economia potencial identificada | **{fmt_usd(total_savings(recommendations))}/mês** |",
        "",
    ]

    ranked = sorted(this_week.items(), key=lambda item: item[1], reverse=True)[:top]
    lines += ["## Maiores serviços da semana", ""]
    if ranked:
        lines += ["| Serviço | Semana | Variação |", "|---|---:|---|"]
        lines += [f"| {s} | {fmt_usd(a)} | {_change(a, last_week.get(s, ZERO))} |" for s, a in ranked]
    else:
        lines.append("Nenhum custo na semana.")
    lines.append("")

    lines += ["## Anomalias", ""]
    if anomalies:
        lines += ["| Período | Conta | Serviço | Pico (esperado) | Custo extra |", "|---|---|---|---|---:|"]
        for e in anomalies:
            period = e.start.strftime("%d/%m") if e.start == e.end else f"{e.start:%d/%m} a {e.end:%d/%m}"
            peak = e.peak
            lines.append(
                f"| {period} | {e.account} | {e.service} | "
                f"{fmt_usd(Decimal(str(round(peak.amount, 2))))} ({fmt_usd(Decimal(str(round(peak.expected, 2))))}) | "
                f"{fmt_usd(e.impact)} |"
            )
    else:
        lines.append("Nenhuma anomalia detectada. ✅")
    lines.append("")

    savings = [(r, r.monthly_savings) for r in recommendations if r.monthly_savings is not None][:top]
    lines += ["## Maiores oportunidades de economia", ""]
    if savings:
        lines += ["| Economia/mês | Conta | Recurso | Recomendação |", "|---:|---|---|---|"]
        lines += [f"| {fmt_usd(amount)} | {r.account} | `{r.resource_id}` | {r.title} |" for r, amount in savings]
    else:
        lines.append("Nenhuma oportunidade encontrada no inventário. ✅")
    governance = sum(1 for r in recommendations if r.monthly_savings is None)
    if governance:
        lines += ["", f"Além disso, **{governance} recurso(s) sem as tags de custo** (Project/Environment)."]
    lines.append("")
    return "\n".join(lines)
