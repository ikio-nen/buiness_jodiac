/* Composer attachments.

   Owns the one piece of state it needs: the file waiting to ride the next
   message. The upload endpoint already existed; what was missing was any way
   to reach it. An attached file is stored on the session, so the draft leg can
   put it on the emails it writes — which is why the pending file is *taken*
   by the sender (takeAttachment) rather than read and left set, so one file
   never silently rides two messages. */

import { esc } from './util.js?v=43';   // same version as app.js's imports

let pending = null;   // {path, name}

let attachChips = null;
let activity = null;

export function initAttachments({ setActivity }) {
  activity = setActivity;
  const filesBtn = document.getElementById('filesBtn');
  const filePicker = document.getElementById('filePicker');
  attachChips = document.getElementById('attachChips');
  if (!filesBtn || !filePicker) return;

  filesBtn.addEventListener('click', () => filePicker.click());
  filePicker.addEventListener('change', async () => {
    const file = filePicker.files && filePicker.files[0];
    if (!file) return;
    filesBtn.disabled = true;
    activity(`Uploading ${file.name}…`, 'busy');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch('/api/upload', { method: 'POST', body: fd });
      const j = await res.json();
      if (j.path) {
        pending = { path: j.path, name: j.name || file.name };
        renderAttachChips();
        activity(`Ready to attach ${pending.name}`, '');
      } else {
        activity(`Upload failed: ${j.error || 'unknown error'}`, '');
      }
    } catch (e) {
      activity('Upload failed — is the office server running?', '');
    } finally {
      filesBtn.disabled = false;
      filePicker.value = '';   // let the same file be picked again
    }
  });
}

/* Hand the pending attachment to the sender and clear it. */
export function takeAttachment() {
  const a = pending;
  pending = null;
  renderAttachChips();
  return a;
}

function renderAttachChips() {
  if (!attachChips) return;
  if (!pending) { attachChips.hidden = true; attachChips.innerHTML = ''; return; }
  attachChips.hidden = false;
  attachChips.innerHTML =
    `<span class="attach-chip"><b>📎 ${esc(pending.name)}</b>` +
    `<button type="button" id="clearAttach" aria-label="Remove attachment">&times;</button></span>`;
  document.getElementById('clearAttach').addEventListener('click', () => {
    pending = null;
    renderAttachChips();
  });
}
