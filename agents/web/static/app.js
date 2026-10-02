/* ═══════════════════════════════════════════════════════════════
   J.A.R.V.I.S — Agent Office client
   Left: living pixel office. Right: command center (chat/agents/
   skills). Bottom: roster strip. Warm Ghibli theme, no lanes.
   ═══════════════════════════════════════════════════════════════ */

// This module is the office itself: the socket, the chat, the floor and
// the roster. The subsystems that own their own state live beside it as
// ES modules (no build step) - the activity strip, view transitions, the
// QUEUE panel, composer attachments, dictation, and the music corner.
// The ?v= on each import is the same version as the document's app.js
// tag: bump both together or a browser keeps serving an old module.
import { esc, setActivity, clearActivityIfIdle, showQueuedChip, setWorkActive,
         wrapAgentEvent } from './js/util.js?v=43';
import { vtAppend, vtSwap } from './js/transitions.js?v=43';
import { initQueue, renderQueue } from './js/queue.js?v=43';
import { initAttachments, takeAttachment } from './js/attachments.js?v=43';
import { initDictation } from './js/voice.js?v=43';
import { initMusicCorner } from './js/music.js?v=43';
import { renderChecklist, renderInterview, removeChecklistCard } from './js/campaign.js?v=43';
import { initVault } from './js/vault.js?v=43';


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

// One way for a panel to put a frame on the wire without owning the
// socket: the connection decides whether it is live, the panel just asks.
// Exposed for ES modules (campaign.js checklist) that render outside this
// module but must send through the same connection.
function sendFrame(obj) {
  if (ws && connected) ws.send(JSON.stringify(obj));
}
window.wsSend = sendFrame;

// Last message is a welcome greeting with nothing new to say? Replace it.
// Returns true when the caller should skip appending (greeting refreshed).
function replaceWelcome(content) {
  const last = messagesEl.lastElementChild;
  const body = last && last.classList.contains('message-jarvis')
    ? last.querySelector('.msg-content') : null;
  if (body && /^JARVIS online/.test(body.textContent)) {
    body.textContent = content;
    scrollToBottom();
    return true;
  }
  return false;
}

function handleMessage(data) {
  removeTypingIndicator();
  switch (data.type) {
    case 'jarvis':
      if (data.interview) {
        renderInterview(data.content);
      } else if (data.welcome && replaceWelcome(data.content)) {
        // Reconnect with nothing new said: refresh the existing greeting
        // instead of appending a second one that reads as a reset.
      } else {
        addMessage('jarvis', data.content, data);
      }
      if (data.session_id) sessionInfo.textContent = data.session_id;
      // A chat-set goal ("i sell X") lands here as action=goal — keep the
      // chip honest without waiting for a reload.
      if (data.action === 'goal') refreshGoalChip();
      break;
    case 'campaign_checklist':
      renderChecklist(data.data);
      break;
    case 'campaign_end':
      removeChecklistCard();
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
    case 'queue_state': renderQueue(data.items); break;
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

  // A report path in a jarvis message becomes a real link — the backend
  // says "click to download", so the click must actually work.
  if (role !== 'user') {
    const rm = String(content).match(/reports[\\/]campaign_(initial|final)_[A-Za-z0-9_]+\.pdf/i);
    if (rm) {
      const [full, which] = rm;
      const parts = String(content).split(full);
      body.textContent = '';
      body.append(parts[0]);
      const a = document.createElement('a');
      a.href = `/api/report/${which}`;
      a.className = 'msg-file-link';
      a.textContent = `campaign_${which} report (PDF)`;
      body.append(a);
      body.append(parts.slice(1).join(full));
    }
  }

  if (meta.error) body.classList.add('is-error');

  msg.appendChild(label);
  msg.appendChild(body);
  vtAppend(messagesEl, msg);
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


function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// Clickable divs (roster cards, conversations, agent heads, bots) get
// button semantics + Enter/Space activation so keyboard users can reach
// everything a mouse can.
function makeActivatable(el) {
  if (!el) return;
  el.setAttribute('role', 'button');
  el.tabIndex = 0;
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      el.click();
    }
  });
}

// ── Data Renderers ───────────────────────────────────────────────

function renderSearchResults(data) {
  if (!data.businesses || data.businesses.length === 0) {
    addMessage('jarvis', 'No businesses found in that area.');
    return;
  }
  const icp = data.icp || {};
  let html = `<div class="data-card"><div class="data-card-title">SEARCH RESULTS</div>`;

  // ICP verdict bar — what the office decided about this batch, shown before
  // the list so the filtering is visible instead of silent.
  if (icp.total) {
    html += `<div class="icp-bar">`;
    if (icp.goal_label) html += `<span class="icp-goal">${esc(icp.goal_label)}</span>`;
    html += `<span class="icp-stat icp-fits"><b>${icp.fits || 0}</b> direct fits</span>`;
    html += `<span class="icp-stat icp-plausible"><b>${icp.plausible || 0}</b> plausible</span>`;
    html += `<span class="icp-stat icp-drop"><b>${icp.dropped || 0}</b> ruled out</span>`;
    if (icp.product) html += `<span class="icp-for">for ${esc(icp.product)}</span>`;
    html += `</div>`;
    if (icp.by_type && icp.by_type.length) {
      html += `<div class="icp-types">` + icp.by_type.map(t =>
        `<span class="icp-type">${esc(t.label)} <b>${t.count}</b></span>`).join('') + `</div>`;
    }
  }

  html += `<table class="data-table"><tr><th>#</th><th>Name</th><th>Fit</th><th>Type</th><th>Site</th></tr>`;
  data.businesses.forEach((b, i) => {
    const fit = b.fit || 'plausible';
    const score = b.fit_score ? `<span class="fit-score">${b.fit_score}</span>` : '';
    const badge = `<span class="fit-badge fit-${esc(fit)}">${fit === 'fits' ? 'FIT' : esc(fit).toUpperCase()}</span>${score}`;
    const type = b.institution_type ? esc(b.institution_type)
                                    : '<span class="fit-unknown">not classified</span>';
    const webTag = b.has_website ? '<span class="tag tag-green">YES</span>' : '<span class="tag tag-red">NO</span>';
    html += `<tr><td>${i + 1}</td><td>${esc(b.name)}</td><td>${badge}</td><td class="fit-type">${type}</td><td>${webTag}</td></tr>`;
  });
  html += `</table><div style="margin-top:8px;font-size:14px;color:var(--ink-soft);">Found ${data.total} total: `;
  html += `<span class="tag tag-red">${data.no_site_count} without site</span> `;
  html += `<span class="tag tag-green">${data.with_site_count} with site</span></div>`;
  if (data.source === 'gmaps') {
    html += `<div style="margin-top:6px;font-size:14px;color:var(--amber-warn);">↳ sourced from Google Maps (Overpass had no data here)</div>`;
  }
  html += `</div>`;
  appendCard(html);
}

function renderDraftResults(data) {
  let html = `<div class="data-card"><div class="data-card-title">DRAFTED ${data.count} EMAILS</div>`;
  html += `<table class="data-table"><tr><th>Business</th><th>Subject</th><th>Email</th></tr>`;
  data.drafts.forEach(d => {
    const emailTag = d.to ? `<span class="tag tag-green">${esc(d.to)}</span>` : '<span class="tag tag-yellow">No email</span>';
    const exec = d.exec_name
      ? `<div style="font-size:13px;color:var(--amber-warn);">${esc(d.exec_name)}${d.exec_title ? ' — ' + esc(d.exec_title) : ''}</div>` : '';
    html += `<tr><td>${esc(d.business)}${exec}</td><td>${esc(d.subject)}</td><td>${emailTag}</td></tr>`;
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
  vtAppend(messagesEl, msg);
  scrollToBottom();
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

// Desk slots for runtime hires (station-hired-0..7) — CSS positions them in
// open floor areas; hiring.py assigns the slot, the API reports it, and
// deriveRosterFromApi points BOT_HOME at it.
function ensureHiredStations() {
  const stage = document.getElementById('opsStage');
  if (!stage) return;
  for (let i = 0; i < 8; i++) {
    const id = `station-hired-${i}`;
    if (document.getElementById(id)) continue;
    const st = document.createElement('div');
    st.className = 'station station-hired';
    st.id = id;
    st.title = 'Hired specialist desk';
    st.innerHTML = '<div class="fur fur-desk"><span class="desk"></span><span class="mon"><i></i></span><span class="chair"></span></div>' +
      `<div class="zone-label">DESK ${i + 1}</div>`;
    stage.appendChild(st);
  }
}
ensureHiredStations();

// ── Roster state: projected from /api/agents, never declared here ────
// An agent's identity — name, role, avatar look, desk — is owned by the
// server (`agent_team.AGENTS`) and published by /api/agents as ONE record
// shape for built-ins and hires alike. The client keeps no roster of its
// own: that duplication is exactly what let the floor drift from the API.
// These three maps are projections of that response, written only by
// deriveRosterFromApi() at init. Anywhere a station is needed, callers fall
// back to 'station-brain', so an unknown key still routes somewhere real.
const BOT_HOME = {};     // key -> floor station id
const LOOKS = {};        // key -> avatar look (skin/hair/hairStyle/shirt/accessory)
const ROSTER_META = {};  // key -> { label, role } for the roster strip

// ── The pixel cast ────────────────────────────────────────────────
// One look schema, one renderer. Every avatar in the office (floor bot,
// roster card, agent pane, command center) comes from spriteHTML(), so a
// detail added here appears everywhere at once.
//   skin      face tone      hair       hair colour
//   hairStyle short|buzz|bob|long|bun|curly|bald
//   shirt     top colour     accessory  none|glasses|headset|cap|tie
//
// The looks for real agents are NOT declared here — the roster serves each
// agent its own (see the ROSTER state above). DEFAULT_LOOK is only the
// fallback so an unrecognised key still draws a person rather than a hole.
const DEFAULT_LOOK = {
  skin: '#f0c9a0', hair: '#2b2b33', hairStyle: 'short',
  shirt: '#8a8172', accessory: 'none', accColor: '',
};

// JARVIS is the app's own interlocutor, not a roster member, so its look is
// chrome and belongs with the chrome.
const JARVIS_LOOK = { skin: '#e8c39a', hair: '#c0c0c8', hairStyle: 'short',
                      shirt: '#c1666b', accessory: 'headset' };
LOOKS.jarvis = JARVIS_LOOK;

function spriteHTML(key) {
  const look = { ...DEFAULT_LOOK, ...(LOOKS[key] || {}) };
  const acc = look.accessory && look.accessory !== 'none' ? look.accessory : '';
  const capStyle = look.accColor ? ` style="background:${look.accColor}"` : '';
  return `<div class="sprite" data-hair="${look.hairStyle}">` +
    `<div class="sp-hair" style="background:${look.hair}"></div>` +
    `<div class="sp-face" style="background:${look.skin}">` +
      (acc === 'glasses' ? `<span class="sp-glasses"><i></i><i></i></span>` : '') +
    `</div>` +
    `<div class="sp-body" style="background:${look.shirt}">` +
      `<span class="sp-badge"></span>` +
      (acc === 'tie' ? `<span class="sp-tie"></span>` : '') +
    `</div>` +
    `<div class="sp-legs"><i></i><i></i></div>` +
    (acc === 'cap' ? `<span class="sp-cap"${capStyle}></span>` : '') +
    (acc === 'headset' ? `<span class="sp-headset"></span>` : '') +
    `</div>`;
}

// Compact avatar (roster card, agent pane, command center): the same figure,
// scaled down by CSS — no second set of sprite rules to keep in sync.
const _cmdAva = document.getElementById('cmdAva');
if (_cmdAva) _cmdAva.innerHTML = spriteHTML('jarvis');

// The one merge point: everything the floor, the roster strip and the agent
// pane know about an agent arrives here. Nothing else may write these maps.
function deriveRosterFromApi(agents) {
  (agents || []).forEach(a => {
    if (!a || !a.key) return;
    BOT_HOME[a.key] = a.home_station || 'station-brain';
    if (a.look) LOOKS[a.key] = a.look;
    ROSTER_META[a.key] = {
      label: String(a.name || a.key).toUpperCase(),
      role: a.role || 'specialist',
    };
  });
}

async function loadRosterAndSpawn() {
  // The floor renders the roster the server hands it — built-ins and hires in
  // one list, each carrying its own look and desk. If the roster cannot be
  // fetched the floor simply stays empty rather than inventing agents that
  // may not exist; the chat connection is independent and keeps working.
  let keys = [];
  try {
    const res = await fetch('/api/agents');
    const data = await res.json();
    if (data && data.agents) {
      deriveRosterFromApi(data.agents);
      keys = data.agents.map(a => a.key).filter(Boolean);
    }
  } catch (e) {
    console.warn('roster fetch failed — floor not populated', e);
  }
  buildRoster();
  keys.forEach((k, i) => {
    if (k === 'jarvis') return;
    setTimeout(() => getBot(k), i * 160);
  });
}

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
  makeActivatable(el);

  el.innerHTML = spriteHTML(name);

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
      // Splitter dragged the floor narrow: bot name pills are wider than
      // their 30px bots and clip at the room edge — drop them, the same
      // declutter the stacked mobile layout already applies.
      opsStage.classList.toggle('is-narrow', w < 420);
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
  opsRoster.innerHTML = '';   // derived maps may have grown hires — rebuild clean
  Object.keys(ROSTER_META).forEach(name => {
    const meta = ROSTER_META[name];
    const card = document.createElement('div');
    card.className = 'roster-card';
    card.addEventListener('click', () => openAgentPane(name));
    makeActivatable(card);
    card.innerHTML =
      `<span class="roster-ava">${spriteHTML(name)}</span>` +
      `<div class="roster-meta">` +
        `<div class="roster-row">` +
          `<span class="roster-name">${esc(meta.label)}</span>` +
          `<span class="roster-state" data-state="idle">idle</span>` +
        `</div>` +
        `<div class="roster-role">${esc(meta.role)}</div>` +
        `<div class="roster-bar" aria-hidden="true"><i></i></div>` +
      `</div>`;
    opsRoster.appendChild(card);
    rosterCards[name] = {
      card, msgs: 0, activeTimer: null,
      stateEl: card.querySelector('.roster-state'),
      barEl: card.querySelector('.roster-bar i'),
    };
  });
  updateRosterBars();
}

// The bar shows each agent's share of the work actually seen this session —
// a real ratio, not a decorative animation.
function updateRosterBars() {
  const counts = Object.values(rosterCards).map(rc => rc.msgs);
  const max = Math.max(1, ...counts);
  Object.values(rosterCards).forEach(rc => {
    if (rc.barEl) rc.barEl.style.width = Math.round(rc.msgs / max * 100) + '%';
  });
}

function rosterPing(name, state, countMsg = true) {
  const rc = rosterCards[name];
  if (!rc) return;
  if (countMsg) {
    rc.msgs += 1;
    updateRosterBars();
  }
  rc.card.classList.remove('active', 'done', 'error');
  if (state === 'error') rc.card.classList.add('error');
  else if (state === 'done') rc.card.classList.add('done');
  else if (state) rc.card.classList.add('active');
  if (rc.stateEl) {
    rc.stateEl.dataset.state = state === 'error' ? 'error'
      : state === 'done' ? 'done'
      : state ? 'working' : 'idle';
    rc.stateEl.textContent = state === 'error' ? 'error'
      : state === 'done' ? 'done'
      : state ? 'working' : 'idle';
  }
  rc.card.title = `${rc.msgs} office event${rc.msgs === 1 ? '' : 's'} this session`;
  clearTimeout(rc.activeTimer);
  rc.activeTimer = setTimeout(() => {
    rc.card.classList.remove('active', 'done', 'error');
    if (rc.stateEl) { rc.stateEl.dataset.state = 'idle'; rc.stateEl.textContent = 'idle'; }
  }, state === 'error' ? 1200 : 2500);
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
    // Packet endpoints are a mix: some are stages ('pipeline', 'drafts',
    // 'sent'), some are roster keys. Stages own their own stations here;
    // roster keys resolve through BOT_HOME so an agent's desk is never
    // restated — and a hire animates to its real slot for free.
    const STAGE_STATION = {
      pipeline: 'station-scout', search: 'station-scraper',
      brain: 'station-brain', drafts: 'station-drafts', sent: 'station-sent',
    };
    const fromStation = STAGE_STATION[ev.from_] || BOT_HOME[ev.from_] || 'station-brain';
    const toStation = STAGE_STATION[ev.to] || BOT_HOME[ev.to] || 'station-brain';
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
    document.querySelectorAll('.tab').forEach(t => {
      const on = t === tab;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    const panes = [...document.querySelectorAll('.tabpane')];
    const next = panes.find(p => p.dataset.pane === tab.dataset.tab);
    vtSwap(next, panes);
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
      const mySkills = allSkillsCache.filter(s =>
        (s.agents || []).includes(a.key) || (s.agents || []).includes('*'));
      const card = document.createElement('div');
      card.className = 'agent-card' + (focusKey === a.key ? ' open' : '');
      card.innerHTML =
        `<div class="agent-card-head">` +
        `<span class="roster-ava">${spriteHTML(a.key)}</span>` +
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
      makeActivatable(h);
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
  toBox.setAttribute('aria-label', 'To');
  card.appendChild(makeField('To', toBox));

  const subjectBox = document.createElement('input');
  subjectBox.type = 'text';
  subjectBox.value = data.subject || '';
  subjectBox.setAttribute('aria-label', 'Subject');
  card.appendChild(makeField('Subject', subjectBox));

  const bodyBox = document.createElement('textarea');
  bodyBox.rows = 10;
  bodyBox.value = data.body || '';
  bodyBox.setAttribute('aria-label', 'Body');
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
  fileInput.setAttribute('aria-label', 'Attachment file');
  const attStatus = document.createElement('span');
  attStatus.className = 'review-att-status';
  attStatus.textContent = data.attachment_name ? `Current: ${data.attachment_name}` : '';

  fileInput.addEventListener('change', async () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f) return;
    attStatus.textContent = 'Uploading…';
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
    addSystemMessage('Not connected. Reconnecting…');
    return;
  }

  // Action mode: with “ask first” on, anything that sends or destroys gets a
  // confirmation step before it leaves the box.
  if (!bypassOn && DESTRUCTIVE.test(text)) {
    showConfirmBar(text, () => deliverMessage(text));
    return;
  }
  deliverMessage(text);
}

function deliverMessage(text) {
  addMessage('user', text);
  inputHistory.unshift(text);
  if (inputHistory.length > 50) inputHistory.pop();
  historyIndex = -1;

  const payload = { content: text };
  const att = takeAttachment();   // one file never rides two messages
  if (att) {
    payload.attachment = att.path;
    payload.attachment_name = att.name;
  }
  ws.send(JSON.stringify(payload));
  userInput.value = '';
  hideConfirmBar();
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



// ── Action mode: run sending/delivery straight, or ask first ────
const modeBtn = document.getElementById('modeBtn');
let bypassOn = localStorage.getItem('jarvis.bypass') === '1';
const DESTRUCTIVE = /\b(send|deliver|fire off|sync|cleanup|delete|remove)\b/i;

function renderModeChip() {
  if (!modeBtn) return;
  modeBtn.setAttribute('aria-pressed', bypassOn ? 'true' : 'false');
  modeBtn.textContent = bypassOn ? 'bypass on' : 'ask first';
  modeBtn.title = bypassOn
    ? 'On — sending and delivery actions run without asking first'
    : 'Off — JARVIS asks before sending or deleting anything';
}
renderModeChip();

function cycleMode() {
  bypassOn = !bypassOn;
  localStorage.setItem('jarvis.bypass', bypassOn ? '1' : '0');
  renderModeChip();
  setActivity(bypassOn
    ? 'Bypass on — sending actions will run without asking.'
    : 'Ask first — sending actions need a confirmation.', '');
}

if (modeBtn) modeBtn.addEventListener('click', cycleMode);

// shift+tab cycles the mode from anywhere in the command center
userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Tab' && e.shiftKey) {
    e.preventDefault();
    cycleMode();
  }
});

function showConfirmBar(text, onRun) {
  hideConfirmBar();
  const bar = document.createElement('div');
  bar.className = 'confirm-bar';
  bar.id = 'confirmBar';
  bar.innerHTML =
    `<span>Run “${esc(text)}”? This sends or changes real data.</span>` +
    `<span class="confirm-acts">` +
    `<button type="button" class="btn btn-primary" id="confirmRun">run</button>` +
    `<button type="button" class="btn" id="confirmCancel">cancel</button></span>`;
  document.querySelector('.composer').appendChild(bar);
  document.getElementById('confirmRun').addEventListener('click', () => {
    hideConfirmBar();
    onRun();
  });
  document.getElementById('confirmCancel').addEventListener('click', hideConfirmBar);
}

function hideConfirmBar() {
  const bar = document.getElementById('confirmBar');
  if (bar) bar.remove();
}

// ── Context meter ────────────────────────────────────────────────
// Estimated tokens for this conversation (characters ÷ 4). Labelled an
// estimate in its tooltip rather than dressed up as exact accounting.
const ctxChip = document.getElementById('ctxChip');
function updateCtxChip() {
  if (!ctxChip || !messagesEl) return;
  const chars = messagesEl.textContent.length;
  const tokens = Math.round(chars / 4);
  ctxChip.textContent = tokens >= 1000
    ? `ctx ${(tokens / 1000).toFixed(1)}k`
    : `ctx ${tokens}`;
}
if (messagesEl && window.MutationObserver) {
  new MutationObserver(updateCtxChip)
    .observe(messagesEl, { childList: true, subtree: true, characterData: true });
}
updateCtxChip();


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
  const opening = !sidebar.classList.contains('open');
  vtSwap(opening ? sidebar : null, [sidebar]);
  // Only refetch when actually opening; closing shouldn't re-render the list.
  if (opening) loadHistory();
});

closeSidebar.addEventListener('click', () => sidebar.classList.remove('open'));

async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (data.conversations && data.conversations.length > 0) {
      convList.innerHTML = data.conversations.map(c => `
        <div class="conv-item" data-id="${c.id}">
          <div class="conv-main">
            <div class="conv-title">${esc(c.title)}</div>
            <div class="conv-meta">${c.message_count} messages | ${c.started_at}</div>
          </div>
          <button class="conv-del" data-del="${c.id}" title="Delete conversation" aria-label="Delete conversation: ${esc(c.title)}">✕</button>
        </div>
      `).join('');
      convList.querySelectorAll('.conv-item').forEach(item => {
        makeActivatable(item);
        item.addEventListener('click', () => loadConversation(item.dataset.id));
      });
      convList.querySelectorAll('.conv-del').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();   // don't load the conversation we're deleting
          const id = btn.dataset.del;
          if (!confirm('Delete this conversation? This cannot be undone.')) return;
          btn.disabled = true;
          try {
            const res = await fetch(`/api/conversation/${id}`, { method: 'DELETE' });
            const j = await res.json();
            if (j.ok) {
              const item = btn.closest('.conv-item');
              if (item) item.remove();
              if (!convList.querySelector('.conv-item')) {
                convList.innerHTML = '<div class="sidebar-empty">No conversations yet</div>';
              }
            } else {
              btn.disabled = false;
              alert(j.error || 'Could not delete the conversation.');
            }
          } catch (err) {
            btn.disabled = false;
            alert('Delete failed — is the office server running?');
          }
        });
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
  const opening = !statusPanel.classList.contains('open');
  vtSwap(opening ? statusPanel : null, [statusPanel]);
  // vtSwap applies classes in an async callback — never re-read the class
  // here (it still holds the OLD value). Trust `opening` instead.
  if (opening) {
    statusContent.innerHTML = 'Loading…';
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

// ── Selling-goal chip + panel ────────────────────────────────────
// What JARVIS is selling is user state, not a guess — the chip shows it,
// the panel pins/clears it, and searches run against the pin.

const goalChip = document.getElementById('goalChip');
const goalChipText = document.getElementById('goalChipText');
const goalPanel = document.getElementById('goalPanel');
const goalBody = document.getElementById('goalBody');

function applyGoalState(data) {
  if (!data || data.error) return;
  goalChip.classList.toggle('pinned', !data.is_auto);
  goalChipText.textContent = `Goal: ${data.is_auto ? 'auto' : (data.label || data.active)}`;
  goalChip.title = data.is_auto
    ? 'No goal pinned — JARVIS infers it per search. Click to pin one.'
    : `Pinned: selling ${data.label}. Click to change or clear.`;
  goalChip.setAttribute('aria-expanded', goalPanel.classList.contains('open') ? 'true' : 'false');
}

async function refreshGoalChip() {
  try {
    const res = await fetch('/api/goals');
    applyGoalState(await res.json());
  } catch (e) { /* chip keeps its last known state */ }
}

async function renderGoalPanel() {
  goalBody.innerHTML = 'Loading…';
  let data;
  try {
    const res = await fetch('/api/goals');
    data = await res.json();
  } catch (e) {
    goalBody.innerHTML = '<div class="goal-note">Could not load goals.</div>';
    return;
  }
  if (data.error) {
    goalBody.innerHTML = `<div class="goal-note">${esc(data.error)}</div>`;
    return;
  }
  applyGoalState(data);
  const parts = [];
  parts.push(`<div class="goal-note">Pin what JARVIS is selling. Searches, drafts and research run against the pin until you change it.</div>`);
  parts.push(`<button class="goal-option${data.is_auto ? ' is-active' : ''}" data-goal="" role="button" tabIndex="0">` +
    `<span>Auto (infer per search)</span>${data.is_auto ? '<span class="goal-set">current</span>' : ''}</button>`);
  for (const g of data.goals || []) {
    const isActive = data.active === g.key;
    parts.push(`<button class="goal-option${isActive ? ' is-active' : ''}" data-goal="${esc(g.key)}" role="button" tabIndex="0">` +
      `<span>${esc(g.label)}</span>${isActive ? '<span class="goal-set">current</span>' : ''}</button>`);
  }
  if (data.active && data.is_auto === false && !((data.goals || []).some(g => g.key === data.active))) {
    parts.push(`<div class="goal-note">Pinned custom goal: <b>${esc(data.label)}</b></div>`);
  }
  parts.push(`<div class="goal-custom-row">` +
    `<input id="goalCustomInput" type="text" placeholder="Something else… e.g. laptops" aria-label="Custom goal">` +
    `<button id="goalCustomSet">Pin</button></div>`);
  goalBody.innerHTML = parts.join('');

  goalBody.querySelectorAll('.goal-option').forEach(btn => {
    btn.addEventListener('click', () => setGoal(btn.dataset.goal));
  });
  const input = document.getElementById('goalCustomInput');
  const setBtn = document.getElementById('goalCustomSet');
  const commit = () => { const v = (input.value || '').trim(); if (v) setGoal(v); };
  setBtn.addEventListener('click', commit);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') commit(); });
}

async function setGoal(goal) {
  goalBody.innerHTML = 'Saving…';
  try {
    const res = await fetch('/api/goals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal }),
    });
    const data = await res.json();
    if (!res.ok) {
      goalBody.innerHTML = `<div class="goal-note">${esc(data.detail || 'Could not set goal')}</div>`;
      return;
    }
    applyGoalState({ active: data.data?.goal || '', label: data.data?.goal_label || '', is_auto: !data.data?.goal });
  } catch (e) {
    goalBody.innerHTML = '<div class="goal-note">Could not set goal.</div>';
    return;
  }
  await renderGoalPanel();
}

goalChip.addEventListener('click', async () => {
  const opening = !goalPanel.classList.contains('open');
  vtSwap(opening ? goalPanel : null, [goalPanel]);
  goalChip.setAttribute('aria-expanded', opening ? 'true' : 'false');
  if (opening) await renderGoalPanel();
});
document.getElementById('closeGoal').addEventListener('click', () => {
  goalPanel.classList.remove('open');
  goalChip.setAttribute('aria-expanded', 'false');
});
refreshGoalChip();

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
  const clockText = document.getElementById('clockText');
  const clockIcon = document.getElementById('clockIcon');
  if (clockText) {
    clockText.textContent = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit', hour12: false }).format(now);
  }
  if (clockIcon) clockIcon.textContent = PHASE_ICON[phase] || '☀';
}
applyTimePhase();
setInterval(applyTimePhase, 30000);


// ── Init ─────────────────────────────────────────────────────────

// The panels that own their own state start here. Order matters: the
// queue panel needs the socket before the first queue_state frame, and the
// activity strip decorates the floor's handler before anything connects.
initQueue({ send: sendFrame, onWork: setWorkActive });
initAttachments({ setActivity });
initDictation({ input: userInput, setActivity });
initMusicCorner({ vtSwap });
initVault();
handleAgentEvent = wrapAgentEvent(handleAgentEvent, STATUS_TEXT);

connect();
addSystemMessage('J.A.R.V.I.S initialized. Type a command or use the buttons below.');
clearActivityIfIdle();
loadRosterAndSpawn();   // one truth: the API roster drives the floor
loadAgentsPane();
loadSkillsPane();

// A campaign waiting on the user must survive a reload: re-render its gate
// (checklist or interview question) instead of silently waiting on a card
// that died with the old page.
fetch('/api/campaign').then(r => r.json()).then(c => {
  if (c.phase === 'awaiting_selection' && c.checklist) renderChecklist(c.checklist);
  else if (c.phase === 'interview' && c.question) renderInterview(c.question);
}).catch(() => {});


// ── Splitter: floor ↔ command center resize ─────────────────────

// The user drags the vertical grip (or focuses it and nudges with ←/→)
// to change how the row splits between the office floor and the chat
// panel. The ratio is stored in --floor-fr on .app (grid fr units) and
// persisted to localStorage, so the split survives reloads. Desktop
// widths only — the stacked layout hides the grip entirely.

(function initSplitter() {
  const appEl = document.querySelector('.app');
  const grip = document.getElementById('splitGrip');
  if (!appEl || !grip) return;

  const KEY = 'jarvis.floorFr';   // stores the floor's flex RATIO (unitless)
  const MIN_PX = 22;        // px the grip must travel to count as a drag

  // The desktop grid takes its whole track list from --floor-cols. A bare
  // number — and even calc(number * 1fr) — is an invalid track size and
  // would silently collapse the entire desktop grid (the squeezed-floor
  // bug), so the JS writes ready-made `Nfr` columns instead.
  function trackList(fr) {
    const clamped = Math.min(6, Math.max(0.2, fr));
    return `minmax(280px, ${clamped}fr) 0px minmax(340px, 1fr)`;
  }

  function setFloorFr(fr) {
    const cols = trackList(fr);
    appEl.style.setProperty('--floor-cols', cols);
    return parseFloat(cols.match(/([\d.]+)fr/)[1]);
  }

  function floorFrNow() {
    // Inline track list is the live truth during a drag; fall back to the
    // saved ratio, then the designed default.
    const inline = appEl.style.getPropertyValue('--floor-cols').trim();
    const m = inline.match(/minmax\(280px, ([\d.]+)fr\)/);
    if (m) return parseFloat(m[1]);
    const saved = parseFloat(localStorage.getItem(KEY));
    if (Number.isFinite(saved) && saved >= 0.2 && saved <= 6) return saved;
    return 1.9;
  }

  // Restore the saved split on load (floorFrNow validates the range).
  if (localStorage.getItem(KEY) !== null) {
    setFloorFr(floorFrNow());
  }

  // True when the side-by-side grid (and therefore the grip) is active.
  function sideBySide() {
    return !window.matchMedia('(max-width: 900px)').matches;
  }

  function beginDrag(e) {
    if (!sideBySide()) return;
    e.preventDefault();
    const startX = e.clientX;
    const startFr = floorFrNow();
    // clientWidth minus 10px padding each side minus the TWO 10px gaps the
    // grip track sits between (floor|gap|0px-grip|gap|cmd).
    const rowWidth = appEl.clientWidth - 20 - 20;
    // Floor pixels are f/(f+1) of the row — NONLINEAR in the ratio f. The
    // first attempt stepped f by dx/pxPerFr (linear) and the grip lagged
    // the cursor badly (260px of mouse moved it 75px at 1400px, observed
    // live). Invert the relationship exactly so the grip tracks the mouse
    // 1:1: from targetFloorPx, f = target / (rowWidth - target). The
    // minmax() minimums (floor 280, chat 340) still clamp the render; the
    // grip then stops at the clamp while the cursor keeps moving, which
    // is the correct feel.
    const startFloorPx = startFr / (startFr + 1) * rowWidth;
    let moved = false;

    document.body.classList.add('is-resizing');
    grip.classList.add('is-active');
    try {
      grip.setPointerCapture(e.pointerId);
    } catch {
      // Stale/synthetic pointer id: capture is an optimization here, the
      // window-level listeners below carry the drag regardless. Never let
      // it abort the drag setup (body would stay stuck in is-resizing).
    }

    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      if (Math.abs(dx) > MIN_PX) moved = true;
      const targetFloorPx = Math.min(
        rowWidth - 340,                       // chat panel minimum
        Math.max(280, startFloorPx + dx)      // floor minimum
      );
      setFloorFr(targetFloorPx / (rowWidth - targetFloorPx));
    };
    const onUp = () => {
      document.body.classList.remove('is-resizing');
      grip.classList.remove('is-active');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      if (moved) {
        localStorage.setItem(KEY, String(floorFrNow()));
        setActivity('Split saved.', '');
      }
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }

  function nudge(dir) {
    if (!sideBySide()) return;
    // Nudge in px against the current row so the step feels constant.
    const rowWidth = appEl.clientWidth - 20 - 20;
    const perFr = rowWidth / (floorFrNow() + 1);
    const stepFr = 24 / perFr;
    setFloorFr(floorFrNow() + dir * stepFr);
    localStorage.setItem(KEY, String(floorFrNow()));
  }

  grip.addEventListener('pointerdown', beginDrag);
  grip.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); nudge(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); nudge(+1); }
    else if (e.key === 'Home') {
      e.preventDefault();
      appEl.style.removeProperty('--floor-cols');  // back to the designed 1.9fr
      localStorage.removeItem(KEY);
    }
  });
  // Double-click: reset to the designed split.
  grip.addEventListener('dblclick', () => {
    appEl.style.removeProperty('--floor-cols');
    localStorage.removeItem(KEY);
  });
})();
