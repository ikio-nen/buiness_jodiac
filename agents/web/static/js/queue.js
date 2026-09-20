/* QUEUE panel: renders the server's real per-socket queue.

   The panel is a pure projection of the `queue_state` frames the server
   sends — there is no client-side notion of what is running, because a
   second opinion about queue state is a second truth that can be wrong.
   Cancel is the one action here, and it goes straight back over the socket
   for the server to honour (or refuse, out loud). */

import { esc } from './util.js?v=28';   // same version as app.js's imports

let sendFrame = null;
let onWork = null;

/* `onWork(running, label)` lets the panel report whether real work is in
   flight to whoever owns the "is the office idle?" question. This module
   knows the answer because it renders the server's queue; it does not decide
   what idle looks like. */
export function initQueue({ send, onWork: workReporter }) {
  sendFrame = send;
  onWork = workReporter || null;
}

export function renderQueue(items) {
  const queuePanel = document.getElementById('queuePanel');
  const queueList = document.getElementById('queueList');
  const queueCount = document.getElementById('queueCount');
  if (!queuePanel || !queueList) return;
  items = items || [];
  if (queueCount) queueCount.textContent = items.length;
  if (!items.length) { queuePanel.hidden = true; queueList.innerHTML = ''; reportWork(items); return; }
  queuePanel.hidden = false;
  reportWork(items);
  queueList.innerHTML = items.map(it =>
    `<div class="queue-item" data-status="${esc(it.status)}">` +
    `<span class="q-state">${it.status === 'running' ? 'running' : 'waiting'}</span>` +
    `<span class="q-label">${esc(it.label)}</span>` +
    (it.status === 'queued'
      ? `<button class="q-cancel" type="button" data-cancel="${it.id}" ` +
        `aria-label="Cancel waiting job: ${esc(it.label)}">&times;</button>`
      : '') +
    `</div>`).join('');
  queueList.querySelectorAll('.q-cancel').forEach(btn => {
    btn.addEventListener('click', () => {
      if (sendFrame) sendFrame({ type: 'cancel_queued', id: Number(btn.dataset.cancel) });
    });
  });
}

function reportWork(items) {
  if (!onWork) return;
  const running = items.find(it => it.status === 'running');
  onWork(!!running, running ? running.label : '');
}
