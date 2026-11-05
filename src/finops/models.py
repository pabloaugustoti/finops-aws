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


UNTAGGED = "(sem tag)"


@dataclass(frozen=True)
class TagCost:
    """Custo de um período somado por valor de tag (showback)."""

    account: str
    tag_key: str
    value: str  # UNTAGGED quando o recurso não tem a tag
    amount: Decimal


@dataclass(frozen=True)
class Forecast:
    """Previsão de gasto para um período futuro (fim exclusivo)."""

    start: date
    end: date
    amount: Decimal
    unit: str
