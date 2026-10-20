// Clearance chat page. All text from the server is inserted with textContent, never
// as HTML, so nothing in a document or answer can run as code on this page.

const $ = (sel) => document.querySelector(sel);
const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private window: fine */ } },
};

const SUGGESTIONS = {
  employee: [
    "How many days of paid sick leave do employees get?",
    "How long is paid parental leave?",
    "Will HR ever ask for my Social Security number by email?",
    "What is Rebecca Heath's annual base salary?",
  ],
  hr: [
    "What is Rebecca Heath's annual base salary?",
    "Who is Rebecca Heath's emergency contact?",
    "What is Nicole Day's phone number?",
    "How much federal income tax was withheld for James Brooks?",
  ],
};
const STATUS_LABEL = { answered: "Answered", no_answer: "Not in the documents", refused: "Refused", blocked: "Blocked", error: "Error" };
const STEP_LABEL = {
  permission: [ "Allowed", "Refused" ], mask: [ "Masked", "Masked" ], search: [ "Searched", "Nothing found" ],
  answer: [ "Answered", "Not in documents" ], safety: [ "Safety check passed", "Blocked by safety check" ],
  reveal: [ "Unsealed for HR", "Unsealed for HR" ],
};
const WAIT_STEPS = ["permission", "mask", "search", "answer", "safety"];

let users = [];
let me = null;

// ---------------------------------------------------------------- theme

function applyTheme(choice) {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  document.querySelectorAll("[data-theme-choice]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.themeChoice === choice)));
  store.set("clearance-theme", choice);
}
document.querySelectorAll("[data-theme-choice]").forEach((b) =>
  b.addEventListener("click", () => applyTheme(b.dataset.themeChoice)));
applyTheme(store.get("clearance-theme") || "system");

// ---------------------------------------------------------------- people

function renderPeople() {
  const box = $("#people");
  box.replaceChildren();
  for (const u of users) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "person";
    btn.setAttribute("role", "radio");
    btn.setAttribute("aria-checked", String(me && me.id === u.id));
    const avatar = Object.assign(document.createElement("span"), { className: "avatar", textContent: u.name[0] });
    const text = document.createElement("span");
    text.append(
      Object.assign(document.createElement("div"), { className: "person-name", textContent: u.name }),
      Object.assign(document.createElement("div"), { className: "person-title", textContent: u.title }),
    );
    const badge = Object.assign(document.createElement("span"), {
      className: `badge ${u.role}`, textContent: u.role === "hr" ? "HR" : "Employee",
    });
    btn.append(avatar, text, badge);
    btn.addEventListener("click", () => signIn(u.id));
    box.append(btn);
  }
}

function signIn(id) {
  const next = users.find((u) => u.id === id) || users[0];
  const changed = !me || me.id !== next.id;
  me = next;
  store.set("clearance-user", me.id);
  renderPeople();
  renderSuggestions();
  $("#whoami").textContent = `${me.name} · ${me.role === "hr" ? "sees real values" : "sees sealed tags"}`;
  $("#tab-audit").hidden = me.role !== "hr";
  if (me.role !== "hr") showTab("chat");
  // Clear the conversation on every switch: HR's unsealed answers must not stay on screen.
  if (changed) resetConversation();
}

function renderSuggestions() {
  const box = $("#suggestions");
  box.replaceChildren(...SUGGESTIONS[me.role].map((q) => {
    const b = Object.assign(document.createElement("button"), { type: "button", className: "suggestion", textContent: q });
    b.addEventListener("click", () => ask(q));
    return b;
  }));
}

// ---------------------------------------------------------------- conversation

const empty = $("#empty");

function resetConversation() {
  $("#stream").replaceChildren(empty);
  empty.hidden = false;
}

function addUserMessage(text) {
  empty.hidden = true;
  const node = $("#tpl-user").content.cloneNode(true);
  node.querySelector(".bubble").textContent = text;
  $("#stream").append(node);
}

function newCard() {
  const node = $("#tpl-answer").content.firstElementChild.cloneNode(true);
  $("#stream").append(node);
  return node;
}

function fillTrail(list, steps) {
  list.replaceChildren(...steps.map((s) => {
    const li = document.createElement("li");
    li.className = `${s.step}${s.ok ? "" : " fail"}`;
    li.textContent = STEP_LABEL[s.step][s.ok ? 0 : 1];
    li.title = s.detail || "";
    return li;
  }));
}

function showThinking() {
  const card = newCard();
  card.classList.add("thinking");
  card.querySelector(".card").dataset.status = "waiting";
  card.querySelector(".pill").textContent = "Working";
  card.querySelector(".answer").textContent = "Checking permission, masking and searching sealed documents…";
  fillTrail(card.querySelector(".trail"), WAIT_STEPS.map((step) => ({ step, ok: true })));
  const items = [...card.querySelectorAll(".trail li")];
  let i = 0;
  items[0].classList.add("on");
  const timer = setInterval(() => { i = Math.min(i + 1, items.length - 1); items[i].classList.add("on"); }, 650);
  scrollDown();
  return { card, stop: () => clearInterval(timer) };
}

function renderAnswer(card, reply) {
  card.classList.remove("thinking");
  const inner = card.querySelector(".card");
  inner.dataset.status = reply.status;
  card.querySelector(".pill").textContent = STATUS_LABEL[reply.status] || reply.status;
  const revealed = reply.segments.some((s) => s.value);
  card.querySelector(".role-note").textContent =
    reply.status === "answered" || reply.status === "no_answer"
      ? (revealed ? "Unsealed for HR · each reveal logged" : "Sealed: tags, not values")
      : "";

  const answer = card.querySelector(".answer");
  answer.replaceChildren(...reply.segments.map((s) => {
    if (s.text !== undefined) return document.createTextNode(s.text);
    if (s.value) {
      return Object.assign(document.createElement("span"), {
        className: "revealed", textContent: s.value, title: `${s.placeholder} · revealed for HR and logged`,
      });
    }
    return Object.assign(document.createElement("code"), {
      className: "tag", textContent: s.placeholder, title: "Sealed: the real value is only shown to HR",
    });
  }));

  card.querySelector(".sources").replaceChildren(...reply.sources.map((src) => {
    const chip = document.createElement("span");
    chip.className = "source";
    chip.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 1.5h5.5L13 5v9.5H4z M9.5 1.5V5H13"/></svg>';
    chip.append(document.createTextNode(`${src.doc} · p. ${src.page}`));
    return chip;
  }));

  fillTrail(card.querySelector(".trail"), reply.steps);
  if (reply.masked_question) {
    card.querySelector(".saw").hidden = false;
    card.querySelector(".saw-q").textContent = reply.masked_question;
  }
  scrollDown();
}

function renderError(card, message) {
  renderAnswer(card, { status: "error", segments: [{ text: message }], sources: [], steps: [], masked_question: null });
}

function scrollDown() {
  const s = $("#stream");
  s.scrollTop = s.scrollHeight;
}

async function ask(question) {
  question = question.trim();
  if (!question || !me) return;
  showTab("chat");
  addUserMessage(question);
  const input = $("#question");
  input.value = "";
  autosize();
  $("#send").disabled = true;
  const { card, stop } = showThinking();
  try {
    const res = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: me.id, question }),
    });
    const data = await res.json();
    stop();
    if (!res.ok) renderError(card, data.detail || "Something went wrong. Please try again.");
    else renderAnswer(card, data);
  } catch {
    stop();
    renderError(card, "Can't reach the server. Is it still running?");
  } finally {
    $("#send").disabled = false;
    input.focus();
  }
}

// ---------------------------------------------------------------- composer

const input = $("#question");
function autosize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
});
$("#composer").addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });

// ---------------------------------------------------------------- tabs and audit log

function showTab(name) {
  for (const t of ["chat", "audit"]) {
    $(`#tab-${t}`).setAttribute("aria-selected", String(t === name));
    $(`#view-${t}`).hidden = t !== name;
  }
  if (name === "audit") loadAudit();
}
$("#tab-chat").addEventListener("click", () => showTab("chat"));
$("#tab-audit").addEventListener("click", () => showTab("audit"));
$("#audit-refresh").addEventListener("click", loadAudit);

async function loadAudit() {
  const body = $("#audit-rows");
  const res = await fetch(`/api/audit?user=${encodeURIComponent(me.id)}`);
  if (!res.ok) { body.replaceChildren(); return; }
  const rows = await res.json();
  body.replaceChildren(...rows.map((e) => {
    const tr = document.createElement("tr");
    const cells = [
      ["when", new Date(e.at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })],
      ["", e.user], ["", e.role === "hr" ? "HR" : e.role],
      ["rec", e.placeholder === "-" ? "—" : e.placeholder],
      [e.allowed ? "ok-cell" : "no-cell", e.allowed ? "Revealed" : "Refused"],
      ["", e.purpose],
    ];
    for (const [cls, text] of cells) tr.append(Object.assign(document.createElement("td"), { className: cls, textContent: text }));
    return tr;
  }));
}

// ---------------------------------------------------------------- start

async function start() {
  users = await (await fetch("/api/users")).json();
  signIn(store.get("clearance-user") || "oliver");
  try {
    const s = await (await fetch("/api/status")).json();
    const status = $("#status");
    status.classList.add(s.documents_ready && s.ai_key ? "ok" : "bad");
    status.lastElementChild.textContent = !s.ai_key ? "No AI key in .env"
      : !s.documents_ready ? "No documents: run ingest" : `${s.chunks} sealed passages\n${s.model}`;
    status.lastElementChild.style.whiteSpace = "pre-line";
  } catch { /* the status line is only a nicety */ }
  input.focus();
}
start();
