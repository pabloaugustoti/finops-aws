// Gráficos desenhados à mão em SVG (sem bibliotecas).
// Cores sempre via variáveis CSS (style.fill = "var(--s1)") para trocar de tema sem redesenhar.

const SVG_NS = "http://www.w3.org/2000/svg";
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD" });
const integer = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 });
const longDate = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
const shortDate = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "UTC" });

export const fmtMoney = (v) => money.format(v ?? 0);
export const fmtShortDate = (iso) => shortDate.format(new Date(`${iso}T00:00:00Z`));
export const fmtLongDate = (iso) => longDate.format(new Date(`${iso}T00:00:00Z`));
export const fmtPct = (v) => `${compact.format(v * 100)}%`;
const axisMoney = (v) => (v >= 1 || v === 0 ? integer.format(v) : compact.format(v));

let uid = 0;

// ---------- criação segura de elementos (nunca innerHTML com dados) ----------

export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "style") Object.entries(value).forEach(([p, v]) => node.style.setProperty(p, v));
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

function s(tag, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "style") Object.entries(value).forEach(([p, v]) => node.style.setProperty(p, v));
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  if (parent) parent.append(node);
  return node;
}

// ---------- tooltip ----------

const tip = () => document.getElementById("tooltip");

export function showTip(event, ...nodes) {
  const el = tip();
  el.replaceChildren(...nodes);
  el.hidden = false;
  const pad = 14;
  const { innerWidth: vw, innerHeight: vh } = window;
  const rect = el.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + rect.width > vw - 8) x = event.clientX - rect.width - pad;
  if (y + rect.height > vh - 8) y = event.clientY - rect.height - pad;
  el.style.left = `${Math.max(8, x)}px`;
  el.style.top = `${Math.max(8, y)}px`;
}

export function hideTip() {
  tip().hidden = true;
}

export const tipTitle = (text) => h("div", { class: "tooltip__title" }, text);
export const tipRow = (color, label, value, extra = "") =>
  h("div", { class: `tooltip__row ${extra}` },
    color ? h("span", { class: "swatch", style: { "--swatch": color } }) : h("span"),
    h("span", {}, label), h("b", {}, value));

// ---------- escalas ----------

function niceMax(value) {
  if (!(value > 0)) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  const f = value / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
}

function yAxis(svg, { left, right, top, bottom, max, title }) {
  const grid = s("g", { class: "grid" }, svg);
  const steps = 4;
  for (let i = 0; i <= steps; i += 1) {
    const value = (max / steps) * i;
    const y = bottom - (value / max) * (bottom - top);
    if (i > 0) s("line", { x1: left, x2: right, y1: y, y2: y }, grid);
    s("text", { x: left - 8, y: y + 4, "text-anchor": "end", text: axisMoney(value) }, svg);
  }
  s("line", { class: "baseline", x1: left, x2: right, y1: bottom, y2: bottom }, svg);
  if (title) s("text", { x: 0, y: top - 10, text: title }, svg);
}

function svgRoot(container, width, height, label) {
  const svg = s("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": label });
  container.replaceChildren(svg);
  return svg;
}

// ---------- barras empilhadas por dia ----------

/**
 * @param {HTMLElement} container
 * @param {{dias: string[], series: {nome: string, valores: number[], cor: string}[]}} data
 * @param {{anomalyDays?: Set<string>, height?: number}} options
 */
export function stackedBars(container, data, { anomalyDays = new Set(), height = 320 } = {}) {
  const width = Math.max(320, container.clientWidth || 800);
  const m = { t: 30, r: 8, b: 26, l: 52 };
  const iw = width - m.l - m.r;
  const ih = height - m.t - m.b;
  const n = data.dias.length;
  const totals = data.dias.map((_, i) => data.series.reduce((sum, serie) => sum + serie.valores[i], 0));
  const max = niceMax(Math.max(...totals, 0) * 1.1);
  const y = (v) => m.t + ih - (v / max) * ih;
  const band = iw / n;
  const bw = Math.max(1, Math.min(26, band * 0.72));
  const r = Math.min(4, bw / 2);

  const svg = svgRoot(container, width, height, `Custo diário por serviço, ${n} dias`);
  yAxis(svg, { left: m.l, right: width - m.r, top: m.t, bottom: m.t + ih, max, title: "US$ por dia" });

  const labelEvery = Math.max(1, Math.ceil(52 / band));
  const defs = s("defs", {}, svg);
  const columns = s("g", {}, svg);
  const bars = s("g", {}, svg);
  const hits = s("g", {}, svg);

  data.dias.forEach((dia, i) => {
    const cx = m.l + band * i + band / 2;
    const x0 = cx - bw / 2;
    if ((n - 1 - i) % labelEvery === 0) {
      s("text", { x: cx, y: height - 6, "text-anchor": "middle", text: fmtShortDate(dia) }, svg);
    }
    const col = s("rect", { class: "hover-col", x: m.l + band * i, y: m.t, width: band, height: ih }, columns);

    if (totals[i] > 0) {
      // recorte com cantos arredondados só no topo da pilha
      const id = `clip${(uid += 1)}`;
      const top = y(totals[i]);
      const base = y(0);
      s("path", {
        d: `M${x0},${base}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + bw - r}Q${x0 + bw},${top} ${x0 + bw},${top + r}V${base}Z`,
      }, s("clipPath", { id }, defs));
      const stack = s("g", { "clip-path": `url(#${id})` }, bars);
      let acc = 0;
      data.series.forEach((serie) => {
        const v = serie.valores[i];
        if (v <= 0) return;
        s("rect", {
          x: x0, y: y(acc + v), width: bw, height: Math.max(0, y(acc) - y(acc + v)),
          style: { fill: serie.cor, stroke: "var(--surface)", "stroke-width": bw > 6 ? "1.5" : "0.6" },
        }, stack);
        acc += v;
      });
    }
    if (anomalyDays.has(dia)) {
      s("text", { class: "flag", x: cx, y: y(totals[i]) - 6, "text-anchor": "middle", text: "⚠" }, svg);
    }

    const hit = s("rect", { class: "hit", x: m.l + band * i, y: m.t, width: band, height: ih }, hits);
    const show = (event) => {
      col.classList.add("is-active");
      const rows = data.series
        .filter((serie) => serie.valores[i] > 0)
        .map((serie) => tipRow(serie.cor, serie.nome, fmtMoney(serie.valores[i])));
      showTip(
        event,
        tipTitle(fmtLongDate(dia)),
        ...(anomalyDays.has(dia) ? [h("div", { class: "tooltip__row" }, "⚠ dia com anomalia")] : []),
        ...rows,
        tipRow(null, "Total do dia", fmtMoney(totals[i]), "tooltip__total"),
      );
    };
    hit.addEventListener("pointerenter", show);
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerleave", () => { col.classList.remove("is-active"); hideTip(); });
  });
}

// ---------- linha do mês: real × previsão ----------

const dayIndex = (iso, startIso) => Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${startIso}T00:00:00Z`)) / 864e5);

export function monthLine(container, mes, { height = 280 } = {}) {
  const width = Math.max(320, container.clientWidth || 800);
  const m = { t: 30, r: 16, b: 26, l: 60 };
  const iw = width - m.l - m.r;
  const ih = height - m.t - m.b;
  const days = dayIndex(mes.fim, mes.inicio) + 1;
  const values = [...mes.real, ...mes.previsao].map((p) => p.valor);
  const max = niceMax(Math.max(...values, 0) * 1.12);
  const x = (iso) => m.l + (dayIndex(iso, mes.inicio) / Math.max(1, days - 1)) * iw;
  const y = (v) => m.t + ih - (v / max) * ih;

  const svg = svgRoot(container, width, height, "Custo acumulado no mês e previsão até o fim do mês");
  yAxis(svg, { left: m.l, right: width - m.r, top: m.t, bottom: m.t + ih, max, title: "US$ acumulado" });
  const every = Math.max(1, Math.ceil(46 / (iw / days)));
  for (let d = 0; d < days; d += every) {
    const iso = new Date(Date.parse(`${mes.inicio}T00:00:00Z`) + d * 864e5).toISOString().slice(0, 10);
    s("text", { x: x(iso), y: height - 6, "text-anchor": "middle", text: fmtShortDate(iso) }, svg);
  }

  const line = (points, color, dash) => {
    if (!points.length) return;
    s("path", {
      d: points.map((p, i) => `${i ? "L" : "M"}${x(p.dia)},${y(p.valor)}`).join(""),
      style: { fill: "none", stroke: color, "stroke-width": "2", "stroke-dasharray": dash || "none", "stroke-linejoin": "round" },
    }, svg);
  };
  const dot = (p, color) =>
    s("circle", { cx: x(p.dia), cy: y(p.valor), r: 4.5, style: { fill: color, stroke: "var(--surface)", "stroke-width": "2" } }, svg);

  line(mes.previsao, "var(--s2)", "6 4");
  line(mes.real, "var(--s1)");
  mes.real.forEach((p) => dot(p, "var(--s1)"));
  if (mes.previsao.length) dot(mes.previsao.at(-1), "var(--s2)");

  // rótulos diretos no fim de cada série
  const label = (p, text, anchor, below = false) =>
    s("text", {
      class: "direct-label", x: x(p.dia) + (anchor === "end" ? -8 : 8), y: y(p.valor) + (below ? 20 : -10), "text-anchor": anchor, text,
    }, svg);
  // "Real" vai abaixo do ponto: acima dele passa a linha de previsão, que sobe a partir dali
  if (mes.real.length) label(mes.real.at(-1), `Real: ${fmtMoney(mes.real.at(-1).valor)}`, mes.real.length > days / 2 ? "end" : "start", true);
  if (mes.previsao.length) label(mes.previsao.at(-1), `Previsão: ${fmtMoney(mes.previsao.at(-1).valor)}`, "end");

  // cursor (crosshair) com o valor do dia mais próximo; escondido até o mouse entrar
  const cross = s("line", { class: "crosshair", y1: m.t, y2: m.t + ih, x1: 0, x2: 0, style: { display: "none" } }, svg);
  const hit = s("rect", { class: "hit", x: m.l, y: m.t, width: iw, height: ih }, svg);
  const realByDay = new Map(mes.real.map((p) => [p.dia, p.valor]));
  const [f0, f1] = mes.previsao;
  hit.addEventListener("pointermove", (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * width;
    const d = Math.min(days - 1, Math.max(0, Math.round(((px - m.l) / iw) * (days - 1))));
    const iso = new Date(Date.parse(`${mes.inicio}T00:00:00Z`) + d * 864e5).toISOString().slice(0, 10);
    cross.setAttribute("x1", x(iso));
    cross.setAttribute("x2", x(iso));
    cross.style.display = "";
    const rows = [];
    if (realByDay.has(iso)) rows.push(tipRow("var(--s1)", "Real acumulado", fmtMoney(realByDay.get(iso))));
    if (f0 && d >= dayIndex(f0.dia, mes.inicio)) {
      const a = dayIndex(f0.dia, mes.inicio);
      const b = dayIndex(f1.dia, mes.inicio);
      const v = f0.valor + ((f1.valor - f0.valor) * (d - a)) / Math.max(1, b - a);
      rows.push(tipRow("var(--s2)", "Previsão", fmtMoney(v)));
    }
    if (!rows.length) rows.push(h("div", { class: "tooltip__row" }, "Sem dados neste dia"));
    showTip(event, tipTitle(fmtLongDate(iso)), ...rows);
  });
  hit.addEventListener("pointerleave", () => { cross.style.display = "none"; hideTip(); });
}

// ---------- barras horizontais (HTML + CSS) ----------

export function hbars(container, items, { color = "var(--s1)", valueFormat = fmtMoney, extra } = {}) {
  const max = Math.max(...items.map((i) => i.valor), 0) || 1;
  container.replaceChildren(
    ...items.map((item) =>
      h("div", { class: "hbar" },
        h("span", { class: "hbar__label", title: item.nome }, item.nome),
        h("span", { class: "hbar__track" },
          h("span", { class: "hbar__bar", style: { width: `${Math.max(0.6, (item.valor / max) * 78)}%`, background: color } }),
          h("span", { class: "hbar__value" }, valueFormat(item.valor),
            h("span", { class: "hbar__share" }, extra ? extra(item) : fmtPct(item.participacao)))))),
  );
}
