"""Orçamentos (AWS Budgets): limite × gasto real × previsão de cada conta."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from finops.aws_session import BILLING_REGION
from finops.sample_client import SampleCostExplorerClient

WARNING_RATIO = Decimal("0.85")  # a partir de 85% do limite, o orçamento pede atenção


@dataclass(frozen=True)
class Budget:
    account: str
    name: str
    limit: Decimal
    actual: Decimal
    forecast: Decimal | None
    unit: str = "USD"
    period: str = "MONTHLY"

    @property
    def used(self) -> Decimal:
        return self.actual / self.limit if self.limit else Decimal("0")

    @property
    def forecast_ratio(self) -> Decimal | None:
        if self.forecast is None or not self.limit:
            return None
        return self.forecast / self.limit

    @property
    def status(self) -> str:
        """estourado > vai estourar > atenção > ok."""
        if self.actual >= self.limit:
            return "estourado"
        if self.forecast is not None and self.forecast > self.limit:
            return "vai estourar"
        if self.used >= WARNING_RATIO or (self.forecast_ratio or 0) >= WARNING_RATIO:
            return "atenção"
        return "ok"


def _amount(spend: dict[str, Any] | None) -> Decimal | None:
    return Decimal(spend["Amount"]) if spend and spend.get("Amount") is not None else None


def fetch_budgets(session: Any, account: str) -> list[Budget]:
    """Orçamentos de custo da conta da sessão (budgets:ViewBudget, sem custo de API)."""
    account_id = session.client("sts", region_name=BILLING_REGION).get_caller_identity()["Account"]
    client = session.client("budgets", region_name=BILLING_REGION)
    budgets: list[Budget] = []
    for page in client.get_paginator("describe_budgets").paginate(AccountId=account_id):
        for raw in page.get("Budgets", []):
            if raw.get("BudgetType") != "COST":
                continue
            spend = raw.get("CalculatedSpend", {})
            budgets.append(
                Budget(
                    account=account,
                    name=raw["BudgetName"],
                    limit=Decimal(raw["BudgetLimit"]["Amount"]),
                    actual=_amount(spend.get("ActualSpend")) or Decimal("0"),
                    forecast=_amount(spend.get("ForecastedSpend")),
                    unit=raw["BudgetLimit"].get("Unit", "USD"),
                    period=raw.get("TimeUnit", "MONTHLY"),
                )
            )
    return budgets


# Limites mensais fictícios: um confortável, um no limite e um que vai estourar.
SAMPLE_LIMITS: dict[str, tuple[str, Decimal]] = {
    "producao": ("producao-mensal", Decimal("1200")),
    "desenvolvimento": ("dev-mensal", Decimal("350")),
    "dados": ("dados-mensal", Decimal("400")),
}


def sample_budgets(account: str, client: SampleCostExplorerClient, today: date) -> list[Budget]:
    """Orçamento de exemplo coerente com os custos de exemplo da mesma conta."""
    if account not in SAMPLE_LIMITS:
        return []
    name, limit = SAMPLE_LIMITS[account]
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    actual = Decimal("0")
    if today > month_start:
        usage = client.get_cost_and_usage(
            TimePeriod={"Start": month_start.isoformat(), "End": today.isoformat()}, Granularity="MONTHLY"
        )
        actual = sum(
            (Decimal(g["Metrics"]["UnblendedCost"]["Amount"]) for r in usage["ResultsByTime"] for g in r["Groups"]),
            Decimal("0"),
        )
    rest = client.get_cost_forecast(TimePeriod={"Start": today.isoformat(), "End": next_month.isoformat()})
    forecast = actual + Decimal(rest["Total"]["Amount"])
    return [Budget(account, name, limit, actual.quantize(Decimal("0.01")), forecast.quantize(Decimal("0.01")))]
