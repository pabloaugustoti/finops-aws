"""Linha de comando: `python -m finops <comando>`."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from finops.cache import JsonCache
from finops.cost_explorer import CostExplorer
from finops.report import build_summary, export_csv, fmt_usd, render_text
from finops.sample_client import SampleCostExplorerClient

DEFAULT_CACHE_DIR = Path("data/cache")
BILLING_REGION = "us-east-1"  # Cost Explorer e Budgets respondem nesta região


def utc_today() -> date:
    # O faturamento da AWS usa dias em UTC.
    return datetime.now(timezone.utc).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finops", description="Ferramentas de FinOps para AWS.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="comando")

    summary = commands.add_parser("resumo", help="resumo de custos por serviço")
    summary.add_argument("--fonte", choices=["exemplo", "aws"], default="exemplo",
                         help="'exemplo' usa dados fictícios; 'aws' consulta sua conta (padrão: exemplo)")
    summary.add_argument("--perfil", default="finops-lab", help="perfil do AWS CLI (padrão: finops-lab)")
    summary.add_argument("--dias", type=int, default=30, help="tamanho da janela em dias, de 1 a 365 (padrão: 30)")
    summary.add_argument("--top", type=int, default=10, help="quantos serviços listar (padrão: 10)")
    summary.add_argument("--sem-cache", action="store_true", help="ignora o cache e consulta a API de novo")
    summary.add_argument("--csv", type=Path, help="exporta os custos diários por serviço para este arquivo CSV")
    summary.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)

    clear = commands.add_parser("limpar-cache", help="apaga as respostas da AWS guardadas em cache")
    clear.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)
    return parser


def make_aws_client(profile: str):
    import boto3

    return boto3.Session(profile_name=profile).client("ce", region_name=BILLING_REGION)


def run_summary(args: argparse.Namespace, today: date) -> int:
    if not 1 <= args.dias <= 365:
        print("erro: --dias precisa estar entre 1 e 365", file=sys.stderr)
        return 2

    if args.fonte == "exemplo":
        explorer = CostExplorer(SampleCostExplorerClient(today=today))
        source = "dados de exemplo"
    else:
        cache = None if args.sem_cache else JsonCache(args.cache_dir)
        explorer = CostExplorer(make_aws_client(args.perfil), cache=cache)
        source = f"AWS, perfil {args.perfil}"

    month_start = today.replace(day=1)
    start = min(today - timedelta(days=args.dias), month_start)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    records = explorer.costs_by_service(start, today) if start < today else []
    forecast = explorer.forecast(today, next_month)

    summary = build_summary(records, today=today, days=args.dias, forecast=forecast)
    print(render_text(summary, source=source, top=args.top))

    if args.csv:
        export_csv(records, args.csv)
        print(f"\nCSV salvo em {args.csv}")
    if args.fonte == "aws":
        print(f"\nChamadas pagas à API do Cost Explorer nesta execução: {explorer.api_calls} "
              f"(~{fmt_usd(explorer.estimated_api_cost)})")
    return 0


def main(argv: list[str] | None = None, today: date | None = None) -> int:
    # Garante que os caracteres de gráfico (█ ▁▂▃) não quebrem consoles antigos do Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    if args.command == "limpar-cache":
        removed = JsonCache(args.cache_dir).clear()
        print(f"{removed} arquivo(s) removido(s) de {args.cache_dir}")
        return 0

    from botocore.exceptions import BotoCoreError, ClientError

    try:
        return run_summary(args, today or utc_today())
    except (BotoCoreError, ClientError) as error:
        print(f"erro ao acessar a AWS: {error}", file=sys.stderr)
        print(f"dica: renove o login com  aws login --profile {args.perfil}", file=sys.stderr)
        return 1
