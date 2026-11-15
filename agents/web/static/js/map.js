/* ═══════════════════════════════════════════════════════════════
   LOCATION MAP — pick many places, run each at a growing radius.

   Tiles are OpenStreetMap raster images (img-src allows that host); nothing
   third-party ever runs. Searches go through /api/map/search, which takes an
   explicit radius — the chat path cannot, and that radius is the whole point
   of "the location gets bigger each turn".

   Pins persist in localStorage, so a campaign survives a reload.
   ═══════════════════════════════════════════════════════════════ */

const TILE_URL = 'https://tile.openstreetmap.org/';
const STORE_KEY = 'jarvis.map.v1';
const GROWTH = 1.4;

const state = {
  lat: 22.5726,          // Kolkata
  lon: 88.3639,
  zoom: 11,
  pins: [],              // {id, lat, lon, label, seen:[], rows:[], leads, radius}
  running: false,
  origin: { x: 0, y: 0 },
};

const el = (id) => document.getElementById(id);
const mapWrap = el('mapWrap');
const tilesEl = el('mapTiles');
const pinsEl = el('mapPins');

/* ── Projection (Web Mercator) ─────────────────────────────────── */
const worldSize = (z) => 256 * Math.pow(2, z);

function project(lat, lon, z = state.zoom) {
  const s = worldSize(z);
  const x = ((lon + 180) / 360) * s;
  const sin = Math.sin((lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s;
  return { x, y };
}

function unproject(x, y, z = state.zoom) {
  const s = worldSize(z);
  const lon = (x / s) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / s;
  const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
  return { lat, lon };
}

const metersPerPixel = () =>
  156543.03392 * Math.cos((state.lat * Math.PI) / 180) / Math.pow(2, state.zoom);

/* ── Tiles ─────────────────────────────────────────────────────── */
function renderTiles() {
  if (!mapWrap || !tilesEl) return;
  const w = mapWrap.clientWidth;
  const h = mapWrap.clientHeight;
  if (!w || !h) return;
  const z = state.zoom;
  const c = project(state.lat, state.lon, z);
  const ox = c.x - w / 2;
  const oy = c.y - h / 2;
  state.origin = { x: ox, y: oy };

  const max = Math.pow(2, z);
  const frag = document.createDocumentFragment();
  for (let tx = Math.floor(ox / 256); tx <= Math.floor((ox + w) / 256); tx++) {
    for (let ty = Math.floor(oy / 256); ty <= Math.floor((oy + h) / 256); ty++) {
      if (ty < 0 || ty >= max) continue;
      const img = document.createElement('img');
      img.className = 'map-tile';
      img.alt = '';
      img.draggable = false;
      img.src = `${TILE_URL}${z}/${((tx % max) + max) % max}/${ty}.png`;
      img.style.left = `${tx * 256 - ox}px`;
      img.style.top = `${ty * 256 - oy}px`;
      frag.appendChild(img);
    }
  }
  tilesEl.replaceChildren(frag);
  tilesEl.style.transform = 'none';
}

/* ── Pins ──────────────────────────────────────────────────────── */
const key = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

function renderPins() {
  if (!pinsEl) return;
  pinsEl.replaceChildren();
  const mpp = metersPerPixel();
  for (const p of state.pins) {
    const w = project(p.lat, p.lon);
    const left = w.x - state.origin.x;
    const top = w.y - state.origin.y;

    if (p.radius) {
      const r = (p.radius / mpp);
      const ring = document.createElement('div');
      ring.className = 'map-ring';
      ring.style.left = `${left - r}px`;
      ring.style.top = `${top - r}px`;
      ring.style.width = `${r * 2}px`;
      ring.style.height = `${r * 2}px`;
      pinsEl.appendChild(ring);
    }
    const pin = document.createElement('button');
    pin.type = 'button';
    pin.className = 'map-pin';
    pin.style.left = `${left}px`;
    pin.style.top = `${top}px`;
    pin.title = p.label || 'pin';
    pin.innerHTML = `<i class="map-pin-dot"></i><span class="map-pin-lab"></span>`;
    pin.querySelector('.map-pin-lab').textContent = p.label || '…';
    pin.addEventListener('click', (e) => { e.stopPropagation(); removePin(p.id); });
    pinsEl.appendChild(pin);
  }
  pinsEl.style.transform = 'none';
}

function addPin(lat, lon) {
  const pin = {
    id: `p${Date.now().toString(36)}`,
    lat, lon, label: '', seen: [], rows: [],
    leads: 0, radius: 0,
  };
  state.pins.push(pin);
  persist();
  renderPins();
  renderPinList();
  // Name it from the point itself, so two pins in one city stay distinct.
  fetch(`/api/geocode?lat=${lat}&lon=${lon}`)
    .then((r) => r.json())
    .then((d) => {
      if (d && d.label) {
        pin.label = d.label;
        // The label alone is ambiguous across India ("Simla" -> Shimla); the
        // full address string is what the geocoder resolves back to this pin.
        pin.display = d.display || '';
        persist();
        renderPins();
        renderPinList();
      } else if (!pin.label) {
        pin.label = `${lat.toFixed(3)}, ${lon.toFixed(3)}`;
        renderPins();
        renderPinList();
      }
    })
    .catch(() => {
      if (!pin.label) {
        pin.label = `${lat.toFixed(3)}, ${lon.toFixed(3)}`;
        renderPins();
        renderPinList();
      }
    });
}

function removePin(id) {
  state.pins = state.pins.filter((p) => p.id !== id);
  persist();
  renderPins();
  renderPinList();
}

function renderPinList() {
  const list = el('pinList');
  if (!list) return;
  list.replaceChildren();
  if (!state.pins.length) {
    const empty = document.createElement('p');
    empty.className = 'pin-empty';
    empty.textContent = 'Click the map to drop a pin. Add as many as you like.';
    list.appendChild(empty);
    return;
  }
  for (const p of state.pins) {
    const row = document.createElement('div');
    row.className = 'pin-row';
    row.innerHTML = `
      <input class="pin-label" aria-label="Pin name">
      <button class="pin-del" type="button" aria-label="Remove pin">×</button>
      <span class="pin-meta"></span>`;
    const input = row.querySelector('.pin-label');
    input.value = p.label || '…';
    input.addEventListener('input', () => { p.label = input.value; persist(); renderPins(); });
    row.querySelector('.pin-del').addEventListener('click', () => removePin(p.id));
    row.querySelector('.pin-meta').textContent =
      `${p.radius ? (p.radius / 1000).toFixed(1) + ' km' : 'idle'} · ${p.leads} new`;

    // Contact hunting belongs beside the pin: a map run stops at discovery +
    // ICP, so the addresses a pin is missing can be hunted without the chat.
    const hunt = document.createElement('button');
    hunt.type = 'button';
    hunt.className = 'pin-hunt';
    const withMail = p.rows.filter((r) => r.email).length;
    hunt.textContent = p.hunting
      ? 'hunting…'
      : `✉ find emails${p.rows.length ? ` · ${withMail}/${p.rows.length}` : ''}`;
    hunt.disabled = !p.rows.length || !!p.hunting;
    hunt.addEventListener('click', () => huntContacts(p));
    row.appendChild(hunt);

    // Drafting is a separate act from hunting: only an address the finder was
    // willing to call verified is sendable, and nothing goes out until the
    // drafts below it are read and confirmed.
    const sendable = sendableRows(p);
    const draftBtn = document.createElement('button');
    draftBtn.type = 'button';
    draftBtn.className = 'pin-hunt';
    draftBtn.textContent = p.drafting
      ? 'drafting…'
      : `✉ draft${sendable.length ? ` · ${sendable.length}` : ''}`;
    draftBtn.disabled = !sendable.length || !!p.drafting;
    draftBtn.addEventListener('click', () => draftForPin(p));
    row.appendChild(draftBtn);
    list.appendChild(row);

    if (p.rows.length) {
      const det = document.createElement('details');
      det.className = 'pin-leads';
      const sum = document.createElement('summary');
      sum.textContent = `${p.rows.length} leads`;
      det.appendChild(sum);
      const ul = document.createElement('ul');
      for (const r of p.rows.slice(0, 40)) {
        const li = document.createElement('li');
        li.innerHTML = `<b></b><span class="lead-meta"></span>`;
        li.querySelector('b').textContent = r.name;
        li.querySelector('.lead-meta').textContent =
          [
            r.email ? `${r.email}${r.email_verified === false ? ' (unverified)' : ''}`
                      + (bounced[(r.email || '').toLowerCase()] ? ' (bounced)' : '')
                    : (r.email_guess ? `${r.email_guess} (guess)` : 'no email'),
            r.fit,
            r.score ? `${r.score}` : '',
          ].filter(Boolean).join(' · ');
        ul.appendChild(li);
      }
      det.appendChild(ul);
      list.appendChild(det);
    }

    if (p.drafts && p.drafts.length) {
      list.appendChild(draftBlock(p));
    }
  }
}

/** Dead inboxes, address -> reason. Filled from the mailbox, not the ledger. */
let bounced = {};

async function loadBounces() {
  try {
    const r = await fetch('/api/map/bounces');
    const d = await r.json();
    bounced = d.addresses || {};
  } catch (e) {
    bounced = {};
  }
  renderPinList();
}

/** Ask the inbox whether anything we sent came back, and relabel the pins. */
async function syncBounces(announce) {
  try {
    const r = await fetch('/api/map/bounces/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const d = await r.json();
    if (d.error) {
      if (announce) logLine(`  inbox check skipped: ${d.error}`);
      return;
    }
    bounced = {};
    for (const b of d.bounces || []) {
      if (b.to) bounced[b.to.toLowerCase()] = b.reason || '';
    }
    renderPinList();
    if (announce) {
      const fresh = (d.new || []).length;
      logLine(fresh ? `  ${fresh} new bounce${fresh === 1 ? '' : 's'} — that address is dead`
                    : '  inbox: no new bounces');
    }
  } catch (e) {
    if (announce) logLine(`  inbox check skipped: ${e.message}`);
  }
}

/** Leads that may receive mail: an address, not flagged unverified, unsent. */
function sendableRows(p) {
  return p.rows.filter((r) => r.email && r.email_verified !== false
    && !r.sent_at && !bounced[(r.email || '').toLowerCase()]);
}

/** The review block: every draft readable in full before anything is sent. */
function draftBlock(p) {
  const box = document.createElement('div');
  box.className = 'pin-drafts';

  const head = document.createElement('div');
  head.className = 'pd-head';
  const count = document.createElement('span');
  count.textContent = `${p.drafts.length} draft${p.drafts.length === 1 ? '' : 's'} ready`;
  const discard = document.createElement('button');
  discard.type = 'button';
  discard.className = 'pd-cancel';
  discard.textContent = 'discard';
  discard.addEventListener('click', () => { p.drafts = null; renderPinList(); });
  head.append(count, discard);
  box.appendChild(head);

  for (const d of p.drafts) {
    const det = document.createElement('details');
    det.className = 'pd-item';
    const sum = document.createElement('summary');
    sum.textContent = `${d.name} — ${d.subject}`;
    det.appendChild(sum);
    const to = document.createElement('div');
    to.className = 'pd-to';
    to.textContent = `to ${d.to}${d.ai_powered ? '' : ' · template copy'}`;
    const body = document.createElement('pre');
    body.className = 'pd-body';
    body.textContent = d.body;
    det.append(to, body);
    box.appendChild(det);
  }

  const send = document.createElement('button');
  send.type = 'button';
  send.className = 'btn-run';
  send.textContent = p.sending ? 'sending…' : `Send ${p.drafts.length}`;
  send.disabled = !!p.sending;
  send.addEventListener('click', () => sendDrafts(p));
  box.appendChild(send);
  return box;
}

async function draftForPin(pin) {
  if (pin.drafting) return;
  const targets = sendableRows(pin).slice(0, 20);
  if (!targets.length) {
    logLine(`${pin.label || 'pin'} · nothing sendable (needs a verified address)`);
    return;
  }
  pin.drafting = true;
  renderPinList();
  logLine(`${pin.label || 'pin'} · drafting ${targets.length}`);
  let data;
  try {
    const r = await fetch('/api/map/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: targets }),
    });
    data = await r.json();
  } catch (e) {
    pin.drafting = false;
    renderPinList();
    logLine(`  draft failed: ${e.message}`);
    return;
  }
  pin.drafting = false;
  if (data.error) {
    renderPinList();
    logLine(`  error: ${data.error}`);
    return;
  }
  pin.drafts = data.drafts || [];
  renderPinList();
  const failed = (data.errors || []).length;
  logLine(`  ${pin.drafts.length} drafted${failed ? ` · ${failed} failed` : ''} — review, then send`);
}

async function sendDrafts(pin) {
  if (pin.sending || !pin.drafts || !pin.drafts.length) return;
  pin.sending = true;
  renderPinList();
  logLine(`${pin.label || 'pin'} · sending ${pin.drafts.length}`);
  let data;
  try {
    const r = await fetch('/api/map/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ drafts: pin.drafts }),
    });
    data = await r.json();
  } catch (e) {
    pin.sending = false;
    renderPinList();
    logLine(`  send failed: ${e.message}`);
    return;
  }
  pin.sending = false;
  if (data.error) {
    renderPinList();
    logLine(`  error: ${data.error}`);
    return;
  }
  const sentAt = new Date().toISOString();
  for (const hit of data.sent || []) {
    const row = pin.rows.find((x) => (x.email || '').toLowerCase() === (hit.to || '').toLowerCase());
    if (row) row.sent_at = sentAt;
  }
  pin.drafts = null;
  persist();
  renderPinList();
  const dupes = (data.duplicates || []).length;
  const errs = (data.errors || []).length;
  const dead = (data.bounced || []).length;
  logLine(`  sent ${(data.sent || []).length}`
    + `${dupes ? ` · ${dupes} already mailed` : ''}`
    + `${dead ? ` · ${dead} bounced address${dead === 1 ? '' : 'es'}` : ''}`
    + `${errs ? ` · ${errs} failed` : ''}`);
  for (const b of data.bounced || []) {
    if (b.to) bounced[b.to.toLowerCase()] = b.reason || '';
  }
  if ((data.sent || []).length) await syncBounces(true);
}

/* ── Persistence ───────────────────────────────────────────────── */
/**
 * A lead as it is stored: only the fields the panel draws and the hunt
 * writes, so a pin's rows survive a reload without the store bloating.
 * Undefined/empty values are dropped rather than written as nulls.
 */
function trimmedRow(r) {
  const out = {};
  for (const k of ['name', 'fit', 'score', 'type', 'email', 'email_guess',
                   'phone', 'website', 'sent_at']) {
    const v = r[k];
    if (v !== undefined && v !== null && v !== '') out[k] = v;
  }
  if (r.email_verified === false) out.email_verified = false;
  return out;
}

function storeShape(withRows) {
  return {
    pins: state.pins.map((p) => {
      const pin = {
        id: p.id, lat: p.lat, lon: p.lon, label: p.label, display: p.display || '',
        seen: p.seen, leads: p.leads, radius: p.radius,
      };
      // 60 rows a pin is far more than the panel shows (40) and keeps a
      // handful of pins comfortably inside the storage budget.
      if (withRows) pin.rows = p.rows.slice(0, 60).map(trimmedRow);
      return pin;
    }),
    lat: state.lat, lon: state.lon, zoom: state.zoom,
  };
}

function persist() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(storeShape(true)));
  } catch (e) {
    // Out of quota: keep the pins (which are the thing worth losing last) by
    // retrying without the lead rows instead of failing the whole write.
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(storeShape(false)));
    } catch (e2) { /* storage blocked entirely: nothing persists */ }
  }
}

function restore() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return;
    const d = JSON.parse(raw);
    if (Array.isArray(d.pins)) {
      state.pins = d.pins.map((p) => ({
        ...p,
        seen: Array.isArray(p.seen) ? p.seen : [],
        // Rows come back exactly as the hunt left them, emails included, so a
        // refresh no longer resets a pin's coverage to zero.
        rows: Array.isArray(p.rows) ? p.rows : [],
      }));
    }
    if (typeof d.lat === 'number') state.lat = d.lat;
    if (typeof d.lon === 'number') state.lon = d.lon;
    if (typeof d.zoom === 'number') state.zoom = d.zoom;
  } catch (e) { /* corrupt store: start clean */ }
}

/* ── Interaction ───────────────────────────────────────────────── */
function wireMap() {
  if (!mapWrap) return;
  let drag = null;

  mapWrap.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.map-zoom') || e.target.closest('.map-pin')) return;
    drag = { x: e.clientX, y: e.clientY, moved: false };
    mapWrap.setPointerCapture?.(e.pointerId);
  });

  mapWrap.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
    if (!drag.moved) return;
    const t = `translate(${dx}px, ${dy}px)`;
    tilesEl.style.transform = t;
    pinsEl.style.transform = t;
  });

  mapWrap.addEventListener('pointerup', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    const moved = drag.moved;
    drag = null;
    if (!moved) {
      const rect = mapWrap.getBoundingClientRect();
      const wx = state.origin.x + (e.clientX - rect.left);
      const wy = state.origin.y + (e.clientY - rect.top);
      const ll = unproject(wx, wy);
      addPin(ll.lat, ll.lon);
      return;
    }
    const c = project(state.lat, state.lon);
    const ll = unproject(c.x - dx, c.y - dy);
    state.lat = ll.lat;
    state.lon = ll.lon;
    persist();
    renderTiles();
    renderPins();
  });

  mapWrap.addEventListener('pointercancel', () => {
    drag = null;
    renderTiles();
    renderPins();
  });

  for (const b of document.querySelectorAll('[data-zoom]')) {
    b.addEventListener('click', () => {
      const dir = Number(b.dataset.zoom);
      state.zoom = Math.max(6, Math.min(16, state.zoom + dir));
      persist();
      renderTiles();
      renderPins();
    });
  }

  window.addEventListener('resize', () => { renderTiles(); renderPins(); });
}

/* ── Runner ────────────────────────────────────────────────────── */
function logLine(txt) {
  const box = el('mapLog');
  if (!box) return;
  const line = document.createElement('div');
  line.className = 'map-log-line';
  line.textContent = txt;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

async function apiSearch(location, radius, category) {
  const r = await fetch('/api/map/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ location, radius, category }),
  });
  return r.json();
}

/**
 * Hunt emails for one pin's leads. Deliberately separate from a run: the map
 * route stops at discovery + ICP, and scraping is slow enough that it must be
 * something the user asks for, per pin, rather than a hidden cost of every
 * search. Only a verified address becomes a recipient; a guess is shown as one.
 */
async function huntContacts(pin) {
  if (pin.hunting) return;
  const targets = pin.rows.filter((r) => !r.email).slice(0, 30);
  if (!targets.length) {
    logLine(`${pin.label || 'pin'} · every lead already has an email`);
    return;
  }
  pin.hunting = true;
  renderPinList();
  // The finder splits the budget across the batch, so handing it 90s for 25
  // leads starves every one of them. Scale the budget to the batch (the route
  // clamps at 180s) instead of using one flat number.
  const budget = Math.min(180, Math.max(60, targets.length * 14));
  logLine(`${pin.label || 'pin'} · hunting emails for ${targets.length}`);
  let data;
  try {
    const r = await fetch('/api/map/contacts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: targets, budget }),
    });
    data = await r.json();
  } catch (e) {
    pin.hunting = false;
    renderPinList();
    logLine(`  hunt failed: ${e.message}`);
    return;
  }
  pin.hunting = false;
  if (data.error) {
    renderPinList();
    logLine(`  error: ${data.error}`);
    return;
  }

  const byName = new Map((data.results || []).map((x) => [key(x.name), x]));
  let added = 0;
  for (const r of pin.rows) {
    const hit = byName.get(key(r.name));
    if (!hit || !hit.email || r.email) continue;
    r.email = hit.email;
    r.email_verified = !!hit.verified;
    added += 1;
  }
  persist();
  renderPinList();
  const total = pin.rows.filter((r) => r.email).length;
  logLine(`  found ${added} of ${targets.length} · ${total}/${pin.rows.length} now have email`);
}

async function runPin(pin) {
  const grow = el('mapGrow')?.checked !== false;
  const baseKm = Number(el('mapBaseKm')?.value || 2.5);
  const target = Math.max(1, Number(el('mapTarget')?.value || 10));
  const maxRounds = Math.max(1, Math.min(8, Number(el('mapRounds')?.value || 4)));
  const category = el('mapQuery')?.value || '';

  let radius = Math.round(baseKm * 1000);
  for (let round = 1; round <= maxRounds; round++) {
    pin.radius = radius;
    renderPins();
    // Full address when we have it: "Simla" on its own geocodes to Shimla.
    const loc = pin.display || pin.label || `${pin.lat},${pin.lon}`;
    logLine(`${pin.label || 'pin'} · round ${round} · ${(radius / 1000).toFixed(1)} km`);
    let data;
    try {
      data = await apiSearch(loc, radius, category);
    } catch (e) {
      logLine(`  failed: ${e.message}`);
      return;
    }
    if (data.error) { logLine(`  error: ${data.error}`); return; }
    const known = new Set(pin.seen.map(key));
    const fresh = (data.rows || []).filter((r) => !known.has(key(r.name)));
    fresh.forEach((r) => { pin.seen.push(key(r.name)); pin.rows.push(r); });
    pin.leads += fresh.length;
    persist();
    renderPinList();
    logLine(`  kept ${data.kept} · new ${fresh.length} · total ${pin.leads}`);
    if (!grow) return;
    if (pin.leads >= target || !(data.rows || []).length) return;
    radius = Math.round(radius * GROWTH);
    if (radius > 15000) { logLine('  hit the 15 km ceiling'); return; }
  }
}

async function runAll() {
  if (state.running) return;
  if (!state.pins.length) { logLine('add a pin first'); return; }
  state.running = true;
  const btn = el('mapRun');
  if (btn) { btn.disabled = true; btn.textContent = 'running…'; }
  logLine('— run started —');
  for (const pin of state.pins) {
    await runPin(pin);
  }
  logLine('— run finished —');
  state.running = false;
  if (btn) { btn.disabled = false; btn.textContent = 'Run pins'; }
}

/* ── Panel wiring ──────────────────────────────────────────────── */
function openPanel(open) {
  const panel = el('sidePanel');
  if (!panel) return;
  panel.hidden = !open;
  if (open) {
    // The panel is display:none until this call, so the first measure must wait
    // for layout -- a single rAF still reads 0x0 in Chromium and draws no tiles.
    setTimeout(() => { renderTiles(); renderPins(); renderPinList(); }, 60);
  }
  const btn = el('mapBtn');
  if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function boot() {
  if (!mapWrap) return;
  restore();
  wireMap();
  renderTiles();
  renderPins();
  renderPinList();
  // Dead inboxes live in the mailbox, not the pin store, so they are read
  // fresh on boot rather than persisted alongside the leads.
  loadBounces();
  el('mapBtn')?.addEventListener('click', () => openPanel(el('sidePanel')?.hidden ?? true));
  el('sideClose')?.addEventListener('click', () => openPanel(false));
  el('mapRun')?.addEventListener('click', runAll);
  el('mapClear')?.addEventListener('click', () => {
    state.pins = [];
    persist();
    renderPins();
    renderPinList();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && el('sidePanel') && !el('sidePanel').hidden) openPanel(false);
  });
}

boot();
