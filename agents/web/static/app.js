/* ═══════════════════════════════════════════════════════════════════
   J.A.R.V.I.S Web Client
   WebSocket chat + Matrix rain + Terminal interactions
   ═══════════════════════════════════════════════════════════════════ */

// ── Matrix Rain ──────────────────────────────────────────────────

(function initMatrix() {
  const canvas = document.getElementById('matrix');
  const ctx = canvas.getContext('2d');
  let w, h, columns, drops;

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
    columns = Math.floor(w / 16);
    drops = Array(columns).fill(1);
  }

  const chars = 'JARVIS01アイウエオカキクケコサシスセソタチツテト';

  function draw() {
    ctx.fillStyle = 'rgba(10, 10, 10, 0.05)';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#e63946';
    ctx.font = '14px monospace';

    for (let i = 0; i < drops.length; i++) {
      const ch = chars[Math.floor(Math.random() * chars.length)];
      ctx.fillText(ch, i * 16, drops[i] * 16);
      if (drops[i] * 16 > h && Math.random() > 0.975) {
        drops[i] = 0;
      }
      drops[i]++;
    }
    requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener('resize', resize);
  draw();
})();

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
    statusText.textContent = 'Online';
    userInput.focus();
  };

  ws.onclose = () => {
    connected = false;
    statusDot.classList.remove('connected');
    statusText.textContent = 'Reconnecting...';
    setTimeout(connect, 2000);
  };

  ws.onerror = () => {
    statusText.textContent = 'Connection error';
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleMessage(data);
  };
}

function handleMessage(data) {
  removeTypingIndicator();

  switch (data.type) {
    case 'jarvis':
      addMessage('jarvis', data.content, data);
      if (data.session_id) {
        sessionInfo.textContent = data.session_id;
      }
      break;

    case 'thinking':
      showTypingIndicator();
      break;

    case 'progress':
      addProgressMessage(data.message, data.step);
      break;

    case 'search_result':
      renderSearchResults(data.data);
      break;

    case 'draft_result':
      renderDraftResults(data.data);
      break;

    case 'send_result':
      renderSendResults(data.data);
      break;

    case 'research_result':
      renderResearchResults(data.data);
      break;

    case 'review_show':
      renderReviewShow(data);
      break;

    case 'review_result':
      renderReviewResult(data.data);
      break;

    case 'error':
      addMessage('jarvis', data.content, { error: true });
      break;

    default:
      if (data.content) {
        addMessage('jarvis', data.content);
      }
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

  if (meta.error) {
    body.style.borderColor = '#e63946';
    body.style.borderLeft = '3px solid #e63946';
  }

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

function scrollToBottom() {
  messagesEl.parentElement.scrollTop = messagesEl.parentElement.scrollHeight;
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
    const webTag = b.has_website
      ? '<span class="tag tag-green">YES</span>'
      : '<span class="tag tag-red">NO</span>';
    html += `<tr><td>${i + 1}</td><td>${esc(b.name)}</td><td>${esc(b.category)}</td><td>${webTag}</td></tr>`;
  });

  html += `</table>`;
  html += `<div style="margin-top:8px;font-size:12px;color:#a8a8a8;">`;
  html += `Found ${data.total} total: <span class="tag tag-red">${data.no_site_count} without site</span> `;
  html += `<span class="tag tag-green">${data.with_site_count} with site</span></div>`;
  html += `</div>`;

  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.innerHTML = `<div class="msg-label">JARVIS</div>${html}`;
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function renderDraftResults(data) {
  let html = `<div class="data-card"><div class="data-card-title">DRAFTED ${data.count} EMAILS</div>`;
  html += `<table class="data-table"><tr><th>Business</th><th>Subject</th><th>Email</th></tr>`;

  data.drafts.forEach(d => {
    const emailTag = d.to
      ? `<span class="tag tag-green">${esc(d.to)}</span>`
      : '<span class="tag tag-yellow">No email</span>';
    html += `<tr><td>${esc(d.business)}</td><td>${esc(d.subject)}</td><td>${emailTag}</td></tr>`;
  });

  html += `</table>`;
  if (data.ai_used > 0) {
    html += `<div style="margin-top:8px;font-size:12px;color:#06d6a0;">AI personalized: ${data.ai_used}/${data.count}</div>`;
  }
  html += `</div>`;

  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.innerHTML = `<div class="msg-label">JARVIS</div>${html}`;
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function renderSendResults(data) {
  let html = `<div class="data-card"><div class="data-card-title">EMAILS SENT</div>`;
  html += `<div style="display:flex;gap:16px;margin-top:4px;">`;
  html += `<div><span style="color:#06d6a0;font-size:24px;font-weight:700;">${data.sent}</span><div style="font-size:11px;color:#a8a8a8;">Sent</div></div>`;
  html += `<div><span style="color:#ffd166;font-size:24px;font-weight:700;">${data.skipped}</span><div style="font-size:11px;color:#a8a8a8;">Skipped</div></div>`;
  html += `<div><span style="color:#e63946;font-size:24px;font-weight:700;">${data.errors}</span><div style="font-size:11px;color:#a8a8a8;">Errors</div></div>`;
  html += `</div></div>`;

  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.innerHTML = `<div class="msg-label">JARVIS</div>${html}`;
  messagesEl.appendChild(msg);
  scrollToBottom();
}

function renderResearchResults(data) {
  let html = `<div class="data-card"><div class="data-card-title">RESEARCH: ${data.count} BUSINESSES</div>`;
  html += `<table class="data-table"><tr><th>Business</th><th>Rating</th><th>Reviews</th><th>Gaps</th></tr>`;

  data.results.forEach(r => {
    const gaps = (r.gaps || []).slice(0, 2).join(', ') || 'None found';
    html += `<tr><td>${esc(r.name)}</td><td><span class="tag tag-yellow">${r.rating || 'N/A'}</span></td><td>${r.review_count || 0}</td><td style="font-size:12px;">${esc(gaps)}</td></tr>`;
  });

  html += `</table></div>`;

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

  // Attachment (uploaded once, applied on approve)
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

  // Actions
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
  btnRow.appendChild(makeBtn('Skip', 'review-btn review-btn-skip', () => {
    sendReview('skip', {});
  }));
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
  html += `<div style="display:flex;gap:16px;margin-top:4px;">`;
  html += `<div><span style="color:#06d6a0;font-size:24px;font-weight:700;">${data.approved || 0}</span><div style="font-size:11px;color:#a8a8a8;">Approved</div></div>`;
  html += `<div><span style="color:#ffd166;font-size:24px;font-weight:700;">${data.skipped || 0}</span><div style="font-size:11px;color:#a8a8a8;">Skipped</div></div>`;
  html += `<div><span style="color:#e63946;font-size:24px;font-weight:700;">${data.total || 0}</span><div style="font-size:11px;color:#a8a8a8;">Total</div></div>`;
  html += `</div></div>`;

  const msg = document.createElement('div');
  msg.className = 'message message-jarvis';
  msg.innerHTML = `<div class="msg-label">JARVIS</div>${html}`;
  messagesEl.appendChild(msg);
  scrollToBottom();
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
}

userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
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

document.querySelectorAll('.quick-btn').forEach(btn => {
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

closeSidebar.addEventListener('click', () => {
  sidebar.classList.remove('open');
});

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
    (data.messages || []).forEach(m => {
      addMessage(m.role, m.content);
    });
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
      statusContent.innerHTML = '<div style="color:#e63946;">Failed to load status</div>';
    }
  }
});

closeStatus.addEventListener('click', () => {
  statusPanel.classList.remove('open');
});

// ── Init ─────────────────────────────────────────────────────────

connect();
addSystemMessage('J.A.R.V.I.S initialized. Type a command or use the buttons below.');
