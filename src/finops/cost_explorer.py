"""Acesso à API do AWS Cost Explorer, com cache e conversão para modelos.

Funciona com o cliente real do boto3 (`boto3.client("ce")`) ou com qualquer
objeto que tenha os mesmos métodos, como o `SampleCostExplorerClient`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from botocore.exceptions import ClientError

from finops.cache import JsonCache
from finops.models import UNTAGGED, CostRecord, Forecast, TagCost

PRICE_PER_REQUEST_USD = Decimal("0.01")
_UNAVAILABLE = {"_unavailable": True}


class CostExplorer:
    def __init__(self, client: Any, cache: JsonCache | None = None, account: str = "") -> None:
        """`account` identifica a conta: rotula os registros e separa o cache de cada conta."""
        self._client = client
        self._cache = cache
        self.account = account
        self.api_calls = 0

    def cache_key(self, operation: str, params: dict[str, Any]) -> str:
        return JsonCache.make_key(operation, {"account": self.account, "params": params})

    @property
    def estimated_api_cost(self) -> Decimal:
        return self.api_calls * PRICE_PER_REQUEST_USD

    def costs_by_service(self, start: date, end: date, granularity: str = "DAILY") -> list[CostRecord]:
        """Custos por serviço entre `start` e `end` (fim exclusivo)."""
        if start >= end:
            raise ValueError(f"início ({start}) precisa ser anterior ao fim ({end})")
        params = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": granularity,
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        response = self._request("get_cost_and_usage", params)
        return _parse_cost_and_usage(response, self.account)

    def costs_by_tag(self, start: date, end: date, tag_key: str) -> list[TagCost]:
        """Custo total do período agrupado pelos valores de uma tag de alocação de custo.

        A AWS devolve as chaves como "Project$loja"; "Project$" é o custo SEM a tag.
        Na conta real, a tag precisa estar ativada em Billing > Cost allocation tags.
        """
        if start >= end:
            raise ValueError(f"início ({start}) precisa ser anterior ao fim ({end})")
        params = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "TAG", "Key": tag_key}],
        }
        response = self._request("get_cost_and_usage", params)
        totals: dict[str, Decimal] = {}
        for result in response.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                value = group["Keys"][0].split("$", 1)[-1] or UNTAGGED
                totals[value] = totals.get(value, Decimal("0")) + Decimal(group["Metrics"]["UnblendedCost"]["Amount"])
        return [TagCost(self.account, tag_key, value, amount) for value, amount in totals.items()]

    def forecast(self, start: date, end: date) -> Forecast | None:
        """Previsão de gasto entre `start` (hoje ou depois) e `end`.

        Retorna None quando a AWS ainda não tem histórico suficiente
        (comum em contas novas).
        """
        params = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Metric": "UNBLENDED_COST",
            "Granularity": "MONTHLY",
        }
        response = self._request("get_cost_forecast", params)
        if response.get("_unavailable"):
            return None
        total = response["Total"]
        return Forecast(start=start, end=end, amount=Decimal(total["Amount"]), unit=total["Unit"])

    def _request(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        key = self.cache_key(operation, params)
        if self._cache is not None:
            cached = self._cache.get(key)
            if isinstance(cached, dict):
                return cached
        try:
            response = self._fetch(operation, params)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "DataUnavailableException":
                raise
            response = dict(_UNAVAILABLE)
        if self._cache is not None:
            self._cache.set(key, response, permanent=_is_final(operation, response))
        return response

    def _fetch(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        method = getattr(self._client, operation)
        # Conta antes de chamar: requisições que terminam em erro também são cobradas.
        self.api_calls += 1
        response = dict(method(**params))
        token = response.pop("NextPageToken", None)
        while token:
            self.api_calls += 1
            page = method(**params, NextPageToken=token)
            response.setdefault("ResultsByTime", []).extend(page.get("ResultsByTime", []))
            token = page.get("NextPageToken")
        response.pop("ResponseMetadata", None)
        return response


def _is_final(operation: str, response: dict[str, Any]) -> bool:
    """Só respostas de períodos fechados podem ficar no cache para sempre."""
    if operation != "get_cost_and_usage":
        return False
    return not any(result.get("Estimated") for result in response.get("ResultsByTime", []))


def _parse_cost_and_usage(response: dict[str, Any], account: str = "") -> list[CostRecord]:
    records: list[CostRecord] = []
    for result in response.get("ResultsByTime", []):
        day = date.fromisoformat(result["TimePeriod"]["Start"])
        estimated = bool(result.get("Estimated", False))
        for group in result.get("Groups", []):
            metric = group["Metrics"]["UnblendedCost"]
            records.append(
                CostRecord(
                    day=day,
                    service=group["Keys"][0],
                    amount=Decimal(metric["Amount"]),
                    unit=metric["Unit"],
                    estimated=estimated,
                    account=account,
                )
            )
    return records
