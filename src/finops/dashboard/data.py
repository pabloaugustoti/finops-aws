"""Preparação de dados para o dashboard (sem Streamlit, para poder testar)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from finops.models import CostRecord

OTHER = "Outros"
COLUMNS = ["dia", "conta", "servico", "custo", "estimado"]


def records_frame(records: list[CostRecord]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in
                             zip(COLUMNS, ["datetime64[ns]", "str", "str", "float", "bool"])})
    return pd.DataFrame(
        {
            "dia": pd.to_datetime([r.day for r in records]),
            "conta": [r.account for r in records],
            "servico": [r.service for r in records],
            "custo": [float(r.amount) for r in records],
            "estimado": [r.estimated for r in records],
        }
    )


def in_window(df: pd.DataFrame, today: date, days: int) -> pd.DataFrame:
    start = pd.Timestamp(today - timedelta(days=days))
    return df[(df["dia"] >= start) & (df["dia"] < pd.Timestamp(today))]


def service_order(df: pd.DataFrame, top: int = 5) -> list[str]:
    """Os `top` serviços mais caros + 'Outros'.

    Calculado sobre os dados SEM filtro de conta, para que a cor de cada serviço
    não mude quando o usuário filtra (a cor segue o serviço, não a posição).
    """
    ranking = df.groupby("servico")["custo"].sum().sort_values(ascending=False)
    ranking = ranking[ranking > 0]
    names = list(ranking.index[:top])
    if len(ranking) > top:
        names.append(OTHER)
    return names


def daily_by_service(df: pd.DataFrame, order: list[str], today: date, days: int) -> pd.DataFrame:
    """Custo diário por serviço (agrupando fora do top em 'Outros'), com todos os dias presentes."""
    keep = set(order) - {OTHER}
    grouped = df.assign(servico=df["servico"].where(df["servico"].isin(keep), OTHER))
    table = grouped.groupby(["dia", "servico"], as_index=False)["custo"].sum()
    all_days = pd.date_range(today - timedelta(days=days), today - timedelta(days=1), freq="D")
    full = pd.MultiIndex.from_product([all_days, order], names=["dia", "servico"]).to_frame(index=False)
    result = full.merge(table, on=["dia", "servico"], how="left").fillna({"custo": 0.0})
    result["ordem"] = result["servico"].map({s: i for i, s in enumerate(order)})
    return result


def totals_by(df: pd.DataFrame, column: str) -> pd.DataFrame:
    total = df["custo"].sum()
    table = df.groupby(column, as_index=False)["custo"].sum().sort_values("custo", ascending=False)
    table = table[table["custo"] > 0]
    table["participacao"] = table["custo"] / total if total else 0.0
    return table.reset_index(drop=True)


@dataclass(frozen=True)
class Kpis:
    total: float
    daily_average: float
    month_to_date: float
    month_forecast: float | None
    last_7: float
    previous_7: float

    @property
    def week_change(self) -> float | None:
        """Variação dos últimos 7 dias contra os 7 anteriores (0,10 = +10%)."""
        if self.previous_7 <= 0:
            return None
        return self.last_7 / self.previous_7 - 1


def kpis(df: pd.DataFrame, today: date, days: int, forecast_amount: float | None) -> Kpis:
    window = in_window(df, today, days)
    month_start = pd.Timestamp(today.replace(day=1))
    end = pd.Timestamp(today)
    mtd = float(df[(df["dia"] >= month_start) & (df["dia"] < end)]["custo"].sum())

    def between(a: int, b: int) -> float:
        start, stop = pd.Timestamp(today - timedelta(days=a)), pd.Timestamp(today - timedelta(days=b))
        return float(df[(df["dia"] >= start) & (df["dia"] < stop)]["custo"].sum())

    total = float(window["custo"].sum())
    return Kpis(
        total=total,
        daily_average=total / days,
        month_to_date=mtd,
        month_forecast=mtd + forecast_amount if forecast_amount is not None else None,
        last_7=between(7, 0),
        previous_7=between(14, 7),
    )


def month_projection(df: pd.DataFrame, today: date, forecast_amount: float | None) -> pd.DataFrame:
    """Custo acumulado no mês (real) e a linha de previsão até o último dia do mês."""
    month_start = today.replace(day=1)
    last_day = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    days = pd.date_range(month_start, today - timedelta(days=1), freq="D") if today > month_start else []
    daily = df.groupby("dia")["custo"].sum()
    actual = pd.DataFrame({"dia": days})
    actual["custo"] = actual["dia"].map(daily).fillna(0.0).cumsum() if len(actual) else []
    actual["serie"] = "Real"

    frames = [actual]
    if forecast_amount is not None:
        start_day = pd.Timestamp(today - timedelta(days=1)) if len(actual) else pd.Timestamp(month_start)
        start_value = float(actual["custo"].iloc[-1]) if len(actual) else 0.0
        frames.append(pd.DataFrame({
            "dia": [start_day, pd.Timestamp(last_day)],
            "custo": [start_value, start_value + forecast_amount],
            "serie": "Previsão",
        }))
    return pd.concat(frames, ignore_index=True)
