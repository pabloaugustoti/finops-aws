"""Detecção de anomalias de custo (estatística robusta, sem serviço extra da AWS).

Para cada série diária (conta + serviço), compara o custo do dia com os
`lookback` dias anteriores usando **mediana** e **MAD** (desvio absoluto
mediano). Ao contrário de média e desvio padrão, essas medidas quase não são
afetadas pelo próprio pico: um dia absurdo não "contamina" a linha de base.

Um dia é anômalo quando, ao mesmo tempo:
- está `threshold` desvios robustos acima da mediana (z robusto);
- o impacto em dinheiro passa de `min_impact` (ignora centavos);
- o aumento relativo passa de `min_relative` (ignora variações pequenas de séries grandes).

Dias anômalos consecutivos da mesma série viram um único **evento**.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from finops.models import CostRecord

MAD_TO_SIGMA = 1.4826  # converte MAD em desvio padrão equivalente (distribuição normal)


@dataclass(frozen=True)
class AnomalousDay:
    day: date
    amount: float
    expected: float
    zscore: float

    @property
    def impact(self) -> float:
        return self.amount - self.expected


@dataclass(frozen=True)
class AnomalyEvent:
    account: str
    service: str
    days: tuple[AnomalousDay, ...]

    @property
    def start(self) -> date:
        return self.days[0].day

    @property
    def end(self) -> date:
        return self.days[-1].day

    @property
    def impact(self) -> Decimal:
        """Custo acima do esperado somando todos os dias do evento."""
        return Decimal(str(round(sum(d.impact for d in self.days), 2)))

    @property
    def peak(self) -> AnomalousDay:
        return max(self.days, key=lambda d: d.amount)

    @property
    def severity(self) -> str:
        ratio = self.peak.amount / self.peak.expected if self.peak.expected > 0 else float("inf")
        return "alta" if ratio >= 2 or self.impact >= 100 else "media"


def _series(records: list[CostRecord]) -> dict[tuple[str, str], dict[date, float]]:
    series: dict[tuple[str, str], dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for r in records:
        series[(r.account, r.service)][r.day] += float(r.amount)
    return series


def detect_anomalies(
    records: list[CostRecord],
    *,
    lookback: int = 14,
    threshold: float = 3.5,
    min_impact: float = 1.0,
    min_relative: float = 0.3,
) -> list[AnomalyEvent]:
    """Eventos anômalos, do maior impacto para o menor."""
    events: list[AnomalyEvent] = []
    for (account, service), points in _series(records).items():
        first, last = min(points), max(points)
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        values = [points.get(d, 0.0) for d in days]

        flagged: list[AnomalousDay] = []
        for i in range(lookback, len(values)):
            window = values[i - lookback : i]
            center = median(window)
            spread = median(abs(v - center) for v in window) * MAD_TO_SIGMA
            # piso no desvio: séries quase constantes não podem gerar alarmes por ruído mínimo
            spread = max(spread, 0.05 * center, 0.01)
            value = values[i]
            z = (value - center) / spread
            impact = value - center
            relative = impact / center if center > 0 else float("inf")
            if z >= threshold and impact >= min_impact and relative >= min_relative:
                flagged.append(AnomalousDay(days[i], value, center, z))

        events.extend(_group_consecutive(account, service, flagged))
    return sorted(events, key=lambda e: e.impact, reverse=True)


def _group_consecutive(account: str, service: str, flagged: list[AnomalousDay]) -> list[AnomalyEvent]:
    groups: list[list[AnomalousDay]] = []
    for day in flagged:
        if groups and (day.day - groups[-1][-1].day).days == 1:
            groups[-1].append(day)
        else:
            groups.append([day])
    return [AnomalyEvent(account, service, tuple(g)) for g in groups]
