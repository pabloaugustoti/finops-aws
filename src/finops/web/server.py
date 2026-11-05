"""Servidor HTTP local, só com a biblioteca padrão do Python.

Rotas:
    GET /                     -> interface (static/index.html)
    GET /static/<arquivo>     -> CSS, JS e ícone
    GET /api/custos           -> custos agregados (?fonte=&perfil=&dias=&contas=a,b&recarregar=1)
    GET /api/recomendacoes    -> recomendações de economia (?fonte=&perfil=&regioes=&recarregar=1)
    GET /api/relatorio        -> relatório semanal em Markdown (download)

Segurança: escuta só em 127.0.0.1, aceita só GET, bloqueia caminhos fora de
static/ e envia cabeçalhos que impedem conteúdo externo (CSP 'self').
"""

from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from finops.accounts import ConfigError
from finops.anomalies import detect_anomalies
from finops.recommendations import analyze
from finops.sources import (
    DEFAULT_ACCOUNTS_FILE,
    SOURCE_KINDS,
    build_inventory_source,
    build_source,
    run_collection,
    run_inventory,
)
from finops.web.api import costs_payload, recommendations_payload
from finops.weekly_report import build_weekly_report

STATIC_DIR = Path(__file__).parent / "static"
FETCH_DAYS = 90  # busca 90 dias de uma vez; trocar o período na tela não gera chamadas pagas
CACHE_TTL_SECONDS = 3600
PERIODS = {7, 14, 30, 60, 90}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon",
}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'",
}


class BadRequest(ValueError):
    pass


class MemoryCache:
    """Cache em memória das coletas, para a interface não refazer chamadas a cada clique."""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._items: dict[tuple, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._ttl, self._clock = ttl, clock

    def get_or_load(self, key: tuple, loader: Callable[[], Any], refresh: bool = False) -> Any:
        with self._lock:
            hit = self._items.get(key)
            if hit and not refresh and self._clock() - hit[0] < self._ttl:
                return hit[1]
        value = loader()  # fora do lock: coletas lentas não travam outras requisições
        with self._lock:
            self._items[key] = (self._clock(), value)
        return value


def _one(query: dict[str, list[str]], name: str, default: str) -> str:
    return (query.get(name) or [default])[0].strip() or default


class FinOpsApp:
    def __init__(self, config_path: Path = DEFAULT_ACCOUNTS_FILE, today: Callable[[], date] | None = None) -> None:
        self.config_path = config_path
        self.cache = MemoryCache()
        self._today = today or (lambda: datetime.now(timezone.utc).date())

    def _source_params(self, query: dict[str, list[str]]) -> tuple[str, str]:
        kind = _one(query, "fonte", "exemplo")
        if kind not in SOURCE_KINDS:
            raise BadRequest(f"fonte inválida: {kind}")
        profile = _one(query, "perfil", "finops-lab")
        if not profile.replace("-", "").replace("_", "").isalnum():
            raise BadRequest("perfil inválido")
        return kind, profile

    def _collection(self, kind: str, profile: str, refresh: bool):
        today = self._today()

        def load():
            source = build_source(kind, today, profile=profile, config_path=self.config_path)
            return source, run_collection(source, today, FETCH_DAYS)

        return today, *self.cache.get_or_load(("custos", kind, profile, today), load, refresh)

    def costs(self, query: dict[str, list[str]]) -> dict[str, Any]:
        kind, profile = self._source_params(query)
        try:
            days = int(_one(query, "dias", "30"))
        except ValueError:
            raise BadRequest("dias precisa ser um número") from None
        if days not in PERIODS:
            raise BadRequest(f"dias precisa ser um de {sorted(PERIODS)}")
        selected = [c for c in _one(query, "contas", "").split(",") if c] or None
        today, source, result = self._collection(kind, profile, "recarregar" in query)
        return costs_payload(result, today=today, days=days, label=source.label, paid=source.paid, selected=selected)

    def _inventory(self, kind: str, profile: str, regions: list[str] | None, refresh: bool):
        def load():
            source = build_inventory_source(kind, profile=profile, config_path=self.config_path, regions=regions)
            inventories = run_inventory(source)
            return source, inventories, analyze(inventories, datetime.now(timezone.utc))

        key = ("inventario", kind, profile, tuple(regions or ()))
        return self.cache.get_or_load(key, load, refresh)

    def recommendations(self, query: dict[str, list[str]]) -> dict[str, Any]:
        kind, profile = self._source_params(query)
        regions = [r for r in _one(query, "regioes", "").split(",") if r] or None
        source, inventories, recs = self._inventory(kind, profile, regions, "recarregar" in query)
        return recommendations_payload(recs, inventories, label=source.label)

    def weekly_report(self, query: dict[str, list[str]]) -> str:
        kind, profile = self._source_params(query)
        today, source, result = self._collection(kind, profile, refresh=False)
        _, _, recs = self._inventory(kind, profile, None, refresh=False)
        cutoff = today.toordinal() - 30
        anomalies = [e for e in detect_anomalies(result.records) if e.end.toordinal() >= cutoff]
        return build_weekly_report(result.records, today=today, source=source.label, anomalies=anomalies,
                                   recommendations=recs, forecast_amount=result.forecast_amount)


def make_handler(app: FinOpsApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "FinOpsLocal/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:  # log curto, sem query string
            print(f"[web] {self.command} {urlparse(self.path).path} -> {args[1] if len(args) > 1 else ''}")

        def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in {**SECURITY_HEADERS, **(extra or {})}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _static(self, relative: str) -> None:
            path = (STATIC_DIR / relative).resolve()
            if STATIC_DIR.resolve() not in path.parents or not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"erro": "não encontrado"})
                return
            content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
            self._send(HTTPStatus.OK, path.read_bytes(), content_type)

        def do_GET(self) -> None:  # noqa: N802 - nome exigido pelo http.server
            url = urlparse(self.path)
            query = parse_qs(url.query, keep_blank_values=True)
            try:
                if url.path in ("/", "/index.html"):
                    self._static("index.html")
                elif url.path == "/favicon.ico":
                    self._static("icone.svg")
                elif url.path.startswith("/static/"):
                    self._static(url.path.removeprefix("/static/"))
                elif url.path == "/api/custos":
                    self._json(HTTPStatus.OK, app.costs(query))
                elif url.path == "/api/recomendacoes":
                    self._json(HTTPStatus.OK, app.recommendations(query))
                elif url.path == "/api/relatorio":
                    body = app.weekly_report(query).encode("utf-8")
                    name = f"relatorio-finops-{date.today().isoformat()}.md"
                    self._send(HTTPStatus.OK, body, "text/markdown; charset=utf-8",
                               {"Content-Disposition": f'attachment; filename="{name}"'})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"erro": "rota não encontrada"})
            except BadRequest as error:
                self._json(HTTPStatus.BAD_REQUEST, {"erro": str(error)})
            except ConfigError as error:
                self._json(HTTPStatus.BAD_REQUEST, {
                    "erro": f"arquivo de contas: {error}",
                    "dica": "Copie accounts.example.toml para accounts.local.toml e preencha suas contas.",
                })
            except Exception as error:  # noqa: BLE001 - falhas da AWS viram uma mensagem amigável
                self._json(HTTPStatus.BAD_GATEWAY, {
                    "erro": str(error).splitlines()[0] if str(error) else type(error).__name__,
                    "dica": "Renove o login com: aws login --profile finops-lab",
                })

        def _method_not_allowed(self) -> None:
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"erro": "somente GET"})

        do_POST = do_PUT = do_DELETE = do_PATCH = _method_not_allowed  # noqa: N815

    return Handler


def serve(port: int = 8000, config_path: Path = DEFAULT_ACCOUNTS_FILE, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(FinOpsApp(config_path)))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Interface FinOps em {url}  (Ctrl+C para parar; acessível só deste computador)")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
