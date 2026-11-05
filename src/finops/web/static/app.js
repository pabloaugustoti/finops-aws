// Interface FinOps AWS: estado, chamadas à API local e renderização (JavaScript puro).
import { fmtLongDate, fmtMoney, fmtPct, fmtShortDate, h, hbars, monthLine, stackedBars } from "./charts.js";

const $ = (id) => document.getElementById(id);
const SERIES_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];
const SEVERITY = { alta: "● Alta", media: "◐ Média", baixa: "○ Baixa" };
const THEMES = ["auto", "light", "dark"];
const THEME_LABEL = { auto: "automático", light: "claro", dark: "escuro" };

// ---------- preferências locais (só conveniência; tudo funciona sem) ----------
const store = {
  get(key, fallback) { try { return localStorage.getItem(`finops.${key}`) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(`finops.${key}`, value); } catch { /* modo privado */ } },
};

// Parâmetros da URL (ex.: ?aba=recomendacoes&tema=escuro&dias=90) têm prioridade sobre o que
// ficou salvo: permitem compartilhar um link que já abre na visão certa.
const url = new URLSearchParams(window.location.search);
const fromUrl = {
  fonte: ["exemplo", "aws", "contas"].includes(url.get("fonte")) ? url.get("fonte") : null,
  aba: { custos: "custos", recomendacoes: "recs" }[url.get("aba")] ?? null,
  tema: { auto: "auto", claro: "light", escuro: "dark" }[url.get("tema")] ?? null,
  dias: ["7", "14", "30", "60", "90"].includes(url.get("dias")) ? url.get("dias") : null,
};

const state = {
  fonte: fromUrl.fonte ?? store.get("fonte", "exemplo"),
  perfil: store.get("perfil", "finops-lab"),
  dias: Number(fromUrl.dias ?? store.get("dias", "30")),
  contas: null, // null = todas
  aba: fromUrl.aba ?? store.get("aba", "custos"),
  categoria: "todas",
  busca: "",
  ordem: { chave: "economia_mes", direcao: "desc" },
  tema: fromUrl.tema ?? store.get("tema", "auto"),
  chaveTag: "Project",
};
let costs = null;
let budgets = null;
let tags = null;
let recs = null;
let recsKey = null;

// ---------- API ----------
async function api(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([k, v]) => v !== null && v !== undefined && url.searchParams.set(k, v));
  const response = await fetch(url);
  const body = await response.json().catch(() => ({ erro: `HTTP ${response.status}` }));
  if (!response.ok) throw Object.assign(new Error(body.erro || "erro desconhecido"), { dica: body.dica });
  return body;
}

const sourceParams = () => ({ fonte: state.fonte, perfil: state.fonte === "aws" ? state.perfil : undefined });

// ---------- avisos ----------
function notice(kind, icon, title, detail) {
  return h("div", { class: `notice notice--${kind}`, role: kind === "critical" ? "alert" : undefined },
    h("span", { class: "notice__icon", "aria-hidden": "true" }, icon),
    h("div", {}, title, detail ? h("small", {}, detail) : null));
}

function showError(error) {
  $("status").replaceChildren(notice("critical", "✕", h("strong", {}, `Não foi possível carregar: ${error.message}`), error.dica));
}

function kpi(label, value, delta) {
  return h("div", { class: "kpi" }, h("div", { class: "kpi__label" }, label), h("div", { class: "kpi__value" }, value), delta);
}

function setBusy(busy) {
  $("recarregar").setAttribute("aria-busy", String(busy));
  if (busy && !costs) $("custos-kpis").replaceChildren(...[1, 2, 3, 4].map(() => h("div", { class: "skeleton" })));
}

// ---------- custos ----------
async function loadCosts(refresh = false) {
  setBusy(true);
  try {
    costs = await api("/api/custos", {
      ...sourceParams(), dias: state.dias, contas: state.contas?.join(",") || undefined, recarregar: refresh ? "1" : undefined,
    });
    $("status").replaceChildren();
    renderCosts();
    loadBudgets(refresh);
    loadTags(refresh);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
}

// ---------- orçamentos ----------
const BUDGET_STATUS = {
  ok: ["ok", "✓ Dentro"],
  "atenção": ["atencao", "! Atenção"],
  "vai estourar": ["estoura", "✕ Vai estourar"],
  estourado: ["estoura", "✕ Estourado"],
};

async function loadBudgets(refresh = false) {
  try {
    budgets = await api("/api/orcamentos", { ...sourceParams(), recarregar: refresh ? "1" : undefined });
    renderBudgets();
  } catch (error) {
    $("orcamentos").replaceChildren(notice("warning", "⚠", `Orçamentos indisponíveis: ${error.message}`));
  }
}

function renderBudgets() {
  if (!budgets) return;
  const selected = costs?.meta.selecionadas ?? [];
  const items = budgets.itens.filter((b) => !selected.length || selected.includes(b.conta));
  const errors = budgets.meta.erros.map((e) => notice("warning", "⚠", `Conta sem acesso aos orçamentos: ${e}`));
  if (!items.length) {
    $("orcamentos").replaceChildren(...errors, h("p", { class: "card__hint" },
      "Nenhum orçamento de custo encontrado. Crie um em Billing > Budgets."));
    return;
  }
  $("orcamentos").replaceChildren(...errors, ...items.map((b) => {
    const [kind, label] = BUDGET_STATUS[b.situacao] ?? ["ok", b.situacao];
    const scale = Math.max(b.limite, b.previsao ?? 0, b.gasto) || 1; // a barra cabe o que for maior
    const pct = (v) => `${Math.min(100, (v / scale) * 100)}%`;
    const forecast = b.previsao === null ? "previsão indisponível"
      : `previsão ${fmtMoney(b.previsao)} (${fmtPct(b.uso_previsto)})`;
    return h("div", { class: `budget budget--${kind}` },
      h("div", { class: "budget__top" },
        h("span", { class: "budget__name", title: b.nome }, b.nome, h("span", { class: "budget__account" }, b.conta)),
        h("span", { class: `status status--${kind}` }, label)),
      h("div", {
        class: "budget__track", role: "img",
        "aria-label": `${b.nome}: ${fmtMoney(b.gasto)} de ${fmtMoney(b.limite)}, ${forecast}`,
      },
        h("span", { class: "budget__fill", style: { width: pct(b.gasto) } }),
        b.previsao === null ? null : h("span", { class: "budget__forecast", title: "Previsão", style: { left: pct(b.previsao) } }),
        h("span", { class: "budget__limit", title: "Limite", style: { left: pct(b.limite), right: "auto" } })),
      h("div", { class: "budget__meta" },
        `${fmtMoney(b.gasto)} de ${fmtMoney(b.limite)} (${fmtPct(b.uso)}) · ${forecast}`));
  }));
}

// ---------- custo por tag ----------
async function loadTags(refresh = false) {
  try {
    tags = await api("/api/tags", {
      ...sourceParams(), dias: state.dias, chave: state.chaveTag,
      contas: state.contas?.join(",") || undefined, recarregar: refresh ? "1" : undefined,
    });
    renderTags();
  } catch (error) {
    $("barras-tag").replaceChildren(notice("warning", "⚠", `Custo por tag indisponível: ${error.message}`));
  }
}

function renderTags() {
  if (!tags) return;
  $("tags-cobertura").textContent = tags.cobertura === null
    ? "Sem custo no período (na conta real, ative a tag em Billing > Cost allocation tags)"
    : `${fmtPct(tags.cobertura)} do custo tem a tag "${tags.chave}" · sem tag: ${fmtMoney(tags.sem_tag)}`;
  hbars($("barras-tag"), tags.valores, { color: (item) => (item.nome === "(sem tag)" ? "var(--other)" : "var(--s3)") });
}

function renderAccountChips(meta) {
  const field = $("campo-contas");
  field.hidden = meta.contas.length < 2;
  if (field.hidden) return;
  $("filtro-contas").replaceChildren(...meta.contas.map((conta) => {
    const on = meta.selecionadas.includes(conta);
    return h("button", {
      class: "chip", type: "button", "aria-pressed": String(on),
      onclick: () => {
        const current = new Set(meta.selecionadas);
        if (on && current.size === 1) return; // pelo menos uma conta
        on ? current.delete(conta) : current.add(conta);
        state.contas = meta.contas.filter((c) => current.has(c));
        loadCosts();
      },
    }, conta);
  }));
}

function renderCosts() {
  const d = costs;
  const { meta, kpis } = d;
  const paid = meta.paga ? ` · ${meta.chamadas_api} chamada(s) paga(s) ao Cost Explorer (~${fmtMoney(meta.custo_api)})` : "";
  $("custos-meta").textContent =
    `Fonte: ${meta.fonte} · ${fmtShortDate(meta.inicio)} a ${fmtShortDate(meta.fim)} (dias em UTC)${meta.estimado ? " · mês corrente estimado" : ""}${paid}`;
  $("custos-avisos").replaceChildren(...meta.erros.map((e) => notice("warning", "⚠", `Conta com problema (fora dos totais): ${e}`)));
  renderAccountChips(meta);

  const change = kpis.variacao_semana;
  const delta = change === null ? null : h("span", {
    class: `kpi__delta ${change > 0 ? "kpi__delta--up" : "kpi__delta--down"}`,
    title: "Últimos 7 dias contra os 7 anteriores (subir é ruim)",
  }, `${change > 0 ? "▲" : "▼"} ${fmtPct(Math.abs(change))} vs. semana anterior`);
  $("custos-kpis").replaceChildren(
    kpi(`Total em ${meta.dias} dias`, fmtMoney(kpis.total), delta),
    kpi("Média diária", fmtMoney(kpis.media_diaria)),
    kpi("Mês atual até ontem", fmtMoney(kpis.mes_ate_ontem)),
    kpi("Previsão de fechamento", kpis.previsao_mes === null ? "indisponível" : fmtMoney(kpis.previsao_mes)),
  );

  const hasData = kpis.total > 0;
  // sem custo, os gráficos somem; os orçamentos continuam (o limite existe mesmo com gasto zero)
  document.querySelectorAll("#painel-custos .card:not(#card-orcamentos)").forEach((card) => { card.hidden = !hasData; });
  if (!hasData) {
    $("anomalias").replaceChildren(h("div", { class: "card empty" },
      h("strong", {}, "Nenhum custo no período"),
      "Em uma conta nova isso é normal. Escolha “Dados de exemplo” em Fonte para ver a interface completa."));
    return;
  }

  const series = d.diario.series.map((serie, i) => ({ ...serie, cor: serie.nome === "Outros" ? "var(--other)" : SERIES_COLORS[i] }));
  $("legenda-diario").replaceChildren(...series.map((serie) =>
    h("li", {}, h("span", { class: "swatch", style: { "--swatch": serie.cor } }), serie.nome)));
  drawCharts();

  $("anomalias").replaceChildren(...(d.anomalias.length
    ? [h("article", { class: "card" },
        h("header", { class: "card__header" }, h("h2", {}, `⚠ Anomalias detectadas (${d.anomalias.length})`),
          h("p", { class: "card__hint" }, "Mediana e MAD dos 14 dias anteriores de cada conta + serviço · z robusto ≥ 3,5, impacto ≥ US$ 1 e ≥ 30%")),
        ...d.anomalias.map((a) => notice(a.severidade === "alta" ? "critical" : "warning", "⚠",
          h("span", {}, h("strong", {}, `${a.inicio === a.fim ? fmtShortDate(a.inicio) : `${fmtShortDate(a.inicio)} a ${fmtShortDate(a.fim)}`} · ${a.conta} · ${a.servico}`),
            `: custo extra de ${fmtMoney(a.custo_extra)}`),
          `Pico de ${fmtMoney(a.pico)} por dia quando o esperado era ${fmtMoney(a.esperado)} (z = ${String(a.z).replace(".", ",")})`)))]
    : []));

  hbars($("barras-conta"), d.por_conta);
  hbars($("barras-servico"), d.por_servico);
  renderCostsTable();
}

function drawCharts() {
  if (!costs || costs.kpis.total <= 0) return;
  const series = costs.diario.series.map((serie, i) => ({ ...serie, cor: serie.nome === "Outros" ? "var(--other)" : SERIES_COLORS[i] }));
  const anomalyDays = new Set(costs.anomalias.flatMap((a) => a.dias));
  stackedBars($("grafico-diario"), { dias: costs.diario.dias, series }, { anomalyDays });
  monthLine($("grafico-mes"), costs.mes);
}

function table(el, columns, rows) {
  el.replaceChildren(
    h("thead", {}, h("tr", {}, ...columns.map((c) => h("th", { class: c.num ? "num" : undefined, scope: "col", ...c.th }, c.label)))),
    h("tbody", {}, ...rows.map((row) => h("tr", {}, ...columns.map((c) => h("td", { class: c.num ? "num" : undefined }, c.cell(row)))))),
  );
}

const LIMIT = 300;
function renderCostsTable() {
  const rows = costs.linhas;
  $("linhas-total").textContent = `${rows.length} linhas${rows.length > LIMIT ? ` (mostrando ${LIMIT}; o CSV tem todas)` : ""}`;
  table($("tabela-custos"), [
    { label: "Dia", cell: (r) => fmtShortDate(r.dia) },
    { label: "Conta", cell: (r) => r.conta },
    { label: "Serviço", cell: (r) => r.servico },
    { label: "Custo", num: true, cell: (r) => fmtMoney(r.custo) },
    { label: "Estimado", cell: (r) => (r.estimado ? "sim" : "não") },
  ], rows.slice(0, LIMIT));
}

// ---------- recomendações ----------
async function loadRecs(refresh = false) {
  const key = JSON.stringify(sourceParams());
  if (recs && recsKey === key && !refresh) return renderRecs();
  $("recs-kpis").replaceChildren(...[1, 2, 3, 4].map(() => h("div", { class: "skeleton" })));
  $("recs-meta").textContent = state.fonte === "exemplo" ? "" : "Coletando inventário em todas as regiões…";
  try {
    recs = await api("/api/recomendacoes", { ...sourceParams(), recarregar: refresh ? "1" : undefined });
    recsKey = key;
    $("status").replaceChildren();
    renderRecs();
  } catch (error) {
    showError(error);
  }
}

function filteredRecs() {
  const q = state.busca.trim().toLowerCase();
  const { chave, direcao } = state.ordem;
  const sign = direcao === "desc" ? -1 : 1;
  return recs.itens
    .filter((r) => state.categoria === "todas" || r.categoria === state.categoria)
    .filter((r) => !q || [r.recurso, r.conta, r.regiao, r.titulo, r.detalhe].some((v) => v.toLowerCase().includes(q)))
    .sort((a, b) => {
      const va = a[chave] ?? -Infinity;
      const vb = b[chave] ?? -Infinity;
      return (va > vb ? 1 : va < vb ? -1 : 0) * sign;
    });
}

function renderRecs() {
  const { meta, resumo } = recs;
  $("recs-meta").textContent =
    `Fonte: ${meta.fonte} · ${meta.recursos} recurso(s) em ${meta.regioes.length} região(ões) · economia estimada com preços sob demanda de us-east-1 · chamadas Describe são gratuitas`;
  $("recs-avisos").replaceChildren(
    ...Object.entries(meta.bloqueadas).map(([conta, regioes]) => notice("info", "ℹ",
      h("span", {}, h("strong", {}, conta), `: ${regioes.length} região(ões) bloqueadas por SCP da organização foram ignoradas`),
      regioes.join(", "))),
    ...meta.erros.map((e) => notice("warning", "⚠", `Problema na coleta: ${e}`)),
  );
  $("recs-kpis").replaceChildren(
    kpi("Economia potencial / mês", fmtMoney(resumo.economia_mes)),
    kpi("Economia potencial / ano", fmtMoney(resumo.economia_ano)),
    kpi("Oportunidades de economia", String(resumo.oportunidades)),
    kpi("Recursos sem tags", String(resumo.sem_tags)),
  );
  $("card-por-tipo").hidden = recs.por_tipo.length === 0;
  hbars($("barras-tipo"), recs.por_tipo, { extra: (item) => `${item.quantidade}×` });

  const rows = filteredRecs();
  const sortable = (key, label, num) => ({
    label, num,
    th: {
      "data-sort": key,
      "aria-sort": state.ordem.chave === key ? (state.ordem.direcao === "desc" ? "descending" : "ascending") : undefined,
      onclick: () => {
        state.ordem = { chave: key, direcao: state.ordem.chave === key && state.ordem.direcao === "desc" ? "asc" : "desc" };
        renderRecs();
      },
    },
  });
  if (!recs.itens.length) {
    $("tabela-recs").replaceChildren(h("caption", { class: "empty" }, h("strong", {}, "Nenhum desperdício encontrado ✅"),
      "Escolha “Dados de exemplo” em Fonte para ver as regras em ação."));
    return;
  }
  table($("tabela-recs"), [
    { ...sortable("severidade", "Severidade"), cell: (r) => h("span", { class: `badge badge--${r.severidade}` }, SEVERITY[r.severidade]) },
    { ...sortable("economia_mes", "Economia/mês", true), cell: (r) => (r.economia_mes === null ? "—" : fmtMoney(r.economia_mes)) },
    { ...sortable("conta", "Conta"), cell: (r) => r.conta },
    { label: "Recurso", cell: (r) => h("code", {}, r.recurso) },
    { label: "Recomendação", cell: (r) => h("div", {}, h("strong", {}, r.titulo), h("div", {}, r.detalhe), h("div", { class: "action" }, `→ ${r.acao}`)) },
    { ...sortable("regiao", "Região"), cell: (r) => r.regiao },
  ], rows);
}

// ---------- CSV (separador ; e vírgula decimal, como o Excel em português espera) ----------
function downloadCsv(filename, header, rows) {
  const cell = (v) => {
    const text = typeof v === "number" ? String(v).replace(".", ",") : String(v ?? "");
    return /[;"\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const csv = `﻿${[header, ...rows].map((r) => r.map(cell).join(";")).join("\r\n")}`;
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = h("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- abas, filtros e tema ----------
function selectTab(name) {
  state.aba = name;
  store.set("aba", name);
  const isCosts = name === "custos";
  $("aba-custos").setAttribute("aria-selected", String(isCosts));
  $("aba-recs").setAttribute("aria-selected", String(!isCosts));
  $("aba-custos").tabIndex = isCosts ? 0 : -1;
  $("aba-recs").tabIndex = isCosts ? -1 : 0;
  $("painel-custos").hidden = !isCosts;
  $("painel-recs").hidden = isCosts;
  $("campo-periodo").hidden = !isCosts;
  $("campo-contas").hidden = !isCosts || !costs || costs.meta.contas.length < 2;
  if (isCosts) drawCharts();
  else loadRecs();
}

function applyTheme() {
  if (state.tema === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = state.tema;
  $("alternar-tema").setAttribute("aria-label", `Tema: ${THEME_LABEL[state.tema]} (clique para trocar)`);
  $("alternar-tema").title = `Tema: ${THEME_LABEL[state.tema]}`;
}

function updateReportLink() {
  const params = new URLSearchParams(Object.entries(sourceParams()).filter(([, v]) => v));
  $("baixar-relatorio").href = `/api/relatorio?${params}`;
}

function bind() {
  $("filtro-fonte").value = state.fonte;
  $("filtro-perfil").value = state.perfil;
  $("campo-perfil").hidden = state.fonte !== "aws";
  document.querySelectorAll("#filtro-periodo button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.dias) === state.dias)));

  $("filtro-fonte").addEventListener("change", (e) => {
    state.fonte = e.target.value;
    state.contas = null;
    store.set("fonte", state.fonte);
    $("campo-perfil").hidden = state.fonte !== "aws";
    updateReportLink();
    loadCosts();
    if (state.aba === "recs") loadRecs();
  });
  $("filtro-perfil").addEventListener("change", (e) => {
    state.perfil = e.target.value.trim() || "finops-lab";
    store.set("perfil", state.perfil);
    updateReportLink();
    loadCosts();
  });
  $("filtro-periodo").addEventListener("click", (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    state.dias = Number(button.dataset.dias);
    store.set("dias", state.dias);
    document.querySelectorAll("#filtro-periodo button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    loadCosts();
  });
  $("recarregar").addEventListener("click", () => {
    loadCosts(true);
    if (state.aba === "recs") loadRecs(true);
    else recs = null;
  });

  $("aba-custos").addEventListener("click", () => selectTab("custos"));
  $("aba-recs").addEventListener("click", () => selectTab("recs"));
  document.querySelector(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next = state.aba === "custos" ? "recs" : "custos";
    selectTab(next);
    $(next === "custos" ? "aba-custos" : "aba-recs").focus();
  });

  $("filtro-tag").addEventListener("click", (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    state.chaveTag = button.dataset.chave;
    document.querySelectorAll("#filtro-tag button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    loadTags();
  });

  $("filtro-categoria").addEventListener("click", (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    state.categoria = button.dataset.cat;
    document.querySelectorAll("#filtro-categoria button").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    renderRecs();
  });
  $("busca-recs").addEventListener("input", (e) => { state.busca = e.target.value; if (recs) renderRecs(); });

  $("csv-custos").addEventListener("click", () => costs && downloadCsv(
    `custos-${costs.meta.fim}.csv`, ["dia", "conta", "servico", "custo_usd", "estimado"],
    costs.linhas.map((r) => [r.dia, r.conta, r.servico, r.custo, r.estimado ? "sim" : "não"])));
  $("csv-recs").addEventListener("click", () => recs && downloadCsv(
    "recomendacoes.csv", ["severidade", "economia_mensal_usd", "conta", "regiao", "recurso", "recomendacao", "detalhe", "acao"],
    filteredRecs().map((r) => [r.severidade, r.economia_mes ?? "", r.conta, r.regiao, r.recurso, r.titulo, r.detalhe, r.acao])));

  $("alternar-tema").addEventListener("click", () => {
    state.tema = THEMES[(THEMES.indexOf(state.tema) + 1) % THEMES.length];
    store.set("tema", state.tema);
    applyTheme();
  });

  // redesenha os gráficos quando a largura muda (responsivo)
  let width = 0;
  new ResizeObserver(([entry]) => {
    const w = Math.round(entry.contentRect.width);
    if (w !== width) { width = w; drawCharts(); }
  }).observe($("conteudo"));
}

applyTheme();
bind();
updateReportLink();
selectTab(state.aba === "recs" ? "recs" : "custos");
loadCosts();

// usado só para depuração no console
window.finops = { state, get costs() { return costs; }, get recs() { return recs; }, fmtLongDate };
