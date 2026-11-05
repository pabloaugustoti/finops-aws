"""Monta as respostas JSON da API (funções puras, sem servidor e sem pandas).

O frontend recebe os dados já agregados e só desenha: toda regra de negócio
fica aqui, onde é testável.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from finops.anomalies import detect_anomalies
from finops.collector import CollectionResult
from finops.inventory import Inventory
from finops.recommendations import Recommendation, savings_by_rule, total_savings

OTHER = "Outros"
TOP_SERVICES = 5


def _money(value: Decimal | float) -> float:
    return round(float(value), 2)


def _ranked(totals: dict[str, float], total: float) -> list[dict[str, Any]]:
    items = sorted(((k, v) for k, v in totals.items() if v > 0), key=lambda kv: kv[1], reverse=True)
    return [{"nome": k, "valor": round(v, 2), "participacao": (v / total) if total else 0.0} for k, v in items]


def costs_payload(
    result: CollectionResult,
    *,
    today: date,
    days: int,
    label: str,
    paid: bool,
    selected: list[str] | None = None,
) -> dict[str, Any]:
    ok_accounts = [a.account for a in result.accounts if not a.error]
    chosen = [a for a in (selected or ok_accounts) if a in ok_accounts]
    records = [r for r in result.records if r.account in chosen]

    start, month_start = today - timedelta(days=days), today.replace(day=1)
    window = [r for r in records if start <= r.day < today]
    day_list = [start + timedelta(days=i) for i in range(days)]

    # Ordem e cores dos serviços calculadas com TODAS as contas: filtrar não repinta ninguém.
    ranking: dict[str, float] = defaultdict(float)
    for r in result.records:
        if start <= r.day < today:
            ranking[r.service] += float(r.amount)
    ordered = [s for s, v in sorted(ranking.items(), key=lambda kv: kv[1], reverse=True) if v > 0]
    order = ordered[:TOP_SERVICES] + ([OTHER] if len(ordered) > TOP_SERVICES else [])
    keep = set(order) - {OTHER}

    stacks: dict[str, dict[date, float]] = {s: defaultdict(float) for s in order}
    by_service: dict[str, float] = defaultdict(float)
    by_account: dict[str, float] = defaultdict(float)
    for r in window:
        group = r.service if r.service in keep else OTHER
        if group in stacks:
            stacks[group][r.day] += float(r.amount)
        by_service[r.service] += float(r.amount)
        by_account[r.account] += float(r.amount)
    total = sum(by_service.values())

    def between(a: int, b: int) -> float:
        lo, hi = today - timedelta(days=a), today - timedelta(days=b)
        return sum(float(r.amount) for r in records if lo <= r.day < hi)

    last7, prev7 = between(7, 0), between(14, 7)
    mtd = sum(float(r.amount) for r in records if month_start <= r.day < today)
    forecasts = [float(a.forecast.amount) for a in result.accounts if a.account in chosen and a.forecast]
    forecast_rest = sum(forecasts) if forecasts else None

    # Acumulado do mês (real) e reta de previsão até o último dia do mês
    daily_total: dict[date, float] = defaultdict(float)
    for r in records:
        daily_total[r.day] += float(r.amount)
    month_days = [month_start + timedelta(days=i) for i in range((today - month_start).days)]
    running, real = 0.0, []
    for d in month_days:
        running += daily_total.get(d, 0.0)
        real.append({"dia": d.isoformat(), "valor": round(running, 2)})
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    projection = []
    if forecast_rest is not None:
        anchor = month_days[-1] if month_days else month_start - timedelta(days=1)
        projection = [
            {"dia": anchor.isoformat(), "valor": round(mtd, 2)},
            {"dia": month_end.isoformat(), "valor": round(mtd + forecast_rest, 2)},
        ]

    cutoff = today - timedelta(days=days)
    events = [e for e in detect_anomalies(records) if e.end >= cutoff]

    return {
        "meta": {
            "fonte": label,
            "paga": paid,
            "chamadas_api": result.api_calls,
            "custo_api": _money(result.api_calls * Decimal("0.01")),
            "contas": ok_accounts,
            "selecionadas": chosen,
            "erros": result.errors,
            "inicio": start.isoformat(),
            "fim": (today - timedelta(days=1)).isoformat(),
            "dias": days,
            "estimado": any(r.estimated for r in window),
        },
        "kpis": {
            "total": round(total, 2),
            "media_diaria": round(total / days, 2),
            "mes_ate_ontem": round(mtd, 2),
            "previsao_mes": round(mtd + forecast_rest, 2) if forecast_rest is not None else None,
            "ultimos_7": round(last7, 2),
            "anteriores_7": round(prev7, 2),
            "variacao_semana": (last7 / prev7 - 1) if prev7 > 0 else None,
        },
        "diario": {
            "dias": [d.isoformat() for d in day_list],
            "series": [{"nome": s, "valores": [round(stacks[s].get(d, 0.0), 4) for d in day_list]} for s in order],
        },
        "por_conta": _ranked(by_account, total),
        "por_servico": _ranked(by_service, total)[:10],
        "mes": {"inicio": month_start.isoformat(), "fim": month_end.isoformat(), "real": real, "previsao": projection},
        "anomalias": [
            {
                "inicio": e.start.isoformat(),
                "fim": e.end.isoformat(),
                "conta": e.account,
                "servico": e.service,
                "custo_extra": float(e.impact),
                "pico": round(e.peak.amount, 2),
                "esperado": round(e.peak.expected, 2),
                "z": round(e.peak.zscore, 1),
                "severidade": e.severity,
                "dias": [d.day.isoformat() for d in e.days],
            }
            for e in events
        ],
        "linhas": [
            {
                "dia": r.day.isoformat(),
                "conta": r.account,
                "servico": r.service,
                "custo": round(float(r.amount), 4),
                "estimado": r.estimated,
            }
            for r in sorted(window, key=lambda r: (r.day, r.account, -r.amount), reverse=True)
            if r.amount > 0
        ],
    }


def recommendations_payload(recs: list[Recommendation], inventories: list[Inventory], *, label: str) -> dict[str, Any]:
    savings = [r for r in recs if r.monthly_savings is not None]
    total = total_savings(recs)
    return {
        "meta": {
            "fonte": label,
            "recursos": sum(i.resource_count for i in inventories),
            "regioes": sorted({r for i in inventories for r in i.regions}),
            "bloqueadas": {i.account: i.blocked_regions for i in inventories if i.blocked_regions},
            "erros": [f"{i.account}: {e}" for i in inventories for e in i.errors],
        },
        "resumo": {
            "economia_mes": _money(total),
            "economia_ano": _money(total * 12),
            "oportunidades": len(savings),
            "sem_tags": len(recs) - len(savings),
        },
        "por_tipo": [
            {"nome": t, "quantidade": c, "valor": _money(a), "participacao": float(a / total) if total else 0.0}
            for t, c, a in savings_by_rule(savings)
        ],
        "itens": [
            {
                "regra": r.rule,
                "titulo": r.title,
                "conta": r.account,
                "regiao": r.region,
                "recurso": r.resource_id,
                "detalhe": r.detail,
                "acao": r.action,
                "severidade": r.severity,
                "categoria": r.category,
                "economia_mes": _money(r.monthly_savings) if r.monthly_savings is not None else None,
            }
            for r in recs
        ],
    }
