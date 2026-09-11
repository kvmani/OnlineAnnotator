// Small DOM toolkit: element builder, icons, toasts, dialogs and inline help.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "html") el.innerHTML = value;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

// ---------------------------------------------------------------- icons (inline SVG paths, 24x24)
const ICONS = {
  pan: "M9 11V5a1.5 1.5 0 013 0v5m0-1V4a1.5 1.5 0 013 0v6m0-3a1.5 1.5 0 013 0v7a6 6 0 01-6 6h-1a6 6 0 01-5-2.7l-2.6-4a1.5 1.5 0 012.4-1.8L9 14",
  brush: "M4 20c3 0 5-1.5 5-4a3 3 0 00-3-3c-2 0-3 1.5-3 3.5V20zm5.5-5.5L20 4l-1-1-10.5 10.5",
  eraser: "M8 20h12M5.5 14.5l7-7 5 5-5.5 5.5H9.5l-4-3.5zm7-7L16 4l5 5-3.5 3.5",
  polygon: "M5 18l2-12 11 3-2 9H5zM5 18h0M7 6h0M18 9h0M16 18h0",
  lasso: "M7 17c-3-1.5-4-3.5-4-5.5C3 7 7 4 12 4s9 3 9 7-4 7-9 7c-1 0-2 0-3-.3M7 17c0 2 1 3 2 3m-2-3c1 0 2-.5 2-1.5",
  wand: "M4 20L15 9m2-5v2m0 4v2m-4-6h2m4 0h2m-4-2l1.5-1.5M20 3l-1.5 1.5",
  threshold: "M4 4h16v16H4zM4 14l4-4 3 3 4-5 5 6",
  fill: "M5 11l6-6 7 7-6 6-7-7zm0 0h13M19 15s-2 2.2-2 3.5a2 2 0 004 0C21 17.2 19 15 19 15z",
  undo: "M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3",
  redo: "M15 14l5-5-5-5m5 5H10a6 6 0 000 12h3",
  fit: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  save: "M5 4h11l4 4v12H4V4h1zm3 0v5h8V4M8 20v-6h8v6",
  send: "M4 12l16-8-6 16-3-7-7-1z",
  check: "M5 13l4 4L19 7",
  x: "M6 6l12 12M18 6L6 18",
  back: "M15 18l-6-6 6-6",
  next: "M9 18l6-6-6-6",
  help: "M12 22a10 10 0 110-20 10 10 0 010 20zm-2.5-13a2.5 2.5 0 115 .3c0 1.7-2.5 2.2-2.5 4M12 17h.01",
  upload: "M12 16V4m-5 5l5-5 5 5M4 16v4h16v-4",
  download: "M12 4v12m-5-5l5 5 5-5M4 20h16",
  users: "M16 20v-1a4 4 0 00-4-4H6a4 4 0 00-4 4v1M9 11a4 4 0 100-8 4 4 0 000 8zm13 9v-1a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8",
  folder: "M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zm10 3a3 3 0 100-6 3 3 0 000 6z",
  eyeoff: "M3 3l18 18M10.6 5.1A10 10 0 0112 5c6.5 0 10 7 10 7a17 17 0 01-3.2 4M6.6 6.6A17 17 0 002 12s3.5 7 10 7a9.7 9.7 0 005.4-1.6M9.9 9.9a3 3 0 004.2 4.2",
  lock: "M6 11h12v10H6V11zm2 0V7a4 4 0 118 0v4",
  play: "M7 4l13 8-13 8V4z",
  review: "M9 11l3 3 8-8M20 12v7a2 2 0 01-2 2H6a2 2 0 01-2-2V5a2 2 0 012-2h9",
  plus: "M12 5v14M5 12h14",
  keyboard: "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10",
  history: "M3 12a9 9 0 103-6.7L3 8m0-5v5h5M12 7v5l3 3",
  clean: "M4 20l6-6m-2-6l8 8m-6-10l2 2-6 6-2-2 6-6zm8 8l2 2",
  info: "M12 22a10 10 0 110-20 10 10 0 010 20zm0-6v-5m0-3h.01",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4m7 14l5-5-5-5m5 5H9",
  home: "M3 11l9-8 9 8v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1v-9z",
  trash: "M4 7h16M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3",
  edit: "M4 20h4L19 9l-4-4L4 16v4z",
  flag: "M5 21V4m0 0h11l-2 4 2 4H5",
  panel: "M4 4h16v16H4zM15 4v16",
};

export function icon(name, size = 18) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name] || ICONS.info);
  svg.append(path);
  return svg;
}

// ---------------------------------------------------------------------------------- toasts
export function toast(message, kind = "info", timeout = 4500) {
  const host = document.getElementById("toasts");
  const el = h("div", { class: `toast toast-${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  host.append(el);
  const close = () => {
    el.classList.add("toast-out");
    setTimeout(() => el.remove(), 250);
  };
  el.addEventListener("click", close);
  setTimeout(close, kind === "error" ? Math.max(timeout, 8000) : timeout);
}

// --------------------------------------------------------------------------------- dialogs
export function modal({ title, body, actions = [], wide = false, onClose }) {
  const backdrop = h("div", { class: "modal-backdrop" });
  const box = h("div", { class: `modal ${wide ? "modal-wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title });
  const footer = h("div", { class: "modal-actions" });
  const closeBtn = h("button", { class: "icon-btn modal-close", title: "Close (Esc)", "aria-label": "Close" }, icon("x"));
  box.append(h("div", { class: "modal-head" }, h("h2", {}, title), closeBtn), h("div", { class: "modal-body" }, body), footer);
  backdrop.append(box);
  document.body.append(backdrop);
  const close = (value) => {
    backdrop.remove();
    document.removeEventListener("keydown", onKey, true);
    if (onClose) onClose(value);
  };
  const onKey = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close(null);
    }
  };
  document.addEventListener("keydown", onKey, true);
  closeBtn.addEventListener("click", () => close(null));
  backdrop.addEventListener("mousedown", (e) => e.target === backdrop && close(null));
  for (const a of actions) {
    const btn = h("button", { class: `btn ${a.kind ? "btn-" + a.kind : ""}`, type: "button" }, a.label);
    btn.addEventListener("click", async () => {
      if (!a.onClick) return close(a.value);
      btn.disabled = true;
      try {
        const keepOpen = await a.onClick(close);
        if (keepOpen !== true) close(a.value);
      } finally {
        btn.disabled = false;
      }
    });
    footer.append(btn);
  }
  setTimeout(() => {
    const first = box.querySelector("input, textarea, select, .btn-primary");
    if (first) first.focus();
  }, 30);
  return { close, box };
}

export function confirmDialog(title, message, { confirmLabel = "Continue", kind = "primary" } = {}) {
  return new Promise((resolve) => {
    modal({
      title,
      body: h("p", {}, message),
      actions: [
        { label: "Cancel", value: false },
        { label: confirmLabel, kind, value: true },
      ],
      onClose: (v) => resolve(Boolean(v)),
    });
  });
}

// ------------------------------------------------------------------------------ inline help
// A small (?) button that opens an explanatory popover. Used at every decision that
// affects scientific meaning or could surprise a first-time user.
let openTip = null;
export function helpTip(text, { title = null, wide = false } = {}) {
  const btn = h("button", { class: "help-tip", type: "button", "aria-label": "Explain this", title: "What does this mean?" }, "?");
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (openTip) {
      const same = openTip.anchor === btn;
      openTip.el.remove();
      openTip = null;
      if (same) return;
    }
    const pop = h("div", { class: `help-pop ${wide ? "help-pop-wide" : ""}`, role: "tooltip" },
      title ? h("strong", {}, title) : null, typeof text === "string" ? h("p", {}, text) : text);
    document.body.append(pop);
    const r = btn.getBoundingClientRect();
    const pw = pop.offsetWidth;
    let left = Math.min(window.innerWidth - pw - 12, Math.max(12, r.left + r.width / 2 - pw / 2));
    let top = r.bottom + 8;
    if (top + pop.offsetHeight > window.innerHeight - 12) top = r.top - pop.offsetHeight - 8;
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
    openTip = { el: pop, anchor: btn };
  });
  return btn;
}
document.addEventListener("click", () => {
  if (openTip) {
    openTip.el.remove();
    openTip = null;
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && openTip) {
    openTip.el.remove();
    openTip = null;
  }
});

// ----------------------------------------------------------------------------- formatting
export const STATUS_LABELS = {
  new: "New",
  in_progress: "In progress",
  submitted: "Waiting for review",
  changes_requested: "Changes requested",
  approved: "Approved",
};

export const STATUS_HELP = {
  new: "Nobody has annotated this image yet.",
  in_progress: "Someone has saved work on this image but not submitted it.",
  submitted: "Submitted by an annotator; a reviewer must approve it or ask for changes.",
  changes_requested: "A reviewer returned it with comments. Fix and submit again.",
  approved: "Checked and approved. Only approved annotations are exported as ground truth.",
};

export function statusBadge(status) {
  return h("span", { class: `badge status-${status}`, title: STATUS_HELP[status] || "" }, STATUS_LABELS[status] || status);
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" }) +
        " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function fmtRelative(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return fmtDate(iso);
}

export function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function plural(n, word, pluralWord = `${word}s`) {
  return `${n.toLocaleString()} ${n === 1 ? word : pluralWord}`;
}

export function fmtPct(x, digits = 1) {
  return `${(100 * x).toFixed(digits)}%`;
}

export function field(label, control, help = null, hint = null) {
  return h("label", { class: "field" },
    h("span", { class: "field-label" }, label, help ? helpTip(help) : null),
    control,
    hint ? h("span", { class: "field-hint" }, hint) : null);
}

export function copyButton(text) {
  const btn = h("button", { class: "btn btn-small", type: "button" }, "Copy");
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied";
    } catch (_) {
      btn.textContent = "Select and copy manually";
    }
  });
  return btn;
}

export function emptyState(iconName, title, text, action = null) {
  return h("div", { class: "empty" }, icon(iconName, 40), h("h3", {}, title), h("p", {}, text), action);
}
