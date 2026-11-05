import json
import threading
from datetime import date
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from finops.sources import build_source, run_collection
from finops.web.api import costs_payload
from finops.web.server import FinOpsApp, MemoryCache, make_handler

TODAY = date(2026, 11, 5)


@pytest.fixture(scope="module")
def sample():
    return run_collection(build_source("exemplo", TODAY), TODAY, 90)


def test_costs_payload_shapes(sample):
    data = costs_payload(sample, today=TODAY, days=30, label="exemplo", paid=False)
    assert len(data["diario"]["dias"]) == 30
    assert [s["nome"] for s in data["diario"]["series"]][-1] == "Outros"
    assert all(len(s["valores"]) == 30 for s in data["diario"]["series"])
    stacked = sum(sum(s["valores"]) for s in data["diario"]["series"])
    assert stacked == pytest.approx(data["kpis"]["total"], abs=0.05)
    assert sum(c["valor"] for c in data["por_conta"]) == pytest.approx(data["kpis"]["total"], abs=0.05)
    assert len(data["anomalias"]) == 1
    assert data["mes"]["previsao"][-1]["dia"] == "2026-11-30"


def test_account_filter_keeps_series_order(sample):
    full = costs_payload(sample, today=TODAY, days=30, label="x", paid=False)
    dev = costs_payload(sample, today=TODAY, days=30, label="x", paid=False, selected=["desenvolvimento"])
    assert [s["nome"] for s in dev["diario"]["series"]] == [s["nome"] for s in full["diario"]["series"]]
    assert {c["nome"] for c in dev["por_conta"]} == {"desenvolvimento"}
    assert dev["anomalias"] == []  # o pico é só na conta de produção
    assert dev["meta"]["selecionadas"] == ["desenvolvimento"]


def test_unknown_account_in_filter_is_ignored(sample):
    data = costs_payload(sample, today=TODAY, days=7, label="x", paid=False, selected=["nao-existe"])
    assert data["meta"]["selecionadas"] == []
    assert data["kpis"]["total"] == 0


def test_memory_cache_ttl_and_refresh():
    now = [0.0]
    cache = MemoryCache(ttl=10, clock=lambda: now[0])
    calls = []
    load = lambda: calls.append(1) or len(calls)  # noqa: E731
    assert cache.get_or_load(("k",), load) == 1
    assert cache.get_or_load(("k",), load) == 1
    assert cache.get_or_load(("k",), load, refresh=True) == 2
    now[0] = 11
    assert cache.get_or_load(("k",), load) == 3


# ---------- servidor HTTP de verdade, numa porta livre ----------


@pytest.fixture(scope="module")
def base_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FinOpsApp(today=lambda: TODAY)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url: str):
    try:
        with urlopen(url, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_index_and_static_files(base_url):
    status, headers, body = get(f"{base_url}/")
    assert status == 200
    assert b"FinOps AWS" in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    for name, kind in (("styles.css", "text/css"), ("app.js", "text/javascript"), ("charts.js", "text/javascript")):
        status, headers, _ = get(f"{base_url}/static/{name}")
        assert status == 200
        assert headers["Content-Type"].startswith(kind)


def test_path_traversal_is_blocked(base_url):
    for path in ("/static/../server.py", "/static/..%2Fserver.py", "/static/../../cli.py"):
        status, _, body = get(f"{base_url}{path}")
        assert status == 404, path
        assert b"def " not in body


def test_api_costs_and_recommendations(base_url):
    status, _, body = get(f"{base_url}/api/custos?fonte=exemplo&dias=14&contas=producao,dados")
    data = json.loads(body)
    assert status == 200
    assert data["meta"]["selecionadas"] == ["producao", "dados"]
    assert len(data["diario"]["dias"]) == 14

    status, _, body = get(f"{base_url}/api/recomendacoes?fonte=exemplo")
    data = json.loads(body)
    assert status == 200
    assert data["resumo"]["oportunidades"] > 0


def test_api_tags_and_budgets(base_url):
    status, _, body = get(f"{base_url}/api/tags?fonte=exemplo&chave=Environment&dias=30")
    data = json.loads(body)
    assert status == 200
    assert data["chave"] == "Environment"
    assert data["cobertura"] > 0.8

    status, _, body = get(f"{base_url}/api/orcamentos?fonte=exemplo")
    assert status == 200
    assert len(json.loads(body)["itens"]) == 3

    status, _, _ = get(f"{base_url}/api/tags?fonte=exemplo&chave=%3Cscript%3E")
    assert status == 400


def test_weekly_report_download(base_url):
    status, headers, body = get(f"{base_url}/api/relatorio?fonte=exemplo")
    assert status == 200
    assert "attachment" in headers["Content-Disposition"]
    assert body.decode("utf-8").startswith("# Relatório semanal")


@pytest.mark.parametrize("query", ["fonte=hacker", "dias=3", "dias=abc", "fonte=aws&perfil=a%3Brm%20-rf"])
def test_invalid_parameters_return_400(base_url, query):
    status, _, body = get(f"{base_url}/api/custos?{query}")
    assert status == 400
    assert "erro" in json.loads(body)


def test_only_get_is_allowed(base_url):
    request = Request(f"{base_url}/api/custos", data=b"{}", method="POST")
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=5)
    assert error.value.code == 405
