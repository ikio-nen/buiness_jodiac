/* ── Key vault ────────────────────────────────────────────────────────
   Only the owner's code opens it. The modal asks for the access code,
   exchanges it for a server-side session token (never persisted), and
   shows masked keys. Revealing a full value copies it to the clipboard
   without ever putting it in the DOM's text content.
   Server contract: /api/vault/status | set-code | unlock | lock |
   keys?token= | reveal/{id}?token=
   ═══════════════════════════════════════════════════════════════════ */

let token = null;          // in-memory only — dies with the page
let ttlTimer = null;

const el = {
  btn:        null, panel: null, close: null, body: null,
  title:      null,
};

function $(id) { return document.getElementById(id); }

function openPanel() {
  el.panel.classList.add('open');
  refresh();
}

function closePanel() {
  el.panel.classList.remove('open');
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail || {};
    const msg = typeof d === 'string' ? d : (d.message || 'Request failed');
    const err = new Error(msg);
    err.detail = d;
    throw err;
  }
  return data;
}

function stopTtl() {
  if (ttlTimer) { clearInterval(ttlTimer); ttlTimer = null; }
}

function renderLocked(message) {
  stopTtl();
  token = null;
  el.body.innerHTML = `
    <p class="vault-note">${message || 'Enter your access code to see the keys.'}</p>
    <form id="vaultForm" class="vault-form">
      <input type="password" id="vaultCode" class="vault-input"
             placeholder="access code" autocomplete="off" aria-label="Access code">
      <button type="submit" class="vault-btn">Unlock</button>
    </form>
    <p class="vault-err" id="vaultErr" role="alert"></p>`;
  $('vaultForm').addEventListener('submit', onUnlock);
  $('vaultCode').focus();
}

function renderSetup() {
  el.body.innerHTML = `
    <p class="vault-note">First time here — pick an access code. Only this
    code can open the key vault.</p>
    <form id="vaultForm" class="vault-form">
      <input type="password" id="vaultCode" class="vault-input"
             placeholder="new access code (4+ chars)" autocomplete="new-password"
             aria-label="New access code">
      <button type="submit" class="vault-btn">Set code</button>
    </form>
    <p class="vault-err" id="vaultErr" role="alert"></p>`;
  $('vaultForm').addEventListener('submit', onSetCode);
  $('vaultCode').focus();
}

function renderUnlocked(entries, ttl) {
  const rows = entries.map((e) => {
    if (e.kind === 'info') {
      return `<div class="vault-row">
        <span class="vault-label">${e.label}</span>
        <span class="vault-value">${e.value || '<i>not set</i>'}</span>
      </div>`;
    }
    const src = e.source === 'env' ? ' <span class="vault-src">env</span>' : '';
    return `<div class="vault-row">
      <span class="vault-label">${e.label}${src}</span>
      <span class="vault-value">${e.set ? e.masked : '<i>not set</i>'}</span>
      ${e.set ? `<button class="vault-eye" data-id="${e.id}"
            title="Reveal and copy" aria-label="Reveal ${e.label}">👁</button>` : ''}
    </div>`;
  }).join('');
  el.body.innerHTML = `
    <p class="vault-note vault-open-note">Vault open
      <span id="vaultTtl" class="vault-ttl"></span></p>
    ${rows}
    <div class="vault-actions">
      <button id="vaultActivity" class="vault-btn vault-btn-ghost">Activity</button>
      <button id="vaultChange" class="vault-btn vault-btn-ghost">Change code</button>
      <button id="vaultLockBtn" class="vault-btn">Lock now</button>
    </div>
    <p class="vault-err" id="vaultErr" role="alert"></p>`;
  el.body.querySelectorAll('.vault-eye').forEach((b) =>
    b.addEventListener('click', () => onReveal(b.dataset.id, b)));
  $('vaultLockBtn').addEventListener('click', onLock);
  $('vaultChange').addEventListener('click', renderChange);
  $('vaultActivity').addEventListener('click', renderActivity);
  startTtl(ttl);
}

async function renderActivity() {
  let events = [], ttlLeft = 0;
  try {
    const data = await api(`/api/vault/activity?token=${encodeURIComponent(token)}`);
    events = data.events || [];
    ttlLeft = data.ttl || 0;
  } catch (e) {
    if (String(e.message).includes('locked')) { token = null; refresh(); return; }
    $('vaultErr').textContent = e.message;
    return;
  }
  const rows = events.length ? events.map((e) => `
    <div class="vault-row vault-log-row">
      <span class="vault-log-kind vault-log-${e.kind}">${e.kind.replace('_', ' ')}</span>
      <span class="vault-log-detail">${e.detail || ''}</span>
      <span class="vault-log-time">${e.t}</span>
    </div>`).join('')
    : '<p class="vault-note">No activity recorded yet.</p>';
  el.body.innerHTML = `
    <p class="vault-note vault-open-note">Vault activity
      <span id="vaultTtl" class="vault-ttl"></span></p>
    ${rows}
    <div class="vault-actions">
      <button id="vaultBack" class="vault-btn vault-btn-ghost">Back to keys</button>
    </div>`;
  $('vaultBack').addEventListener('click', refresh);
  startTtl(ttlLeft);
}

function renderChange() {
  el.body.innerHTML = `
    <p class="vault-note">Change the access code. The current code is required.</p>
    <form id="vaultForm" class="vault-form">
      <input type="password" id="vaultCurrent" class="vault-input"
             placeholder="current code" autocomplete="off" aria-label="Current code">
      <input type="password" id="vaultCode" class="vault-input"
             placeholder="new code (4+ chars)" autocomplete="new-password"
             aria-label="New code">
      <button type="submit" class="vault-btn">Save</button>
    </form>
    <p class="vault-err" id="vaultErr" role="alert"></p>`;
  $('vaultForm').addEventListener('submit', onChangeCode);
  $('vaultCurrent').focus();
}

function startTtl(seconds) {
  stopTtl();
  const node = $('vaultTtl');
  let left = seconds;
  const tick = () => {
    if (left <= 0 || !token) { refresh(); return; }
    if (node) node.textContent = `— auto-locks in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
    left -= 1;
  };
  tick();
  ttlTimer = setInterval(tick, 1000);
}

async function refresh() {
  try {
    const st = await api('/api/vault/status');
    if (!st.has_code) { renderSetup(); return; }
    if (st.locked) { renderLocked(`Vault locked — try again in ${st.seconds_left}s.`); return; }
    if (token) {
      const data = await api(`/api/vault/keys?token=${encodeURIComponent(token)}`);
      renderUnlocked(data.entries, data.ttl);
    } else {
      renderLocked(st.fails_left < 5 ? `${st.fails_left} attempts left before lockout.` : '');
    }
  } catch (e) {
    renderLocked(`Vault unavailable: ${e.message}`);
  }
}

async function onUnlock(ev) {
  ev.preventDefault();
  const code = $('vaultCode').value;
  $('vaultErr').textContent = '';
  try {
    const data = await api('/api/vault/unlock', {
      method: 'POST', body: JSON.stringify({ code }),
    });
    token = data.token;
    refresh();
  } catch (e) {
    const d = e.detail || {};
    const extra = d.locked ? ` — locked ${d.seconds_left}s` :
      (d.fails_left != null ? ` — ${d.fails_left} attempts left` : '');
    $('vaultErr').textContent = e.message + extra;
    if (d.locked) { token = null; setTimeout(refresh, 1500); }
  }
}

async function onSetCode(ev) {
  ev.preventDefault();
  const code = $('vaultCode').value;
  $('vaultErr').textContent = '';
  try {
    await api('/api/vault/set-code', {
      method: 'POST', body: JSON.stringify({ code }),
    });
    renderLocked('Code saved. Unlock to continue.');
  } catch (e) {
    $('vaultErr').textContent = e.message;
  }
}

async function onChangeCode(ev) {
  ev.preventDefault();
  const current = $('vaultCurrent').value;
  const code = $('vaultCode').value;
  $('vaultErr').textContent = '';
  try {
    await api('/api/vault/set-code', {
      method: 'POST', body: JSON.stringify({ code, current }),
    });
    token = null;
    renderLocked('Code changed. Unlock with the new code.');
  } catch (e) {
    $('vaultErr').textContent = e.message;
  }
}

async function onLock() {
  if (token) {
    try { await api('/api/vault/lock', { method: 'POST', body: JSON.stringify({ token }) }); }
    catch { /* the local token drop below is enough */ }
  }
  renderLocked('');
}

// Reveal copies to the clipboard and shows the value ONLY inside the
// button that was clicked, then wipes it from the DOM after 15s.
async function onReveal(id, btn) {
  try {
    const data = await api(`/api/vault/reveal/${encodeURIComponent(id)}?token=${encodeURIComponent(token)}`);
    let copied = false;
    try { await navigator.clipboard.writeText(data.secret); copied = true; } catch { /* http or denial */ }
    btn.textContent = data.secret;
    btn.classList.add('vault-eye-open');
    setTimeout(() => {
      btn.textContent = '👁';
      btn.classList.remove('vault-eye-open');
    }, 15000);
    $('vaultErr').textContent = copied ? 'Copied to clipboard.' : 'Clipboard blocked — copied from the button instead.';
  } catch (e) {
    if (String(e.message).includes('locked')) { token = null; refresh(); return; }
    $('vaultErr').textContent = e.message;
  }
}

export function initVault() {
  el.btn = $('vaultBtn');
  el.panel = $('vaultPanel');
  el.close = $('closeVault');
  el.body = $('vaultBody');
  if (!el.btn || !el.panel) return;
  el.btn.addEventListener('click', () =>
    el.panel.classList.contains('open') ? closePanel() : openPanel());
  el.close.addEventListener('click', closePanel);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && el.panel.classList.contains('open')) closePanel();
  });
}
