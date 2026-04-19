const INTRO_STORAGE_KEY = "fundclear_intro_dismissed";

const state = {
  messages: [],
  loading: false,
  config: window.__FUNDCLEAR_CONFIG__ || window.FUNDCLEAR_CONFIG || { examples: [] },
};

const intro = document.getElementById("intro");
const introStart = document.getElementById("intro-start");
const introAgain = document.getElementById("intro-again");
const chatScroll = document.getElementById("chat-scroll");
const input = document.getElementById("q");
const sendBtn = document.getElementById("send");
const chipsWrap = document.getElementById("chips");
const statusCluster = document.getElementById("status-cluster");
const activityGraph = document.getElementById("activity-graph");
const statusTextEl = document.getElementById("status-text");
const toolbarHint = document.getElementById("toolbar-hint");
const typingRow = document.getElementById("typing-row");
const statusCard = document.getElementById("status-card");
const statusPdfs = document.getElementById("status-pdfs");
const statusEligible = document.getElementById("status-eligible");
const statusIndex = document.getElementById("status-index");
const statusChunks = document.getElementById("status-chunks");
const rebuildBtn = document.getElementById("btn-rebuild-index");
const aboutModal = document.getElementById("modal-about");
const aboutButton = document.getElementById("btn-about");
const aboutClose = document.getElementById("modal-close");
const resetButton = document.getElementById("btn-new");
const statusButton = document.getElementById("btn-status");
const introButton = document.getElementById("btn-intro");
const docsLink = document.getElementById("docs-link");
const toastRoot = document.getElementById("toast-root");

function setNodeText(node, value) {
  if (!node) return;
  node.textContent = value;
}

function focusComposer() {
  if (!input) return;
  input.focus({ preventScroll: true });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const LEAF_ICON_SRC =
  (state.config && state.config.leafIcon) || "/assets/icons/leaf-mark.svg";
const LEAF_ICON = `<img class="leaf-icon" src="${escapeHtml(LEAF_ICON_SRC)}" width="18" height="18" alt="" aria-hidden="true">`;

function autoResizeTextarea() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
}

function scrollToBottom() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function showToast(message, tone = "info") {
  const icon = tone === "success" ? "✓" : tone === "warn" ? "!" : "i";
  const toast = document.createElement("div");
  toast.className = `toast ${tone}`;
  toast.innerHTML = `
    <div class="toast-icon">${icon}</div>
    <div>${escapeHtml(message)}</div>
  `;
  toastRoot.prepend(toast);
  window.setTimeout(() => {
    toast.classList.add("toast-out");
    window.setTimeout(() => toast.remove(), 280);
  }, 2500);
}

function dismissIntro(persist = false) {
  if (persist) {
    localStorage.setItem(INTRO_STORAGE_KEY, "1");
  } else {
    localStorage.removeItem(INTRO_STORAGE_KEY);
  }
  intro.classList.add("leaving");
  window.setTimeout(() => {
    intro.classList.add("hidden");
    intro.classList.remove("leaving");
    focusComposer();
  }, 320);
}

function openAbout() {
  aboutModal.classList.add("open");
}

function closeAbout() {
  aboutModal.classList.remove("open");
}

function buildWelcomeState() {
  return `
    <section class="welcome-card msg">
      <p class="bubble-title">FundClear</p>
      <h3>Ask a factual HDFC mutual fund question</h3>
      <p>
        FundClear answers only from indexed HDFC Mutual Fund documents.
        Try benchmark, exit load, ELSS lock-in, expense ratio, minimum investment, or riskometer queries.
      </p>
      <ul>
        <li>Max 3 sentences per answer, from official documents only</li>
        <li>Source link on each grounded answer</li>
        <li>No investment advice, no fund comparisons</li>
      </ul>
      <div class="disclaimer-strip">
        Facts-only. No investment advice.
      </div>
    </section>
  `;
}

function setStatusCardOpen(open) {
  statusCard.classList.toggle("open", Boolean(open));
}

function fillCorpusStatus(data) {
  statusPdfs.textContent = String(data.pdfs_in_downloaded_sources ?? "—");
  statusEligible.textContent = String(data.eligible_official_pdfs ?? "—");
  statusIndex.textContent = data.vector_index_ready ? "Yes" : "No";
  statusChunks.textContent = String(data.vector_chunks ?? "—");
}

function buildRetrievedEvidence(data) {
  const items = Array.isArray(data.retrieved_excerpts) ? data.retrieved_excerpts : [];
  if (!items.length) return "";

  const cards = items.map((item) => {
    const title = `Excerpt ${escapeHtml(String(item.rank || ""))}${item.scheme_name ? ` · ${escapeHtml(String(item.scheme_name))}` : ""}`;
    const exact = [];
    if (item.source) exact.push(`source=${String(item.source)}`);
    if (item.chunk_index !== null && item.chunk_index !== undefined) exact.push(`chunk=${String(item.chunk_index)}`);
    if (item.distance !== null && item.distance !== undefined) exact.push(`distance=${String(item.distance)}`);
    return `
      <div class="source-item">
        <div class="title">${title}</div>
        ${item.citation_url ? `<div class="line"><strong>Citation:</strong> <a href="${escapeHtml(String(item.citation_url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(String(item.citation_url))}</a></div>` : ""}
        ${exact.length ? `<div class="line"><strong>Exact details:</strong> ${escapeHtml(exact.join(" · "))}</div>` : ""}
        ${item.excerpt ? `<div class="excerpt">${escapeHtml(String(item.excerpt))}</div>` : ""}
      </div>
    `;
  }).join("");

  return `
    <div class="source-details">
      <details>
        <summary>View retrieved excerpts with source details</summary>
        <div class="source-list">${cards}</div>
      </details>
    </div>
  `;
}

/**
 * FIX: Separate render paths for refusal vs grounded responses.
 *
 * Previously both paths were identical — refusal messages got citation URLs
 * (pulled from whatever FAISS ranked first) displayed as valid sources.
 * Now:
 *   - is_refusal=true  → amber-tinted refusal bubble, no source line,
 *                        optional AMFI educational link
 *   - is_refusal=false → standard grounded bubble with citation metadata
 */
function buildAssistantBubble(message) {
  if (message.isRefusal) {
    const eduLink = message.educationalUrl
      ? `<div class="meta-line refusal-edu"><a href="${escapeHtml(message.educationalUrl)}" target="_blank" rel="noopener noreferrer">AMFI Investor Education ↗</a></div>`
      : "";
    return `
      <div class="msg assistant refusal">
        <div class="msg-cloud">
          <div class="msg-avatar" aria-label="FundClear">${LEAF_ICON}</div>
          <div class="bubble-wrap">
            <div class="bubble bubble--refusal">
              <p class="bubble-text">${escapeHtml(message.text)}</p>
              ${eduLink}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  const sourceLine = message.citationUrl
    ? `<a class="source-link" href="${escapeHtml(message.citationUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(message.sourceText || "Official source")} ↗</a>`
    : escapeHtml(message.sourceText || "Official documents");

  const updatedLine = message.lastUpdated && message.lastUpdated !== "N/A" && message.lastUpdated !== ""
    ? `<div class="meta-line"><strong>Updated:</strong> ${escapeHtml(message.lastUpdated)}</div>`
    : "";

  return `
    <div class="msg assistant">
      <div class="msg-cloud">
        <div class="msg-avatar" aria-label="FundClear">${LEAF_ICON}</div>
        <div class="bubble-wrap">
          <div class="bubble">
            <p class="bubble-text">${escapeHtml(message.text)}</p>
            <div class="bubble-meta">
              <div class="meta-line"><strong>Source:</strong> ${sourceLine}</div>
              ${updatedLine}
            </div>
            ${buildRetrievedEvidence(message)}
            <div class="bubble-actions">
              <button type="button" data-copy="${escapeHtml(message.text)}">Copy reply</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderMessages() {
  if (!state.messages.length) {
    chatScroll.innerHTML = buildWelcomeState();
    return;
  }

  const html = state.messages
    .map((message) => {
      if (message.role === "typing") return "";

      if (message.role === "user") {
        return `
          <div class="msg user">
            <div class="msg-cloud">
              <div class="bubble-wrap">
                <div class="bubble">
                  <p class="bubble-text">${escapeHtml(message.text)}</p>
                </div>
              </div>
            </div>
          </div>
        `;
      }

      return buildAssistantBubble(message);
    })
    .join("");

  chatScroll.innerHTML = html;
}

function flashActivityGraph() {
  if (!statusCluster) return;
  statusCluster.classList.remove("graph-flash");
  void statusCluster.offsetWidth;
  statusCluster.classList.add("graph-flash");
  window.setTimeout(() => statusCluster.classList.remove("graph-flash"), 520);
}

function setLoading(isLoading) {
  state.loading = isLoading;
  sendBtn.disabled = isLoading;
  statusCluster?.classList.toggle("thinking", isLoading);
  if (isLoading) {
    setNodeText(statusTextEl, "Thinking");
  }
  typingRow.classList.toggle("visible", isLoading);

  state.messages = state.messages.filter((message) => message.role !== "typing");
  if (isLoading) {
    state.messages.push({ role: "typing" });
  }
  renderMessages();
  scrollToBottom();
}

function pushUserMessage(text) {
  state.messages.push({ role: "user", text });
  renderMessages();
  scrollToBottom();
}

function pushAssistantMessage(payload) {
  // FIX: Pass is_refusal through to render path.
  state.messages.push({
    role: "assistant",
    text: payload.answer,
    sourceText: payload.source_text,
    citationUrl: payload.citation_url,
    lastUpdated: payload.last_updated,
    retrieved_excerpts: payload.retrieved_excerpts || [],
    isRefusal: Boolean(payload.is_refusal),
    educationalUrl: payload.educational_url || "",
  });
  renderMessages();
  scrollToBottom();
}

function showError(message) {
  chatScroll.innerHTML = `<div class="error-banner">${escapeHtml(message)}</div>${chatScroll.innerHTML}`;
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    const data = await response.json();
    state.config = data;

    const nextStatus = data.status.index_ready ? "Online" : "Index missing";
    statusCluster?.classList.remove("thinking");
    statusCluster?.classList.remove("offline");
    statusCluster?.classList.toggle("index-missing", !data.status.index_ready);
    window.requestAnimationFrame(() => {
      setNodeText(statusTextEl, nextStatus);
    });
    if (toolbarHint) {
      toolbarHint.textContent = data.status.index_ready
        ? `Facts-only · ${data.status.indexed_files} official files indexed`
        : "Index missing · add documents";
    }
  } catch (error) {
    statusCluster?.classList.remove("thinking");
    statusCluster?.classList.add("offline");
    statusCluster?.classList.remove("index-missing");
    setNodeText(statusTextEl, "Offline");
    if (toolbarHint) {
      toolbarHint.textContent = "Unable to load status";
    }
    showToast("Unable to load status", "warn");
  }
}

async function refreshCorpusStatus() {
  try {
    const response = await fetch("/api/corpus-status");
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Could not load document status.");
    }
    fillCorpusStatus(data);
  } catch (error) {
    showToast(error.message || "Could not load document status.", "warn");
  }
}

async function rebuildIndex() {
  rebuildBtn.disabled = true;
  showToast("Rebuilding index…", "info");
  try {
    const response = await fetch("/api/rebuild-index", { method: "POST" });
    const data = await response.json();
    if (!response.ok || data.status !== "ok") {
      throw new Error(data.detail || "Could not rebuild index.");
    }
    fillCorpusStatus(data);
    await loadConfig();
    showToast("Index rebuilt successfully.", "success");
  } catch (error) {
    showToast(error.message || "Could not rebuild index.", "warn");
  } finally {
    rebuildBtn.disabled = false;
  }
}

async function askQuestion(text) {
  const question = text.trim();
  if (!question || state.loading) return;

  pushUserMessage(question);
  setLoading(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Unable to fetch an answer right now.");
    }

    setLoading(false);
    await loadConfig();
    pushAssistantMessage(data.response);
  } catch (error) {
    setLoading(false);
    statusCluster?.classList.remove("thinking");
    statusCluster?.classList.remove("offline");
    setNodeText(statusTextEl, "Online");
    showError(error.message || "Something went wrong.");
    showToast(error.message || "Something went wrong.", "warn");
  }
}

async function submitCurrentQuestion() {
  const value = input.value;
  if (!value.trim()) return;
  input.value = "";
  autoResizeTextarea();
  await askQuestion(value);
}

sendBtn.addEventListener("click", submitCurrentQuestion);

input.addEventListener("input", autoResizeTextarea);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitCurrentQuestion();
  }
  if (event.key === "Escape") {
    closeAbout();
    setStatusCardOpen(false);
  }
});

chipsWrap.addEventListener("click", async (event) => {
  const chip = event.target.closest("[data-q]");
  if (!chip) return;
  chip.classList.add("pulse");
  window.setTimeout(() => chip.classList.remove("pulse"), 450);
  await askQuestion(chip.dataset.q || "");
});

aboutButton.addEventListener("click", openAbout);
aboutClose.addEventListener("click", closeAbout);
aboutModal.addEventListener("click", (event) => {
  if (event.target === aboutModal) closeAbout();
});

statusButton.addEventListener("click", async () => {
  const opening = !statusCard.classList.contains("open");
  setStatusCardOpen(opening);
  if (opening) {
    await refreshCorpusStatus();
  }
});

rebuildBtn.addEventListener("click", rebuildIndex);

activityGraph?.addEventListener("click", flashActivityGraph);
activityGraph?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    flashActivityGraph();
  }
});

resetButton.addEventListener("click", () => {
  state.messages = [];
  renderMessages();
  setStatusCardOpen(false);
  showToast("Started a new conversation", "success");
});

introStart.addEventListener("click", () => dismissIntro(true));
introAgain.addEventListener("click", () => {
  dismissIntro(false);
  showToast("Intro will be shown again next time", "info");
});

introButton.addEventListener("click", () => {
  intro.classList.remove("hidden", "leaving");
});

docsLink.addEventListener("click", () => showToast("Opening API docs", "info"));

chatScroll.addEventListener("click", async (event) => {
  const copyButton = event.target.closest("[data-copy]");
  if (!copyButton) return;
  try {
    await navigator.clipboard.writeText(copyButton.getAttribute("data-copy") || "");
    showToast("Reply copied", "success");
  } catch {
    showToast("Could not copy reply", "warn");
  }
});

if (localStorage.getItem(INTRO_STORAGE_KEY) === "1") {
  intro.classList.add("hidden");
}

renderMessages();
loadConfig();
refreshCorpusStatus();
autoResizeTextarea();
focusComposer();
