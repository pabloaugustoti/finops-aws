"""Motor de recomendações: regras que procuram desperdício no inventário.

Cada regra é uma função pura (inventário -> recomendações), fácil de testar
e de estender. A economia é uma ESTIMATIVA mensal com a tabela de `pricing`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finops import pricing
from finops.inventory import REQUIRED_TAGS, Inventory, Volume

SEVERITY_ORDER = {"alta": 0, "media": 1, "baixa": 2}

# Limiares (ajustáveis)
UNATTACHED_VOLUME_HIGH_DAYS = 30
OLD_SNAPSHOT_DAYS = 90
STOPPED_INSTANCE_DAYS = 7
IDLE_CPU_AVG = 5.0
IDLE_CPU_MAX = 10.0
IDLE_MIN_AGE_DAYS = 14
DOWNSIZE_SAVINGS = Decimal("0.5")  # reduzir 1 tamanho costuma cortar ~50% do preço
SNAPSHOT_SHARED_FACTOR = Decimal("0.2")  # blocos exclusivos estimados quando há vários snapshots do volume


def _pct(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")


@dataclass(frozen=True)
class Recommendation:
    rule: str
    title: str
    account: str
    region: str
    resource_id: str
    detail: str
    action: str
    severity: str  # "alta" | "media" | "baixa"
    monthly_savings: Decimal | None  # None = governança, sem economia direta

    @property
    def category(self) -> str:
        return "economia" if self.monthly_savings is not None else "governança"


Rule = Callable[[Inventory, datetime], list[Recommendation]]


def _age_days(moment: datetime, now: datetime) -> int:
    return (now - moment).days


def _volume_cost(volume: Volume) -> Decimal:
    return pricing.volume_monthly_cost(volume.volume_type, volume.size_gb, volume.iops, volume.throughput)


def _long_stopped_instances(inv: Inventory, now: datetime) -> set[str]:
    return {
        i.id
        for i in inv.instances
        if i.state == "stopped" and _age_days(i.stopped_since or i.launched, now) >= STOPPED_INSTANCE_DAYS
    }


def rule_gp2_to_gp3(inv: Inventory, now: datetime) -> list[Recommendation]:
    # Volumes de instâncias paradas há muito tempo ficam na regra "instância parada"
    # (a sugestão lá é encerrar), para não contar a mesma economia duas vezes.
    skip_instances = _long_stopped_instances(inv, now)
    recs = []
    for v in inv.volumes:
        if v.volume_type != "gp2" or v.state != "in-use" or v.instance_id in skip_instances:
            continue  # volumes soltos entram na regra de volume solto
        savings = _volume_cost(v) - pricing.gp3_equivalent_cost(v.size_gb)
        if savings <= 0:
            continue
        recs.append(
            Recommendation(
                rule="ebs-gp2-para-gp3",
                title="Migrar volume gp2 para gp3",
                account=inv.account,
                region=v.region,
                resource_id=v.id,
                severity="media",
                monthly_savings=savings,
                detail=(
                    f"gp2 de {v.size_gb} GB anexado a {v.instance_id}; gp3 é ~20% mais barato com o mesmo desempenho"
                ),
                action=f"aws ec2 modify-volume --region {v.region} --volume-id {v.id} --volume-type gp3 (sem parada)",
            )
        )
    return recs


def rule_unattached_volume(inv: Inventory, now: datetime) -> list[Recommendation]:
    recs = []
    for v in inv.volumes:
        if v.state != "available":
            continue
        age = _age_days(v.created, now)
        recs.append(
            Recommendation(
                rule="ebs-volume-solto",
                title="Volume EBS sem uso",
                account=inv.account,
                region=v.region,
                resource_id=v.id,
                severity="alta" if age >= UNATTACHED_VOLUME_HIGH_DAYS else "media",
                monthly_savings=_volume_cost(v),
                detail=f"{v.volume_type} de {v.size_gb} GB sem instância, criado há {age} dias",
                action="Criar um snapshot (se precisar guardar os dados) e excluir o volume",
            )
        )
    return recs


def rule_idle_elastic_ip(inv: Inventory, now: datetime) -> list[Recommendation]:
    return [
        Recommendation(
            rule="eip-ocioso",
            title="IP elástico sem uso",
            account=inv.account,
            region=a.region,
            resource_id=a.allocation_id,
            severity="alta",
            monthly_savings=pricing.public_ipv4_monthly_cost(),
            detail=f"IP {a.public_ip} alocado, mas não associado a nenhum recurso",
            action=f"aws ec2 release-address --region {a.region} --allocation-id {a.allocation_id}",
        )
        for a in inv.addresses
        if a.association_id is None
    ]


def rule_old_snapshot(inv: Inventory, now: datetime) -> list[Recommendation]:
    """Snapshots são incrementais: quando há vários do mesmo volume, apagar um só libera
    os blocos exclusivos dele. Estimamos esses blocos em SNAPSHOT_SHARED_FACTOR do tamanho."""
    existing = {v.id for v in inv.volumes}
    per_volume: dict[str | None, int] = {}
    for s in inv.snapshots:
        per_volume[s.volume_id] = per_volume.get(s.volume_id, 0) + 1

    recs = []
    for s in inv.snapshots:
        age = _age_days(s.created, now)
        if age < OLD_SNAPSHOT_DAYS:
            continue
        orphan = s.volume_id not in existing
        shared = per_volume[s.volume_id] > 1
        factor = SNAPSHOT_SHARED_FACTOR if shared else Decimal("1")
        origin = "volume de origem já excluído" if orphan else f"volume {s.volume_id} ainda existe"
        basis = (
            f"estimado em {int(factor * 100)}% do tamanho, pois há outros snapshots do mesmo volume"
            if shared
            else "estimativa máxima"
        )
        recs.append(
            Recommendation(
                rule="snapshot-antigo",
                title="Snapshot antigo" + (" e órfão" if orphan else ""),
                account=inv.account,
                region=s.region,
                resource_id=s.id,
                severity="media" if orphan else "baixa",
                monthly_savings=pricing.SNAPSHOT_GB_MONTH * s.size_gb * factor,
                detail=f"{s.size_gb} GB, criado há {age} dias, {origin} ({basis})",
                action="Confirmar que não é backup exigido e excluir, ou mover para o EBS Snapshots Archive",
            )
        )
    return recs


def rule_stopped_instance(inv: Inventory, now: datetime) -> list[Recommendation]:
    volumes = {v.id: v for v in inv.volumes}
    recs = []
    for i in inv.instances:
        if i.state != "stopped":
            continue
        since = i.stopped_since or i.launched
        days = _age_days(since, now)
        if days < STOPPED_INSTANCE_DAYS:
            continue
        attached = [volumes[v] for v in i.volume_ids if v in volumes]
        cost = sum((_volume_cost(v) for v in attached), Decimal("0"))
        size = sum(v.size_gb for v in attached)
        recs.append(
            Recommendation(
                rule="instancia-parada",
                title="Instância parada há muito tempo",
                account=inv.account,
                region=i.region,
                resource_id=i.id,
                severity="media",
                monthly_savings=cost,
                detail=f"{i.instance_type} parada há {days} dias; continua pagando {size} GB de disco EBS",
                action="Criar uma AMI ou snapshot e encerrar a instância (terminate)",
            )
        )
    return recs


def rule_idle_instance(inv: Inventory, now: datetime) -> list[Recommendation]:
    recs = []
    for i in inv.instances:
        if i.state != "running" or i.cpu_avg is None or i.cpu_max is None:
            continue
        if i.cpu_avg >= IDLE_CPU_AVG or i.cpu_max >= IDLE_CPU_MAX:
            continue
        if _age_days(i.launched, now) < IDLE_MIN_AGE_DAYS:
            continue
        monthly = pricing.instance_monthly_cost(i.instance_type)
        recs.append(
            Recommendation(
                rule="instancia-ociosa",
                title="Instância ociosa (superdimensionada)",
                account=inv.account,
                region=i.region,
                resource_id=i.id,
                severity="alta",
                monthly_savings=monthly * DOWNSIZE_SAVINGS if monthly is not None else None,
                detail=f"{i.instance_type} com CPU média de {_pct(i.cpu_avg)} (pico {_pct(i.cpu_max)}) em 14 dias",
                action="Reduzir para um tamanho menor, agendar para desligar fora do horário ou encerrar",
            )
        )
    return recs


def rule_missing_tags(inv: Inventory, now: datetime) -> list[Recommendation]:
    resources = (
        [(v.id, v.region, "volume", v.tags) for v in inv.volumes]
        + [(i.id, i.region, "instância", i.tags) for i in inv.instances]
        + [(s.id, s.region, "snapshot", s.tags) for s in inv.snapshots]
        + [(a.allocation_id, a.region, "IP elástico", a.tags) for a in inv.addresses]
    )
    recs = []
    for resource_id, region, kind, tags in resources:
        missing = [t for t in REQUIRED_TAGS if not tags.get(t)]
        if not missing:
            continue
        recs.append(
            Recommendation(
                rule="sem-tags",
                title="Recurso sem tags de custo",
                account=inv.account,
                region=region,
                resource_id=resource_id,
                severity="baixa",
                monthly_savings=None,
                detail=f"{kind} sem as tags: {', '.join(missing)}",
                action="Adicionar as tags para permitir alocar o custo por projeto e ambiente",
            )
        )
    return recs


ALL_RULES: list[Rule] = [
    rule_idle_instance,
    rule_unattached_volume,
    rule_idle_elastic_ip,
    rule_stopped_instance,
    rule_gp2_to_gp3,
    rule_old_snapshot,
    rule_missing_tags,
]


def analyze(inventories: list[Inventory], now: datetime, rules: list[Rule] | None = None) -> list[Recommendation]:
    recs = [rec for inv in inventories for rule in (rules or ALL_RULES) for rec in rule(inv, now)]
    return sorted(
        recs,
        key=lambda r: (r.monthly_savings is None, -(r.monthly_savings or 0), SEVERITY_ORDER[r.severity], r.resource_id),
    )


def total_savings(recs: list[Recommendation]) -> Decimal:
    return sum((r.monthly_savings for r in recs if r.monthly_savings is not None), Decimal("0"))


def savings_by_rule(recs: list[Recommendation]) -> list[tuple[str, int, Decimal]]:
    """(título da regra, quantidade, economia mensal), da maior economia para a menor."""
    groups: dict[str, tuple[int, Decimal]] = {}
    for r in recs:
        count, amount = groups.get(r.title.replace(" e órfão", ""), (0, Decimal("0")))
        groups[r.title.replace(" e órfão", "")] = (count + 1, amount + (r.monthly_savings or 0))
    return sorted(((t, c, a) for t, (c, a) in groups.items()), key=lambda item: item[2], reverse=True)
