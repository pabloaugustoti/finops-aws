from datetime import date
from decimal import Decimal

import boto3
import pytest
from botocore.stub import Stubber

from finops.cache import JsonCache
from finops.cost_explorer import CostExplorer

START, END = date(2026, 10, 1), date(2026, 10, 3)
USAGE_PARAMS = {
    "TimePeriod": {"Start": "2026-10-01", "End": "2026-10-03"},
    "Granularity": "DAILY",
    "Metrics": ["UnblendedCost"],
    "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
}
FORECAST_PARAMS = {
    "TimePeriod": {"Start": "2026-11-04", "End": "2026-12-01"},
    "Metric": "UNBLENDED_COST",
    "Granularity": "MONTHLY",
}


def _result(day: str, next_day: str, groups: dict[str, str], estimated: bool = False) -> dict:
    return {
        "TimePeriod": {"Start": day, "End": next_day},
        "Total": {},
        "Groups": [
            {"Keys": [service], "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}
            for service, amount in groups.items()
        ],
        "Estimated": estimated,
    }


@pytest.fixture
def ce_client():
    # Credenciais falsas: o Stubber intercepta as chamadas antes de qualquer acesso à rede.
    client = boto3.client(
        "ce", region_name="us-east-1", aws_access_key_id="teste", aws_secret_access_key="teste"
    )
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def test_parses_groups_into_records(ce_client):
    client, stubber = ce_client
    stubber.add_response(
        "get_cost_and_usage",
        {"ResultsByTime": [
            _result("2026-10-01", "2026-10-02", {"Amazon S3": "1.50", "AWS Lambda": "0.25"}),
            _result("2026-10-02", "2026-10-03", {"Amazon S3": "2.00"}),
        ]},
        USAGE_PARAMS,
    )
    records = CostExplorer(client).costs_by_service(START, END)

    assert len(records) == 3
    assert records[0].day == date(2026, 10, 1)
    assert records[0].service == "Amazon S3"
    assert records[0].amount == Decimal("1.50")
    assert sum(r.amount for r in records) == Decimal("3.75")


def test_follows_pagination(ce_client):
    client, stubber = ce_client
    stubber.add_response(
        "get_cost_and_usage",
        {"ResultsByTime": [_result("2026-10-01", "2026-10-02", {"A": "1"})], "NextPageToken": "p2"},
        USAGE_PARAMS,
    )
    stubber.add_response(
        "get_cost_and_usage",
        {"ResultsByTime": [_result("2026-10-02", "2026-10-03", {"B": "2"})]},
        {**USAGE_PARAMS, "NextPageToken": "p2"},
    )
    explorer = CostExplorer(client)
    records = explorer.costs_by_service(START, END)

    assert [r.service for r in records] == ["A", "B"]
    assert explorer.api_calls == 2


def test_cache_avoids_second_paid_call(ce_client, tmp_path):
    client, stubber = ce_client
    stubber.add_response(
        "get_cost_and_usage",
        {"ResultsByTime": [_result("2026-10-01", "2026-10-02", {"A": "1"})]},
        USAGE_PARAMS,
    )
    cache = JsonCache(tmp_path)
    first = CostExplorer(client, cache=cache)
    second = CostExplorer(client, cache=cache)

    assert first.costs_by_service(START, END) == second.costs_by_service(START, END)
    assert first.api_calls == 1
    assert second.api_calls == 0


def test_closed_period_is_cached_forever_but_estimated_is_not(ce_client, tmp_path):
    client, stubber = ce_client
    stubber.add_response(
        "get_cost_and_usage",
        {"ResultsByTime": [_result("2026-10-01", "2026-10-02", {"A": "1"}, estimated=True)]},
        USAGE_PARAMS,
    )
    cache = JsonCache(tmp_path)
    CostExplorer(client, cache=cache).costs_by_service(START, END)

    key = JsonCache.make_key("get_cost_and_usage", USAGE_PARAMS)
    assert '"permanent": false' in (tmp_path / f"{key}.json").read_text(encoding="utf-8")


def test_forecast(ce_client):
    client, stubber = ce_client
    stubber.add_response(
        "get_cost_forecast", {"Total": {"Amount": "12.3456", "Unit": "USD"}}, FORECAST_PARAMS
    )
    forecast = CostExplorer(client).forecast(date(2026, 11, 4), date(2026, 12, 1))
    assert forecast is not None
    assert forecast.amount == Decimal("12.3456")


def test_forecast_unavailable_on_new_account(ce_client):
    client, stubber = ce_client
    stubber.add_client_error(
        "get_cost_forecast",
        service_error_code="DataUnavailableException",
        expected_params=FORECAST_PARAMS,
    )
    explorer = CostExplorer(client)
    assert explorer.forecast(date(2026, 11, 4), date(2026, 12, 1)) is None
    assert explorer.api_calls == 1  # a chamada com erro também é cobrada


def test_other_errors_are_raised(ce_client):
    client, stubber = ce_client
    stubber.add_client_error("get_cost_forecast", service_error_code="AccessDeniedException",
                             expected_params=FORECAST_PARAMS)
    with pytest.raises(Exception, match="AccessDenied"):
        CostExplorer(client).forecast(date(2026, 11, 4), date(2026, 12, 1))


def test_rejects_empty_period(ce_client):
    client, _ = ce_client
    with pytest.raises(ValueError):
        CostExplorer(client).costs_by_service(END, END)
