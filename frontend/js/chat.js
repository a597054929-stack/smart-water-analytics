// === AI Assistant Chat Module ===
// Supports SSE streaming, tool call visualization, and chart rendering
const AI_API_URL = "http://localhost:8000/api/chat";
let _chatInited = false;
let _chatStreaming = false;
let _chatMode = 'agent'; // 'agent' or 'multi'

const TOOL_NAMES = {
  'query_anomalies': 'Querying anomalies',
  'query_meters': 'Looking up meters',
  'get_anomaly_stats': 'Computing anomaly stats',
  'get_predictions': 'Fetching predictions',
  'get_building_predictions': 'Fetching building predictions',
  'get_data_overview': 'Getting data overview',
  'query_daily_dma': 'Querying daily DMA data',
  'query_weekly': 'Querying weekly data',
  'query_rank_changes': 'Checking rankings',
  'query_monthly_diff': 'Analyzing NRW data',
  'generate_chart': 'Generating chart',
};

function toggleChat() {
  const popup = document.getElementById('chatPopup');
  const fab = document.getElementById('chatFab');
  if (!popup) return;
  const open = popup.classList.toggle('open');
  fab.classList.toggle('active', open);
  if (!_chatInited) {
    _chatInited = true;
    chatAppend('ai', 'Hello! I am the Smart Water AI Assistant.\n\nYou can ask me:\n- Anomaly statistics for Zone-3\n- Which meters are long-term Top20?\n- Draw an anomaly type distribution chart\n- Main/sub meter diff and NRW rate\n- Predict next week consumption\n\nTip: Toggle between Agent and Multi-Agent mode below.');
  }
  if (open) {
    setTimeout(function() { document.getElementById('chatInput').focus(); }, 200);
  }
}

function toggleChatMode() {
  _chatMode = _chatMode === 'agent' ? 'multi' : 'agent';
  var btn = document.getElementById('chatModeBtn');
  if (btn) {
    btn.textContent = _chatMode === 'agent' ? 'Agent' : 'Multi-Agent';
    btn.title = _chatMode === 'agent' ? 'Single agent mode' : 'Planner + Executor + Synthesizer';
  }
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const q = input.value.trim();
  if (!q || _chatStreaming) return;
  input.value = '';

  chatAppend('user', q);

  if (!AI_API_URL) {
    chatAppend('ai', 'AI backend not connected. To enable:\n1. Start your LangChain server\n2. Set AI_API_URL in chat.js');
    input.focus();
    return;
  }

  _chatStreaming = true;
  var loadId = chatAppend('ai', '<span class="chat-thinking">Thinking...</span>');
  var fullAnswer = '';

  try {
    var resp = await fetch(AI_API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, mode: _chatMode }),
    });

    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';

    while (true) {
      var { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      var lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line

      for (var line of lines) {
        if (!line.startsWith('data: ')) continue;
        var jsonStr = line.slice(6);
        try {
          var evt = JSON.parse(jsonStr);

          if (evt.type === 'tool') {
            // Show tool call status
            var toolLabel = TOOL_NAMES[evt.name] || evt.name;
            chatToolStatus(loadId, toolLabel);
          }

          if (evt.type === 'answer') {
            fullAnswer = evt.content;
            chatUpdate(loadId, fullAnswer);
            if (evt.chart) {
              setTimeout(function() { chatRenderChart(evt.chart); }, 200);
            }
          }

          if (evt.type === 'error') {
            chatUpdate(loadId, 'Error: ' + evt.content);
          }
        } catch (e) { /* skip invalid JSON */ }
      }
    }
  } catch (e) {
    chatUpdate(loadId, 'Failed to connect to AI service.\nPlease ensure the agent server is running (start_agent_*.bat).');
  }

  _chatStreaming = false;
  input.focus();
}

function chatAppend(role, html) {
  var c = document.getElementById('chatMsgs');
  var id = 'cm-' + Date.now() + Math.random();
  var d = document.createElement('div');
  d.className = 'chat-msg ' + role;
  d.id = id;
  d.innerHTML = '<div class="chat-bubble">' + html + '</div>';
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

function chatToolStatus(id, toolName) {
  var d = document.getElementById(id);
  if (!d) return;
  d.innerHTML = '<div class="chat-bubble"><span class="chat-thinking">' + chatEsc(toolName) + '...</span></div>';
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
