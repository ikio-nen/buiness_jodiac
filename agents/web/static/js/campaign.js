/* ═══════════════════════════════════════════════════════════════
   campaign.js — the guided campaign UI (stages 2 & 4).

   The interactive checklist card (curated businesses, tick to select,
   approve/cancel) and the interview question banner (one targeted
   question per approved business). Both are blocking gates: nothing
   downstream runs until the user acts.
   ═══════════════════════════════════════════════════════════════ */

import { esc } from './util.js?v=28';

const messagesEl = document.getElementById('messages');

export function removeChecklistCard() {
  const el = document.getElementById('campaignCard');
  if (el) el.remove();
}

export function renderChecklist(data) {
  removeChecklistCard();
  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.id = 'campaignCard';

  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'JARVIS';
  msg.appendChild(label);

  const card = document.createElement('div');
  card.className = 'data-card campaign-card';
  const title = document.createElement('div');
  title.className = 'data-card-title';
  title.textContent = `CAMPAIGN CHECKLIST — ${data.location || 'YOUR AREA'}`;
  card.appendChild(title);
  if (data.goal) {
    const goal = document.createElement('div');
    goal.className = 'campaign-goal';
    goal.textContent = `Selling: ${data.goal}`;
    card.appendChild(goal);
  }

  const list = document.createElement('div');
  list.className = 'campaign-list';
  (data.businesses || []).forEach((b, i) => {
    const row = document.createElement('label');
    row.className = 'campaign-row';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'campaign-check';
    cb.value = b.name || '';
    cb.setAttribute('aria-label', `Select ${b.name || 'business'}`);
    if ((data.selected || []).includes(b.name)) cb.checked = true;

    const main = document.createElement('span');
    main.className = 'campaign-main';
    main.innerHTML =
      `<span class="campaign-num">${i + 1}.</span> ` +
      `<b>${esc(b.name || '?')}</b>` +
      (b.category ? ` <span class="campaign-cat">${esc(b.category)}</span>` : '');
    const sub = document.createElement('span');
    sub.className = 'campaign-sub';
    const bits = [];
    if (b.email) bits.push(`✉ ${esc(b.email)}`);
    if (b.phone) bits.push(`☎ ${esc(b.phone)}`);
    if (!bits.length) bits.push('<span class="campaign-nocontact">no contact on file</span>');
    if (b.fit_score) bits.push(`fit ${esc(String(b.fit_score))}`);
    sub.innerHTML = bits.join(' · ');
    main.appendChild(sub);

    row.appendChild(cb);
    row.appendChild(main);
    list.appendChild(row);
  });
  card.appendChild(list);

  const count = document.createElement('div');
  count.className = 'campaign-count';
  const sync = () => {
    const n = card.querySelectorAll('.campaign-check:checked').length;
    count.textContent = n ? `${n} selected` : 'Select the businesses you want to target';
  };
  list.addEventListener('change', sync);
  sync();

  const acts = document.createElement('div');
  acts.className = 'review-actions';
  const mkBtn = (text, cls, fn) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = text;
    b.addEventListener('click', fn);
    return b;
  };
  acts.appendChild(mkBtn('Approve & Continue', 'review-btn review-btn-approve', () => {
    const selected = [...card.querySelectorAll('.campaign-check:checked')]
      .map(c => c.value).filter(Boolean);
    if (!selected.length) {
      count.textContent = 'Tick at least one business first.';
      return;
    }
    [...acts.querySelectorAll('button')].forEach(b => (b.disabled = true));
    window.wsSend && window.wsSend({ type: 'campaign_checklist_action', action: 'approve', selected });
  }));
  acts.appendChild(mkBtn('Approve All', 'review-btn', () => {
    card.querySelectorAll('.campaign-check').forEach(c => (c.checked = true));
    sync();
  }));
  acts.appendChild(mkBtn('Cancel', 'review-btn review-btn-cancel', () => {
    removeChecklistCard();
    window.wsSend && window.wsSend({ type: 'campaign_checklist_action', action: 'cancel' });
  }));
  acts.appendChild(count);
  card.appendChild(acts);

  msg.appendChild(card);
  messagesEl.appendChild(msg);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

export function renderInterview(text) {
  // Remove any previous interview banner: only the current question stays up.
  document.querySelectorAll('.interview-card').forEach(el => el.remove());
  const msg = document.createElement('div');
  msg.className = 'message message-jarvis interview-card';
  const label = document.createElement('div');
  label.className = 'msg-label';
  label.textContent = 'JARVIS';
  const body = document.createElement('div');
  body.className = 'msg-content';
  const [head, ...rest] = String(text).split('\n');
  const strong = document.createElement('b');
  strong.textContent = head;
  body.appendChild(strong);
  if (rest.length) {
    body.appendChild(document.createElement('br'));
    body.appendChild(document.createTextNode(rest.join('\n')));
  }
  msg.appendChild(label);
  msg.appendChild(body);
  messagesEl.appendChild(msg);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
