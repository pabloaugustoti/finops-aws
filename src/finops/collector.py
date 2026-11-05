"""Coleta de custos de várias contas.

Cada conta é independente: se uma falhar (role não implantada, sem permissão,
credencial expirada), as outras continuam e a falha aparece no relatório.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from finops.cache import JsonCache
from finops.cost_explorer import CostExplorer
from finops.models import CostRecord, Forecast

ClientFactory = Callable[[str], Any]


@dataclass
class AccountResult:
    account: str
    records: list[CostRecord] = field(default_factory=list)
    forecast: Forecast | None = None
    api_calls: int = 0
    error: str | None = None


@dataclass
class CollectionResult:
    accounts: list[AccountResult]

    @property
    def records(self) -> list[CostRecord]:
        return [r for a in self.accounts for r in a.records]

    @property
    def api_calls(self) -> int:
        return sum(a.api_calls for a in self.accounts)

    @property
    def errors(self) -> list[str]:
        return [f"{a.account}: {a.error}" for a in self.accounts if a.error]

    @property
    def forecast_amount(self) -> Decimal | None:
        """Soma das previsões disponíveis; None se nenhuma conta tiver previsão."""
        forecasts = [a.forecast.amount for a in self.accounts if a.forecast]
        return sum(forecasts, Decimal("0")) if forecasts else None

    @property
    def forecast_is_partial(self) -> bool:
        ok = [a for a in self.accounts if not a.error]
        return any(a.forecast is None for a in ok) and any(a.forecast for a in ok)


def collect(
    account_names: list[str],
    client_factory: ClientFactory,
    *,
    start: date,
    end: date,
    forecast_end: date,
    cache: JsonCache | None = None,
) -> CollectionResult:
    """Coleta custos de `start` a `end` e a previsão de `end` a `forecast_end` para cada conta."""
    results = []
    for name in account_names:
        result = AccountResult(account=name)
        explorer: CostExplorer | None = None
        try:
            explorer = CostExplorer(client_factory(name), cache=cache, account=name)
            if start < end:
                result.records = explorer.costs_by_service(start, end)
            result.forecast = explorer.forecast(end, forecast_end)
        except Exception as error:  # noqa: BLE001 - uma conta com problema não derruba as outras
            result.error = _describe(error)
        if explorer is not None:
            result.api_calls = explorer.api_calls
        results.append(result)
    return CollectionResult(results)


def _describe(error: Exception) -> str:
    code = getattr(error, "response", {}).get("Error", {}).get("Code") if hasattr(error, "response") else None
    message = str(error).splitlines()[0]
    return f"{code}: {message}" if code else f"{type(error).__name__}: {message}"
