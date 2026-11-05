"""Inventário de exemplo com desperdício proposital, para demonstrar as recomendações.

Cada conta fictícia (mesmos nomes de `sample_client.SAMPLE_ACCOUNTS`) tem um
cenário diferente, parecido com o que se encontra em ambientes reais.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from finops.inventory import Address, Instance, Inventory, Snapshot, Volume

TAGS_PROD = {"Project": "loja", "Environment": "producao"}
TAGS_DEV = {"Project": "loja", "Environment": "dev"}
TAGS_DATA = {"Project": "analytics", "Environment": "producao"}


def sample_inventory(account: str, now: datetime) -> Inventory:
    def ago(days: int) -> datetime:
        return now - timedelta(days=days)

    if account == "producao":
        r = "us-east-1"
        return Inventory(
            account=account, regions=[r],
            instances=[
                Instance("i-0web01", r, "m5.large", "running", ago(200), volume_ids=("vol-0web01",),
                         cpu_avg=38.0, cpu_max=81.0, tags=TAGS_PROD),
                Instance("i-0batch1", r, "m5.xlarge", "running", ago(150), volume_ids=("vol-0batch1",),
                         cpu_avg=2.1, cpu_max=6.4, tags=TAGS_PROD),
                Instance("i-0legado", r, "t3.medium", "stopped", ago(400), stopped_since=ago(63),
                         volume_ids=("vol-0legado",), tags={"Project": "loja"}),
            ],
            volumes=[
                Volume("vol-0web01", r, 100, "gp2", "in-use", ago(200), "i-0web01", iops=300, tags=TAGS_PROD),
                Volume("vol-0batch1", r, 500, "gp2", "in-use", ago(150), "i-0batch1", iops=1500, tags=TAGS_PROD),
                Volume("vol-0legado", r, 100, "gp2", "in-use", ago(400), "i-0legado", iops=300),
                Volume("vol-0solto1", r, 200, "gp2", "available", ago(120), iops=600),
                Volume("vol-0solto2", r, 50, "gp3", "available", ago(5), iops=3000, throughput=125, tags=TAGS_PROD),
            ],
            addresses=[
                Address("eipalloc-0web", "54.10.20.30", r, association_id="eipassoc-0web", instance_id="i-0web01",
                        tags=TAGS_PROD),
                Address("eipalloc-0velho", "54.10.20.31", r),
            ],
            snapshots=[
                Snapshot("snap-0diario", r, 100, ago(1), "vol-0web01", "backup diário", TAGS_PROD),
                Snapshot("snap-0migracao", r, 500, ago(240), "vol-0apagado", "antes da migração 2025"),
                Snapshot("snap-0trimestral", r, 100, ago(95), "vol-0web01", "backup trimestral", TAGS_PROD),
            ],
        )

    if account == "desenvolvimento":
        r = "us-east-2"
        return Inventory(
            account=account, regions=[r],
            instances=[
                Instance("i-0dev01", r, "t3.large", "running", ago(90), volume_ids=("vol-0dev01",),
                         cpu_avg=12.0, cpu_max=64.0, tags=TAGS_DEV),
                Instance("i-0teste", r, "t3.medium", "stopped", ago(60), stopped_since=ago(21),
                         volume_ids=("vol-0teste",)),
            ],
            volumes=[
                Volume("vol-0dev01", r, 80, "gp3", "in-use", ago(90), "i-0dev01", iops=3000, throughput=125,
                       tags=TAGS_DEV),
                Volume("vol-0teste", r, 30, "gp2", "in-use", ago(60), "i-0teste", iops=100),
                Volume("vol-0esquecido", r, 100, "io1", "available", ago(45), iops=1000),
            ],
            addresses=[Address("eipalloc-0dev", "3.20.30.40", r)],
        )

    if account == "dados":
        r = "us-east-1"
        return Inventory(
            account=account, regions=[r],
            volumes=[
                Volume("vol-0etl", r, 1500, "gp2", "in-use", ago(300), "i-0etl", iops=4500, tags=TAGS_DATA),
            ],
            instances=[
                Instance("i-0etl", r, "r5.xlarge", "running", ago(300), volume_ids=("vol-0etl",),
                         cpu_avg=46.0, cpu_max=97.0, tags=TAGS_DATA),
            ],
            snapshots=[
                Snapshot(f"snap-0hist{n}", r, 1500, ago(120 + 30 * n), "vol-0etl", f"histórico {n}", TAGS_DATA)
                for n in range(3)
            ],
        )

    return Inventory(account=account)
