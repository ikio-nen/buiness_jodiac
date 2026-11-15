/* ═══════════════════════════════════════════════════════════════
   GNOSIS SHELL — loader, slash palette, chat polish.
   Separate module on purpose: every hook here is additive (it reads the
   DOM app.js owns and never rewrites app.js state), so deleting this
   file's <script> tag leaves the app exactly as it was.
   ═══════════════════════════════════════════════════════════════ */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

/* ── 1. Boot screen ──────────────────────────────────────────────
   Hide when the socket reports online; the CSS backstop covers the case
   where no script runs, and the JS ceiling covers a socket that never
   connects. Three independent ways out, so the splash can never strand. */
function finishBoot() {
  const boot = document.getElementById('boot');
  if (!boot || boot.classList.contains('is-done')) return;
  boot.classList.add('is-done');
  window.setTimeout(() => boot.remove(), 520);
}

function watchBoot() {
  const status = document.getElementById('statusText');
  if (!status) return;
  const check = () => {
    if (/online/i.test(status.textContent || '')) finishBoot();
  };
  check();
  const mo = new MutationObserver(check);
  mo.observe(status, { childList: true, characterData: true, subtree: true });
  window.setTimeout(finishBoot, 5000);
}
watchBoot();

/* ── 2. Chat polish ──────────────────────────────────────────────
   Timestamps + the empty state, driven by observing the log. app.js
   keeps full ownership of message nodes; we only annotate them once. */
const messagesEl = document.getElementById('messages');
const chatEmpty = document.getElementById('chatEmpty');

function stamp(node) {
  if (!(node instanceof HTMLElement) || node.dataset.gpStamped) return;
  if (!node.classList.contains('message')) return;
  node.dataset.gpStamped = '1';
  const label = node.querySelector('.msg-label');
  if (label && !label.querySelector('.msg-time')) {
    const t = document.createElement('span');
    t.className = 'msg-time';
    t.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    label.appendChild(t);
  }
}

function refreshChat() {
  if (!messagesEl) return;
  const kids = [...messagesEl.children].filter((n) => n.classList.contains('message'));
  kids.forEach(stamp);
  if (chatEmpty) chatEmpty.hidden = kids.length > 0;
}

if (messagesEl) {
  new MutationObserver(refreshChat).observe(messagesEl, { childList: true });
  refreshChat();
  // Streaming caret on the newest JARVIS bubble while a reply is arriving.
  new MutationObserver(() => {
    const last = messagesEl.lastElementChild;
    $$('.msg-content.is-streaming').forEach((el) => {
      if (!last || !last.contains(el)) el.classList.remove('is-streaming');
    });
    const live = last && last.classList.contains('message-jarvis')
      ? last.querySelector('.msg-content') : null;
    if (live) live.classList.add('is-streaming');
    if (window.__gpStreamTimer) clearTimeout(window.__gpStreamTimer);
    window.__gpStreamTimer = setTimeout(() => {
      $$('.msg-content.is-streaming').forEach((el) => el.classList.remove('is-streaming'));
    }, 2600);
  }).observe(messagesEl, { childList: true, subtree: true, characterData: true });
}

/* ── 3. Slash palette ────────────────────────────────────────────
   Each command expands into the plain phrase the existing parser already
   understands, so nothing here invents a second dispatch path. */
const COMMANDS = [
  { cmd: '/brainstorm', phrase: 'brainstorm', hint: 'think out loud with the team' },
  { cmd: '/search', phrase: 'search ', hint: 'find training institutes near a place', arg: true },
  { cmd: '/draft', phrase: 'draft emails', hint: 'write drafts for the results' },
  { cmd: '/research', phrase: 'research ', hint: 'research a business or a market', arg: true },
  { cmd: '/status', phrase: 'status', hint: 'what the office knows right now' },
  { cmd: '/send', phrase: 'send', hint: 'send the approved drafts' },
];

function buildSlash() {
  const pane = document.querySelector('.tabpane[data-pane="chat"]');
  const input = document.getElementById('userInput');
  if (!pane || !input || document.getElementById('slashMenu')) return;

  const menu = document.createElement('div');
  menu.className = 'slash-menu';
  menu.id = 'slashMenu';
  menu.setAttribute('role', 'listbox');
  menu.setAttribute('aria-label', 'Slash commands');
  menu.hidden = true;
  for (const c of COMMANDS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'slash-item';
    b.dataset.cmd = c.cmd;
    b.setAttribute('role', 'option');
    b.innerHTML = `<b></b><span></span>`;
    b.querySelector('b').textContent = c.cmd;
    b.querySelector('span').textContent = c.hint;
    b.addEventListener('mousedown', (e) => {
      e.preventDefault();
      applyCommand(c);
    });
    menu.appendChild(b);
  }
  pane.appendChild(menu);

  let sel = 0;
  const items = () => [...menu.querySelectorAll('.slash-item')];

  function filter() {
    const q = input.value.startsWith('/') ? input.value.toLowerCase() : null;
    if (q === null) { menu.hidden = true; return; }
    let shown = 0;
    for (const el of items()) {
      const hit = el.dataset.cmd.startsWith(q.split(' ')[0]) || q === '/';
      el.hidden = !hit;
      if (hit) shown++;
    }
    menu.hidden = shown === 0;
    sel = 0;
    paint();
  }
  function paint() {
    items().forEach((el, i) => {
      const on = !el.hidden && i === sel;
      el.classList.toggle('is-sel', on);
      el.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }
  function visible() { return items().filter((el) => !el.hidden); }
  function applyCommand(c) {
    menu.hidden = true;
    input.value = c.arg ? c.phrase : c.phrase;
    input.focus();
    if (!c.arg) {
      const send = document.getElementById('sendBtn');
      if (send) send.click();
    } else {
      input.setSelectionRange(input.value.length, input.value.length);
    }
  }

  input.addEventListener('input', filter);
  input.addEventListener('keydown', (e) => {
    if (menu.hidden) return;
    const vis = visible();
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = (sel + 1) % vis.length; paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = (sel - 1 + vis.length) % vis.length; paint(); }
    else if (e.key === 'Tab') { e.preventDefault(); if (vis[sel]) applyCommand(COMMANDS.find((c) => c.cmd === vis[sel].dataset.cmd)); }
    else if (e.key === 'Escape') { menu.hidden = true; }
    else if (e.key === 'Enter' && vis[sel] && input.value.toLowerCase() === vis[sel].dataset.cmd) {
      e.preventDefault();
      e.stopPropagation();
      applyCommand(COMMANDS.find((c) => c.cmd === vis[sel].dataset.cmd));
    }
  }, true);
}
buildSlash();

/* ── 4. Empty-state cards ────────────────────────────────────── */
for (const card of $$('[data-empty]')) {
  card.addEventListener('click', () => {
    const input = document.getElementById('userInput');
    if (!input) return;
    const cmd = COMMANDS.find((c) => c.cmd === card.dataset.empty);
    if (!cmd) return;
    input.value = cmd.phrase;
    input.focus();
    if (!cmd.arg) {
      const send = document.getElementById('sendBtn');
      if (send) send.click();
    } else {
      input.setSelectionRange(input.value.length, input.value.length);
    }
  });
}
