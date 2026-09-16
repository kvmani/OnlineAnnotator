// Annotation workspace: the editor plus everything around it (classes, tools, review,
// history, autosave and the editing lease).
import { api, fetchBytes, putLabels, releaseLockBeacon } from "../api.js";
import { Editor, TOOLS, isTyping } from "../editor/editor.js";
import { go, modeButton, setCrumbs, showShortcuts } from "../nav.js";
import { app, inReview, savePref } from "../state.js";
import {
  STATUS_HELP, STATUS_LABELS, clear, confirmDialog, field, fmtDate, fmtPct, fmtRelative, h, helpTip, icon, modal, statusBadge, toast,
} from "../ui.js";

const BRUSH_MIN = 1; // brush and eraser diameter in image pixels
const BRUSH_MAX = 160;
const TOLERANCE_MIN = 1;
const TOLERANCE_MAX = 100;
const MOSTLY_SELECTED = 0.7; // above this share of a threshold region, warn that Otsu lacks background

function clampInt(value, min, max) {
  return Math.max(min, Math.min(max, Math.round(Number(value) || 0)));
}
import { startNext } from "./home.js";
import { analysisView, importSummary, maskImportControls, previewer } from "./maskimport.js";

const AUTOSAVE_DELAY = 2500;

export async function renderWorkspace(view, projectId, imageId) {
  const [{ project }, { image: initial }, { images }] = await Promise.all([
    api.get(`api/v1/projects/${projectId}`),
    api.get(`api/v1/images/${imageId}`),
    api.get(`api/v1/projects/${projectId}/images`),
  ]);
  if (initial.project_id !== projectId) throw new Error("This image belongs to another project.");
  setCrumbs([{ label: "Projects", href: "#/" }, { label: project.name, href: `#/p/${projectId}` }, { label: initial.stem }]);
  const ws = new Workspace(view, project, initial, images);
  await ws.start();
  return ws;
}

class Workspace {
  constructor(view, project, image, images) {
    this.view = view;
    this.project = project;
    this.image = image;
    this.order = images.map((i) => i.id); // same order as the gallery (by name)
    this.classes = project.classes;
    this.revision = image.working_revision;
    this.editable = false;
    this.haveLock = false;
    this.changeCount = 0;
    this.savedCount = 0;
    this.saveError = null;
    this.saving = null;
    this.destroyed = false;
    const prefs = app.prefs;
    this.prefs = {
      // Brush size is a diameter since 2.2.0; `brush` (a radius) is what older releases saved.
      tool: TOOLS[prefs.tool] ? prefs.tool : "brush", brushDiameter: prefs.brushDiameter || (prefs.brush ? prefs.brush * 2 : 12),
      tolerance: prefs.tolerance || 18,
      opacity: prefs.opacity ?? 0.5, protect: Boolean(prefs.protect),
    };
  }

  // ------------------------------------------------------------------ layout
  async start() {
    this.root = h("div", { class: "ws" });
    this.top = h("div", { class: "ws-top" });
    this.banner = h("div", { class: "ws-banner", hidden: true });
    this.toolbar = h("div", { class: "ws-tools", role: "toolbar", "aria-label": "Tools" });
    this.canvasHost = h("div", { class: "ws-canvas" });
    this.loading = h("div", { class: "ws-loading" }, "Loading image…");
    this.canvasHost.append(this.loading);
    this.side = h("aside", { class: "ws-side" });
    this.hint = h("div", { class: "ws-hint" });
    this.root.append(this.top, this.banner, h("div", { class: "ws-main" }, this.toolbar, this.canvasHost, this.side), this.hint);
    this.view.append(this.root);

    this.editor = new Editor(this.canvasHost, {
      onChange: () => this.onEdit(),
      onHover: (info) => this.showHover(info),
      onPickClass: (index) => this.selectClass(index),
      onThreshold: (state) => this.renderToolOptions(state),
      onMessage: (msg) => toast(msg, "info"),
      onViewChange: (scale) => {
        if (this.zoomLabel) this.zoomLabel.textContent = `${Math.round(scale * 100)}%`;
      },
    });
    this.editor.setClasses(this.classes);
    this.editor.brushSize = clampInt(this.prefs.brushDiameter, BRUSH_MIN, BRUSH_MAX) / 2;
    this.editor.tolerance = this.prefs.tolerance;
    this.editor.opacity = this.prefs.opacity;
    this.editor.protect = this.prefs.protect;
    this.editor.activeClass = (this.classes[0] || { index: 1 }).index;

    await this.decideMode();
    const [labels] = await Promise.all([this.loadLabels(), null]);
    try {
      await this.editor.load({ imageUrl: this.image.display_url, width: this.image.width, height: this.image.height, labels });
    } catch (err) {
      this.loading.textContent = err.message;
      throw err;
    }
    this.loading.remove();
    this.editor.readOnly = !this.editable;
    this.renderToolbar();
    this.renderTop();
    this.renderSide();
    this.setTool(this.editable ? this.prefs.tool : "pan");
    this.updateCoverage();
    fetchBytes(`api/v1/images/${this.image.id}/grey`).then(({ bytes }) => this.editor.setGrey(bytes)).catch(() => {});
    this._keys = (e) => this.onKey(e);
    window.addEventListener("keydown", this._keys);
    this._reauth = () => {
      this.saveError = null;
      if (this.hasUnsaved()) this.saveNow(false);
      else this.updateSaveState();
    };
    window.addEventListener("oa:reauthenticated", this._reauth);
    this.editor.canvas.focus({ preventScroll: true });
  }

  async loadLabels(version = null) {
    const url = `api/v1/images/${this.image.id}/labels${version ? `?version=${version}` : ""}`;
    const { bytes, headers } = await fetchBytes(url);
    if (!version) this.revision = Number(headers.get("X-Revision") || this.image.working_revision);
    if (bytes.length !== this.image.width * this.image.height) throw new Error("The stored labels do not match the image size.");
    return bytes;
  }

  // Decide whether this user edits, reviews, or only looks. The working mode decides which
  // images are editable here, mirroring the rules the server enforces.
  async decideMode() {
    const img = this.image;
    const pending = (img.versions || []).find((v) => v.status === "submitted");
    this.ownSubmission = Boolean(img.status === "submitted" && pending && pending.created_by === app.me.email);
    const mayReview = !this.ownSubmission || Boolean(app.meta && app.meta.allow_self_approval);
    this.reviewMode = inReview() && img.status === "submitted" && mayReview;
    this.readReason = null;
    if (img.status === "submitted" && !this.reviewMode) this.readReason = inReview() ? "own_submission" : "submitted";
    else if (inReview() && img.status !== "submitted") this.readReason = "not_for_review";
    else if (img.status === "approved" && !this.reopenApproved) this.readReason = "approved";
    if (!this.readReason) {
      try {
        await api.post(`api/v1/images/${img.id}/lock`);
        this.haveLock = true;
        this.startHeartbeat();
      } catch (err) {
        if (err.status === 423) this.readReason = "locked";
        else throw err;
      }
    }
    this.editable = !this.readReason;
    this.renderBanner();
  }

  startHeartbeat() {
    clearInterval(this.heartbeat);
    const every = Math.max(20, Math.floor((app.meta.lock_lease_seconds || 300) / 3)) * 1000;
    this.heartbeat = setInterval(async () => {
      try {
        await api.post(`api/v1/images/${this.image.id}/lock`);
      } catch (err) {
        if (err.status === 423) this.loseLock(err.message);
      }
    }, every);
  }

  loseLock(message) {
    clearInterval(this.heartbeat);
    this.haveLock = false;
    this.editable = false;
    this.editor.readOnly = true;
    this.readReason = "lost";
    this.lostMessage = message;
    this.renderBanner();
    this.renderTop();
    this.renderToolbar();
  }

  renderBanner() {
    const b = clear(this.banner);
    const img = this.image;
    const latest = img.versions && img.versions[0];
    const add = (cls, ...children) => {
      b.className = `ws-banner ${cls}`;
      b.hidden = false;
      b.append(...children);
    };
    b.hidden = true;
    if (this.readReason === "locked") {
      add("banner-grey", icon("lock", 16), h("span", {}, h("strong", {}, `${img.lock.user_name || img.lock.user_email || "Someone"} is editing this image.`),
        " You can look but not change it. It unlocks when they leave or after a few idle minutes."),
      h("button", { class: "btn btn-small", onclick: () => this.retryLock() }, "Try again"),
      helpTip("Only one person can edit an image at a time, so nobody's work is overwritten. The reservation (lease) renews while that person works and expires after a few minutes of inactivity."));
    } else if (this.readReason === "lost") {
      add("banner-red", icon("lock", 16), h("span", {}, h("strong", {}, "Editing paused. "), this.lostMessage || "Your reservation of this image expired.",
        this.changeCount !== this.savedCount ? " Your latest changes are still here; re-open to save them." : ""),
      h("button", { class: "btn btn-small", onclick: () => this.retryLock() }, "Re-open for editing"));
    } else if (this.readReason === "submitted") {
      const by = latest ? ` Submitted by ${latest.created_by === app.me.email ? "you" : latest.created_by.split("@")[0]} ${fmtRelative(latest.created_at)}.` : "";
      add("banner-blue", icon("send", 16), h("span", {}, h("strong", {}, "Waiting for review."), by,
        this.ownSubmission ? " It is read-only until someone else reviews it; you can take it back while it waits."
          : " To review it, switch to Review mode."),
      this.ownSubmission ? h("button", { class: "btn btn-small", onclick: () => this.withdraw() }, "Withdraw to edit") : modeButton("review"));
    } else if (this.readReason === "own_submission") {
      add("banner-purple", icon("review", 16), h("span", {}, h("strong", {}, "This is your own submission. "),
        "Someone else reviews it, so it is view-only for you in Review mode. To change it, switch to Annotate mode and withdraw it."),
      modeButton("annotate"),
      h("button", { class: "btn btn-small", type: "button", onclick: () => startNext(this.project.id, "review", img.id) }, "Review next"));
    } else if (this.readReason === "not_for_review") {
      add("banner-purple", icon("review", 16), h("span", {}, h("strong", {}, "Review mode. "),
        `This image is ${(STATUS_LABELS[img.status] || img.status).toLowerCase()}, not waiting for review, so it is view-only here. Switch to Annotate mode to edit it.`),
      modeButton("annotate"),
      h("button", { class: "btn btn-small", type: "button", onclick: () => startNext(this.project.id, "review", img.id) }, "Review next"));
    } else if (this.readReason === "approved") {
      const approved = img.versions.find((v) => v.status === "approved");
      add("banner-green", icon("check", 16), h("span", {}, h("strong", {}, "Approved"),
        approved ? ` by ${approved.reviewed_by ? approved.reviewed_by.split("@")[0] : "?"} ${fmtRelative(approved.reviewed_at)} (version ${approved.number}).` : ".",
        " This is ground truth. Editing reopens it; the approved version stays in history and keeps being exported until a new one is approved."),
      h("button", { class: "btn btn-small", onclick: () => this.reopen() }, "Edit anyway"));
    } else if (this.reviewMode) {
      add("banner-blue", icon("review", 16), h("span", {}, h("strong", {}, "Review. "),
        `Submitted by ${latest ? latest.created_by.split("@")[0] : "?"} ${latest ? fmtRelative(latest.created_at) : ""}`,
        latest && latest.note ? h("span", {}, " with the note: “", h("em", {}, latest.note), "”") : ".",
        " Check the labels against the guidelines. You may correct them; then approve, or request changes with a comment."),
      helpTip("Tip: press H to hide the labels and compare with the image underneath, and O to see outlines only. If you correct labels, your corrected version is what gets approved; the original submission stays in history."));
    } else if (img.status === "changes_requested") {
      const returned = img.versions.find((v) => v.status === "changes_requested");
      add("banner-amber", icon("flag", 16), h("span", {}, h("strong", {}, "Changes requested"),
        returned ? ` by ${returned.reviewed_by.split("@")[0]}: “` : ".", returned ? h("em", {}, returned.review_comment) : null, returned ? "”" : "",
        " Fix it, then submit again."));
    }
  }

  async retryLock() {
    this.image = (await api.get(`api/v1/images/${this.image.id}`)).image;
    const unsaved = this.changeCount !== this.savedCount;
    const oldRevision = this.revision;
    await this.decideMode();
    if (this.editable) {
      if (!unsaved || this.image.working_revision !== oldRevision) {
        if (unsaved) toast("Someone saved this image meanwhile, so their version is shown. Your unsaved strokes were discarded.", "error", 9000);
        this.editor.replaceLabels(await this.loadLabels());
        this.changeCount = this.savedCount = 0;
      }
      this.editor.readOnly = false;
      this.setTool(this.prefs.tool);
      if (unsaved) this.scheduleSave(0);
      toast("You can edit again.", "success");
    }
    this.renderTop();
    this.renderToolbar();
    this.renderSide();
  }

  async reopen() {
    const ok = await confirmDialog("Edit an approved image?", "The image goes back to 'In progress' and must be submitted and approved again. The approved version stays in history and is still exported until then.", { confirmLabel: "Edit anyway" });
    if (!ok) return;
    this.reopenApproved = true;
    await this.retryLock();
  }

  async withdraw() {
    try {
      const res = await api.post(`api/v1/images/${this.image.id}/withdraw`);
      this.image = res.image;
      toast("Submission withdrawn. You can edit again.", "success");
      await this.retryLock();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // ------------------------------------------------------------------ top bar
  renderTop() {
    const img = this.image;
    const idx = this.order.indexOf(img.id);
    const prev = h("button", { class: "icon-btn", title: "Previous image (Ctrl+←)", "aria-label": "Previous image", disabled: idx <= 0 }, icon("back"));
    const next = h("button", { class: "icon-btn", title: "Next image (Ctrl+→)", "aria-label": "Next image", disabled: idx < 0 || idx >= this.order.length - 1 }, icon("next"));
    prev.addEventListener("click", () => this.step(-1));
    next.addEventListener("click", () => this.step(1));
    this.saveState = h("span", { class: "save-state" });
    this.updateSaveState();
    const actions = h("div", { class: "ws-actions" });
    if (this.editable) {
      const save = h("button", { class: "btn", title: "Save now (Ctrl+S). Work is also saved automatically." }, icon("save", 16), "Save");
      save.addEventListener("click", () => this.saveNow(true));
      actions.append(save);
    }
    if (this.reviewMode && this.editable) {
      const reject = h("button", { class: "btn btn-warn" }, icon("flag", 16), "Request changes");
      reject.addEventListener("click", () => this.requestChanges());
      const approve = h("button", { class: "btn btn-success" }, icon("check", 16), "Approve");
      approve.addEventListener("click", () => this.approve());
      actions.append(reject, approve,
        helpTip("Approve: the labels become ground truth and will be exported. Request changes: the image goes back to the person who submitted it, with your comment, to fix in Annotate mode. Nobody reviews their own submissions unless an administrator allows it."));
    } else if (this.editable && img.status !== "submitted") {
      const submit = h("button", { class: "btn btn-primary", title: "Send it to be reviewed by someone else" }, icon("send", 16), "Submit for review");
      submit.addEventListener("click", () => this.submit());
      actions.append(submit, helpTip("When you are satisfied with every label on this image, submit it. Someone else, working in Review mode, then approves it or returns it with a comment. You can still withdraw it while it waits."));
    }
    clear(this.top).append(
      h("a", { class: "icon-btn", href: `#/p/${this.project.id}`, title: "Back to the project", "aria-label": "Back to the project" }, icon("back")),
      h("div", { class: "ws-title" }, h("strong", { title: img.original_filename }, img.stem), statusBadge(img.status),
        h("span", { class: "muted small" }, `${img.width} × ${img.height}`, idx >= 0 ? ` · ${idx + 1} of ${this.order.length}` : "")),
      this.saveState, h("div", { class: "spacer" }), actions, h("div", { class: "nav-pair" }, prev, next));
  }

  updateSaveState() {
    if (!this.saveState) return;
    const s = this.saveState;
    const unsaved = this.changeCount !== this.savedCount;
    s.className = "save-state";
    if (!this.editable) {
      s.textContent = "View only";
      s.classList.add("muted");
    } else if (this.saveError) {
      s.replaceChildren(icon("x", 14), `Not saved: ${this.saveError}`);
      s.classList.add("save-error");
    } else if (this.saving) {
      s.textContent = "Saving…";
    } else if (unsaved) {
      s.textContent = "Unsaved changes";
      s.classList.add("save-pending");
    } else {
      s.replaceChildren(icon("check", 14), this.lastSaved ? `Saved ${fmtRelative(this.lastSaved)}` : "No changes");
      s.classList.add("save-ok");
    }
  }

  // ------------------------------------------------------------------ toolbar
  renderToolbar() {
    clear(this.toolbar);
    this.toolButtons = {};
    for (const [name, t] of Object.entries(TOOLS)) {
      const disabled = !this.editable && name !== "pan";
      const b = h("button", { class: `tool ${this.editor.tool === name ? "active" : ""}`, title: `${t.label} (${t.key})`, "aria-label": t.label, disabled },
        icon(t.icon, 20), h("span", { class: "tool-key" }, t.key));
      b.addEventListener("click", () => this.setTool(name));
      this.toolButtons[name] = b;
      this.toolbar.append(b);
    }
    const undo = h("button", { class: "tool", title: "Undo (Ctrl+Z)", "aria-label": "Undo", disabled: !this.editable }, icon("undo", 20));
    undo.addEventListener("click", () => this.editor.undo());
    const redo = h("button", { class: "tool", title: "Redo (Ctrl+Y)", "aria-label": "Redo", disabled: !this.editable }, icon("redo", 20));
    redo.addEventListener("click", () => this.editor.redo());
    const fit = h("button", { class: "tool", title: "Fit image to window (F)", "aria-label": "Fit" }, icon("fit", 20));
    fit.addEventListener("click", () => this.editor.fit());
    this.zoomLabel = h("div", { class: "zoom-label", title: "Zoom. Scroll to zoom at the cursor; + and - also work." }, `${Math.round(this.editor.scale * 100)}%`);
    const keys = h("button", { class: "tool", title: "Keyboard shortcuts (?)", "aria-label": "Keyboard shortcuts" }, icon("keyboard", 20));
    keys.addEventListener("click", showShortcuts);
    const panel = h("button", { class: "tool", title: "Show or hide the side panel (more room for the image)", "aria-label": "Toggle side panel" }, icon("panel", 20));
    panel.addEventListener("click", () => {
      const collapsed = this.root.classList.toggle("side-collapsed");
      savePref("sideCollapsed", collapsed);
    });
    this.root.classList.toggle("side-collapsed", Boolean(app.prefs.sideCollapsed));
    this.toolbar.append(h("div", { class: "tool-sep" }), undo, redo, h("div", { class: "tool-sep" }), fit, this.zoomLabel, h("div", { class: "spacer" }), panel, keys);
  }

  setTool(name) {
    if (!this.editable && name !== "pan") name = "pan";
    this.editor.setTool(name);
    if (this.editable) {
      this.prefs.tool = name;
      savePref("tool", name);
    }
    for (const [k, b] of Object.entries(this.toolButtons || {})) b.classList.toggle("active", k === name);
    this.renderToolOptions(this.editor.thresholdState);
    this.renderHint();
  }

  renderHint(extra = null) {
    const t = TOOLS[this.editor.tool];
    this.hintText = this.editable ? `${t.label}: ${t.hint}` : "View only: drag to pan, scroll to zoom. Press H to hide labels.";
    this.drawHint(extra);
  }

  drawHint(hover) {
    const parts = [h("span", { class: "hint-text" }, this.hintText)];
    if (hover) {
      const cls = this.classes.find((c) => c.index === hover.label);
      parts.push(h("span", { class: "hint-pos mono" }, `x ${hover.x}  y ${hover.y}`, hover.grey !== null ? `  grey ${hover.grey}` : ""),
        h("span", { class: "hint-class" }, cls ? h("span", { class: "swatch", style: { background: cls.color } }) : null, cls ? cls.name : "background"));
    }
    clear(this.hint).append(...parts);
  }

  showHover(info) {
    this.drawHint(info);
  }

  // ------------------------------------------------------------------ side panel
  renderSide() {
    clear(this.side);
    this.side.append(this.classesSection(), this.toolOptionsSection(), this.viewSection());
    if (this.editable) this.side.append(this.cleanupSection());
    this.side.append(this.maskSourceSection(), this.historySection(), this.guidelinesSection());
    this.renderToolOptions(this.editor.thresholdState);
  }

  section(title, help, ...children) {
    return h("section", { class: "side-section" }, h("h3", {}, title, help ? helpTip(help) : null), ...children);
  }

  classesSection() {
    this.classList = h("div", { class: "class-list", role: "listbox", "aria-label": "Classes" });
    this.classes.forEach((c, k) => {
      const item = h("button", { class: "class-item", role: "option", title: c.description || c.name, "data-index": c.index },
        h("span", { class: "swatch big", style: { background: c.color } }),
        h("span", { class: "class-name" }, c.name),
        h("span", { class: "class-cov mono small", "data-cov": c.index }, ""),
        k < 9 ? h("kbd", {}, k + 1) : null);
      item.addEventListener("click", () => this.selectClass(c.index));
      this.classList.append(item);
    });
    this.classDesc = h("p", { class: "small muted class-desc" });
    const protect = h("input", { type: "checkbox" });
    protect.checked = this.editor.protect;
    protect.addEventListener("change", () => {
      this.editor.protect = protect.checked;
      savePref("protect", protect.checked);
    });
    const sec = this.section("Classes",
      "Choose what you are labelling. Keys 1-9 select a class; Alt+click on the image picks the class under the cursor. Background (unlabelled) is 0 and is what the Eraser produces.",
      this.classList, this.classDesc,
      this.editable ? h("label", { class: "check small" }, protect, "Protect other classes ",
        helpTip("When ticked, painting only changes unlabelled pixels (and pixels of the selected class), and erasing only removes the selected class. Use it to touch up one class without damaging a neighbouring one.")) : null);
    setTimeout(() => this.selectClass(this.editor.activeClass), 0);
    return sec;
  }

  selectClass(index) {
    if (!this.classes.some((c) => c.index === index)) return;
    this.editor.activeClass = index;
    for (const el of this.classList.children) el.classList.toggle("active", Number(el.dataset.index) === index);
    const c = this.classes.find((k) => k.index === index);
    this.classDesc.textContent = c && c.description ? c.description : "";
    if (this.editor.thresholdState) this.editor.updateThreshold({});
    this.editor.requestDraw();
  }

  updateCoverage() {
    clearTimeout(this._covTimer);
    this._covTimer = setTimeout(() => {
      if (!this.editor.map) return;
      const counts = this.editor.map.counts();
      const total = this.image.width * this.image.height;
      this.counts = counts;
      for (const el of this.side.querySelectorAll("[data-cov]")) {
        const n = counts[Number(el.dataset.cov)];
        el.textContent = n ? fmtPct(n / total, n / total < 0.001 ? 3 : 1) : "";
        el.title = `${n.toLocaleString()} pixels`;
      }
    }, 150);
  }

  toolOptionsSection() {
    this.toolOptions = h("div", { class: "tool-options" });
    return this.section("Tool options", null, this.toolOptions);
  }

  // A slider with a number box beside it: drag for speed, type for an exact value. Both stay
  // in step. A typed value is applied on Enter or when the box loses focus (out-of-range values
  // are clamped, anything unreadable reverts); Enter and Esc hand the keyboard back to the image
  // so tool shortcuts work again straight away.
  numberSlider({ label, name, min, max, value, unit = "", help = null, onChange }) {
    const slider = h("input", { type: "range", min, max, step: 1, value, "aria-label": name });
    const box = h("input", { type: "number", min, max, step: 1, value, class: "num", "aria-label": unit ? `${name} in ${unit === "px" ? "pixels" : unit}` : `${name} value` });
    const set = (v) => {
      slider.value = v;
      if (document.activeElement !== box) box.value = v;
    };
    slider.addEventListener("input", () => {
      box.value = slider.value;
      onChange(Number(slider.value));
    });
    const commit = () => {
      const typed = box.value.trim() === "" ? NaN : Number(box.value);
      if (!Number.isFinite(typed)) {
        box.value = slider.value;
        return;
      }
      const v = clampInt(typed, min, max);
      box.value = v;
      slider.value = v;
      onChange(v);
    };
    box.addEventListener("change", commit);
    box.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== "Escape") return;
      e.preventDefault();
      if (e.key === "Enter") commit();
      else box.value = slider.value;
      this.editor.canvas.focus({ preventScroll: true });
    });
    const el = h("div", { class: "slider" }, h("span", {}, label, help ? [" ", helpTip(help)] : null), slider,
      h("span", { class: "slider-num" }, box, unit ? h("span", { class: "muted" }, unit) : null));
    return { el, set };
  }

  renderToolOptions(thresholdState) {
    if (!this.toolOptions) return;
    // Every change to a preview re-reports it; update the open panel in place so a slider
    // being dragged or a number being typed is not replaced under the pointer.
    const panel = this.thresholdPanel;
    if (thresholdState && panel && panel.state === thresholdState && panel.el.isConnected) return panel.update();
    this.thresholdPanel = null;
    const box = clear(this.toolOptions);
    const tool = this.editor.tool;
    if (!this.editable) {
      box.append(h("p", { class: "small muted" }, "Tools are disabled while viewing."));
      return;
    }
    if (tool === "brush" || tool === "eraser") {
      this.sizeControl = this.numberSlider({
        label: "Diameter", name: "Brush diameter", min: BRUSH_MIN, max: BRUSH_MAX, value: this.brushDiameter(), unit: "px",
        help: "Brush and eraser share this size, in image pixels (not screen pixels). A 1 px brush changes exactly one pixel. [ and ] make it smaller or larger; Shift+[ and Shift+] halve or double it.",
        onChange: (d) => this.setBrush(d),
      });
      box.append(this.sizeControl.el, h("p", { class: "small muted" }, "Type a size or use [ and ]. Zoom in for fine edges."));
    } else if (tool === "wand") {
      this.toleranceControl = this.numberSlider({
        label: "Tolerance", name: "Tolerance", min: TOLERANCE_MIN, max: TOLERANCE_MAX, value: this.editor.tolerance,
        help: "The wand takes every connected pixel at least as dark as the one you clicked (or as bright, for a bright feature). Tolerance allows that many grey levels (0-255) of extra slack at faint edges. Too much spreads into the matrix; too little misses faint tips. [ and ] change it by 1, with Shift by 10.",
        onChange: (v) => this.setTolerance(v),
      });
      box.append(this.toleranceControl.el);
    } else if (tool === "threshold" || tool === "polythreshold") {
      const polygon = tool === "polythreshold";
      if (!thresholdState) {
        box.append(h("p", { class: "small" }, polygon
          ? "Click corners around a region with dark (or bright) features and close the outline (double-click, Enter or the first corner). A threshold is chosen automatically from the pixels inside it (Otsu's method) and previewed; nothing outside the outline is changed."
          : "Drag a box over a region with dark (or bright) features. A threshold is chosen automatically (Otsu's method) and previewed in yellow-outlined colour."));
        return;
      }
      const t = thresholdState;
      const where = t.shape === "polygon" ? "outline" : "box";
      const threshold = this.numberSlider({
        label: "Threshold", name: "Threshold", min: 0, max: 255, value: t.threshold,
        help: `Automatic (Otsu) value for this ${where}: ${t.otsu}. Move it until the preview matches the features. [ and ] nudge it by 1, with Shift by 10.` +
          (t.shape === "polygon" ? " Only the pixels inside the outline decide the automatic value and can be labelled; a feature crossing the outline is cut along it." : ""),
        onChange: (v) => this.editor.updateThreshold({ threshold: v }),
      });
      const dark = h("select", { "aria-label": "Feature brightness" }, h("option", { value: "dark" }, "Features darker than threshold"), h("option", { value: "bright" }, "Features brighter than threshold"));
      dark.addEventListener("change", () => this.editor.updateThreshold({ dark: dark.value === "dark" }));
      const speck = h("input", { type: "number", min: 1, max: 5000, value: t.minSize, class: "num", "aria-label": "Ignore specks under (pixels)" });
      speck.addEventListener("change", () => this.editor.updateThreshold({ minSize: Math.max(1, Number(speck.value) || 1) }));
      const count = h("p", { class: "small" });
      const warning = h("p", { class: "alert alert-warn small", role: "status" },
        `Most of the ${where} is selected. The automatic threshold needs some background to compare with: include some surrounding matrix, or set the threshold by hand.`);
      const apply = h("button", { class: "btn btn-primary btn-small" }, "Apply (Enter)");
      apply.addEventListener("click", () => this.applyThreshold());
      const cancel = h("button", { class: "btn btn-small" }, "Cancel (Esc)");
      cancel.addEventListener("click", () => this.editor.cancelThreshold());
      const el = h("div", { class: "threshold-panel" }, threshold.el, dark, h("label", { class: "inline-field small" }, "Ignore specks under", speck, "px"),
        count, warning, h("div", { class: "row" }, apply, cancel));
      const update = () => {
        threshold.set(t.threshold);
        dark.value = t.dark ? "dark" : "bright";
        if (document.activeElement !== speck) speck.value = t.minSize;
        count.replaceChildren(h("strong", {}, t.count.toLocaleString()), ` of ${t.area.toLocaleString()} pixels selected in the ${where}.`);
        warning.hidden = !(t.area && t.count / t.area > MOSTLY_SELECTED);
      };
      update();
      box.append(el);
      this.thresholdPanel = { state: t, el, update };
    } else if (tool === "polygon") {
      box.append(h("p", { class: "small" }, "Click corners around a feature. Close with a double-click, Enter, or by clicking the first (yellow) corner. Backspace removes a corner; Esc cancels."));
    } else if (tool === "lasso") {
      box.append(h("p", { class: "small" }, "Hold the mouse button and draw around a region. Everything inside is filled when you release."));
    } else if (tool === "fill") {
      box.append(h("p", { class: "small" }, "Draw a closed outline with the brush, then click inside it with Fill to fill the enclosed area."));
    } else {
      box.append(h("p", { class: "small" }, "Drag to move around. Scroll to zoom at the cursor."));
    }
  }

  brushDiameter() {
    return Math.round(this.editor.brushSize * 2);
  }

  setBrush(diameter) {
    const d = clampInt(diameter, BRUSH_MIN, BRUSH_MAX);
    this.editor.brushSize = d / 2;
    savePref("brushDiameter", d);
    if (this.sizeControl && this.sizeControl.el.isConnected) this.sizeControl.set(d);
    this.editor.requestDraw();
  }

  setTolerance(value) {
    const v = clampInt(value, TOLERANCE_MIN, TOLERANCE_MAX);
    this.editor.tolerance = v;
    savePref("tolerance", v);
    if (this.toleranceControl && this.toleranceControl.el.isConnected) this.toleranceControl.set(v);
  }

  // [ and ] change the active tool's main value: brush/eraser diameter, wand tolerance, or
  // the threshold being previewed. Shift makes the step big.
  nudgeToolValue(direction, big) {
    const ed = this.editor;
    if (!this.editable) return;
    if (ed.thresholdState) {
      ed.updateThreshold({ threshold: clampInt(ed.thresholdState.threshold + direction * (big ? 10 : 1), 0, 255) });
    } else if (ed.tool === "brush" || ed.tool === "eraser") {
      const d = this.brushDiameter();
      this.setBrush(big ? (direction > 0 ? d * 2 : d / 2) : d + direction * Math.max(1, Math.round(d * 0.15)));
    } else if (ed.tool === "wand") {
      this.setTolerance(ed.tolerance + direction * (big ? 10 : 1));
    }
  }

  applyThreshold() {
    const n = this.editor.applyThreshold();
    toast(n ? `Labelled ${n.toLocaleString()} pixels.` : "Nothing changed (the selected pixels were already labelled or protected).", "info");
  }

  viewSection() {
    const ed = this.editor;
    const opacity = h("input", { type: "range", min: 0, max: 100, value: Math.round(ed.opacity * 100), "aria-label": "Label opacity" });
    opacity.addEventListener("input", () => {
      ed.opacity = Number(opacity.value) / 100;
      savePref("opacity", ed.opacity);
      ed.requestDraw();
    });
    this.showLabels = h("input", { type: "checkbox", checked: ed.showOverlay });
    this.showLabels.addEventListener("change", () => this.toggleOverlay(this.showLabels.checked));
    this.outlineBox = h("input", { type: "checkbox", checked: ed.outline });
    this.outlineBox.addEventListener("change", () => ed.setOutline(this.outlineBox.checked));
    const adj = (key, min, max) => {
      const s = h("input", { type: "range", min, max, value: ed.adjust[key], "aria-label": key });
      s.addEventListener("input", () => {
        ed.adjust[key] = Number(s.value);
        ed.requestDraw();
      });
      return s;
    };
    const brightness = adj("brightness", 30, 250);
    const contrast = adj("contrast", 30, 300);
    const invert = h("input", { type: "checkbox" });
    invert.addEventListener("change", () => {
      ed.adjust.invert = invert.checked;
      ed.requestDraw();
    });
    const reset = h("button", { class: "btn btn-small" }, "Reset");
    reset.addEventListener("click", () => {
      ed.adjust = { brightness: 100, contrast: 100, invert: false };
      brightness.value = 100;
      contrast.value = 100;
      invert.checked = false;
      ed.requestDraw();
    });
    return this.section("View", "These settings change only what you see on screen. They never change the image or the labels.",
      h("label", { class: "check" }, this.showLabels, "Show labels (H)"),
      h("label", { class: "check" }, this.outlineBox, "Outlines only (O)"),
      h("label", { class: "slider" }, h("span", {}, "Label opacity"), opacity),
      h("label", { class: "slider" }, h("span", {}, "Brightness"), brightness),
      h("label", { class: "slider" }, h("span", {}, "Contrast"), contrast),
      h("div", { class: "row" }, h("label", { class: "check" }, invert, "Invert"), h("div", { class: "spacer" }), reset));
  }

  toggleOverlay(on) {
    this.editor.showOverlay = on;
    if (this.showLabels) this.showLabels.checked = on;
    this.editor.requestDraw();
  }

  cleanupSection() {
    const specks = h("input", { type: "number", min: 1, value: 20, class: "num", "aria-label": "Speck size" });
    const holes = h("input", { type: "number", min: 1, value: 50, class: "num", "aria-label": "Hole size" });
    const run = (kind, input) => {
      const b = h("button", { class: "btn btn-small" }, "Run");
      b.addEventListener("click", () => {
        const c = this.classes.find((k) => k.index === this.editor.activeClass);
        const r = this.editor.cleanup(kind, Math.max(1, Number(input.value) || 1));
        toast(kind === "specks" ? `Removed ${r.regions} speck(s) of ${c.name} (${r.removed} px). Ctrl+Z undoes.`
          : `Filled ${r.regions} hole(s) in ${c.name} (${r.filled} px). Ctrl+Z undoes.`, "info");
      });
      return b;
    };
    return this.section("Clean up", "Tidy the selected class over the whole image. Specks are isolated blobs smaller than the size; holes are unlabelled gaps completely surrounded by the class. Both are undoable.",
      h("div", { class: "inline-field small" }, "Remove specks under", specks, "px", run("specks", specks)),
      h("div", { class: "inline-field small" }, "Fill holes under", holes, "px", run("holes", holes)));
  }

  historySection() {
    const img = this.image;
    const list = h("div", { class: "history" });
    if (!img.versions.length) list.append(h("p", { class: "small muted" }, "No versions yet. Submitting creates version 1."));
    for (const v of img.versions) {
      const item = h("div", { class: "version" },
        h("div", { class: "version-head" }, h("strong", {}, `v${v.number}`), h("span", { class: `badge vstatus-${v.status}` }, v.status.replace("_", " ")),
          h("span", { class: "muted small" }, fmtDate(v.created_at))),
        h("div", { class: "small" }, v.kind === "reviewer_edit" ? "Corrected in review by " : "By ", v.created_by),
        v.note ? h("div", { class: "small" }, "Note: ", h("em", {}, v.note)) : null,
        v.reviewed_by ? h("div", { class: "small" }, `${v.status === "approved" ? "Approved" : "Reviewed"} by ${v.reviewed_by}`, v.review_comment ? h("span", {}, ": “", h("em", {}, v.review_comment), "”") : null) : null);
      const acts = h("div", { class: "row small" });
      const dl = h("a", { href: `api/v1/images/${img.id}/mask.png?style=colour&version=${v.number}`, class: "btn btn-small" }, icon("download", 12), "Mask");
      acts.append(dl);
      if (this.editable) {
        const restore = h("button", { class: "btn btn-small", title: "Replace the current working labels with this version (undo is not possible, but the version stays in history)" }, "Restore");
        restore.addEventListener("click", () => this.restore(v.number));
        acts.append(restore);
      }
      item.append(acts);
      list.append(item);
    }
    const info = h("dl", { class: "info small" },
      h("dt", {}, "File"), h("dd", {}, img.original_filename),
      h("dt", {}, "Size"), h("dd", {}, `${img.width} × ${img.height} px`),
      h("dt", {}, "Split"), h("dd", {}, img.split),
      img.working_updated_by ? [h("dt", {}, "Last saved"), h("dd", {}, `${img.working_updated_by.split("@")[0]}, ${fmtRelative(img.working_updated_at)}`)] : null,
      img.working_origin && img.working_origin !== "edited in browser" ? [h("dt", {}, "Origin"), h("dd", {}, img.working_origin)] : null,
      img.conversion_note ? [h("dt", {}, "Display"), h("dd", {}, img.conversion_note)] : null);
    return this.section("Image & history", "Every submission is kept as an immutable version with its review decision, so the history of the ground truth can always be traced.",
      info, h("a", { href: `api/v1/images/${img.id}/original`, class: "small" }, "Download original file"), list);
  }

  // Where this image's labels came from, and the way in to importing an existing mask.
  maskSourceSection() {
    const img = this.image;
    const imported = img.mask_source === "imported";
    const rows = [];
    if (imported) {
      rows.push(h("p", { class: "small" },
        h("strong", {}, "Imported mask, corrected here."),
        img.mask_source_file ? ` From ${img.mask_source_file}.` : ""));
      const info = h("dl", { class: "info small" },
        img.mask_source_tool ? [h("dt", {}, "Made with"), h("dd", {}, img.mask_source_tool)] : null,
        img.mask_import ? [h("dt", {}, "Read as"), h("dd", {}, importSummary(img.mask_import))] : null,
        img.mask_imported_by ? [h("dt", {}, "Imported by"), h("dd", {}, `${img.mask_imported_by.split("@")[0]}, ${fmtRelative(img.mask_imported_at)}`)] : null);
      if (info.children.length) rows.push(info);
      if (img.mask_source_remarks) rows.push(h("pre", { class: "guidelines" }, img.mask_source_remarks));
    } else {
      rows.push(h("p", { class: "small muted" }, "Drawn here from scratch. If you already have a mask for this image from another tool, import it and correct it instead."));
    }
    if (this.editable) {
      const btn = h("button", { class: "btn btn-small", type: "button" }, icon("download", 16),
        imported ? "Replace with another mask…" : "Import a mask…");
      btn.addEventListener("click", () => this.importMaskDialog());
      const acts = h("div", { class: "card-actions" }, btn);
      if (imported) {
        const edit = h("button", { class: "btn btn-small", type: "button" }, "Edit remarks…");
        edit.addEventListener("click", () => this.editMaskRemarksDialog());
        acts.append(edit);
      }
      rows.push(acts);
    }
    return this.section("Mask source",
      "Says whether these labels were drawn here or started as a mask made by another tool. The answer travels with every submitted version into the export manifest, so anyone training on this dataset can tell hand-drawn ground truth from corrected machine output.",
      ...rows);
  }

  importMaskDialog() {
    const input = h("input", { type: "file", accept: ".png,.tif,.tiff,.bmp" });
    const controls = maskImportControls(this.classes);
    const tool = h("input", { type: "text", maxlength: "200", value: this.image.mask_source_tool || "", placeholder: "e.g. HydrideSegmentation v2.3, ImageJ threshold, in-house script" });
    const remarks = h("textarea", { rows: "3", maxlength: "4000", placeholder: "e.g. Model run of 2026-09-10; misses faint hydride tips near grain boundaries." }, this.image.mask_source_remarks || "");
    const preview = h("div", { class: "mask-preview", "aria-live": "polite" });
    const result = h("div");
    let analysis = null;
    const refresh = previewer(async () => {
      if (!input.files.length) return null;
      const fd = new FormData();
      fd.append("file", input.files[0], input.files[0].name);
      controls.append(fd);
      return (await api.form(`api/v1/images/${this.image.id}/mask-import/analyze`, fd)).analysis;
    }, (found, err) => {
      analysis = found;
      clear(preview);
      clear(result);
      if (err) preview.append(h("div", { class: "alert alert-error" }, err.message));
      else if (found) preview.append(analysisView(found, { onUseMode: (m, t) => controls.useMode(m, t) }));
      controls.setConfirmation(found && found.ok && found.requires_confirmation ? found.confirmation : null);
    });
    input.addEventListener("change", refresh);
    controls.onChange(refresh);
    const body = h("div", { class: "stack" },
      h("p", {}, "Load a mask you already have for ", h("strong", {}, this.image.stem), " and correct it here, instead of labelling from scratch."),
      h("ul", { class: "compact small" },
        h("li", {}, "It must be exactly ", h("strong", {}, `${this.image.width} × ${this.image.height}`), " pixels. A mask of any other size is refused rather than resized, because resizing would change the ground truth."),
        h("li", {}, "After you choose the file, the preview says what was detected and which class numbers will be stored. Nothing changes until you press Import."),
        h("li", {}, "This replaces the labels currently on screen. Earlier submitted versions stay in the history.")),
      field("Mask file", input),
      controls.fields,
      preview,
      controls.confirmBox,
      field("Which tool made this mask?", tool, "Recorded with the image and written into the export manifest."),
      field("Remarks (optional)", remarks, "Anything worth knowing: the model version, settings, known weaknesses. Kept with the image and exported."),
      result);
    modal({
      title: "Import an existing mask",
      body,
      wide: true,
      actions: [
        { label: "Cancel" },
        {
          label: "Import",
          kind: "primary",
          onClick: async () => {
            if (!input.files.length) {
              toast("Choose a mask file first.", "info");
              return true; // keep open
            }
            if (analysis && !analysis.ok) {
              clear(result).append(h("div", { class: "alert alert-error" }, "Nothing was imported. ", analysis.error));
              return true;
            }
            if (analysis && analysis.requires_confirmation && !controls.confirmed) {
              clear(result).append(h("div", { class: "alert alert-warn" }, "Check the preview and tick the confirmation above, then press Import."));
              return true;
            }
            if (this.hasUnsaved()) await this.saveNow(false);
            const fd = new FormData();
            fd.append("file", input.files[0], input.files[0].name);
            controls.append(fd, { withConfirm: true });
            fd.append("source_tool", tool.value);
            fd.append("remarks", remarks.value);
            try {
              const res = await api.form(`api/v1/images/${this.image.id}/mask-import`, fd);
              this.image = res.image;
              this.editor.replaceLabels(await this.loadLabels());
              this.changeCount = this.savedCount = 0;
              this.updateCoverage();
              this.renderTop();
              this.renderSide();
              toast(res.message, "success");
              return false; // close the dialog
            } catch (err) {
              clear(result).append(h("div", { class: "alert alert-error" }, err.message));
              return true; // keep it open so the message is readable
            }
          },
        },
      ],
    });
  }

  editMaskRemarksDialog() {
    const tool = h("input", { type: "text", maxlength: "200", value: this.image.mask_source_tool || "" });
    const remarks = h("textarea", { rows: "4", maxlength: "4000" }, this.image.mask_source_remarks || "");
    modal({
      title: "Remarks about the imported mask",
      body: h("div", { class: "stack" },
        field("Which tool made this mask?", tool),
        field("Remarks", remarks, "Kept with the image and written into the export manifest.")),
      actions: [
        { label: "Cancel" },
        {
          label: "Save",
          kind: "primary",
          onClick: async () => {
            try {
              const res = await api.patch(`api/v1/images/${this.image.id}/mask-source`,
                { source_tool: tool.value, remarks: remarks.value });
              this.image = res.image;
              this.renderSide();
              toast("Remarks saved.", "success");
              return false; // close the dialog
            } catch (err) {
              toast(err.message, "error");
              return true; // keep it open so the text is not lost
            }
          },
        },
      ],
    });
  }

  guidelinesSection() {
    const open = app.prefs.guidelinesOpen !== false;
    const det = h("details", { class: "side-section guidelines-box", open },
      h("summary", {}, "Annotation guidelines"),
      this.project.guidelines ? h("pre", { class: "guidelines" }, this.project.guidelines) : h("p", { class: "small muted" }, "This project has no written guidelines."));
    det.addEventListener("toggle", () => savePref("guidelinesOpen", det.open));
    return det;
  }

  // ------------------------------------------------------------------ saving
  onEdit() {
    this.changeCount++;
    this.saveError = null;
    this.updateSaveState();
    this.updateCoverage();
    this.scheduleSave(AUTOSAVE_DELAY);
  }

  scheduleSave(delay) {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => this.saveNow(false), delay);
  }

  async saveNow(manual) {
    clearTimeout(this._saveTimer);
    if (!this.editable) return false;
    if (this.saving) {
      await this.saving;
      if (this.changeCount === this.savedCount) return true;
    }
    if (this.changeCount === this.savedCount) {
      if (manual) toast("Everything is already saved.", "info", 2000);
      return true;
    }
    const target = this.changeCount;
    const snapshot = this.editor.map.data.slice();
    this.saving = (async () => {
      this.updateSaveState();
      try {
        const res = await putLabels(this.image.id, snapshot, this.revision);
        this.revision = res.revision;
        this.savedCount = target;
        this.lastSaved = new Date().toISOString();
        this.saveError = null;
        if (res.status !== this.image.status) {
          this.image.status = res.status;
          this.renderTop();
        }
        return true;
      } catch (err) {
        this.saveError = err.status === 409 ? "someone else saved a newer version" : err.status === 423 ? "editing session ended" : err.message;
        if (err.status === 423) this.loseLock(err.message);
        else if (err.status === 409) {
          modal({
            title: "This image changed elsewhere",
            body: h("p", {}, err.message),
            actions: [{ label: "Keep my view" }, { label: "Load the latest version", kind: "primary", onClick: async () => this.reloadLatest() }],
          });
        } else if (manual) toast(`Not saved: ${err.message}`, "error");
        else this.scheduleSave(10000);
        return false;
      } finally {
        this.saving = null;
        this.updateSaveState();
      }
    })();
    return this.saving;
  }

  async reloadLatest() {
    this.image = (await api.get(`api/v1/images/${this.image.id}`)).image;
    this.editor.replaceLabels(await this.loadLabels());
    this.changeCount = this.savedCount = 0;
    this.saveError = null;
    this.updateCoverage();
    this.renderTop();
    this.renderSide();
  }

  hasUnsaved() {
    return this.editable && this.changeCount !== this.savedCount;
  }

  // ------------------------------------------------------------------ workflow actions
  async submit() {
    if (!(await this.saveNow(false)) && this.hasUnsaved()) {
      toast("Save failed, so nothing was submitted. Fix the problem shown at the top first.", "error");
      return;
    }
    const counts = this.editor.map.counts();
    const labelled = this.editor.map.data.length - counts[0];
    const note = h("textarea", { rows: 3, placeholder: "Optional: anything the person reviewing it should know (unclear regions, doubts)" });
    const summary = h("ul", { class: "compact small" }, this.classes.map((c) => h("li", {}, h("span", { class: "swatch", style: { background: c.color } }), ` ${c.name}: `,
      h("strong", {}, fmtPct(counts[c.index] / this.editor.map.data.length, 2)), ` (${counts[c.index].toLocaleString()} px)`)));
    modal({
      title: "Submit for review",
      body: h("div", { class: "stack" },
        labelled === 0 ? h("div", { class: "alert alert-warn" }, "No pixel is labelled. That is correct only if this image truly contains none of the classes; say so in the note.") : null,
        h("p", {}, "Labelled area on this image:"), summary,
        h("label", { class: "field" }, h("span", { class: "field-label" }, "Note for the person who reviews it"), note),
        h("p", { class: "small muted" }, "After submitting, the image is read-only for you until it is reviewed. You can withdraw it while it waits.")),
      actions: [{ label: "Keep working" }, {
        label: "Submit",
        kind: "primary",
        onClick: async () => {
          try {
            await api.post(`api/v1/images/${this.image.id}/submit`, { note: note.value });
            this.haveLock = false;
            clearInterval(this.heartbeat);
            toast("Submitted for review. Opening the next image…", "success");
            this.afterDecision("annotate");
          } catch (err) {
            toast(err.message, "error");
            return true;
          }
          return false;
        },
      }],
    });
  }

  async approve() {
    if (!(await this.saveNow(false)) && this.hasUnsaved()) return toast("Save failed; nothing was approved.", "error");
    const pending = this.image.versions.find((v) => v.status === "submitted");
    const edited = this.savedCount > 0 || (pending && this.image.working_revision !== this.revision);
    const comment = h("textarea", { rows: 2, placeholder: "Optional comment for the person who submitted it" });
    modal({
      title: "Approve as ground truth",
      body: h("div", { class: "stack" },
        edited ? h("div", { class: "alert alert-info" }, "You corrected the labels. Your corrected version is approved as a new version; the original submission stays in the history.")
          : h("p", {}, "The submitted labels become ground truth and are included in approved exports."),
        h("label", { class: "field" }, h("span", { class: "field-label" }, "Comment"), comment)),
      actions: [{ label: "Cancel" }, {
        label: "Approve",
        kind: "success",
        onClick: async () => {
          try {
            await api.post(`api/v1/images/${this.image.id}/review`, { decision: "approve", comment: comment.value });
            this.haveLock = false;
            clearInterval(this.heartbeat);
            await api.del(`api/v1/images/${this.image.id}/lock`).catch(() => {});
            toast("Approved. Opening the next submission…", "success");
            this.afterDecision("review");
          } catch (err) {
            toast(err.message, "error");
            return true;
          }
          return false;
        },
      }],
    });
  }

  async requestChanges() {
    if (this.hasUnsaved()) await this.saveNow(false);
    const comment = h("textarea", { rows: 4, placeholder: "What should be changed? Be specific, e.g. 'The platelet at the top right is missing its tip.'", required: true });
    modal({
      title: "Request changes",
      body: h("div", { class: "stack" }, h("p", {}, "The image goes back to the person who submitted it, with your comment. They fix it in Annotate mode and submit again."),
        h("label", { class: "field" }, h("span", { class: "field-label" }, "Comment (required)"), comment)),
      actions: [{ label: "Cancel" }, {
        label: "Send back",
        kind: "warn",
        onClick: async () => {
          if (!comment.value.trim()) {
            toast("Please write what should change.", "error");
            return true;
          }
          try {
            await api.post(`api/v1/images/${this.image.id}/review`, { decision: "request_changes", comment: comment.value });
            this.haveLock = false;
            clearInterval(this.heartbeat);
            await api.del(`api/v1/images/${this.image.id}/lock`).catch(() => {});
            toast("Returned with your comment. Opening the next submission…", "success");
            this.afterDecision("review");
          } catch (err) {
            toast(err.message, "error");
            return true;
          }
          return false;
        },
      }],
    });
  }

  async afterDecision(mode) {
    this.changeCount = this.savedCount;
    const url = `api/v1/projects/${this.project.id}/next?mode=${mode}&after=${this.image.id}`;
    try {
      const { image_id } = await api.get(url);
      if (image_id && image_id !== this.image.id) return go(`#/p/${this.project.id}/i/${image_id}`);
    } catch (_) {
      /* fall through */
    }
    toast(mode === "review" ? "No more submissions are waiting. Well done!" : "No more images need work right now.", "success", 6000);
    go(`#/p/${this.project.id}`);
  }

  async restore(number) {
    const ok = await confirmDialog(`Restore version ${number}?`, "The current working labels are replaced by that version. The version history itself is not changed.", { confirmLabel: "Restore" });
    if (!ok) return;
    if (this.hasUnsaved()) await this.saveNow(false);
    try {
      const res = await api.post(`api/v1/images/${this.image.id}/restore/${number}`);
      this.image = res.image;
      this.editor.replaceLabels(await this.loadLabels());
      this.changeCount = this.savedCount = 0;
      this.updateCoverage();
      this.renderTop();
      this.renderSide();
      toast(`Version ${number} restored into the working copy.`, "success");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  step(delta) {
    const idx = this.order.indexOf(this.image.id) + delta;
    if (idx >= 0 && idx < this.order.length) go(`#/p/${this.project.id}/i/${this.order[idx]}`);
  }

  // ------------------------------------------------------------------ keyboard
  onKey(e) {
    if (isTyping(e) || document.querySelector(".modal-backdrop")) return;
    const ed = this.editor;
    const ctrl = e.ctrlKey || e.metaKey;
    const key = e.key;
    if (ctrl && (key === "z" || key === "Z")) {
      e.preventDefault();
      if (!this.editable) return;
      if (e.shiftKey) ed.redo();
      else ed.undo();
      return;
    }
    if (ctrl && (key === "y" || key === "Y")) {
      e.preventDefault();
      if (this.editable) ed.redo();
      return;
    }
    if (ctrl && (key === "s" || key === "S")) {
      e.preventDefault();
      this.saveNow(true);
      return;
    }
    if (ctrl && key === "ArrowRight") {
      e.preventDefault();
      return this.step(1);
    }
    if (ctrl && key === "ArrowLeft") {
      e.preventDefault();
      return this.step(-1);
    }
    if (ctrl || e.altKey) return;
    if (key === "Enter") {
      if (ed.poly.length) ed.closePolygon(e.shiftKey);
      else if (ed.thresholdState) this.applyThreshold();
      return;
    }
    if (key === "Escape") {
      if (ed.poly.length) ed.cancelPolygon();
      if (ed.thresholdState) ed.cancelThreshold();
      return;
    }
    if (key === "Backspace" && ed.poly.length) {
      e.preventDefault();
      ed.popPolygonPoint();
      return;
    }
    // The physical [ and ] keys, so layouts where the characters need AltGr (German, French,
    // Nordic) work too; the characters themselves (and { }) cover remapped keyboards.
    const nudge = e.code === "BracketLeft" || key === "[" || key === "{" ? -1 : e.code === "BracketRight" || key === "]" || key === "}" ? 1 : 0;
    if (nudge) {
      e.preventDefault();
      return this.nudgeToolValue(nudge, e.shiftKey || key === "{" || key === "}");
    }
    const lower = key.toLowerCase();
    const tool = Object.entries(TOOLS).find(([, t]) => t.key.toLowerCase() === lower);
    if (tool && !e.shiftKey) {
      this.setTool(tool[0]);
      return;
    }
    if (/^[1-9]$/.test(key)) {
      const c = this.classes[Number(key) - 1];
      if (c) this.selectClass(c.index);
      return;
    }
    if (lower === "h") return this.toggleOverlay(!ed.showOverlay);
    if (lower === "o") {
      this.outlineBox.checked = !ed.outline;
      return ed.setOutline(!ed.outline);
    }
    if (lower === "f") return ed.fit();
    if (key === "+" || key === "=") return ed.zoomAt(1.25);
    if (key === "-") return ed.zoomAt(0.8);
  }

  // ------------------------------------------------------------------ lifecycle
  async leave() {
    if (this.destroyed) return true;
    if (this.hasUnsaved()) {
      const ok = await this.saveNow(false);
      if (!ok && this.hasUnsaved()) {
        const leave = await confirmDialog("Leave without saving?", `Your latest changes could not be saved (${this.saveError || "unknown error"}). If you leave now they are lost.`, { confirmLabel: "Leave anyway", kind: "danger" });
        if (!leave) return false;
      }
    }
    if (this.haveLock) {
      this.haveLock = false;
      api.del(`api/v1/images/${this.image.id}/lock`).catch(() => {});
    }
    return true;
  }

  onPageHide() {
    if (this.haveLock) releaseLockBeacon(this.image.id);
  }

  destroy() {
    this.destroyed = true;
    clearInterval(this.heartbeat);
    clearTimeout(this._saveTimer);
    window.removeEventListener("keydown", this._keys);
    window.removeEventListener("oa:reauthenticated", this._reauth);
    this.editor.destroy();
  }
}

export { STATUS_HELP };
