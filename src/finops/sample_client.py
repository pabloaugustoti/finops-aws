"""Cliente falso do Cost Explorer com dados de exemplo realistas.

Devolve respostas no mesmo formato da API real, então o resto do código
não sabe (nem precisa saber) se os dados são reais ou de exemplo.

Os dados incluem padrões que um analista de FinOps procura:
- computação mais barata no fim de semana (ambientes de dev desligados);
- S3 e Lambda crescendo um pouco a cada dia;
- um pico de EC2 entre 10 e 12 dias atrás, simulando uma instância esquecida ligada.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

EC2_COMPUTE = "Amazon Elastic Compute Cloud - Compute"

# serviço: (custo diário base em USD, fator no fim de semana, crescimento diário)
SERVICES: dict[str, tuple[float, float, float]] = {
    EC2_COMPUTE: (18.0, 0.85, 0.0),
    "Amazon Relational Database Service": (9.5, 1.0, 0.0),
    "EC2 - Other": (4.1, 1.0, 0.0),
    "Amazon Simple Storage Service": (3.2, 1.0, 0.004),
    "AmazonCloudWatch": (1.4, 1.0, 0.0),
    "Amazon Virtual Private Cloud": (1.1, 1.0, 0.0),
    "AWS Lambda": (0.6, 0.6, 0.002),
    "AWS Key Management Service": (0.3, 1.0, 0.0),
}
SPIKE_SERVICE = EC2_COMPUTE
SPIKE_AGE_DAYS = range(10, 13)
SPIKE_FACTOR = 2.4

# Contas fictícias usadas no modo de exemplo: nome -> (seed, escala, tem pico)
SAMPLE_ACCOUNTS: dict[str, tuple[int, float, bool]] = {
    "producao": (42, 1.0, True),
    "desenvolvimento": (7, 0.35, False),
    "dados": (13, 0.2, False),
}

# Rateio do custo por tag em cada conta fictícia: chave -> {valor: fração}.
# O que falta para 100% é custo SEM a tag (o problema que o showback revela).
SAMPLE_TAGS: dict[str, dict[str, dict[str, float]]] = {
    "producao": {"Project": {"loja": 0.58, "checkout": 0.27}, "Environment": {"producao": 0.85}},
    "desenvolvimento": {"Project": {"loja": 0.5, "checkout": 0.2}, "Environment": {"dev": 0.7}},
    "dados": {"Project": {"analytics": 0.9}, "Environment": {"producao": 0.9}},
}


class SampleCostExplorerClient:
    def __init__(
        self,
        today: date,
        seed: int = 42,
        scale: float = 1.0,
        spike: bool = True,
        tags: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """`scale` multiplica todos os custos; `spike` liga o pico simulado de EC2;
        `tags` define o rateio usado quando a consulta agrupa por tag."""
        self.today = today
        self.seed = seed
        self.scale = scale
        self.spike = spike
        self.tags = tags or {}

    def daily_cost(self, day: date, service: str) -> Decimal:
        base, weekend_factor, growth = SERVICES[service]
        age = (self.today - day).days
        value = base * self.scale * (1 + growth) ** (-age)
        if day.weekday() >= 5:
            value *= weekend_factor
        if self.spike and service == SPIKE_SERVICE and age in SPIKE_AGE_DAYS:
            value *= SPIKE_FACTOR
        # Ruído determinístico para dados FICTÍCIOS: não é uso criptográfico.
        rng = random.Random(f"{self.seed}:{day.isoformat()}:{service}")  # noqa: S311
        value *= rng.uniform(0.92, 1.08)
        return Decimal(str(round(value, 4)))

    def get_cost_and_usage(self, **params: Any) -> dict[str, Any]:
        start = date.fromisoformat(params["TimePeriod"]["Start"])
        end = min(date.fromisoformat(params["TimePeriod"]["End"]), self.today)
        granularity = params.get("Granularity", "DAILY")
        month_start = self.today.replace(day=1)

        group_by = (params.get("GroupBy") or [{}])[0]
        results = []
        for period_start, period_end in _periods(start, end, granularity):
            by_service = {
                service: sum((self.daily_cost(day, service) for day in _days(period_start, period_end)), Decimal("0"))
                for service in SERVICES
            }
            if group_by.get("Type") == "TAG":
                groups = self._tag_groups(group_by["Key"], sum(by_service.values(), Decimal("0")))
            else:
                groups = [
                    {"Keys": [service], "Metrics": {"UnblendedCost": {"Amount": str(amount), "Unit": "USD"}}}
                    for service, amount in by_service.items()
                ]
            results.append(
                {
                    "TimePeriod": {"Start": period_start.isoformat(), "End": period_end.isoformat()},
                    "Total": {},
                    "Groups": groups,
                    "Estimated": period_end > month_start,
                }
            )
        return {
            "GroupDefinitions": params.get("GroupBy", []),
            "ResultsByTime": results,
            "DimensionValueAttributes": [],
        }

    def _tag_groups(self, key: str, total: Decimal) -> list[dict[str, Any]]:
        """Grupos no formato da API: "Chave$valor"; "Chave$" é o custo sem a tag."""
        shares = self.tags.get(key, {})
        untagged = Decimal(str(round(1 - sum(shares.values()), 6)))
        pairs = [(value, Decimal(str(share))) for value, share in shares.items()] + [("", untagged)]
        groups = []
        for value, share in pairs:
            if share <= 0:
                continue
            amount = str((total * share).quantize(Decimal("0.0001")))
            groups.append({"Keys": [f"{key}${value}"], "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}})
        return groups

    def get_cost_forecast(self, **params: Any) -> dict[str, Any]:
        start = date.fromisoformat(params["TimePeriod"]["Start"])
        end = date.fromisoformat(params["TimePeriod"]["End"])
        last_week = list(_days(self.today - timedelta(days=7), self.today))
        daily_average = sum(
            (self.daily_cost(day, service) for day in last_week for service in SERVICES),
            Decimal("0"),
        ) / len(last_week)
        amount = daily_average * (end - start).days
        return {
            "Total": {"Amount": str(amount.quantize(Decimal("0.0001"))), "Unit": "USD"},
            "ForecastResultsByTime": [],
        }


def _days(start: date, end: date) -> Iterator[date]:
    day = start
    while day < end:
        yield day
        day += timedelta(days=1)


def _periods(start: date, end: date, granularity: str) -> Iterator[tuple[date, date]]:
    if granularity == "DAILY":
        for day in _days(start, end):
            yield day, day + timedelta(days=1)
        return
    if granularity != "MONTHLY":
        raise ValueError(f"granularidade não suportada nos dados de exemplo: {granularity}")
    period_start = start
    while period_start < end:
        next_month = (period_start.replace(day=1) + timedelta(days=32)).replace(day=1)
        period_end = min(next_month, end)
        yield period_start, period_end
        period_start = period_end
