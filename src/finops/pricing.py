"""Tabela de preços simplificada (USD, região us-east-1, preço sob demanda).

Os valores são de referência para **estimar** economia. Preços variam por
região e mudam com o tempo: para números exatos, use a AWS Price List API ou
o Cost and Usage Report (fase 6).
"""

from __future__ import annotations

from decimal import Decimal

D = Decimal
HOURS_PER_MONTH = D("730")

# EBS: USD por GB-mês
EBS_GB_MONTH: dict[str, Decimal] = {
    "gp2": D("0.10"),
    "gp3": D("0.08"),
    "io1": D("0.125"),
    "io2": D("0.125"),
    "st1": D("0.045"),
    "sc1": D("0.015"),
    "standard": D("0.05"),
}
GP3_FREE_IOPS = 3000
GP3_FREE_THROUGHPUT = 125  # MB/s
GP3_IOPS_MONTH = D("0.005")  # por IOPS provisionado acima de 3.000
GP3_THROUGHPUT_MONTH = D("0.04")  # por MB/s acima de 125
PROVISIONED_IOPS_MONTH = D("0.065")  # io1/io2

SNAPSHOT_GB_MONTH = D("0.05")
PUBLIC_IPV4_HOUR = D("0.005")  # todo IPv4 público é cobrado desde fev/2024

# EC2 Linux sob demanda: USD por hora (amostra dos tipos mais comuns)
INSTANCE_HOURLY: dict[str, Decimal] = {
    "t2.micro": D("0.0116"), "t3.micro": D("0.0104"), "t3.small": D("0.0208"),
    "t3.medium": D("0.0416"), "t3.large": D("0.0832"), "t3.xlarge": D("0.1664"),
    "m5.large": D("0.096"), "m5.xlarge": D("0.192"), "m5.2xlarge": D("0.384"),
    "m6i.large": D("0.096"), "m6i.xlarge": D("0.192"),
    "c5.large": D("0.085"), "c5.xlarge": D("0.17"),
    "r5.large": D("0.126"), "r5.xlarge": D("0.252"),
}


def gp2_baseline_iops(size_gb: int) -> int:
    """gp2 entrega 3 IOPS por GB, entre 100 e 16.000."""
    return min(max(3 * size_gb, 100), 16000)


def volume_monthly_cost(volume_type: str, size_gb: int, iops: int | None = None, throughput: int | None = None) -> Decimal:
    price = EBS_GB_MONTH.get(volume_type)
    if price is None:
        return D("0")
    cost = price * size_gb
    if volume_type == "gp3":
        cost += max(0, (iops or GP3_FREE_IOPS) - GP3_FREE_IOPS) * GP3_IOPS_MONTH
        cost += max(0, (throughput or GP3_FREE_THROUGHPUT) - GP3_FREE_THROUGHPUT) * GP3_THROUGHPUT_MONTH
    elif volume_type in ("io1", "io2"):
        cost += (iops or 0) * PROVISIONED_IOPS_MONTH
    return cost


def gp3_equivalent_cost(size_gb: int) -> Decimal:
    """Custo de um gp3 com o mesmo desempenho de IOPS que um gp2 do mesmo tamanho."""
    return volume_monthly_cost("gp3", size_gb, iops=max(GP3_FREE_IOPS, gp2_baseline_iops(size_gb)))


def instance_monthly_cost(instance_type: str) -> Decimal | None:
    hourly = INSTANCE_HOURLY.get(instance_type)
    return hourly * HOURS_PER_MONTH if hourly is not None else None


def public_ipv4_monthly_cost() -> Decimal:
    return PUBLIC_IPV4_HOUR * HOURS_PER_MONTH
