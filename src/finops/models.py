"""Modelos de dados usados pelo coletor e pelos relatórios."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CostRecord:
    """Custo de um serviço num período (normalmente um dia)."""

    day: date
    service: str
    amount: Decimal
    unit: str
    estimated: bool
    account: str = ""


@dataclass(frozen=True)
class Forecast:
    """Previsão de gasto para um período futuro (fim exclusivo)."""

    start: date
    end: date
    amount: Decimal
    unit: str
