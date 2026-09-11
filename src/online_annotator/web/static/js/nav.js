// Navigation helpers shared by the views (kept separate from main.js to avoid import cycles).
import { clear, h, modal } from "./ui.js";
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
