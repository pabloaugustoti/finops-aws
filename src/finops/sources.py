"""Fontes de dados (custos, tags, orçamentos e inventário), compartilhadas pela CLI e pela interface web."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from finops.accounts import load_accounts
from finops.aws_session import BILLING_REGION, assume_role_session, profile_session
from finops.budgets import Budget, fetch_budgets, sample_budgets
from finops.cache import JsonCache
from finops.collector import ClientFactory, CollectionResult, collect
from finops.cost_explorer import CostExplorer
from finops.inventory import Inventory, collect_inventory
from finops.models import TagCost
from finops.sample_client import SAMPLE_ACCOUNTS, SAMPLE_TAGS, SampleCostExplorerClient
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


def sample_client(name: str, today: date) -> SampleCostExplorerClient:
    seed, scale, spike = SAMPLE_ACCOUNTS[name]
    return SampleCostExplorerClient(today=today, seed=seed, scale=scale, spike=spike, tags=SAMPLE_TAGS.get(name))


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
        return Source(list(SAMPLE_ACCOUNTS), lambda name: sample_client(name, today), "dados de exemplo", paid=False)

    names, sessions, label = _aws_sessions(kind, profile, config_path)
    return Source(names, lambda name: sessions(name).client("ce", region_name=BILLING_REGION), label, paid=True)


def run_collection(
    source: Source, today: date, days: int, *, use_cache: bool = True, cache_dir: Path = DEFAULT_CACHE_DIR
) -> CollectionResult:
    window = collection_window(today, days)
    cache = JsonCache(cache_dir) if source.paid and use_cache else None
    return collect(
        source.names,
        source.factory,
        start=window.start,
        end=window.end,
        forecast_end=window.forecast_end,
        cache=cache,
    )


@dataclass
class TagResult:
    tag_key: str
    costs: list[TagCost] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    api_calls: int = 0


def run_tags(
    source: Source,
    today: date,
    days: int,
    tag_key: str,
    *,
    use_cache: bool = True,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> TagResult:
    """Custo do período por valor de tag, em cada conta (uma conta com erro não derruba as outras)."""
    cache = JsonCache(cache_dir) if source.paid and use_cache else None
    result = TagResult(tag_key)
    for name in source.names:
        explorer: CostExplorer | None = None
        try:
            explorer = CostExplorer(source.factory(name), cache=cache, account=name)
            result.costs += explorer.costs_by_tag(today - timedelta(days=days), today, tag_key)
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{name}: {str(error).splitlines()[0]}")
        if explorer is not None:
            result.api_calls += explorer.api_calls
    return result


@dataclass
class BudgetResult:
    label: str
    budgets: list[Budget] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_budgets(
    kind: str, today: date, *, profile: str = "finops-lab", config_path: Path = DEFAULT_ACCOUNTS_FILE
) -> BudgetResult:
    """Orçamentos de cada conta (AWS Budgets é gratuito para leitura)."""
    if kind == "exemplo":
        result = BudgetResult("dados de exemplo")
        for name in SAMPLE_ACCOUNTS:
            result.budgets += sample_budgets(name, sample_client(name, today), today)
        return result

    names, sessions, label = _aws_sessions(kind, profile, config_path)
    result = BudgetResult(label)
    for name in names:
        try:
            result.budgets += fetch_budgets(sessions(name), name)
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{name}: {str(error).splitlines()[0]}")
    return result


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
        moment = now or datetime.now(UTC)
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
