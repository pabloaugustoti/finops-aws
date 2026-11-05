"""Fontes de dados de custo, compartilhadas pela CLI e pelo dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from finops.accounts import load_accounts
from finops.aws_session import BILLING_REGION, assume_role_session, profile_session
from finops.cache import JsonCache
from finops.collector import ClientFactory, CollectionResult, collect
from finops.sample_client import SAMPLE_ACCOUNTS, SampleCostExplorerClient

SOURCE_KINDS = ("exemplo", "aws", "contas")
DEFAULT_CACHE_DIR = Path("data/cache")
DEFAULT_ACCOUNTS_FILE = Path("accounts.local.toml")


@dataclass(frozen=True)
class Source:
    names: list[str]
    factory: ClientFactory
    label: str
    paid: bool  # True quando consulta a API real (US$ 0,01 por requisição)


@dataclass(frozen=True)
class Window:
    start: date  # início da coleta (cobre a janela e o mês atual)
    end: date  # hoje (exclusivo)
    forecast_end: date  # primeiro dia do próximo mês


def collection_window(today: date, days: int) -> Window:
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return Window(start=min(today - timedelta(days=days), month_start), end=today, forecast_end=next_month)


def build_source(
    kind: str,
    today: date,
    *,
    profile: str = "finops-lab",
    config_path: Path = DEFAULT_ACCOUNTS_FILE,
) -> Source:
    if kind == "exemplo":
        def sample_factory(name: str) -> SampleCostExplorerClient:
            seed, scale, spike = SAMPLE_ACCOUNTS[name]
            return SampleCostExplorerClient(today=today, seed=seed, scale=scale, spike=spike)

        return Source(list(SAMPLE_ACCOUNTS), sample_factory, "dados de exemplo", paid=False)

    if kind == "aws":
        def profile_factory(_: str):
            return profile_session(profile).client("ce", region_name=BILLING_REGION)

        return Source([profile], profile_factory, f"AWS, perfil {profile}", paid=True)

    if kind == "contas":
        config = load_accounts(config_path)
        by_name = {a.name: a for a in config.accounts}
        sts = profile_session(config.hub_profile).client("sts")

        def assume_factory(name: str):
            return assume_role_session(sts, by_name[name]).client("ce", region_name=BILLING_REGION)

        label = f"AWS, {len(by_name)} conta(s) via AssumeRole a partir do perfil {config.hub_profile}"
        return Source(list(by_name), assume_factory, label, paid=True)

    raise ValueError(f"fonte desconhecida: {kind} (use {', '.join(SOURCE_KINDS)})")


def run_collection(
    source: Source, today: date, days: int, *, use_cache: bool = True, cache_dir: Path = DEFAULT_CACHE_DIR
) -> CollectionResult:
    window = collection_window(today, days)
    cache = JsonCache(cache_dir) if source.paid and use_cache else None
    return collect(
        source.names, source.factory,
        start=window.start, end=window.end, forecast_end=window.forecast_end, cache=cache,
    )
