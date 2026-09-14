// Navigation helpers shared by the views (kept separate from main.js to avoid import cycles).
import { MODE_LABELS } from "./state.js";
import { clear, h, icon, modal } from "./ui.js";
import { shortcutsTable } from "./views/help.js";

export function go(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = hash;
}

export function setCrumbs(items) {
  const nav = clear(document.getElementById("crumbs"));
  items.forEach((item, k) => {
    if (k) nav.append(h("span", { class: "crumb-sep", "aria-hidden": "true" }, "/"));
    nav.append(item.href ? h("a", { href: item.href }, item.label) : h("span", { class: "crumb-current" }, item.label));
  });
}

export function showShortcuts() {
  modal({ title: "Keyboard shortcuts", body: shortcutsTable(), wide: true, actions: [{ label: "Close", kind: "primary" }] });
}

// Switching the working mode is owned by main.js (it saves and leaves the current view first,
// then redraws it in the new mode). Views ask for it through here.
let modeHandler = null;

export function setModeHandler(fn) {
  modeHandler = fn;
}

export function switchMode(target) {
  return modeHandler ? modeHandler(target) : undefined;
}

export function modeButton(target, label = `Switch to ${MODE_LABELS[target]} mode`, small = true) {
  return h("button", { class: `btn ${small ? "btn-small" : ""}`, type: "button", onclick: () => switchMode(target) },
    icon(target === "review" ? "review" : "edit", 14), label);
}
