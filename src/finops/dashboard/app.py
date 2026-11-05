"""Dashboard de custos AWS (Streamlit).

Rode a partir da raiz do projeto:  python -m finops dashboard
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from finops.accounts import ConfigError
from finops.cost_explorer import PRICE_PER_REQUEST_USD
from finops.dashboard.data import (
    OTHER,
    daily_by_service,
    in_window,
    kpis,
    month_projection,
    records_frame,
    service_order,
    totals_by,
)
from finops.report import fmt_usd
from finops.sources import DEFAULT_ACCOUNTS_FILE, build_source, run_collection

# A coleta sempre busca 90 dias; mudar o período no filtro não gera novas chamadas pagas.
FETCH_DAYS = 90
PERIOD_OPTIONS = [7, 14, 30, 60, 90]
SOURCE_LABELS = {
    "exemplo": "Dados de exemplo (3 contas fictícias)",
    "aws": "Minha conta (perfil do AWS CLI)",
    "contas": "Várias contas (AssumeRole)",
}

# Paleta categórica validada (claro / escuro), na ordem fixa dos slots.
PALETTE = {
    "light": {
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
        "other": "#898781", "surface": "#fcfcfb", "text": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7",
    },
    "dark": {
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
        "other": "#898781", "surface": "#1a1a19", "text": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835",
    },
}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def theme_colors() -> dict:
    try:
        mode = st.context.theme.type or "light"
    except AttributeError:
        mode = "light"
    return PALETTE["dark" if mode == "dark" else "light"]


@st.cache_data(ttl=3600, show_spinner="Coletando custos...")
def load(kind: str, profile: str, config_path: str, today_iso: str) -> dict:
    today = date.fromisoformat(today_iso)
    source = build_source(kind, today, profile=profile, config_path=Path(config_path))
    result = run_collection(source, today, FETCH_DAYS)
    return {
        "label": source.label,
        "paid": source.paid,
        "records": result.records,
        "forecasts": {a.account: a.forecast.amount if a.forecast else None for a in result.accounts},
        "accounts": [a.account for a in result.accounts if not a.error],
        "errors": result.errors,
        "api_calls": result.api_calls,
    }


def style(chart: alt.Chart, colors: dict, height: int) -> alt.Chart:
    return (
        chart.properties(height=height, background="transparent")
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=colors["muted"], titleColor=colors["text"], gridColor=colors["grid"],
            domainColor=colors["axis"], tickColor=colors["axis"], labelFontSize=12, titleFontWeight="normal",
        )
        .configure_legend(labelColor=colors["text"], titleColor=colors["text"], orient="top", title=None)
    )


# Eixos no padrão brasileiro: 1.200 em vez de 1,200
PT_NUMBER = "replace(format(datum.value, ',.0f'), ',', '.')"


def money_axis(title: str) -> alt.Axis:
    return alt.Axis(title=title, tickCount=5, labelExpr=PT_NUMBER)


def date_axis() -> alt.Axis:
    return alt.Axis(title=None, format="%d/%m", grid=False, labelOverlap="greedy", labelSeparation=12)


def with_money(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(valor=df["custo"].map(lambda v: fmt_usd(Decimal(str(round(v, 2))))))


def daily_chart(daily: pd.DataFrame, order: list[str], colors: dict) -> alt.Chart:
    palette = [colors["other"] if s == OTHER else colors["series"][i] for i, s in enumerate(order)]
    data = with_money(daily).assign(dia_txt=daily["dia"].dt.strftime("%d/%m/%Y"))
    chart = alt.Chart(data).mark_bar(stroke=colors["surface"], strokeWidth=1).encode(
        x=alt.X("dia:T", axis=date_axis()),
        y=alt.Y("sum(custo):Q", axis=money_axis("US$ por dia")),
        color=alt.Color("servico:N", scale=alt.Scale(domain=order, range=palette), sort=order,
                        legend=alt.Legend(columns=3, labelLimit=320, symbolType="square")),
        order=alt.Order("ordem:Q", sort="ascending"),
        tooltip=[alt.Tooltip("dia_txt:N", title="Dia"), alt.Tooltip("servico:N", title="Serviço"),
                 alt.Tooltip("valor:N", title="Custo")],
    )
    return style(chart, colors, 340)


def ranking_chart(table: pd.DataFrame, column: str, title: str, colors: dict) -> alt.Chart:
    data = with_money(table).assign(pct=table["participacao"].map(lambda p: f"{p * 100:.1f}%".replace(".", ",")))
    # 35% de folga à direita para o rótulo de valor caber ao lado da barra
    domain_max = float(data["custo"].max()) * 1.35 if len(data) else 1.0
    base = alt.Chart(data).encode(
        y=alt.Y(f"{column}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X("custo:Q", scale=alt.Scale(domain=[0, domain_max], nice=False),
                axis=alt.Axis(title="US$ no período", tickCount=4, labelExpr=PT_NUMBER)),
        tooltip=[alt.Tooltip(f"{column}:N", title=title), alt.Tooltip("valor:N", title="Custo"),
                 alt.Tooltip("pct:N", title="Participação")],
    )
    bars = base.mark_bar(color=colors["series"][0], cornerRadiusEnd=4, height={"band": 0.7})
    labels = base.mark_text(align="left", dx=6, color=colors["text"]).encode(text="valor:N")
    return style(alt.layer(bars, labels), colors, max(120, 34 * len(data)))


def projection_chart(projection: pd.DataFrame, colors: dict) -> alt.Chart:
    data = with_money(projection).assign(dia_txt=projection["dia"].dt.strftime("%d/%m/%Y"))
    domain = ["Real", "Previsão"]
    base = alt.Chart(data).encode(
        x=alt.X("dia:T", axis=date_axis()),
        y=alt.Y("custo:Q", axis=money_axis("US$ acumulado no mês")),
        color=alt.Color("serie:N", scale=alt.Scale(domain=domain, range=colors["series"][:2]), sort=domain),
        strokeDash=alt.StrokeDash("serie:N", scale=alt.Scale(domain=domain, range=[[1, 0], [6, 4]]), legend=None),
        tooltip=[alt.Tooltip("dia_txt:N", title="Dia"), alt.Tooltip("serie:N", title="Série"),
                 alt.Tooltip("valor:N", title="Acumulado")],
    )
    line = base.mark_line(strokeWidth=2)
    points = base.mark_point(filled=True, size=70, stroke=colors["surface"], strokeWidth=2)
    # Rótulo direto no último ponto de cada série
    last = data.sort_values("dia").groupby("serie", as_index=False).tail(1)
    last = last.assign(rotulo=last["serie"] + ": " + last["valor"])
    labels = alt.Chart(last).mark_text(align="right", dx=-10, dy=-12, color=colors["text"], fontWeight="bold").encode(
        x="dia:T", y="custo:Q", text="rotulo:N",
    )
    return style(alt.layer(line, points, labels), colors, 280)


def sidebar() -> tuple[str, str, str, int]:
    st.sidebar.header("Fonte de dados")
    kind = st.sidebar.radio("Origem", list(SOURCE_LABELS), format_func=SOURCE_LABELS.get, label_visibility="collapsed")
    profile, config = "finops-lab", str(DEFAULT_ACCOUNTS_FILE)
    if kind == "aws":
        profile = st.sidebar.text_input("Perfil do AWS CLI", value=profile)
    if kind == "contas":
        config = st.sidebar.text_input("Arquivo de contas", value=config)
    if kind != "exemplo":
        st.sidebar.caption("Cada consulta nova ao Cost Explorer custa US$ 0,01. "
                           "Respostas repetidas vêm do cache em `data/cache/`.")
    if st.sidebar.button("Recarregar dados", use_container_width=True):
        load.clear()
    days = st.sidebar.select_slider("Período (dias)", options=PERIOD_OPTIONS, value=30)
    return kind, profile, config, days


def main() -> None:
    st.set_page_config(page_title="FinOps AWS", page_icon="💰", layout="wide")
    colors = theme_colors()
    kind, profile, config, days = sidebar()
    today = utc_today()

    st.title("FinOps AWS")
    try:
        data = load(kind, profile, config, today.isoformat())
    except ConfigError as error:
        st.error(f"Erro no arquivo de contas: {error}")
        st.info("Copie `accounts.example.toml` para `accounts.local.toml` e preencha suas contas.")
        return
    except Exception as error:  # noqa: BLE001 - mostra qualquer falha de credencial/rede na tela
        st.error(f"Não foi possível acessar a AWS: {str(error).splitlines()[0]}")
        st.info(f"Renove o login com `aws login --profile {profile}` e clique em **Recarregar dados**.")
        return

    api_note = ""
    if data["paid"]:
        api_note = (f" · chamadas pagas ao Cost Explorer nesta carga: {data['api_calls']} "
                    f"(~{fmt_usd(data['api_calls'] * PRICE_PER_REQUEST_USD)})")
    st.caption(f"Fonte: {data['label']} · dias em UTC · período encerrado em "
               f"{(today - pd.Timedelta(days=1)).strftime('%d/%m/%Y')}{api_note}")
    for message in data["errors"]:
        st.warning(f"Conta com problema (fora dos totais): {message}", icon="⚠️")

    all_df = records_frame(data["records"])
    accounts = data["accounts"]
    selected = st.multiselect("Contas", accounts, default=accounts) if len(accounts) > 1 else accounts
    df = all_df[all_df["conta"].isin(selected)]

    forecasts = [data["forecasts"][a] for a in selected if data["forecasts"].get(a) is not None]
    forecast = float(sum(forecasts)) if forecasts else None
    window = in_window(df, today, days)
    k = kpis(df, today, days, forecast)

    c1, c2, c3, c4 = st.columns(4)
    change = k.week_change
    c1.metric(f"Total em {days} dias", fmt_usd(Decimal(str(round(k.total, 2)))),
              delta=None if change is None else f"{change * 100:+.1f}% vs. semana anterior".replace(".", ","),
              delta_color="inverse", help="Variação: últimos 7 dias contra os 7 dias anteriores")
    c2.metric("Média diária", fmt_usd(Decimal(str(round(k.daily_average, 2)))))
    c3.metric("Mês atual até ontem", fmt_usd(Decimal(str(round(k.month_to_date, 2)))))
    c4.metric("Previsão de fechamento",
              "indisponível" if k.month_forecast is None else fmt_usd(Decimal(str(round(k.month_forecast, 2)))),
              help="Mês até ontem + previsão do Cost Explorer até o fim do mês")

    if window.empty or window["custo"].sum() == 0:
        st.info("Nenhum custo no período selecionado. Em uma conta nova isso é normal. "
                "Use **Dados de exemplo** na barra lateral para ver o dashboard completo.")
        return

    order = service_order(in_window(all_df, today, days))
    st.subheader("Custo diário por serviço")
    st.altair_chart(daily_chart(daily_by_service(window, order, today, days), order, colors),
                    use_container_width=True, theme=None)

    left, right = st.columns(2)
    with left:
        st.subheader("Por conta")
        st.altair_chart(ranking_chart(totals_by(window, "conta"), "conta", "Conta", colors),
                        use_container_width=True, theme=None)
    with right:
        st.subheader("Top 10 serviços")
        st.altair_chart(ranking_chart(totals_by(window, "servico").head(10), "servico", "Serviço", colors),
                        use_container_width=True, theme=None)

    st.subheader("Mês atual: acumulado e previsão")
    st.altair_chart(projection_chart(month_projection(df, today, forecast), colors),
                    use_container_width=True, theme=None)

    with st.expander("Tabela detalhada"):
        table = window.sort_values(["dia", "conta", "custo"], ascending=[False, True, False])
        st.dataframe(table, use_container_width=True, hide_index=True, column_config={
            "dia": st.column_config.DateColumn("Dia", format="DD/MM/YYYY"),
            "conta": "Conta", "servico": "Serviço",
            "custo": st.column_config.NumberColumn("Custo (US$)", format="%.4f"),
            "estimado": "Estimado",
        })
        st.download_button("Baixar CSV", table.to_csv(index=False).encode("utf-8"),
                           file_name=f"custos-{today.isoformat()}.csv", mime="text/csv")


main()
