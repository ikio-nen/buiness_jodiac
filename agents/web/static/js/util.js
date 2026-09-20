/* Shared vocabulary for the office client: text escaping and the live
   activity strip.

   These two are used by nearly every panel, so they live in one place rather
   than being re-declared per module. The activity strip owns its own feeding
   policy (what counts as busy, and when the office is idle again) and exposes
   `wrapAgentEvent` so the floor can hand it the event handler to decorate
   instead of the strip reaching into the floor. */

export function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

/* ── Live activity strip ──────────────────────────────────────────
   A single line under the composer that mirrors what the office is
   doing RIGHT NOW — agent events, pipeline steps, queued jobs — so
   the user never wonders whether anything is happening. */

export function activityStrip() { return document.getElementById('activityStrip'); }

export function setActivity(text, cls = '') {
  const el = activityStrip();
  if (!el) return;
  el.textContent = text;
  el.className = 'activity-strip ' + cls;
  el.classList.toggle('busy', cls === 'busy');
}

export function clearActivityIfIdle() {
  setActivity('office idle — run a search or “team act”');
}

export function showQueuedChip(text) {
  setActivity('⏳ ' + (text || 'queued — will run after the current job'), 'busy');
}

/* Keep the strip fed from every event source the app already has. */
let _idleTimer = null;

/* Is real work still in flight? The QUEUE panel owns that answer (it renders
   the server's queue), so it tells us — this module just refuses to call the
   office idle while work is running. Without this, a long job that goes quiet
   for 7 s (scraping 20 sites emits nothing for minutes) decayed to "office
   idle" while the queue said running: the strip and the panel disagreed. */
let _workActive = false;
export function setWorkActive(active, label = '') {
  _workActive = !!active;
  if (!_workActive) { _armIdleDecay(); return; }
  clearTimeout(_idleTimer);
  // If the strip already decayed to "idle" while this job was quiet, take it
  // back: a specific line is never overwritten, only the idle claim is.
  const el = activityStrip();
  if (el && !el.classList.contains('busy')) setActivity(`⏳ ${label || 'working…'}`, 'busy');
}

function _armIdleDecay() {
  // After a finished job and 7 quiet seconds, the office is idle again.
  if (_workActive) return;
  clearTimeout(_idleTimer);
  _idleTimer = setTimeout(() => {
    const el = activityStrip();
    if (_workActive) return;
    if (el && el.classList.contains('busy')) clearActivityIfIdle();
  }, 7000);
}

/* Decorate the floor's event handler so every bus event also updates the
   strip. The floor keeps owning the handler; this returns the wrapped one. */
export function wrapAgentEvent(orig, statusText) {
  return function (ev, silent = false) {
    orig(ev, silent);
    if (!ev || !ev.kind) return;
    if (ev.kind === 'bot') {
      const who = (ev.bot || 'agent').toUpperCase();
      const what = ev.task ? ` — ${String(ev.task).slice(0, 60)}` : '';
      setActivity(`${who} ${statusText[ev.status] || ev.status || 'working'}${what}`, 'busy');
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
}
