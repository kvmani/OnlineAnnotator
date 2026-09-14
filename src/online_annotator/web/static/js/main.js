// Application shell: boot, hash router, top bar (with the Annotate / Review switch), help menu
// and keyboard help.
import { api, setUnauthorizedHandler } from "./api.js";
import { MODES, MODE_HELP, MODE_LABELS, app, isAdmin, mode } from "./state.js";
import { clear, h, icon, modal, toast } from "./ui.js";
import { go, setCrumbs, setModeHandler, showShortcuts } from "./nav.js";
import { renderHelp } from "./views/help.js";
import { renderHome } from "./views/home.js";
import { loginForm, renderLogin, renderPasswordChange } from "./views/login.js";
import { renderProject } from "./views/project.js";
import { renderUsers } from "./views/users.js";
import { renderWorkspace } from "./views/workspace.js";

const view = document.getElementById("view");
let current = null; // { leave: async () => boolean, destroy: () => void }
let navigating = false;
let modeChanging = false;
let skipNextRoute = false; // set when we undo a navigation the current view refused

function renderTopbar() {
  const bar = document.getElementById("topbar");
  bar.hidden = !app.me;
  document.getElementById("demo-banner").hidden = !(app.meta && app.meta.demo);
  document.body.classList.toggle("mode-annotate", Boolean(app.me) && mode() === "annotate");
  document.body.classList.toggle("mode-review", Boolean(app.me) && mode() === "review");
  const right = clear(document.getElementById("topbar-right"));
  if (!app.me) return;
  if (!app.me.must_change_password) right.append(modeSwitch());
  if (app.meta && app.meta.portal_url) {
    right.append(h("a", { class: "top-link", href: portalHref(app.meta.portal_url), title: "Back to the tools portal" }, icon("home", 16), "All tools"));
  }
  if (isAdmin()) right.append(h("a", { class: "top-link", href: "#/users" }, icon("users", 16), "Users"));
  const helpBtn = h("button", { class: "top-link", type: "button", "aria-haspopup": "menu" }, icon("help", 16), "Help");
  helpBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown(helpBtn, [
      { label: "Help centre", icon: "help", action: () => go("#/help") },
      { label: "Getting started", icon: "play", action: () => go("#/help/start") },
      { label: "Annotate and Review modes", icon: "review", action: () => go("#/help/modes") },
      { label: "Keyboard shortcuts  (?)", icon: "keyboard", action: showShortcuts },
      app.meta && app.meta.feedback_url ? { label: "Send feedback", icon: "flag", action: () => window.open(app.meta.feedback_url, "_blank") } : null,
      { label: `About (version ${app.meta ? app.meta.version : ""})`, icon: "info", action: showAbout },
    ]);
  });
  right.append(helpBtn);
  const initials = (app.me.full_name || app.me.email).split(/\s+/).map((s) => s[0]).join("").slice(0, 2).toUpperCase();
  const userBtn = h("button", { class: "user-chip", type: "button", title: app.me.email },
    h("span", { class: "avatar" }, initials), h("span", { class: "user-name" }, app.me.full_name),
    isAdmin() ? h("span", { class: "role", title: "Administrator: can also manage projects, classes and accounts" }, "admin") : null);
  userBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    dropdown(userBtn, [
      { label: "Change password", icon: "lock", action: () => go("#/account") },
      { label: "Sign out", icon: "logout", action: signOut },
    ]);
  });
  right.append(userBtn);
}

// The working-mode switch: always visible, always says which mode is on.
function modeSwitch() {
  const group = h("div", { class: "mode-switch", role: "radiogroup", "aria-label": "Working mode" });
  for (const m of MODES) {
    const active = mode() === m.id;
    const b = h("button", { class: `mode-btn${active ? " active" : ""}`, type: "button", role: "radio",
      "aria-checked": active ? "true" : "false", title: MODE_HELP[m.id] }, icon(m.icon, 15), m.label);
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      changeMode(m.id);
    });
    group.append(b);
  }
  return group;
}

// Save and leave the current view (which also hands back an editing reservation), switch
// the mode on the server, then draw the same page again for the new mode.
async function changeMode(target) {
  if (!app.me || modeChanging || navigating || mode() === target) return;
  modeChanging = true;
  try {
    if (current && current.leave && !(await current.leave())) return;
    try {
      app.me = (await api.put("api/v1/auth/mode", { mode: target })).user;
      toast(target === "review"
        ? "Review mode: work that other people submitted is waiting for you. Your own submissions are reviewed by someone else."
        : "Annotate mode: label images and submit them for review.", "info", 5000);
    } catch (err) {
      toast(err.message, "error");
    }
    renderTopbar();
    await render(false);
  } finally {
    modeChanging = false;
  }
}
setModeHandler(changeMode);

// Another tab or desk may have switched the mode: follow it when this tab is looked at again.
document.addEventListener("visibilitychange", async () => {
  if (document.hidden || !app.me || navigating || modeChanging) return;
  const before = { mode: mode(), admin: isAdmin() };
  let me;
  try {
    me = (await api.get("api/v1/auth/me")).user;
  } catch (_) {
    return; // a lapsed session is handled by the sign-in dialog
  }
  app.me = me;
  if (mode() === before.mode && isAdmin() === before.admin) return;
  renderTopbar();
  if (mode() !== before.mode) toast(`Your working mode was switched to ${MODE_LABELS[mode()]} in another window, so this page now shows ${MODE_LABELS[mode()]} mode.`, "info", 7000);
  if (current && current.leave && !(await current.leave())) return;
  await render(false);
});

// A portal URL starting with ":" (e.g. ":5000/") means "this host, that port", so one
// setting works from every desk without knowing the server's intranet address.
function portalHref(url) {
  return url.startsWith(":") ? `${location.protocol}//${location.hostname}${url}` : url;
}

let openMenu = null;
function dropdown(anchor, items) {
  if (openMenu) {
    openMenu.remove();
    openMenu = null;
  }
  const menu = h("div", { class: "menu", role: "menu" });
  for (const item of items.filter(Boolean)) {
    const b = h("button", { class: "menu-item", role: "menuitem", type: "button" }, icon(item.icon, 16), item.label);
    b.addEventListener("click", () => {
      menu.remove();
      openMenu = null;
      item.action();
    });
    menu.append(b);
  }
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.top = `${r.bottom + 6}px`;
  menu.style.left = `${Math.max(8, Math.min(window.innerWidth - menu.offsetWidth - 8, r.right - menu.offsetWidth))}px`;
  openMenu = menu;
}
document.addEventListener("click", () => {
  if (openMenu) {
    openMenu.remove();
    openMenu = null;
  }
});

function showAbout() {
  const m = app.meta || {};
  modal({
    title: "About Online Annotator",
    body: h("div", { class: "about" },
      h("p", {}, "Create, review and export pixel-exact semantic-segmentation ground truth for microstructures."),
      h("dl", {},
        h("dt", {}, "Version"), h("dd", {}, m.version),
        h("dt", {}, "Tool id"), h("dd", {}, m.tool_id),
        h("dt", {}, "Editing lease"), h("dd", {}, `${Math.round((m.lock_lease_seconds || 0) / 60)} minutes, renewed automatically while you work`),
        h("dt", {}, "Upload limit"), h("dd", {}, `${m.max_upload_mb} MB per file, ${m.max_image_megapixels} megapixels`),
        h("dt", {}, "Self-approval"), h("dd", {}, m.allow_self_approval ? "allowed: people may review their own submissions" : "not allowed: a second person reviews every submission"))),
    actions: [{ label: "Close", kind: "primary" }],
  });
}

async function signOut() {
  if (current && current.leave && !(await current.leave())) return;
  try {
    await api.post("api/v1/auth/logout");
  } catch (_) {
    /* already signed out */
  }
  app.me = null;
  renderTopbar();
  go("#/login");
}

export async function refreshMe() {
  try {
    app.me = (await api.get("api/v1/auth/me")).user;
  } catch (_) {
    app.me = null;
  }
  renderTopbar();
  return app.me;
}

function route() {
  if (skipNextRoute) {
    skipNextRoute = false;
    return;
  }
  return render(true);
}

// Draw the view for the current hash. `askLeave` is false when the caller already asked the
// current view to leave (switching mode does that before it changes anything). A navigation
// that arrives while a view is still being drawn is not dropped: it runs as soon as that
// drawing finishes.
let renderAgain = false;
async function render(askLeave) {
  if (navigating) {
    renderAgain = true;
    return;
  }
  navigating = true;
  try {
    if (askLeave && current && current.leave) {
      const ok = await current.leave();
      if (!ok) {
        skipNextRoute = true;
        history.back();
        return;
      }
    }
    if (current && current.destroy) current.destroy();
    current = null;
    const hash = location.hash.replace(/^#/, "") || "/";
    const parts = hash.split("/").filter(Boolean);
    document.body.classList.toggle("in-workspace", parts[0] === "p" && parts[2] === "i");
    clear(view);
    setCrumbs([]);
    if (!app.me && parts[0] !== "login" && parts[0] !== "help") {
      sessionStorage.setItem("oa.after-login", location.hash);
      renderLogin(view, { onDone: afterLogin });
      return;
    }
    if (app.me && app.me.must_change_password && parts[0] !== "help") {
      renderPasswordChange(view, { forced: true, onDone: afterLogin });
      return;
    }
    if (parts[0] === "login") return renderLogin(view, { onDone: afterLogin });
    if (parts[0] === "help") {
      current = renderHelp(view, parts[1]);
      return;
    }
    if (parts[0] === "account") return renderPasswordChange(view, { forced: false, onDone: () => go("#/") });
    if (parts[0] === "users") {
      if (!isAdmin()) return go("#/");
      current = await renderUsers(view);
      return;
    }
    if (parts[0] === "p" && parts[1]) {
      const projectId = Number(parts[1]);
      if (parts[2] === "i" && parts[3]) {
        current = await renderWorkspace(view, projectId, Number(parts[3]));
        return;
      }
      current = await renderProject(view, projectId, parts[2] || "images");
      return;
    }
    current = await renderHome(view);
  } catch (err) {
    view.append(h("div", { class: "page" }, h("div", { class: "alert alert-error" }, err.message || String(err))));
  } finally {
    navigating = false;
    if (renderAgain) {
      renderAgain = false;
      render(true);
    }
  }
}

async function afterLogin() {
  await refreshMe();
  const target = sessionStorage.getItem("oa.after-login");
  sessionStorage.removeItem("oa.after-login");
  go(target && !target.includes("login") ? target : "#/");
}

// A lapsed session must never throw away an open image: sign in again in a dialog,
// on top of the current view, and carry on.
let reauthOpen = false;
setUnauthorizedHandler(() => {
  if (!app.me || reauthOpen) return;
  reauthOpen = true;
  const email = app.me.email;
  const dlg = modal({
    title: "Please sign in again",
    body: h("div", {}, h("p", { class: "muted" }, "Your session ended (for example after a long break). Unsaved work on this page is kept; sign in to continue."),
      loginForm({ presetEmail: email, onDone: async () => {
        dlg.close(true);
        await refreshMe();
        toast("Signed in again. You can continue where you were.", "success");
        window.dispatchEvent(new CustomEvent("oa:reauthenticated"));
      } })),
    onClose: () => {
      reauthOpen = false;
    },
  });
});

document.addEventListener("keydown", (e) => {
  const t = e.target;
  const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT");
  if (!typing && e.key === "?" && app.me) {
    e.preventDefault();
    showShortcuts();
  }
});

window.addEventListener("beforeunload", (e) => {
  if (current && current.hasUnsaved && current.hasUnsaved()) {
    e.preventDefault();
    e.returnValue = "";
  }
});
window.addEventListener("pagehide", () => current && current.onPageHide && current.onPageHide());

async function boot() {
  try {
    app.meta = await api.get("api/v1/meta");
    document.title = app.meta.site_name || "Online Annotator";
  } catch (err) {
    view.append(h("div", { class: "page" }, h("div", { class: "alert alert-error" }, "The server is not responding. " + err.message)));
    return;
  }
  await refreshMe();
  window.addEventListener("hashchange", route);
  route();
}

boot();
