/* ═══════════════════════════════════════════════════════════════
   J.A.R.V.I.S — Agent Office client
   Left: living pixel office. Right: command center (chat/agents/
   skills). Bottom: roster strip. Warm Ghibli theme, no lanes.
   ═══════════════════════════════════════════════════════════════ */

// ── WebSocket Connection ─────────────────────────────────────────

const WS_URL = `ws://${location.host}/ws`;
let ws = null;
let connected = false;
let inputHistory = [];
let historyIndex = -1;

const messagesEl = document.getElementById('messages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const sessionInfo = document.getElementById('sessionInfo');

function connect() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    connected = true;
    statusDot.classList.add('connected');
    statusText.textContent = 'online';
    userInput.focus();
  };

  ws.onclose = () => {
    connected = false;
    statusDot.classList.remove('connected');
    statusText.textContent = 'reconnecting…';
    setTimeout(connect, 2000);
  };

  ws.onerror = () => { statusText.textContent = 'connection error'; };

  ws.onmessage = (event) => handleMessage(JSON.parse(event.data));
}

function handleMessage(data) {
  removeTypingIndicator();

  switch (data.type) {
    case 'jarvis':
      addMessage('jarvis', data.content, data);
      if (data.session_id) sessionInfo.textContent = data.session_id;
      break;
    case 'thinking': showTypingIndicator(); break;
    case 'queued': removeTypingIndicator(); showQueuedChip(data.message); break;
    case 'progress': addProgressMessage(data.message, data.step); break;
    case 'search_result': renderSearchResults(data.data); break;
    case 'draft_result': renderDraftResults(data.data); break;
    case 'send_result': renderSendResults(data.data); break;
    case 'research_result': renderResearchResults(data.data); break;
    case 'review_show': renderReviewShow(data); break;
    case 'review_result': renderReviewResult(data.data); break;
    case 'agent_event': handleAgentEvent(data.event); break;
    case 'agent_events_replay':
      (data.events || []).forEach(ev => handleAgentEvent(ev, true));
      break;
    case 'error': addMessage('jarvis', data.content, { error: true }); break;
    default:
      if (data.content) addMessage('jarvis', data.content);
  }
}

// ── Message Rendering ────────────────────────────────────────────

function addMessage(role, content, meta = {}) {
  const msg = document.createElement('div');
  msg.className = `message message-${role}`;

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = role === 'user' ? 'YOU' : 'JARVIS';

  const body = document.createElement('div');
  body.className = 'msg-content';
  body.textContent = content;

  if (meta.error) body.classList.add('is-error');

  msg.appendChild(label);
  msg.appendChild(body);
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function addSystemMessage(text) {
  const msg = document.createElement('div');
  msg.className = 'message message-system';
  const body = document.createElement('div');
  body.className = 'msg-content';
  body.textContent = text;
  msg.appendChild(body);
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function addProgressMessage(text, step) {
  const msg = document.createElement('div');
  msg.className = 'message message-jarvis message-progress';
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'JARVIS';
  const body = document.createElement('div');
  body.className = 'msg-content';
  body.textContent = text;
  const bar = document.createElement('div');
  bar.className = 'progress-bar';
  bar.innerHTML = '<div class="progress-fill"></div>';
  body.appendChild(bar);
  msg.appendChild(label);
  msg.appendChild(body);
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function showTypingIndicator() {
  if (document.getElementById('typingIndicator')) return;
  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.id = 'typingIndicator';
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'JARVIS';
  const indicator = document.createElement('div');
  indicator.className = 'typing-indicator';
  indicator.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  msg.appendChild(label);
  msg.appendChild(indicator);
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function removeTypingIndicator() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

// ── Live activity strip ──────────────────────────────────────────
// A single line under the composer that mirrors what the office is
// doing RIGHT NOW — agent events, pipeline steps, queued jobs — so
// the user never wonders whether anything is happening.

function activityStrip() { return document.getElementById('activityStrip'); }

function setActivity(text, cls = '') {
  const el = activityStrip();
  if (!el) return;
  el.textContent = text;
  el.className = 'activity-strip ' + cls;
  el.classList.toggle('busy', cls === 'busy');
}

function clearActivityIfIdle() {
  setActivity('office idle — run a search or “team act”');
}

function showQueuedChip(text) {
  setActivity('⏳ ' + (text || 'queued — will run after the current job'), 'busy');
}

// Keep the strip fed from every event source the app already has:
let _idleTimer = null;
function _armIdleDecay() {
  // After a finished job and 7 quiet seconds, the office is idle again.
  clearTimeout(_idleTimer);
  _idleTimer = setTimeout(() => {
    const el = activityStrip();
    if (el && el.classList.contains('busy')) clearActivityIfIdle();
  }, 7000);
}
const _origHandleAgentEvent = handleAgentEvent;
handleAgentEvent = function (ev, silent = false) {
  _origHandleAgentEvent(ev, silent);
  if (!ev || !ev.kind) return;
  if (ev.kind === 'bot') {
    const who = (ev.bot || 'agent').toUpperCase();
    const what = ev.task ? ` — ${String(ev.task).slice(0, 60)}` : '';
    setActivity(`${who} ${STATUS_TEXT[ev.status] || ev.status || 'working'}${what}`, 'busy');
    if (ev.status === 'done' || ev.status === 'error') _armIdleDecay();
    else clearTimeout(_idleTimer);
  } else if (ev.kind === 'packet') {
    setActivity(`✉ ${ev.from_ || '?'} → ${ev.to || '?'}${ev.label ? ' — ' + ev.label : ''}`, 'busy');
    clearTimeout(_idleTimer);
  } else if (ev.kind === 'brain') {
    setActivity('🧠 brain ' + (ev.action || 'updated'), 'busy');
    _armIdleDecay();
  } else if (ev.kind === 'step') {
    setActivity(String(ev.message || ev.label || ev.phase || 'working…'), 'busy');
    clearTimeout(_idleTimer);
  }
};

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Data Renderers ───────────────────────────────────────────────

function renderSearchResults(data) {
  if (!data.businesses || data.businesses.length === 0) {
    addMessage('jarvis', 'No businesses found in that area.');
    return;
  }
  let html = `<div class="data-card"><div class="data-card-title">SEARCH RESULTS</div>`;
  html += `<table class="data-table"><tr><th>#</th><th>Name</th><th>Category</th><th>Website</th></tr>`;
  data.businesses.forEach((b, i) => {
    const webTag = b.has_website ? '<span class="tag tag-green">YES</span>' : '<span class="tag tag-red">NO</span>';
    html += `<tr><td>${i + 1}</td><td>${esc(b.name)}</td><td>${esc(b.category)}</td><td>${webTag}</td></tr>`;
  });
  html += `</table><div style="margin-top:8px;font-size:14px;color:var(--ink-soft);">Found ${data.total} total: `;
  html += `<span class="tag tag-red">${data.no_site_count} without site</span> `;
  html += `<span class="tag tag-green">${data.with_site_count} with site</span></div></div>`;
  appendCard(html);
}

function renderDraftResults(data) {
  let html = `<div class="data-card"><div class="data-card-title">DRAFTED ${data.count} EMAILS</div>`;
  html += `<table class="data-table"><tr><th>Business</th><th>Subject</th><th>Email</th></tr>`;
  data.drafts.forEach(d => {
    const emailTag = d.to ? `<span class="tag tag-green">${esc(d.to)}</span>` : '<span class="tag tag-yellow">No email</span>';
    html += `<tr><td>${esc(d.business)}</td><td>${esc(d.subject)}</td><td>${emailTag}</td></tr>`;
  });
  html += `</table>`;
  if (data.ai_used > 0) html += `<div style="margin-top:8px;font-size:14px;color:var(--green-ok);">AI personalized: ${data.ai_used}/${data.count}</div>`;
  html += `</div>`;
  appendCard(html);
}

function renderSendResults(data) {
  let html = `<div class="data-card"><div class="data-card-title">EMAILS SENT</div><div style="display:flex;gap:18px;margin-top:4px;">`;
  html += `<div><span style="color:var(--green-ok);font-size:26px;">${data.sent}</span><div style="font-size:13px;color:var(--ink-soft);">Sent</div></div>`;
  html += `<div><span style="color:var(--amber-warn);font-size:26px;">${data.skipped}</span><div style="font-size:13px;color:var(--ink-soft);">Skipped</div></div>`;
  html += `<div><span style="color:var(--red-bad);font-size:26px;">${data.errors}</span><div style="font-size:13px;color:var(--ink-soft);">Errors</div></div>`;
  html += `</div></div>`;
  appendCard(html);
}

function renderResearchResults(data) {
  let html = `<div class="data-card"><div class="data-card-title">RESEARCH: ${data.count} BUSINESSES</div>`;
  html += `<table class="data-table"><tr><th>Business</th><th>Rating</th><th>Reviews</th><th>Gaps</th></tr>`;
  data.results.forEach(r => {
    const gaps = (r.gaps || []).slice(0, 2).join(', ') || 'None found';
    html += `<tr><td>${esc(r.name)}</td><td><span class="tag tag-yellow">${r.rating || 'N/A'}</span></td><td>${r.review_count || 0}</td><td style="font-size:14px;">${esc(gaps)}</td></tr>`;
  });
  html += `</table></div>`;
  appendCard(html);
}

function appendCard(html) {
  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.innerHTML = `<div class="msg-label">JARVIS</div>${html}`;
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

// ═══════════════════════════════════════════════════════════════
//  THE OFFICE — agents as pixel people at their work zones.
//  Backend events (agents/event_bus.py) arrive as agent_event
//  frames and make the little people walk, work, and talk.
// ═══════════════════════════════════════════════════════════════

const opsStage = document.getElementById('opsStage');
const opsFeed = document.getElementById('opsFeed');
const opsStats = document.getElementById('opsStats');
const opsRoster = document.getElementById('opsRoster');
const botsLayer = document.getElementById('botsLayer');
const packetsLayer = document.getElementById('packetsLayer');

// Home zone per agent (furniture they idle at)
const BOT_HOME = {
  scout: 'station-scout',
  strategist: 'station-strategist',
  analyst: 'station-analyst',
  librarian: 'station-brain',
  mailer: 'station-mailer',
  jarvis: 'station-brain',
};

// Pixel-person look: hair + shirt colors (original palette)
const BOT_LOOK = {
  scout:      { hair: '#2b2b33', shirt: '#4e8f7d' },
  strategist: { hair: '#4a2c17', shirt: '#c1666b' },
  analyst:    { hair: '#111114', shirt: '#d9a441' },
  librarian:  { hair: '#5a5a66', shirt: '#8e6fa8' },
  mailer:     { hair: '#3a2a1a', shirt: '#6f9e58' },
  jarvis:     { hair: '#c0c0c8', shirt: '#c1666b' },
  agent:      { hair: '#2b2b33', shirt: '#8a8172' },
  unknown:    { hair: '#2b2b33', shirt: '#8a8172' },
};

const ROSTER_META = {
  scout:      { label: 'SCOUT',      role: 'lead hunter' },
  strategist: { label: 'STRATEGIST', role: 'outreach tactician' },
  analyst:    { label: 'ANALYST',    role: 'numbers' },
  librarian:  { label: 'LIBRARIAN',  role: 'brain keeper' },
  mailer:     { label: 'MAILER',     role: 'sends the mail' },
};

const bots = {};        // botName -> {el, bubbleEl, bubbleTimer}
const stationBusy = {}; // stationId -> timeout handle
const rosterCards = {}; // name -> {card, msgsEl, msgs, activeTimer}

function stationCenterPx(stationId) {
  const st = document.getElementById(stationId);
  if (!st || !opsStage) return { x: 0, y: 0 };
  const sr = opsStage.getBoundingClientRect();
  const r = st.getBoundingClientRect();
  return { x: (r.left + r.width / 2) - sr.left, y: (r.top + r.height / 2) - sr.top };
}

function pxToPct(pt) {
  const sr = opsStage.getBoundingClientRect();
  if (!sr.width || !sr.height) return { x: 50, y: 50 };
  return { x: pt.x / sr.width * 100, y: pt.y / sr.height * 100 };
}

function getBot(name) {
  if (bots[name]) return bots[name];
  const el = document.createElement('div');
  el.className = 'bot';
  el.dataset.bot = name;
  el.title = name;
  el.addEventListener('click', () => openAgentPane(name === 'jarvis' ? null : name));

  const look = BOT_LOOK[name] || BOT_LOOK.agent;
  const sprite = document.createElement('div');
  sprite.className = 'sprite';
  sprite.innerHTML =
    `<div class="sp-hair" style="background:${look.hair}"></div>` +
    `<div class="sp-face"></div>` +
    `<div class="sp-body" style="background:${look.shirt}"></div>` +
    `<div class="sp-legs"><i></i><i></i></div>`;
  el.appendChild(sprite);

  const tag = document.createElement('div');
  tag.className = 'bot-tag';
  tag.textContent = name.toUpperCase();
  el.appendChild(tag);

  const home = pxToPct(botDockPoint(BOT_HOME[name] || 'station-brain'));
  el.style.left = home.x + '%';
  el.style.top = home.y + '%';
  botsLayer.appendChild(el);
  bots[name] = { el, bubbleEl: null, bubbleTimer: null, walkTimer: null };
  return bots[name];
}

// Bots stand just above their furniture, feet on its top edge.
const DOCK_SIDE = { 'station-brain': 'right' };
const DOCK_GAP_PX = 4;
const BOT_H = 56;

function botDockPoint(stationId) {
  const st = document.getElementById(stationId);
  const c = stationCenterPx(stationId);
  if (!st || !opsStage) return c;
  const sr = opsStage.getBoundingClientRect();
  const r = st.getBoundingClientRect();
  const side = DOCK_SIDE[stationId] || 'top';
  if (side === 'right') {
    return { x: (r.right - sr.left) + 22, y: c.y };
  }
  return { x: c.x, y: Math.max(BOT_H, (r.top - sr.top) - DOCK_GAP_PX) };
}

function moveBot(name, stationId) {
  const b = getBot(name);
  const sr = opsStage.getBoundingClientRect();
  const cur = { x: parseFloat(b.el.style.left) || 0, y: parseFloat(b.el.style.top) || 0 };
  const fromPx = { x: cur.x * sr.width / 100, y: cur.y * sr.height / 100 };
  const toPx = botDockPoint(stationId);
  const pos = pxToPct(toPx);
  b.el.style.left = pos.x + '%';
  b.el.style.top = pos.y + '%';
  b.el.classList.remove('walking');
  if (Math.hypot(toPx.x - fromPx.x, toPx.y - fromPx.y) > 24) {
    b.el.classList.add('walking');
    clearTimeout(b.walkTimer);
    b.walkTimer = setTimeout(() => b.el.classList.remove('walking'), 1500);
    const steps = 5;
    for (let i = 1; i <= steps; i++) {
      setTimeout(() => {
        const t = i / (steps + 1);
        spawnTrail((fromPx.x + (toPx.x - fromPx.x) * t) / sr.width * 100,
                   (fromPx.y + (toPx.y - fromPx.y) * t) / sr.height * 100);
      }, i * 260);
    }
  }
}

// Bots store % positions; the stage resizes — so re-dock every bot to
// its home station whenever the floor changes size. Otherwise a bot
// parked at, say, 85% of the OLD width is stranded left of its desk.
let __lastStageW = 0, __lastStageH = 0;
const botsResizeObserver = ('ResizeObserver' in window)
  ? new ResizeObserver(() => {
      if (!opsStage) return;
      const w = opsStage.clientWidth, h = opsStage.clientHeight;
      if (Math.abs(w - __lastStageW) < 2 && Math.abs(h - __lastStageH) < 2) return;
      __lastStageW = w; __lastStageH = h;
      for (const name in bots) moveBot(name, BOT_HOME[name] || 'station-brain');
    })
  : null;
if (botsResizeObserver && opsStage) botsResizeObserver.observe(opsStage);

function spawnTrail(xPct, yPct) {
  const dot = document.createElement('div');
  dot.className = 'bot-trail';
  dot.style.left = xPct + '%';
  dot.style.top = yPct + '%';
  packetsLayer.appendChild(dot);
  setTimeout(() => dot.remove(), 850);
}

function burstAt(xPct, yPct) {
  for (let i = 0; i < 6; i++) {
    const dot = document.createElement('div');
    dot.className = 'burst-dot';
    const ang = Math.random() * Math.PI * 2;
    const r = 12 + Math.random() * 16;
    dot.style.setProperty('--bx', Math.cos(ang) * r + 'px');
    dot.style.setProperty('--by', Math.sin(ang) * r + 'px');
    dot.style.left = xPct + '%';
    dot.style.top = yPct + '%';
    packetsLayer.appendChild(dot);
    setTimeout(() => dot.remove(), 700);
  }
}

function botSay(name, text, ms = 3500) {
  const b = getBot(name);
  if (b.bubbleEl) b.bubbleEl.remove();
  clearTimeout(b.bubbleTimer);
  const bubble = document.createElement('div');
  bubble.className = 'bot-bubble';
  bubble.textContent = text;
  b.el.appendChild(bubble);
  b.bubbleEl = bubble;
  b.bubbleTimer = setTimeout(() => {
    bubble.remove();
    if (b.bubbleEl === bubble) b.bubbleEl = null;
  }, ms);
}

function setBotStatus(name, status) {
  const b = getBot(name);
  b.el.classList.remove('walking', 'working', 'done', 'error');
  if (status === 'done') b.el.classList.add('done');
  else if (status === 'error') b.el.classList.add('error');
  else if (status && status !== 'idle') b.el.classList.add('working');
}

function pulseStation(stationId, ms = 2200) {
  const st = document.getElementById(stationId);
  if (!st) return;
  st.classList.add('active');
  clearTimeout(stationBusy[stationId]);
  stationBusy[stationId] = setTimeout(() => st.classList.remove('active'), ms);
}

function botStation(botName) {
  return BOT_HOME[botName] || 'station-brain';
}

// ── Roster strip ─────────────────────────────────────────────────

function buildRoster() {
  if (!opsRoster) return;
  Object.keys(ROSTER_META).forEach(name => {
    const meta = ROSTER_META[name];
    const look = BOT_LOOK[name] || BOT_LOOK.agent;
    const card = document.createElement('div');
    card.className = 'roster-card';
    card.addEventListener('click', () => openAgentPane(name));
    card.innerHTML =
      `<div class="roster-ava">` +
      `<div class="sp-hair" style="background:${look.hair}"></div>` +
      `<div class="sp-face"></div>` +
      `<div class="sp-body" style="background:${look.shirt}"></div>` +
      `</div>` +
      `<div><div class="roster-name">${meta.label}</div>` +
      `<div class="roster-role">${meta.role}</div></div>` +
      `<span class="roster-msgs">0</span>`;
    opsRoster.appendChild(card);
    rosterCards[name] = { card, msgsEl: card.querySelector('.roster-msgs'), msgs: 0, activeTimer: null };
  });
}

function rosterPing(name, state, countMsg = true) {
  const rc = rosterCards[name];
  if (!rc) return;
  if (countMsg) {
    rc.msgs += 1;
    rc.msgsEl.textContent = rc.msgs;
  }
  rc.card.classList.remove('active', 'done', 'error');
  if (state === 'error') rc.card.classList.add('error');
  else if (state === 'done') rc.card.classList.add('done');
  else if (state) rc.card.classList.add('active');
  clearTimeout(rc.activeTimer);
  rc.activeTimer = setTimeout(() => rc.card.classList.remove('active', 'done', 'error'),
                              state === 'error' ? 1200 : 2500);
}

// Packet: a little envelope hops from one zone to another (no lanes)
function flyPacket(fromId, toId, label) {
  if (fromId === toId) { pulseStation(toId, 1600); return; }
  const sr = opsStage.getBoundingClientRect();
  const from = stationCenterPx(fromId);
  const to = stationCenterPx(toId);

  const env = document.createElement('div');
  env.className = 'packet';
  if (label) {
    const lbl = document.createElement('div');
    lbl.className = 'packet-label';
    lbl.textContent = label;
    env.appendChild(lbl);
  }
  packetsLayer.appendChild(env);
  pulseStation(fromId, 1100);

  // gentle two-arc hop (up then down), like tossing mail across the room
  const midX = (from.x + to.x) / 2;
  const midY = Math.min(from.y, to.y) - Math.min(90, Math.hypot(to.x - from.x, to.y - from.y) * 0.22);
  const dur = Math.min(1400, 600 + Math.hypot(to.x - from.x, to.y - from.y) * 1.8);
  const t0 = performance.now();
  let lastTrail = 0;

  function frame(t) {
    const p = Math.min(1, (t - t0) / dur);
    const u = 1 - p;
    const x = u * u * from.x + 2 * u * p * midX + p * p * to.x;
    const y = u * u * from.y + 2 * u * p * midY + p * p * to.y;
    env.style.left = (x / sr.width * 100) + '%';
    env.style.top = (y / sr.height * 100) + '%';
    if (t - lastTrail > 60 && p > 0.05 && p < 0.95) {
      lastTrail = t;
      spawnTrail(x / sr.width * 100, y / sr.height * 100);
    }
    if (p < 1) requestAnimationFrame(frame);
    else {
      env.remove();
      pulseStation(toId, 1600);
      burstAt(to.x / sr.width * 100, to.y / sr.height * 100);
    }
  }
  requestAnimationFrame(frame);
}

const STATUS_TEXT = {
  'thinking': 'thinking…',
  'reading-brain': 'reading the brain…',
  'searching-web': 'searching the web…',
  'writing-pdf': 'writing PDF…',
  'done': 'done ✔',
  'error': 'error ✖',
};

function opsFeedLine(chip, chipCls, text, cls = '') {
  const idle = opsFeed.querySelector('.ops-idle');
  if (idle) idle.remove();
  const line = document.createElement('div');
  line.className = 'ops-feed-line ' + cls;
  const t = new Date().toLocaleTimeString([], { hour12: false });
  line.innerHTML = `<span class="feed-time">${t}</span>`
    + `<span class="feed-chip ${chipCls}">${esc(chip)}</span>`
    + text;
  opsFeed.appendChild(line);
  while (opsFeed.children.length > 30) opsFeed.firstChild.remove();
  opsFeed.scrollTop = opsFeed.scrollHeight;
}

function handleAgentEvent(ev, silent = false) {
  if (!ev || !ev.kind) return;

  if (ev.kind === 'bot') {
    const botName = ev.bot || 'agent';
    const status = ev.status || 'thinking';
    moveBot(botName, botStation(botName));
    setBotStatus(botName, status);
    pulseStation(botStation(botName));
    if (ev.task) botSay(botName, String(ev.task).slice(0, 90));
    rosterPing(botName, status);
    const cls = status === 'error' ? 'feed-err' : (status === 'done' ? 'feed-done' : '');
    opsFeedLine(botName.toUpperCase(), 'feed-chip-bot',
      `${esc(STATUS_TEXT[status] || status)} — ${esc(ev.task || '')}`, cls);

  } else if (ev.kind === 'packet') {
    const fromStation = ev.from_ === 'pipeline' ? 'station-scout'
      : ev.from_ === 'search' ? 'station-scraper'
      : BOT_HOME[ev.from_] || 'station-brain';
    const toStation = ev.to === 'brain' ? 'station-brain'
      : ev.to === 'drafts' ? 'station-drafts'
      : ev.to === 'sent' ? 'station-sent'
      : ev.to === 'builder' ? 'station-builder'
      : ev.to === 'scraper' ? 'station-scraper'
      : ev.to === 'enricher' ? 'station-enricher'
      : BOT_HOME[ev.to] || 'station-brain';
    flyPacket(fromStation, toStation, ev.label || '');
    opsFeedLine('DATA', 'feed-chip-data',
      `${esc(ev.from_ || '?')} → ${esc(ev.to || '?')}${ev.label ? ' — ' + esc(ev.label) : ''}`);

  } else if (ev.kind === 'brain') {
    pulseStation('station-brain', 1500);
    opsFeedLine('BRAIN', 'feed-chip-brain',
      `${esc(ev.action || 'learn')}: ${esc(ev.detail || '')}`);

  } else if (ev.kind === 'team') {
    ['scout', 'strategist', 'analyst'].forEach(n => {
      setBotStatus(n, ev.status === 'done' ? 'done' : 'working');
    });
    opsFeedLine('TEAM', 'feed-chip-team', `${esc(ev.status || '')}: ${esc(ev.task || '')}`);

  } else if (ev.kind === 'step') {
    const phaseStation = {
      search: 'station-scout', scrape: 'station-scraper',
      enrich: 'station-enricher', draft: 'station-strategist',
      send: 'station-mailer', sync: 'station-brain',
    }[ev.phase] || 'station-brain';
    pulseStation(phaseStation, 3000);
    if (!silent && !ev.done) {
      opsFeedLine((ev.phase || '?').toUpperCase(), 'feed-chip-step', esc(ev.message || ''));
    } else {
      opsFeedLine((ev.phase || '?').toUpperCase(), 'feed-chip-step',
        `<span class="${ev.failed ? 'feed-err' : 'feed-done'}">${esc(ev.message || 'done')}</span>`,
        ev.failed ? 'feed-err' : '');
    }
  }
}

// ── Brain stats line ─────────────────────────────────────────────

async function refreshOpsStats() {
  try {
    const res = await fetch('/api/brain');
    const d = await res.json();
    if (!d || d.error) return;
    const s = d.stats || {};
    const mem = (d.agents || []).reduce((a, x) => a + (x.facts || 0), 0);
    opsStats.textContent =
      `🧠 ${s.total_files || 0} memories · ${s.industries || 0} industries · ${s.businesses || 0} businesses · team knows ${mem} facts`;
  } catch (e) { /* stats are cosmetic */ }
}
refreshOpsStats();
setInterval(refreshOpsStats, 30000);

// ── Tabs ─────────────────────────────────────────────────────────

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('is-active'));
    document.querySelectorAll('.tabpane').forEach(p => p.classList.remove('is-active'));
    tab.classList.add('is-active');
    const pane = document.querySelector(`.tabpane[data-pane="${tab.dataset.tab}"]`);
    if (pane) pane.classList.add('is-active');
    if (tab.dataset.tab === 'agents') loadAgentsPane();
    if (tab.dataset.tab === 'skills') loadSkillsPane();
  });
});

function openAgentPane(agentKey) {
  const tab = document.querySelector('.tab[data-tab="agents"]');
  if (tab) tab.click();
  loadAgentsPane(agentKey);
}

// ── Agents pane ──────────────────────────────────────────────────

let allSkillsCache = [];

async function loadAgentsPane(focusKey = null) {
  const pane = document.getElementById('agentsList');
  if (!pane) return;
  try {
    const [aRes, sRes] = await Promise.all([fetch('/api/agents'), fetch('/api/skills')]);
    const aData = await aRes.json();
    const sData = await sRes.json();
    const agents = aData.agents || [];
    allSkillsCache = sData.skills || [];
    const skillsStatsEl = document.getElementById('skillsStats');
    if (skillsStatsEl && sData.stats) {
      skillsStatsEl.textContent =
        `${sData.stats.enabled}/${sData.stats.total} active · ${sData.stats.learned} self-taught · used ${sData.stats.total_uses}×`;
    }

    pane.innerHTML = '';
    agents.forEach(a => {
      const look = BOT_LOOK[a.key] || BOT_LOOK.agent;
      const mySkills = allSkillsCache.filter(s =>
        (s.agents || []).includes(a.key) || (s.agents || []).includes('*'));
      const card = document.createElement('div');
      card.className = 'agent-card' + (focusKey === a.key ? ' open' : '');
      card.innerHTML =
        `<div class="agent-card-head">` +
        `<span class="roster-ava">` +
        `<div class="sp-hair" style="background:${look.hair}"></div>` +
        `<div class="sp-face"></div><div class="sp-body" style="background:${look.shirt}"></div></span>` +
        `<div><div class="agent-name">${esc(a.name.toUpperCase())}</div>` +
        `<div class="agent-role">${esc(a.role)}</div></div>` +
        `<span class="agent-meta">${a.memory || 0} memories · ${mySkills.length} skills</span>` +
        `</div><div class="agent-card-body" style="display:${focusKey === a.key ? 'block' : 'none'}">` +
        `<h4>THEIR SKILLS</h4>` +
        (mySkills.length ? mySkills.map(s => `
          <div class="agent-skill-row">
            <span class="sk-name">${esc(s.name)}${s.enabled ? '' : ' <i style="color:var(--ink-soft)">(off)</i>'}</span>
            <button class="btn" data-unassign="${s.id}" data-agent="${a.key}">remove</button>
          </div>`).join('')
          : `<div style="color:var(--ink-soft);font-size:15px;">none yet — assign from the skills tab</div>`) +
        `<h4>ASSIGN A SKILL</h4>` +
        `<select class="btn" data-assign-select="${a.key}" style="width:100%;">
          <option value="">choose a skill…</option>
          ${allSkillsCache.filter(s => !(s.agents || []).includes(a.key)).map(s =>
            `<option value="${s.id}">${esc(s.name)}</option>`).join('')}
        </select>` +
        `<div style="margin-top:8px;"><button class="btn" data-ask="${a.key}">💬 chat with ${esc(a.name)}</button></div>` +
        `</div>`;
      pane.appendChild(card);
    });

    // interactions
    pane.querySelectorAll('.agent-card-head').forEach(h => {
      h.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        const body = h.parentElement.querySelector('.agent-card-body');
        const open = body.style.display !== 'none';
        body.style.display = open ? 'none' : 'block';
        h.parentElement.classList.toggle('open', !open);
      });
    });
    pane.querySelectorAll('[data-unassign]').forEach(b => {
      b.addEventListener('click', async () => {
        await fetch(`/api/skills/${b.dataset.unassign}/assign`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent: b.dataset.agent, add: false }),
        });
        loadAgentsPane(b.dataset.agent);
      });
    });
    pane.querySelectorAll('[data-assign-select]').forEach(sel => {
      sel.addEventListener('change', async () => {
        if (!sel.value) return;
        await fetch(`/api/skills/${sel.value}/assign`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent: sel.dataset.assignSelect, add: true }),
        });
        loadAgentsPane(sel.dataset.assignSelect);
      });
    });
    pane.querySelectorAll('[data-ask]').forEach(b => {
      b.addEventListener('click', () => {
        const chatTab = document.querySelector('.tab[data-tab="chat"]');
        if (chatTab) chatTab.click();
        userInput.value = `ask ${b.dataset.ask} `;
        userInput.focus();
      });
    });
  } catch (e) {
    pane.innerHTML = '<div class="pane-note">Could not load the team.</div>';
  }
}

// ── Skills pane ──────────────────────────────────────────────────

async function loadSkillsPane() {
  const pane = document.getElementById('skillsList');
  if (!pane) return;
  try {
    const res = await fetch('/api/skills');
    const data = await res.json();
    allSkillsCache = data.skills || [];
    const statsEl = document.getElementById('skillsStats');
    if (statsEl && data.stats) {
      statsEl.textContent =
        `${data.stats.enabled}/${data.stats.total} active · ${data.stats.learned} self-taught · used ${data.stats.total_uses}×`;
    }

    pane.innerHTML = '';
    allSkillsCache.forEach(s => {
      const card = document.createElement('div');
      card.className = 'skill-card' + (s.enabled ? '' : ' disabled');
      card.innerHTML =
        `<div class="skill-head">` +
        `<span class="skill-name">${esc(s.name)}</span>` +
        `<span class="skill-owner">${(s.agents || []).join(', ')}</span>` +
        `</div>` +
        `<div class="skill-desc">${esc(s.description)}</div>` +
        (s.steps && s.steps.length ? `<ol class="skill-steps">${s.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ol>` : '') +
        `<div class="skill-actions">` +
        `<button class="btn" data-toggle="${s.id}">${s.enabled ? 'disable' : 'enable'}</button>` +
        `<button class="btn btn-danger" data-del="${s.id}">remove</button>` +
        `<span class="skill-source ${s.source === 'learned' ? 'learned' : ''}">${esc(s.source || 'user')} · used ${s.uses || 0}×</span>` +
        `</div>`;
      pane.appendChild(card);
    });

    pane.querySelectorAll('[data-toggle]').forEach(b => {
      b.addEventListener('click', async () => {
        await fetch(`/api/skills/${b.dataset.toggle}/toggle`, { method: 'POST' });
        loadSkillsPane();
      });
    });
    pane.querySelectorAll('[data-del]').forEach(b => {
      b.addEventListener('click', async () => {
        if (!confirm('Remove this skill from the library?')) return;
        await fetch(`/api/skills/${b.dataset.del}`, { method: 'DELETE' });
        loadSkillsPane();
      });
    });
  } catch (e) {
    pane.innerHTML = '<div class="pane-note">Could not load skills.</div>';
  }
}

// add-skill form
document.getElementById('addSkillForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const agents = [...document.querySelectorAll('#skillAgents input:checked')]
    .map(i => i.value).filter(v => v !== '*');
  const everyone = document.getElementById('skillAll').checked;
  const body = {
    name: document.getElementById('skillName').value,
    description: document.getElementById('skillDesc').value,
    steps: document.getElementById('skillSteps').value.split('\n').map(s => s.trim()).filter(Boolean),
    agents: everyone ? ['*'] : (agents.length ? agents : ['*']),
  };
  const res = await fetch('/api/skills', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const j = await res.json();
  if (j.ok) {
    document.getElementById('addSkillForm').reset();
    document.getElementById('addSkillBox').removeAttribute('open');
    loadSkillsPane();
  } else {
    alert(j.error || 'Could not add skill');
  }
});

// roster "+ skill" button jumps to the skills tab
document.getElementById('teachBtn').addEventListener('click', () => {
  const tab = document.querySelector('.tab[data-tab="skills"]');
  if (tab) tab.click();
});

// ── Interactive Email Review ─────────────────────────────────────

function removeReviewCard() {
  const el = document.getElementById('reviewCard');
  if (el) el.remove();
}

function renderReviewShow(data) {
  removeReviewCard();
  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.id = 'reviewCard';
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'JARVIS';
  const card = document.createElement('div');
  card.className = 'data-card';
  const title = document.createElement('div');
  title.className = 'data-card-title';
  title.textContent = `EMAIL REVIEW (${data.index + 1}/${data.total})`;
  card.appendChild(title);

  const bizLine = document.createElement('div');
  bizLine.className = 'review-biz';
  bizLine.textContent = data.business || 'Business';
  if (data.ai_powered) {
    const tag = document.createElement('span');
    tag.className = 'tag tag-green';
    tag.textContent = 'AI';
    bizLine.appendChild(document.createTextNode(' '));
    bizLine.appendChild(tag);
  }
  card.appendChild(bizLine);

  const makeField = (labelText, control) => {
    const row = document.createElement('div');
    row.className = 'review-field';
    const l = document.createElement('div');
    l.className = 'review-label';
    l.textContent = labelText;
    row.appendChild(l);
    row.appendChild(control);
    return row;
  };

  const toBox = document.createElement('input');
  toBox.type = 'text';
  toBox.value = data.to || '';
  toBox.disabled = true;
  card.appendChild(makeField('To', toBox));

  const subjectBox = document.createElement('input');
  subjectBox.type = 'text';
  subjectBox.value = data.subject || '';
  card.appendChild(makeField('Subject', subjectBox));

  const bodyBox = document.createElement('textarea');
  bodyBox.rows = 10;
  bodyBox.value = data.body || '';
  card.appendChild(makeField('Body', bodyBox));

  let uploadedPath = null;
  const attRow = document.createElement('div');
  attRow.className = 'review-field';
  const attLabel = document.createElement('div');
  attLabel.className = 'review-label';
  attLabel.textContent = 'Attachment';
  const attControls = document.createElement('div');
  attControls.className = 'review-attach';
  const fileInput = document.createElement('input');
  fileInput.type = 'file';
  const attStatus = document.createElement('span');
  attStatus.className = 'review-att-status';
  attStatus.textContent = data.attachment_name ? `Current: ${data.attachment_name}` : '';

  fileInput.addEventListener('change', async () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f) return;
    attStatus.textContent = 'Uploading...';
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await fetch('/api/upload', { method: 'POST', body: fd });
      const j = await res.json();
      if (j.path) {
        uploadedPath = j.path;
        attStatus.textContent = `Attached: ${j.name}`;
      } else {
        attStatus.textContent = 'Upload failed.';
      }
    } catch (e) {
      attStatus.textContent = 'Upload error.';
    }
  });

  attControls.appendChild(fileInput);
  attControls.appendChild(attStatus);
  attRow.appendChild(attLabel);
  attRow.appendChild(attControls);
  card.appendChild(attRow);

  const btnRow = document.createElement('div');
  btnRow.className = 'review-actions';

  const makeBtn = (text, cls, onClick) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = text;
    b.addEventListener('click', onClick);
    return b;
  };

  const lockButtons = () => {
    btnRow.querySelectorAll('button').forEach(b => { b.disabled = true; });
    fileInput.disabled = true;
  };

  const sendReview = (action, extra) => {
    lockButtons();
    ws.send(JSON.stringify(Object.assign({
      type: 'review_action',
      index: data.index,
      action: action,
    }, extra || {})));
  };

  btnRow.appendChild(makeBtn('Approve & Next', 'review-btn review-btn-approve', () => {
    sendReview('approve', {
      subject: subjectBox.value,
      body: bodyBox.value,
      attachment: uploadedPath,
    });
  }));
  btnRow.appendChild(makeBtn('Skip', 'review-btn review-btn-skip', () => sendReview('skip', {})));
  btnRow.appendChild(makeBtn('Cancel Review', 'review-btn review-btn-cancel', () => {
    removeReviewCard();
    ws.send(JSON.stringify({ type: 'review_cancel' }));
  }));
  card.appendChild(btnRow);

  msg.appendChild(label);
  msg.appendChild(card);
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function renderReviewResult(d) {
  const data = d || {};
  let html = `<div class="data-card"><div class="data-card-title">EMAIL REVIEW COMPLETE</div>`;
  html += `<div style="display:flex;gap:18px;margin-top:4px;">`;
  html += `<div><span style="color:var(--green-ok);font-size:26px;">${data.approved || 0}</span><div style="font-size:13px;color:var(--ink-soft);">Approved</div></div>`;
  html += `<div><span style="color:var(--amber-warn);font-size:26px;">${data.skipped || 0}</span><div style="font-size:13px;color:var(--ink-soft);">Skipped</div></div>`;
  html += `<div><span style="color:var(--red-bad);font-size:26px;">${data.total || 0}</span><div style="font-size:13px;color:var(--ink-soft);">Total</div></div>`;
  html += `</div></div>`;
  appendCard(html);
}

// ── Input Handling ───────────────────────────────────────────────

function sendMessage() {
  const text = userInput.value.trim();
  if (!text) return;

  if (!connected) {
    addSystemMessage('Not connected. Reconnecting...');
    return;
  }

  addMessage('user', text);
  inputHistory.unshift(text);
  if (inputHistory.length > 50) inputHistory.pop();
  historyIndex = -1;

  ws.send(JSON.stringify({ content: text }));
  userInput.value = '';
  setActivity('JARVIS is thinking…', 'busy');
}

userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    sendMessage();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (historyIndex < inputHistory.length - 1) {
      historyIndex++;
      userInput.value = inputHistory[historyIndex];
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (historyIndex > 0) {
      historyIndex--;
      userInput.value = inputHistory[historyIndex];
    } else {
      historyIndex = -1;
      userInput.value = '';
    }
  }
});

sendBtn.addEventListener('click', sendMessage);

// ── Quick Actions ────────────────────────────────────────────────

document.querySelectorAll('#quickActions .chip').forEach(btn => {
  btn.addEventListener('click', () => {
    const action = btn.dataset.action;
    const prompts = {
      search: 'find businesses in Bandel',
      draft: 'draft emails for the businesses',
      research: 'research these businesses',
      send: 'send all emails',
      status: 'show status',
      dashboard: 'show dashboard',
    };
    const text = prompts[action] || action;
    userInput.value = text;
    sendMessage();
  });
});

// ── Sidebar ──────────────────────────────────────────────────────

const sidebar = document.getElementById('sidebar');
const historyBtn = document.getElementById('historyBtn');
const closeSidebar = document.getElementById('closeSidebar');
const convList = document.getElementById('conversationList');

historyBtn.addEventListener('click', () => {
  sidebar.classList.toggle('open');
  loadHistory();
});

closeSidebar.addEventListener('click', () => sidebar.classList.remove('open'));

async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (data.conversations && data.conversations.length > 0) {
      convList.innerHTML = data.conversations.map(c => `
        <div class="conv-item" data-id="${c.id}">
          <div class="conv-title">${esc(c.title)}</div>
          <div class="conv-meta">${c.message_count} messages | ${c.started_at}</div>
        </div>
      `).join('');
      convList.querySelectorAll('.conv-item').forEach(item => {
        item.addEventListener('click', () => loadConversation(item.dataset.id));
      });
    } else {
      convList.innerHTML = '<div class="sidebar-empty">No conversations yet</div>';
    }
  } catch (e) {
    convList.innerHTML = '<div class="sidebar-empty">Failed to load history</div>';
  }
}

async function loadConversation(id) {
  try {
    const res = await fetch(`/api/conversation/${id}`);
    const data = await res.json();
    messagesEl.innerHTML = '';
    (data.messages || []).forEach(m => addMessage(m.role, m.content));
    sidebar.classList.remove('open');
  } catch (e) {
    addSystemMessage('Failed to load conversation');
  }
}

// ── Status Panel ─────────────────────────────────────────────────

const statusPanel = document.getElementById('statusPanel');
const statusBtn = document.getElementById('statusBtn');
const closeStatus = document.getElementById('closeStatus');
const statusContent = document.getElementById('statusContent');

statusBtn.addEventListener('click', async () => {
  statusPanel.classList.toggle('open');
  if (statusPanel.classList.contains('open')) {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      statusContent.innerHTML = `
        <div class="status-row"><span class="status-label">Session</span><span class="status-value">${esc(data.session_id || 'None')}</span></div>
        <div class="status-row"><span class="status-label">Name</span><span class="status-value">${esc(data.session_name || 'None')}</span></div>
        <div class="status-row"><span class="status-label">Product</span><span class="status-value">${esc(data.profile?.product || 'Not set')}</span></div>
        <div class="status-row"><span class="status-label">Target</span><span class="status-value">${esc(data.profile?.target_customers || 'Not set')}</span></div>
        <div class="status-row"><span class="status-label">Tone</span><span class="status-value">${esc(data.profile?.email_tone || 'professional')}</span></div>
        <div class="status-row"><span class="status-label">AI Engine</span><span class="status-value">${data.ai_configured ? 'Configured' : 'Not configured'}</span></div>
        <div class="status-row"><span class="status-label">Businesses</span><span class="status-value">${data.businesses_found || 0}</span></div>
        <div class="status-row"><span class="status-label">No Website</span><span class="status-value">${data.businesses_no_site || 0}</span></div>
        <div class="status-row"><span class="status-label">Drafts</span><span class="status-value">${data.drafts_count || 0}</span></div>
      `;
    } catch (e) {
      statusContent.innerHTML = '<div style="color:var(--red-bad);">Failed to load status</div>';
    }
  }
});

closeStatus.addEventListener('click', () => statusPanel.classList.remove('open'));

// ── Time-of-day ambience ─────────────────────────────────────────
// The outer chrome, window skies and room lighting follow the real
// clock: morning warm, afternoon black & minimal, evening dusk,
// night near-black with stars in the windows.

function phaseForHour(h) {
  if (h >= 5 && h < 11) return 'morning';
  if (h >= 11 && h < 17) return 'afternoon';
  if (h >= 17 && h < 20) return 'evening';
  return 'night';
}

const PHASE_ICON = { morning: '☀', afternoon: '☼', evening: '🌇', night: '☾' };

function applyTimePhase() {
  const now = new Date();
  const phase = phaseForHour(now.getHours());
  document.documentElement.dataset.phase = phase;
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const clockText = document.getElementById('clockText');
  const clockIcon = document.getElementById('clockIcon');
  if (clockText) clockText.textContent = `${hh}:${mm}`;
  if (clockIcon) clockIcon.textContent = PHASE_ICON[phase] || '☀';
}
applyTimePhase();
setInterval(applyTimePhase, 30000);

// ── Music corner ───────────────────────────────────────────────
// A tiny generative lo-fi player: WebAudio synthesizes everything
// live (no files, no streaming). Three stations, one engine.

const MusicCorner = (() => {
  let ctx = null;
  let master = null;
  let playing = false;
  let station = 'lofi';
  let schedulerTimer = null;
  let nextTime = 0;   // when the next scheduled step plays (AudioContext time)
  let step = 0;

  const STATIONS = {
    lofi:  { name: 'lo-fi office',   desc: 'warm tape hiss · soft keys',      bpm: 72,  root: 220, wave: 'triangle' },
    rain:  { name: 'monsoon rain',   desc: 'filtered noise · far thunder',    bpm: 60,  root: 174, wave: 'sine' },
    night: { name: 'midnight synth', desc: 'slow pads · deep pulse',          bpm: 50,  root: 130.8, wave: 'sawtooth' },
  };

  // Simple pentatonic palette per station — safe, always consonant.
  const SCALES = {
    lofi:  [0, 3, 5, 7, 10, 12],
    rain:  [0, 2, 5, 7, 9, 12],
    night: [0, 3, 7, 10, 12, 15],
  };

  function ensureCtx() {
    if (ctx) return;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    master = ctx.createGain();
    master.gain.value = (document.getElementById('musicVol')?.value || 35) / 100 * 0.5;
    master.connect(ctx.destination);
  }

  function noteFreq(root, semis) { return root * Math.pow(2, semis / 12); }

  function playTone(freq, t, dur, gainVal, type) {
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(gainVal, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g).connect(master);
    osc.start(t); osc.stop(t + dur + 0.05);
  }

  function playNoise(t, dur, gainVal, filterFreq) {
    const len = Math.max(1, Math.floor(ctx.sampleRate * dur));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const filt = ctx.createBiquadFilter();
    filt.type = 'lowpass';
    filt.frequency.value = filterFreq;
    const g = ctx.createGain();
    g.gain.setValueAtTime(gainVal, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(filt).connect(g).connect(master);
    src.start(t); src.stop(t + dur);
  }

  function scheduleStep(t) {
    const st = STATIONS[station];
    const scale = SCALES[station];
    const beat = 60 / st.bpm;
    // Bass every 4 steps, melody sparkle probabilistically, hats quietly.
    if (step % 4 === 0) {
      playTone(st.root / 2, t, beat * 3.4, 0.16, st.wave);
    }
    if (Math.random() < 0.62) {
      const semi = scale[Math.floor(Math.random() * scale.length)];
      playTone(noteFreq(st.root, semi + 12), t, beat * 1.1, 0.07, station === 'night' ? 'sine' : 'triangle');
    }
    if (station === 'rain') {
      // Continuous-ish rain bed + occasional thunder rumble.
      playNoise(t, beat * 0.9, 0.045, 1600);
      if (Math.random() < 0.05) playNoise(t, beat * 4, 0.09, 220);
    } else if (step % 2 === 1) {
      playNoise(t, 0.05, 0.02, 6000); // soft hat
    }
    if (station === 'night' && step % 8 === 0) {
      playTone(st.root / 4, t, beat * 7, 0.1, 'sine');
    }
    step++;
  }

  function scheduler() {
    const st = STATIONS[station];
    const beat = 60 / st.bpm;
    if (!nextTime) nextTime = ctx.currentTime + 0.06;
    // Look-ahead scheduling: fill the next 120ms with steps.
    while (nextTime < ctx.currentTime + 0.12) {
      scheduleStep(nextTime);
      nextTime += beat / 2;
    }
  }

  function start() {
    ensureCtx();
    if (ctx.state === 'suspended') ctx.resume();
    playing = true;
    nextTime = 0;
    schedulerTimer = setInterval(scheduler, 90);
    updateUI();
  }

  function stop() {
    playing = false;
    if (schedulerTimer) { clearInterval(schedulerTimer); schedulerTimer = null; }
    updateUI();
  }

  function setStation(key) {
    station = key;
    step = 0;
    updateUI();
  }

  function setVolume(v) {
    if (master) master.gain.value = (v / 100) * 0.5;
  }

  function updateUI() {
    const st = STATIONS[station];
    document.getElementById('musicStation').textContent = st.name;
    document.getElementById('musicDesc').textContent = st.desc;
    const play = document.getElementById('musicPlay');
    play.textContent = playing ? '⏸' : '▶';
    document.getElementById('vinyl').classList.toggle('spin', playing);
    document.querySelectorAll('.station-btn').forEach(b =>
      b.classList.toggle('is-active', b.dataset.station === station));
  }

  // Wiring
  document.getElementById('musicBtn')?.addEventListener('click', () =>
    document.getElementById('musicCorner').classList.toggle('open'));
  document.getElementById('closeMusic')?.addEventListener('click', () =>
    document.getElementById('musicCorner').classList.remove('open'));
  document.getElementById('musicPlay')?.addEventListener('click', () =>
    playing ? stop() : start());
  document.getElementById('musicVol')?.addEventListener('input', (e) => setVolume(+e.target.value));
  document.querySelectorAll('.station-btn').forEach(b =>
    b.addEventListener('click', () => setStation(b.dataset.station)));

  return { start, stop, setStation };
})();

// ── Init ─────────────────────────────────────────────────────────

connect();
addSystemMessage('J.A.R.V.I.S initialized. Type a command or use the buttons below.');
clearActivityIfIdle();
buildRoster();
['scout', 'strategist', 'analyst', 'librarian', 'mailer'].forEach((n, i) => {
  setTimeout(() => getBot(n), i * 160);
});
loadAgentsPane();
loadSkillsPane();
