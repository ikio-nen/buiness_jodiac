/* ═══════════════════════════════════════════════════════════════
   CHARTS — small, dependency-free SVG builders for JARVIS output.
   Every chart is real SVG (no canvas, no CDN), drawn with the
   theme's own ink/accent tokens so it matches the paper aesthetic.
   Each one carries a title + aria-label, so the numbers are still
   readable by assistive tech and when the page is printed.
   ═══════════════════════════════════════════════════════════════ */

const NS = 'http://www.w3.org/2000/svg';
const nf = new Intl.NumberFormat();
export const fmt = (n) => nf.format(Math.round(Number(n) || 0));

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// SVG text has no ellipsis of its own: a long category name would run into
// the bars. Clip to the label gutter and keep the full text in a tooltip.
function fitLabel(text, px, size = 12) {
  const s = String(text ?? '');
  const max = Math.max(3, Math.floor(px / (size * 0.6)));
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

export const TONE = {
  accent: 'var(--accent)',
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  bad: 'var(--bad)',
  moss: 'var(--moss)',
  ink: 'var(--ink)',
  faint: 'var(--ink-faint)',
};

/* ── Horizontal bars ────────────────────────────────────────────
   rows: [{ label, value, tone }] — the honest workhorse for
   "how many of each". Values are printed at the end of each bar. */
export function hBars(rows, opts = {}) {
  const data = (rows || []).filter((r) => r && r.label !== undefined);
  if (!data.length) return '';
  const width = opts.width || 320;
  const labelW = opts.labelWidth || 120;
  const valueW = 44;
  const rowH = opts.rowHeight || 26;
  const gap = 6;
  const max = Math.max(opts.max || 0, ...data.map((r) => Number(r.value) || 0), 1);
  const barMax = width - labelW - valueW - 16;
  const height = data.length * (rowH + gap);
  const bars = data.map((r, i) => {
    const y = i * (rowH + gap);
    const v = Number(r.value) || 0;
    const w = Math.max(v > 0 ? 3 : 0, (v / max) * barMax);
    const tone = TONE[r.tone] || r.tone || TONE.accent;
    return `
      <g class="chart-row">
        <title>${esc(r.label)}: ${fmt(v)}</title>
        <text class="chart-label" x="${labelW - 8}" y="${y + rowH / 2 + 4}"
              text-anchor="end">${esc(fitLabel(r.label, labelW - 14))}</text>
        <rect class="chart-track" x="${labelW}" y="${y + 5}"
              width="${barMax}" height="${rowH - 10}" rx="2"></rect>
        <rect class="chart-bar" x="${labelW}" y="${y + 5}"
              width="${w.toFixed(2)}" height="${rowH - 10}" rx="2"
              fill="${tone}"></rect>
        <text class="chart-value" x="${width - 2}" y="${y + rowH / 2 + 4}"
              text-anchor="end">${fmt(v)}</text>
      </g>`;
  }).join('');
  return svgWrap({
    width, height,
    title: opts.title || 'Bar chart',
    label: opts.label || data.map((r) => `${r.label}: ${fmt(r.value)}`).join(', '),
    body: bars,
  });
}

/* ── Donut ──────────────────────────────────────────────────────
   parts: [{ label, value, tone }] + a centre figure. Used where
   the parts make a whole (sent / skipped / failed). */
export function donut(parts, opts = {}) {
  const data = (parts || []).filter((p) => p && (Number(p.value) || 0) > 0);
  const size = opts.size || 148;
  const thickness = opts.thickness || 20;
  const r = (size - thickness) / 2;
  const c = size / 2;
  const total = data.reduce((sum, p) => sum + (Number(p.value) || 0), 0);
  if (!total) {
    return svgWrap({
      width: size, height: size,
      title: opts.title || 'Donut chart',
      label: opts.emptyLabel || 'No data yet',
      body: `<circle cx="${c}" cy="${c}" r="${r}" fill="none"
                stroke="var(--line)" stroke-width="${thickness}"></circle>
             <text class="chart-center-value" x="${c}" y="${c + 4}"
                   text-anchor="middle">0</text>`,
    });
  }
  let offset = 0;
  const circumference = 2 * Math.PI * r;
  const arcs = data.map((p) => {
    const share = (Number(p.value) || 0) / total;
    const dash = share * circumference;
    const arc = `
      <circle class="chart-arc" cx="${c}" cy="${c}" r="${r}" fill="none"
              stroke="${TONE[p.tone] || p.tone || TONE.accent}"
              stroke-width="${thickness}"
              stroke-dasharray="${dash.toFixed(2)} ${(circumference - dash).toFixed(2)}"
              stroke-dashoffset="${(-offset).toFixed(2)}"
              transform="rotate(-90 ${c} ${c})">
        <title>${esc(p.label)}: ${fmt(p.value)}</title>
      </circle>`;
    offset += dash;
    return arc;
  }).join('');
  const centerValue = opts.centerValue !== undefined ? opts.centerValue : fmt(total);
  const centerLabel = opts.centerLabel || 'total';
  return svgWrap({
    width: size, height: size,
    title: opts.title || 'Donut chart',
    label: data.map((p) => `${p.label}: ${fmt(p.value)}`).join(', '),
    body: `${arcs}
      <text class="chart-center-value" x="${c}" y="${c - 2}" text-anchor="middle">${esc(centerValue)}</text>
      <text class="chart-center-label" x="${c}" y="${c + 15}" text-anchor="middle">${esc(centerLabel)}</text>`,
  });
}

/* ── Funnel ─────────────────────────────────────────────────────
   stages: [{ label, value }] in pipeline order. Shows where a run
   lost leads instead of only reporting the survivor count. */
export function funnel(stages, opts = {}) {
  const data = (stages || []).filter((s) => s && typeof s.label === 'string');
  if (!data.length) return '';
  const width = opts.width || 320;
  const rowH = 30;
  const gap = 8;
  const top = Math.max(...data.map((s) => Number(s.value) || 0), 1);
  const height = data.length * (rowH + gap);
  const labelW = opts.labelWidth || 96;
  const barMax = width - labelW - 52;
  const rows = data.map((s, i) => {
    const y = i * (rowH + gap);
    const v = Number(s.value) || 0;
    const w = Math.max(v > 0 ? 3 : 0, (v / top) * barMax);
    const share = top ? Math.round((v / top) * 100) : 0;
    return `
      <g class="chart-row">
        <title>${esc(s.label)}: ${fmt(v)}</title>
        <text class="chart-label" x="${labelW - 8}" y="${y + rowH / 2 + 4}"
              text-anchor="end">${esc(fitLabel(s.label, labelW - 14))}</text>
        <rect class="chart-track" x="${labelW}" y="${y + 4}"
              width="${barMax}" height="${rowH - 8}" rx="2"></rect>
        <rect class="chart-bar" x="${labelW}" y="${y + 4}"
              width="${w.toFixed(2)}" height="${rowH - 8}" rx="2"
              fill="${TONE[s.tone] || s.tone || TONE.accent}"></rect>
        <text class="chart-value" x="${width - 2}" y="${y + rowH / 2 + 4}"
              text-anchor="end">${fmt(v)}<tspan class="chart-pct"> ${share}%</tspan></text>
      </g>`;
  }).join('');
  return svgWrap({
    width, height,
    title: opts.title || 'Pipeline funnel',
    label: data.map((s) => `${s.label}: ${fmt(s.value)}`).join(', '),
    body: rows,
  });
}

/* ── Stat tiles ─────────────────────────────────────────────────
   The headline numbers above a chart: one figure, one word. */
export function statTiles(tiles) {
  const data = (tiles || []).filter(Boolean);
  if (!data.length) return '';
  return `<div class="chart-tiles">${data.map((t) => `
    <div class="chart-tile">
      <b>${esc(t.value)}</b>
      <span>${esc(t.label)}</span>
    </div>`).join('')}</div>`;
}

/* ── Legend ───────────────────────────────────────────────────── */
export function legend(parts) {
  const data = (parts || []).filter((p) => p && p.label !== undefined);
  if (!data.length) return '';
  return `<div class="chart-legend">${data.map((p) => `
    <span class="chart-key"><i style="background:${TONE[p.tone] || p.tone || TONE.accent}"></i>
      ${esc(p.label)} <b>${fmt(p.value)}</b></span>`).join('')}</div>`;
}

/* ── Shared wrapper ───────────────────────────────────────────── */
function svgWrap({ width, height, title, label, body }) {
  return `<figure class="chart" role="group" aria-label="${esc(label)}">
    <svg viewBox="0 0 ${width} ${height}" width="${width}"
         preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(label)}">
      <title>${esc(title)}</title>
      ${body}
    </svg>
  </figure>`;
}
