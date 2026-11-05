"""Fontes de dados (custos e inventário), compartilhadas pela CLI e pelo dashboard."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from finops.accounts import load_accounts
from finops.aws_session import BILLING_REGION, assume_role_session, profile_session
from finops.cache import JsonCache
from finops.collector import ClientFactory, CollectionResult, collect
from finops.inventory import Inventory, collect_inventory
from finops.sample_client import SAMPLE_ACCOUNTS, SampleCostExplorerClient
from finops.sample_inventory import sample_inventory

SOURCE_KINDS = ("exemplo", "aws", "contas")
DEFAULT_CACHE_DIR = Path("data/cache")
DEFAULT_ACCOUNTS_FILE = Path("accounts.local.toml")

SessionFactory = Callable[[str], Any]


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


def _aws_sessions(kind: str, profile: str, config_path: Path) -> tuple[list[str], SessionFactory, str]:
    """Contas e uma fábrica de sessões boto3 para as fontes reais."""
    if kind == "aws":
        return [profile], (lambda _: profile_session(profile)), f"AWS, perfil {profile}"
    if kind == "contas":
        config = load_accounts(config_path)
        by_name = {a.name: a for a in config.accounts}
        sts = profile_session(config.hub_profile).client("sts", region_name=BILLING_REGION)
        label = f"AWS, {len(by_name)} conta(s) via AssumeRole a partir do perfil {config.hub_profile}"
        return list(by_name), (lambda name: assume_role_session(sts, by_name[name])), label
    raise ValueError(f"fonte desconhecida: {kind} (use {', '.join(SOURCE_KINDS)})")


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

    names, sessions, label = _aws_sessions(kind, profile, config_path)
    return Source(names, lambda name: sessions(name).client("ce", region_name=BILLING_REGION), label, paid=True)


def run_collection(
    source: Source, today: date, days: int, *, use_cache: bool = True, cache_dir: Path = DEFAULT_CACHE_DIR
) -> CollectionResult:
    window = collection_window(today, days)
    cache = JsonCache(cache_dir) if source.paid and use_cache else None
    return collect(
        source.names, source.factory,
        start=window.start, end=window.end, forecast_end=window.forecast_end, cache=cache,
    )


@dataclass(frozen=True)
class InventorySource:
    names: list[str]
    loader: Callable[[str], Inventory]
    label: str


def build_inventory_source(
    kind: str,
    *,
    profile: str = "finops-lab",
    config_path: Path = DEFAULT_ACCOUNTS_FILE,
    regions: list[str] | None = None,
    now: datetime | None = None,
) -> InventorySource:
    if kind == "exemplo":
        moment = now or datetime.now(timezone.utc)
        return InventorySource(list(SAMPLE_ACCOUNTS), lambda name: sample_inventory(name, moment), "dados de exemplo")

    names, sessions, label = _aws_sessions(kind, profile, config_path)
    return InventorySource(names, lambda name: collect_inventory(sessions(name), name, regions), label)


def run_inventory(source: InventorySource) -> list[Inventory]:
    """Inventário de cada conta; uma conta com erro vira um inventário vazio com o erro anotado."""
    inventories = []
    for name in source.names:
        try:
            inventories.append(source.loader(name))
        except Exception as error:  # noqa: BLE001
            inventories.append(Inventory(account=name, errors=[str(error).splitlines()[0]]))
    return inventories
