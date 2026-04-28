const API_BASE = "http://localhost:5000/api";

// ── DOM refs ──────────────────────────────────────────────────────────────────
const messagesEl = document.getElementById("chat-messages");
const inputEl    = document.getElementById("chat-input");
const sendBtn    = document.getElementById("chat-send-btn");
const inputError = document.getElementById("chat-input-error");

let isSending = false;

// ── Helpers ───────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Bubble rendering ──────────────────────────────────────────────────────────

function addUserBubble(text) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble chat-bubble--user";
  bubble.textContent = text;
  messagesEl.appendChild(bubble);
  scrollToBottom();
}

function addAssistantBubble(answer, sql) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble chat-bubble--assistant";

  let html = escapeHtml(answer);

  if (sql) {
    const toggleId = "sql-toggle-" + Date.now();
    const blockId  = "sql-block-" + Date.now();
    html += `
      <span class="sql-toggle" id="${toggleId}" data-block="${blockId}">▸ Show SQL</span>
      <div class="sql-block" id="${blockId}">${escapeHtml(sql)}</div>
    `;
  }

  bubble.innerHTML = html;
  messagesEl.appendChild(bubble);

  // Wire SQL toggle
  if (sql) {
    const toggle = bubble.querySelector(".sql-toggle");
    const block  = bubble.querySelector(".sql-block");
    toggle.addEventListener("click", () => {
      const isOpen = block.classList.toggle("open");
      toggle.textContent = isOpen ? "▾ Hide SQL" : "▸ Show SQL";
    });
  }

  scrollToBottom();
}

function addErrorBubble(text) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble chat-bubble--error";
  bubble.textContent = text;
  messagesEl.appendChild(bubble);
  scrollToBottom();
}

function addLoadingBubble() {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble chat-bubble--loading";
  bubble.id = "loading-bubble";
  bubble.innerHTML = 'Thinking<span class="typing-dots"></span>';
  messagesEl.appendChild(bubble);
  scrollToBottom();
  return bubble;
}

function removeLoadingBubble() {
  const el = document.getElementById("loading-bubble");
  if (el) el.remove();
}

// ── Send message ──────────────────────────────────────────────────────────────

async function sendMessage() {
  const text = inputEl.value.trim();
  inputError.textContent = "";

  if (!text) return;
  if (text.length > 1000) {
    inputError.textContent = "Message must be 1000 characters or fewer";
    return;
  }

  isSending = true;
  inputEl.value = "";
  sendBtn.disabled = true;
  inputEl.disabled = true;

  addUserBubble(text);
  const loadingBubble = addLoadingBubble();

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();

    removeLoadingBubble();

    if (!res.ok) {
      addErrorBubble(data.error || "Something went wrong");
    } else {
      addAssistantBubble(data.answer, data.sql);
    }
  } catch (err) {
    removeLoadingBubble();
    addErrorBubble("Could not reach the server. Is the backend running?");
  } finally {
    isSending = false;
    inputEl.disabled = false;
    inputEl.focus();
    updateSendButton();
  }
}

// ── Input handling ────────────────────────────────────────────────────────────

function updateSendButton() {
  sendBtn.disabled = isSending || inputEl.value.trim().length === 0;
}

inputEl.addEventListener("input", updateSendButton);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !isSending) {
    e.preventDefault();
    sendMessage();
  }
});

sendBtn.addEventListener("click", () => {
  if (!isSending) sendMessage();
});

// ── Welcome message + config indicator ─────────────────────────────────────────

async function loadChatConfig() {
  try {
    const res = await fetch(`${API_BASE}/chat/config`);
    const config = await res.json();
    const badge = document.getElementById("chat-mode-badge");
    if (badge) {
      if (config.use_bedrock_flow) {
        badge.textContent = "Bedrock Flow";
        badge.classList.add("badge--flow");
      } else {
        badge.textContent = "Direct Model";
        badge.classList.add("badge--model");
      }
      badge.classList.remove("hidden");
    }
  } catch { /* non-critical */ }
}

addAssistantBubble(
  "Ask me anything about your expenses — for example:\n" +
  "• \"What's my total spending?\"\n" +
  "• \"Show all airline costs\"\n" +
  "• \"How much did I spend in April 2026?\"",
  null
);

loadChatConfig();
inputEl.focus();
