"""Linha de comando: `python -m finops <comando>`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from finops.accounts import ConfigError, load_accounts
from finops.aws_session import BILLING_REGION, assume_role_session, profile_session
from finops.cache import JsonCache
from finops.cost_explorer import PRICE_PER_REQUEST_USD
from finops.anomalies import detect_anomalies
from finops.recommendations import analyze
from finops.weekly_report import build_weekly_report
from finops.report import (
    build_summary,
    export_csv,
    export_recommendations_csv,
    fmt_usd,
    render_recommendations,
    render_text,
)
from finops.sources import (
    DEFAULT_ACCOUNTS_FILE,
    DEFAULT_CACHE_DIR,
    SOURCE_KINDS,
    build_inventory_source,
    build_source,
    run_collection,
    run_inventory,
)

DASHBOARD_APP = Path(__file__).parent / "dashboard" / "app.py"


def utc_today() -> date:
    # O faturamento da AWS usa dias em UTC.
    return datetime.now(timezone.utc).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finops", description="Ferramentas de FinOps para AWS.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="comando")

    summary = commands.add_parser("resumo", help="resumo de custos por conta e serviço")
    summary.add_argument(
        "--fonte", choices=SOURCE_KINDS, default="exemplo",
        help="'exemplo': dados fictícios de 3 contas; 'aws': só a conta do --perfil; "
             "'contas': todas as contas do --config via AssumeRole (padrão: exemplo)",
    )
    summary.add_argument("--perfil", default="finops-lab", help="perfil do AWS CLI para --fonte aws")
    summary.add_argument("--config", type=Path, default=DEFAULT_ACCOUNTS_FILE,
                         help=f"arquivo de contas para --fonte contas (padrão: {DEFAULT_ACCOUNTS_FILE})")
    summary.add_argument("--dias", type=int, default=30, help="tamanho da janela em dias, de 1 a 365 (padrão: 30)")
    summary.add_argument("--top", type=int, default=10, help="quantos serviços listar (padrão: 10)")
    summary.add_argument("--sem-cache", action="store_true", help="ignora o cache e consulta a API de novo")
    summary.add_argument("--csv", type=Path, help="exporta os custos diários por conta e serviço para CSV")
    summary.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)

    recs = commands.add_parser("recomendacoes", help="procura desperdício e estima a economia mensal")
    recs.add_argument("--fonte", choices=SOURCE_KINDS, default="exemplo",
                      help="'exemplo': inventário fictício com desperdício; 'aws'; 'contas' (padrão: exemplo)")
    recs.add_argument("--perfil", default="finops-lab", help="perfil do AWS CLI para --fonte aws")
    recs.add_argument("--config", type=Path, default=DEFAULT_ACCOUNTS_FILE)
    recs.add_argument("--regioes", help="regiões separadas por vírgula (padrão: todas as habilitadas)")
    recs.add_argument("--csv", type=Path, help="exporta todas as recomendações para CSV")

    anomalies = commands.add_parser("anomalias", help="detecta dias com custo fora do padrão")
    anomalies.add_argument("--fonte", choices=SOURCE_KINDS, default="exemplo")
    anomalies.add_argument("--perfil", default="finops-lab")
    anomalies.add_argument("--config", type=Path, default=DEFAULT_ACCOUNTS_FILE)
    anomalies.add_argument("--dias", type=int, default=30, help="mostra eventos dos últimos N dias (padrão: 30)")
    anomalies.add_argument("--sensibilidade", type=float, default=3.5,
                           help="z robusto mínimo; menor = mais alertas (padrão: 3.5)")
    anomalies.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)

    weekly = commands.add_parser("relatorio", help="relatório semanal em Markdown (custos, anomalias, economia)")
    weekly.add_argument("--fonte", choices=SOURCE_KINDS, default="exemplo")
    weekly.add_argument("--perfil", default="finops-lab")
    weekly.add_argument("--config", type=Path, default=DEFAULT_ACCOUNTS_FILE)
    weekly.add_argument("--regioes", help="regiões do inventário, separadas por vírgula (padrão: todas)")
    weekly.add_argument("--saida", type=Path, help="arquivo .md de saída (padrão: imprime na tela)")
    weekly.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)

    check = commands.add_parser("verificar-contas", help="testa o AssumeRole e as permissões em cada conta")
    check.add_argument("--config", type=Path, default=DEFAULT_ACCOUNTS_FILE)

    dashboard = commands.add_parser("dashboard", help="abre o dashboard no navegador (Streamlit)")
    dashboard.add_argument("--porta", type=int, default=8501)

    clear = commands.add_parser("limpar-cache", help="apaga as respostas da AWS guardadas em cache")
    clear.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help=argparse.SUPPRESS)
    return parser


def run_summary(args: argparse.Namespace, today: date) -> int:
    if not 1 <= args.dias <= 365:
        print("erro: --dias precisa estar entre 1 e 365", file=sys.stderr)
        return 2

    source = build_source(args.fonte, today, profile=args.perfil, config_path=args.config)
    result = run_collection(source, today, args.dias, use_cache=not args.sem_cache, cache_dir=args.cache_dir)
    summary = build_summary(result.records, today=today, days=args.dias, forecast_amount=result.forecast_amount)
    print(render_text(summary, source=source.label, top=args.top, warnings=result.errors,
                      forecast_is_partial=result.forecast_is_partial))

    if args.csv:
        export_csv(result.records, args.csv)
        print(f"\nCSV salvo em {args.csv}")
    if source.paid:
        print(f"\nChamadas pagas à API do Cost Explorer nesta execução: {result.api_calls} "
              f"(~{fmt_usd(result.api_calls * PRICE_PER_REQUEST_USD)})")
    return 1 if result.errors and not result.records else 0


def run_recommendations(args: argparse.Namespace) -> int:
    regions = [r.strip() for r in args.regioes.split(",") if r.strip()] if args.regioes else None
    source = build_inventory_source(args.fonte, profile=args.perfil, config_path=args.config, regions=regions)
    if args.fonte != "exemplo":
        print("Coletando inventário (EC2, EBS, snapshots, IPs) em todas as regiões...", file=sys.stderr)
    inventories = run_inventory(source)
    recs = analyze(inventories, datetime.now(timezone.utc))
    print(render_recommendations(recs, source=source.label, inventories=inventories))
    if args.csv:
        export_recommendations_csv(recs, args.csv)
        print(f"\nCSV salvo em {args.csv}")
    return 0


# Histórico usado na detecção: janela pedida + linha de base (14 dias) + folga
ANOMALY_HISTORY_DAYS = 90


def _recent_anomalies(records, today: date, days: int, threshold: float = 3.5):
    cutoff = today - timedelta(days=days)
    return [e for e in detect_anomalies(records, threshold=threshold) if e.end >= cutoff]


def run_anomalies(args: argparse.Namespace, today: date) -> int:
    source = build_source(args.fonte, today, profile=args.perfil, config_path=args.config)
    result = run_collection(source, today, ANOMALY_HISTORY_DAYS, cache_dir=args.cache_dir)
    events = _recent_anomalies(result.records, today, args.dias, args.sensibilidade)

    print(f"FinOps AWS: anomalias de custo nos últimos {args.dias} dias (fonte: {source.label})")
    print(f"Método: mediana e MAD dos 14 dias anteriores, z robusto >= {args.sensibilidade}\n")
    if not events:
        print("Nenhuma anomalia detectada. ✅")
    for e in events:
        period = e.start.isoformat() if e.start == e.end else f"{e.start.isoformat()} a {e.end.isoformat()}"
        print(f"  [{e.severity.upper():5}] {period}  {e.account} · {e.service}")
        print(f"          custo extra: {fmt_usd(e.impact)}  ·  pico {fmt_usd(Decimal(str(round(e.peak.amount, 2))))} "
              f"vs. esperado {fmt_usd(Decimal(str(round(e.peak.expected, 2))))}  ·  "
              f"z = {f'{e.peak.zscore:.1f}'.replace('.', ',')}")
    for message in result.errors:
        print(f"\n⚠ {message}")
    return 0


def run_weekly_report(args: argparse.Namespace, today: date) -> int:
    source = build_source(args.fonte, today, profile=args.perfil, config_path=args.config)
    result = run_collection(source, today, ANOMALY_HISTORY_DAYS, cache_dir=args.cache_dir)
    regions = [r.strip() for r in args.regioes.split(",") if r.strip()] if args.regioes else None
    inventory_source = build_inventory_source(args.fonte, profile=args.perfil, config_path=args.config,
                                              regions=regions)
    recs = analyze(run_inventory(inventory_source), datetime.now(timezone.utc))
    markdown = build_weekly_report(
        result.records, today=today, source=source.label,
        anomalies=_recent_anomalies(result.records, today, 30), recommendations=recs,
        forecast_amount=result.forecast_amount,
    )
    if args.saida:
        args.saida.parent.mkdir(parents=True, exist_ok=True)
        args.saida.write_text(markdown, encoding="utf-8")
        print(f"Relatório salvo em {args.saida}")
    else:
        print(markdown)
    return 0


def run_check(args: argparse.Namespace) -> int:
    config = load_accounts(args.config)
    sts = profile_session(config.hub_profile).client("sts", region_name=BILLING_REGION)
    hub = sts.get_caller_identity()
    print(f"Conta hub: {hub['Account']} (perfil {config.hub_profile})\n")

    failures = 0
    for account in config.accounts:
        try:
            session = assume_role_session(sts, account)
            identity = session.client("sts", region_name=BILLING_REGION).get_caller_identity()
            budgets = session.client("budgets", region_name=BILLING_REGION).describe_budgets(
                AccountId=account.account_id
            )
            print(f"  OK    {account.name} ({account.account_id})")
            print(f"        identidade: {identity['Arn']}")
            print(f"        leitura de budgets: {len(budgets.get('Budgets', []))} encontrado(s)")
        except Exception as error:  # noqa: BLE001
            failures += 1
            print(f"  FALHA {account.name} ({account.account_id}): {str(error).splitlines()[0]}")
    print(f"\n{len(config.accounts) - failures} de {len(config.accounts)} conta(s) acessível(is).")
    return 1 if failures else 0


def run_dashboard(args: argparse.Namespace) -> int:
    command = [sys.executable, "-m", "streamlit", "run", str(DASHBOARD_APP),
               "--server.port", str(args.porta), "--browser.gatherUsageStats", "false"]
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
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
    if args.command == "dashboard":
        return run_dashboard(args)

    from botocore.exceptions import BotoCoreError, ClientError

    try:
        if args.command == "verificar-contas":
            return run_check(args)
        if args.command == "recomendacoes":
            return run_recommendations(args)
        if args.command == "anomalias":
            return run_anomalies(args, today or utc_today())
        if args.command == "relatorio":
            return run_weekly_report(args, today or utc_today())
        return run_summary(args, today or utc_today())
    except ConfigError as error:
        print(f"erro de configuração: {error}", file=sys.stderr)
        print("dica: copie accounts.example.toml para accounts.local.toml e preencha", file=sys.stderr)
        return 2
    except (BotoCoreError, ClientError) as error:
        print(f"erro ao acessar a AWS: {error}", file=sys.stderr)
        print("dica: renove o login com  aws login --profile <perfil>", file=sys.stderr)
        return 1
