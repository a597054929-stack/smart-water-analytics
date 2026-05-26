// === AI Assistant Chat Module ===
// Optional: connect to a LangChain / AI backend for natural language queries
// Set AI_API_URL to your backend endpoint, or leave empty to disable
const AI_API_URL = "";  // e.g. "http://localhost:8000/api/chat"
let _chatInited = false;

function toggleChat() {
  const popup = document.getElementById('chatPopup');
  const fab = document.getElementById('chatFab');
  if (!popup) return;
  const open = popup.classList.toggle('open');
  fab.classList.toggle('active', open);
  if (!_chatInited) {
    _chatInited = true;
    chatAppend('ai', 'Hello! I am the Smart Water AI Assistant. You can ask me:\n- Anomaly statistics for Zone-3\n- Which meters are long-term Top20?\n- Draw an anomaly type distribution chart\n- Main/sub meter diff and NRW rate\n- Predict next week consumption');
  }
  if (open) {
    setTimeout(function() { document.getElementById('chatInput').focus(); }, 200);
  }
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';

  chatAppend('user', q);

  if (!AI_API_URL) {
    chatAppend('ai', 'AI backend not connected. To enable:\n1. Start your LangChain server\n2. Set AI_API_URL in chat.js\n\nThis is a demo dashboard showing the UI integration point.');
    input.focus();
    return;
  }

  var loadId = chatAppend('ai', 'Thinking...');

  try {
    var resp = await fetch(AI_API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q }),
    });
    var data = await resp.json();
    chatUpdate(loadId, data.answer || 'No response');
    if (data.chart) {
      setTimeout(function() { chatRenderChart(data.chart); }, 200);
    }
  } catch (e) {
    chatUpdate(loadId, 'Failed to connect to AI service.\nPlease ensure the backend server is running.');
  }
  input.focus();
}

function chatAppend(role, text) {
  var c = document.getElementById('chatMsgs');
  var id = 'cm-' + Date.now() + Math.random();
  var d = document.createElement('div');
  d.className = 'chat-msg ' + role;
  d.id = id;
  d.innerHTML = '<div class="chat-bubble">' + chatEsc(text) + '</div>';
  c.appendChild(d);
  c.scrollTop = c.scrollHeight;
  return id;
}

function chatUpdate(id, text) {
  var d = document.getElementById(id);
  if (!d) return;
  d.innerHTML = '<div class="chat-bubble">' + chatFmt(text) + '</div>';
  var c = document.getElementById('chatMsgs');
  c.scrollTop = c.scrollHeight;
}

function chatEsc(t) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

function chatFmt(t) {
  return t
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

function chatRenderChart(option) {
  var c = document.getElementById('chatMsgs');
  var id = 'cc-' + Date.now();
  var d = document.createElement('div');
  d.className = 'chat-msg ai';
  d.innerHTML = '<div class="chat-bubble"><div id="' + id + '" class="chat-chart"></div></div>';
  c.appendChild(d);
  c.scrollTop = c.scrollHeight;
  setTimeout(function() {
    var el = document.getElementById(id);
    if (el && typeof echarts !== 'undefined') {
      var ch = echarts.init(el);
      ch.setOption(option);
      window.addEventListener('resize', function() { ch.resize(); });
    }
  }, 100);
}
