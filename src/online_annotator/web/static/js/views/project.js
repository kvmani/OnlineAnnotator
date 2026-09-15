// Project page: image gallery with filters, uploads, mask import, classes, exports, activity.
import { api, uploadWithProgress } from "../api.js";
import { go, setCrumbs } from "../nav.js";
import { app, inReview, isAdmin, mode } from "../state.js";
import {
  STATUS_HELP, STATUS_LABELS, clear, confirmDialog, emptyState, field, fmtBytes, fmtDate, fmtPct, fmtRelative, h,
  helpTip, icon, modal, plural, statusBadge, toast,
} from "../ui.js";
import { modeNote, startNext } from "./home.js";
import { batchView, maskImportControls, previewer } from "./maskimport.js";

// Every tab is for every user, in either working mode, except the administrator's Settings.
const TABS = [
  { id: "images", label: "Images" },
  { id: "classes", label: "Classes & guidelines" },
  { id: "export", label: "Export dataset" },
  { id: "activity", label: "Activity" },
  { id: "settings", label: "Settings", admin: true },
];

export async function renderProject(view, projectId, tab) {
  let { project } = await api.get(`api/v1/projects/${projectId}`);
  setCrumbs([{ label: "Projects", href: "#/" }, { label: project.name }]);
  const page = h("div", { class: "page" });
  view.append(page);
  let timer = null;

  const header = h("div");
  const tabBar = h("nav", { class: "tabs", role: "tablist" });
  const body = h("div", { class: "tab-body" });
  page.append(header, tabBar, body);

  // The header leads with the one action that matters in the current working mode.
  const renderHeader = () => {
    const c = project.counts;
    const q = project.queue || { annotate: 0, review: 0, own_pending: 0 };
    const primary = inReview()
      ? h("button", { class: "btn btn-primary", type: "button", disabled: !q.review, onclick: () => startNext(project.id, "review"),
        title: q.review ? "Open the oldest submission from someone else" : "Nothing from other people is waiting for review" },
      icon("review"), `Review next${q.review ? ` (${q.review})` : ""}`)
      : (c.total ? h("button", { class: "btn btn-primary", type: "button", onclick: () => startNext(project.id, "annotate"),
        title: "Open the next image that needs work and is not being edited by someone else" }, icon("play"), "Annotate next") : null);
    clear(header).append(h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, project.name), project.description ? h("p", { class: "muted" }, project.description) : null),
      h("div", { class: "head-actions" }, primary)),
    c.total ? modeNote(q.review, q.own_pending) : null,
    statusSummary(c));
  };

  const renderTabs = () => {
    clear(tabBar);
    for (const t of TABS) {
      if (t.admin && !isAdmin()) continue;
      tabBar.append(h("a", { href: `#/p/${project.id}/${t.id}`, class: `tab ${t.id === tab ? "active" : ""}`, role: "tab",
        "aria-selected": t.id === tab ? "true" : "false" }, t.label));
    }
  };

  const reload = async () => {
    project = (await api.get(`api/v1/projects/${projectId}`)).project;
    renderHeader();
  };

  renderHeader();
  renderTabs();
  if (tab === "images") timer = await imagesTab(body, project, reload);
  else if (tab === "classes") classesTab(body, project, reload);
  else if (tab === "export") await exportTab(body, project);
  else if (tab === "activity") await activityTab(body, project);
  else if (tab === "settings" && isAdmin()) settingsTab(body, project, reload);
  else go(`#/p/${project.id}`);
  return { destroy: () => timer && clearInterval(timer) };
}

function statusSummary(c) {
  const chip = (key) => h("span", { class: `summary-chip status-${key}`, title: STATUS_HELP[key] },
    h("strong", {}, c[key] || 0), " ", STATUS_LABELS[key]);
  return h("div", { class: "summary-row" }, h("span", { class: "summary-total" }, h("strong", {}, c.total), " images:"),
    ["new", "in_progress", "submitted", "changes_requested", "approved"].map(chip),
    helpTip(h("div", {}, h("p", {}, "Every image moves through these stages:"),
      h("ol", { class: "compact" }, h("li", {}, "New: not started."), h("li", {}, "In progress: saved work, not submitted."),
        h("li", {}, "Waiting for review: submitted, for someone else to review in Review mode."),
        h("li", {}, "Changes requested: returned with a comment by the person who reviewed it."),
        h("li", {}, "Approved: accepted as ground truth. Only approved images are exported by default."))), { wide: true }));
}

// -------------------------------------------------------------------------------- images
async function imagesTab(body, project, reloadProject) {
  let images = [];
  // The filter is remembered per working mode; Review mode starts on what waits for me.
  const filterKey = `oa.filter.${project.id}.${mode()}`;
  let filter = sessionStorage.getItem(filterKey) || (inReview() ? "for_review" : "all");
  let query = "";
  const selected = new Set();
  const toolbar = h("div", { class: "toolbar" });
  const grid = h("div", { class: "image-grid" });
  const bulkBar = h("div", { class: "bulk-bar", hidden: true });
  body.append(toolbar, bulkBar, grid);

  const upload = h("button", { class: "btn", type: "button" }, icon("upload"), "Upload images");
  upload.addEventListener("click", () => uploadDialog(project, refresh));
  const importBtn = h("button", { class: "btn", type: "button", disabled: inReview(),
    title: inReview() ? "Importing masks is annotation work: switch to Annotate mode" : "Load existing masks (e.g. model predictions) as a starting point" },
  icon("download"), "Import masks");
  importBtn.addEventListener("click", () => importMasksDialog(project, refresh));
  const search = h("input", { type: "search", placeholder: "Search file names", class: "search" });
  search.addEventListener("input", () => {
    query = search.value.trim().toLowerCase();
    draw();
  });
  const filters = h("div", { class: "filter-chips", role: "group", "aria-label": "Filter by status" });

  toolbar.append(filters, search, h("div", { class: "spacer" }), importBtn, upload);

  const draw = () => {
    const counts = { all: images.length };
    for (const img of images) counts[img.status] = (counts[img.status] || 0) + 1;
    const mine = images.filter((i) => i.assigned_to === app.me.email).length;
    const forReview = images.filter(isForMyReview).length;
    clear(filters);
    const opts = [["all", "All"], ["new", STATUS_LABELS.new], ["in_progress", STATUS_LABELS.in_progress],
      ["submitted", STATUS_LABELS.submitted], ["changes_requested", STATUS_LABELS.changes_requested], ["approved", STATUS_LABELS.approved]];
    if (mine) opts.push(["mine", "Assigned to me"]);
    if (inReview()) opts.splice(1, 0, ["for_review", "For me to review"]);
    for (const [key, label] of opts) {
      const n = key === "mine" ? mine : key === "for_review" ? forReview : counts[key] || 0;
      if (key !== "all" && key !== filter && !n) continue;
      const b = h("button", { class: `chip ${filter === key ? "active" : ""}`, type: "button" }, label, h("span", { class: "chip-n" }, n));
      b.addEventListener("click", () => {
        filter = key;
        sessionStorage.setItem(filterKey, key);
        draw();
      });
      filters.append(b);
    }
    const matches = (i) => filter === "all" || (filter === "mine" ? i.assigned_to === app.me.email
      : filter === "for_review" ? isForMyReview(i) : i.status === filter);
    const shown = images.filter((i) => matches(i) &&
      (!query || i.original_filename.toLowerCase().includes(query) || i.stem.toLowerCase().includes(query)));
    clear(grid);
    if (!images.length) {
      grid.append(emptyState("upload", "No images yet",
        "Upload micrographs (PNG, JPEG, TIFF including 16-bit, or BMP). You can also drag files onto the upload window.",
        h("button", { class: "btn btn-primary", type: "button", onclick: () => uploadDialog(project, refresh) }, icon("upload"), "Upload images")));
      return;
    }
    if (!shown.length) {
      grid.append(h("p", { class: "muted" }, filter === "for_review"
        ? "Nothing from other people is waiting for your review in this project." : "No images match this filter."));
    }
    for (const img of shown) grid.append(imageCard(project, img, selected, drawBulk));
    drawBulk();
  };

  const drawBulk = () => {
    bulkBar.hidden = selected.size === 0;
    if (!selected.size) return;
    const split = h("select", {}, h("option", { value: "" }, "Set split…"), ["train", "val", "test", "unassigned"].map((s) => h("option", { value: s }, s)));
    split.addEventListener("change", async () => {
      if (!split.value) return;
      await api.post(`api/v1/projects/${project.id}/images/bulk`, { image_ids: [...selected], split: split.value });
      toast(`Split set to ${split.value} for ${plural(selected.size, "image")}.`, "success");
      selected.clear();
      refresh();
    });
    const assign = h("select", {}, h("option", { value: "" }, "Assign to…"), h("option", { value: "-" }, "Nobody"));
    api.get("api/v1/users").then(({ users }) => users.filter((u) => u.is_active).forEach((u) => assign.append(h("option", { value: u.email }, u.full_name))));
    assign.addEventListener("change", async () => {
      if (!assign.value) return;
      await api.post(`api/v1/projects/${project.id}/images/bulk`, { image_ids: [...selected], assigned_to: assign.value === "-" ? "" : assign.value });
      toast(`Assignment updated for ${plural(selected.size, "image")}.`, "success");
      selected.clear();
      refresh();
    });
    const clearSel = h("button", { class: "btn btn-small", type: "button", onclick: () => { selected.clear(); draw(); } }, "Clear selection");
    clear(bulkBar).append(h("strong", {}, `${selected.size} selected`), split, assign,
      helpTip("Splits decide which images go to training, validation and test folders when you export with 'use the split set on each image'. Assigning an image makes it appear first in that person's 'Annotate next'."), clearSel);
  };

  const refresh = async () => {
    const res = await api.get(`api/v1/projects/${project.id}/images`);
    images = res.images;
    draw();
    reloadProject();
  };
  await refresh();
  // Keep lock indicators and statuses current while the page is open.
  return setInterval(async () => {
    if (document.hidden) return;
    try {
      images = (await api.get(`api/v1/projects/${project.id}/images`)).images;
      draw();
      await reloadProject(); // header counts: "Review next (n)" follows other people's submissions
    } catch (_) {
      /* transient */
    }
  }, 20000);
}

// Waiting for review, and submitted by someone else (or self-approval is allowed).
function isForMyReview(img) {
  const v = img.latest_version;
  return img.status === "submitted" && Boolean(v) && (v.created_by !== app.me.email || Boolean(app.meta.allow_self_approval));
}

function imageCard(project, img, selected, onSelect) {
  const lock = img.lock && img.lock.locked && !img.lock.by_me
    ? h("span", { class: "lock-tag", title: `Being edited by ${img.lock.user_name || img.lock.user_email}` }, icon("lock", 12), img.lock.user_name || img.lock.user_email)
    : null;
  const latest = img.latest_version;
  const note = img.status === "changes_requested" && latest && latest.review_comment
    ? h("p", { class: "card-note" }, "“", latest.review_comment, "”") : null;
  const link = h("a", { class: "thumb", href: `#/p/${project.id}/i/${img.id}`, title: `Open ${img.original_filename}` },
    h("img", { src: img.thumb_url, alt: "", loading: "lazy" }), lock);
  const card = h("article", { class: `image-card status-border-${img.status}` }, link,
    h("div", { class: "image-card-body" },
      h("div", { class: "image-card-title", title: img.original_filename }, img.stem),
      h("div", { class: "image-card-meta" }, statusBadge(img.status),
        img.split !== "unassigned" ? h("span", { class: "tag", title: "Dataset split" }, img.split) : null,
        img.assigned_to ? h("span", { class: "tag", title: `Assigned to ${img.assigned_to}` }, "@", img.assigned_to.split("@")[0]) : null,
        img.status === "submitted" && img.latest_version && img.latest_version.created_by === app.me.email
          ? h("span", { class: "tag", title: "You submitted this, so someone else reviews it" }, "yours") : null),
      note,
      h("div", { class: "image-card-foot muted small" },
        img.working_updated_by ? `${img.working_updated_by.split("@")[0]} · ${fmtRelative(img.working_updated_at)}` : `${img.width} × ${img.height}`)));
  if (onSelect) {
    const cb = h("input", { type: "checkbox", class: "select-box", "aria-label": `Select ${img.stem}` });
    cb.checked = selected.has(img.id);
    cb.addEventListener("change", () => {
      if (cb.checked) selected.add(img.id);
      else selected.delete(img.id);
      card.classList.toggle("selected", cb.checked);
      onSelect();
    });
    card.classList.toggle("selected", cb.checked);
    card.prepend(cb);
  }
  return card;
}

function uploadDialog(project, onDone) {
  const input = h("input", { type: "file", multiple: true, accept: ".png,.jpg,.jpeg,.tif,.tiff,.bmp", hidden: true });
  const list = h("ul", { class: "file-list" });
  const drop = h("div", { class: "dropzone", tabindex: "0" }, icon("upload", 32),
    h("p", {}, h("strong", {}, "Drop micrographs here"), " or click to choose files"),
    h("p", { class: "muted small" }, `PNG, JPEG, TIFF (8- or 16-bit) or BMP · up to ${app.meta.max_upload_mb} MB and ${app.meta.max_image_megapixels} megapixels each`));
  const split = h("select", {}, ["unassigned", "train", "val", "test"].map((s) => h("option", { value: s }, s === "unassigned" ? "Decide later" : s)));
  const progress = h("progress", { max: 1, value: 0, hidden: true });
  const result = h("div");
  let files = [];
  const show = () => {
    clear(list);
    for (const f of files) list.append(h("li", {}, f.name, h("span", { class: "muted" }, fmtBytes(f.size))));
  };
  const add = (fl) => {
    files = files.concat([...fl]);
    show();
  };
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && input.click());
  input.addEventListener("change", () => add(input.files));
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    add(e.dataTransfer.files);
  });
  const body = h("div", { class: "stack" }, drop, input, list,
    field("Dataset split for these images", split, "Which export folder these images belong to: train (model learns from them), val (tunes training), test (final unbiased check). Leave 'Decide later' if unsure; you can change it any time or let the export split automatically."),
    h("p", { class: "muted small" }, "Identical files are recognised and skipped. The original file is kept unchanged; 16-bit and TIFF images get a display copy, and the conversion is recorded."),
    progress, result);
  modal({
    title: `Upload images to ${project.name}`,
    body,
    wide: true,
    actions: [
      { label: "Close" },
      {
        label: "Upload",
        kind: "primary",
        onClick: async () => {
          if (!files.length) {
            toast("Choose some files first.", "info");
            return true;
          }
          const fd = new FormData();
          for (const f of files) fd.append("files", f, f.name);
          fd.append("split", split.value);
          progress.hidden = false;
          try {
            const res = await uploadWithProgress(`api/v1/projects/${project.id}/images`, fd, (p) => (progress.value = p));
            clear(result).append(
              h("div", { class: `alert ${res.errors.length ? "alert-warn" : "alert-ok"}` },
                h("strong", {}, `${plural(res.added, "image")} added.`),
                res.messages.filter((m) => m.includes("identical")).map((m) => h("div", { class: "small" }, m)),
                res.errors.map((e) => h("div", { class: "small" }, "✗ ", e))));
            files = [];
            show();
            onDone();
          } catch (err) {
            clear(result).append(h("div", { class: "alert alert-error" }, err.message));
          } finally {
            progress.hidden = true;
            progress.value = 0;
          }
          return true;
        },
      },
    ],
  });
}

function importMasksDialog(project, onDone) {
  const input = h("input", { type: "file", multiple: true, accept: ".png,.tif,.tiff,.bmp" });
  const controls = maskImportControls(project.classes);
  const tool = h("input", { type: "text", maxlength: "200", placeholder: "e.g. HydrideSegmentation v2.3, ImageJ threshold, in-house script" });
  const remarks = h("textarea", { rows: "3", maxlength: "4000", placeholder: "e.g. Model run of 2026-09-10; tends to miss faint hydride tips near grain boundaries." });
  const preview = h("div", { class: "mask-preview", "aria-live": "polite" });
  const result = h("div");
  const formData = () => {
    const fd = new FormData();
    for (const f of input.files) fd.append("files", f, f.name);
    return fd;
  };
  const refresh = previewer(async () => {
    if (!input.files.length) return null;
    const fd = formData();
    controls.append(fd);
    return (await api.form(`api/v1/projects/${project.id}/masks/analyze`, fd)).results;
  }, (found, err) => {
    clear(preview);
    clear(result);
    if (err) preview.append(h("div", { class: "alert alert-error" }, err.message));
    else if (found) preview.append(batchView(found, { onUseMode: (m, t) => controls.useMode(m, t) }));
    const waiting = found ? found.filter((r) => r.status === "needs_confirmation").length : 0;
    controls.setConfirmation(waiting ? `Import the ${plural(waiting, "file")} marked “needs your confirmation” as described there.` : null);
  });
  input.addEventListener("change", refresh);
  controls.onChange(refresh);
  const body = h("div", { class: "stack" },
    h("p", {}, "Use this to start from existing masks, for example predictions from a HydrideSegmentation model. People then only correct the mistakes."),
    h("ul", { class: "compact small" },
      h("li", {}, "Name each mask after its image: ", h("code", {}, "sample_07_mask.png"), ", ", h("code", {}, "sample_07_mask_labels.png"), " or ", h("code", {}, "sample_07.png"), " matches the image ", h("code", {}, "sample_07"), "."),
      h("li", {}, "After you choose the files, the preview lists how each one will be read. Files that cannot be read safely are skipped and say why."),
      h("li", {}, "The mask becomes the image's working copy (status In progress). Submitted and approved images are never overwritten.")),
    field("Masks", input),
    controls.fields,
    preview,
    controls.confirmBox,
    field("Which tool made these masks?", tool, "Recorded with every image in this batch and written into the export manifest, so anyone reading the dataset later knows the labels started as this tool's output rather than as hand-drawn work."),
    field("Remarks (optional)", remarks, "Anything worth knowing about these masks: the model version, known weaknesses, the settings used. Annotators see it while they correct the mask."),
    result);
  modal({
    title: "Import masks as a starting point",
    body,
    wide: true,
    actions: [
      { label: "Close" },
      {
        label: "Import",
        kind: "primary",
        onClick: async () => {
          if (!input.files.length) {
            toast("Choose mask files first.", "info");
            return true;
          }
          const fd = formData();
          controls.append(fd, { withConfirm: true });
          fd.append("source_tool", tool.value);
          fd.append("remarks", remarks.value);
          try {
            const res = await api.form(`api/v1/projects/${project.id}/masks`, fd);
            clear(preview);
            controls.setConfirmation(null);
            clear(result).append(h("div", { class: `alert ${res.errors.length ? "alert-warn" : "alert-ok"}` },
              h("strong", {}, `${plural(res.imported.length, "mask")} imported.`)), batchView(res.results));
            onDone();
          } catch (err) {
            clear(result).append(h("div", { class: "alert alert-error" }, err.message));
          }
          return true;
        },
      },
    ],
  });
}

// ------------------------------------------------------------------------------ classes
function classesTab(body, project, reload) {
  const table = h("table", { class: "table" },
    h("thead", {}, h("tr", {}, h("th", {}, "Value ", helpTip("The pixel value of this class in indexed masks. 0 is always background (unlabelled) and is not listed.")),
      h("th", {}, "Class"), h("th", {}, "What to label"), isAdmin() ? h("th", {}, "") : null)));
  const tbody = h("tbody");
  table.append(tbody);
  for (const c of project.classes) {
    const edit = isAdmin() ? h("button", { class: "btn btn-small", type: "button" }, icon("edit", 14), "Edit") : null;
    const del = isAdmin() ? h("button", { class: "icon-btn", type: "button", title: "Delete class", "aria-label": "Delete class" }, icon("trash", 16)) : null;
    if (edit) edit.addEventListener("click", () => classDialog(project, c, reloadAndRender));
    if (del) del.addEventListener("click", async () => {
      if (!(await confirmDialog("Delete class", `Delete class ${c.index} (${c.name})? This is only possible while no annotation uses it.`, { confirmLabel: "Delete", kind: "danger" }))) return;
      try {
        await api.del(`api/v1/projects/${project.id}/classes/${c.id}`);
        toast("Class deleted.", "success");
        reloadAndRender();
      } catch (err) {
        toast(err.message, "error");
      }
    });
    tbody.append(h("tr", {}, h("td", { class: "mono" }, c.index),
      h("td", {}, h("span", { class: "swatch", style: { background: c.color } }), " ", h("strong", {}, c.name), h("span", { class: "muted small mono" }, " ", c.color)),
      h("td", {}, c.description || h("span", { class: "muted" }, "No description")),
      isAdmin() ? h("td", { class: "right" }, edit, del) : null));
  }
  const addBtn = isAdmin() ? h("button", { class: "btn", type: "button", onclick: () => classDialog(project, null, reloadAndRender) }, icon("plus"), "Add class") : null;
  const guide = h("section", { class: "card" }, h("h3", {}, "Annotation guidelines"),
    project.guidelines ? h("pre", { class: "guidelines" }, project.guidelines) : h("p", { class: "muted" }, "No guidelines written yet."),
    isAdmin() ? h("p", { class: "small muted" }, "Edit them in the Settings tab.") : null);
  body.append(h("div", { class: "two-col" }, h("section", { class: "card" }, h("h3", {}, "Classes"), table, addBtn), guide));

  async function reloadAndRender() {
    await reload();
    const fresh = (await api.get(`api/v1/projects/${project.id}`)).project;
    Object.assign(project, fresh);
    clear(body);
    classesTab(body, project, reload);
  }
}

function classDialog(project, cls, onDone) {
  const name = h("input", { value: cls ? cls.name : "", required: true, maxlength: 80 });
  const color = h("input", { type: "color", value: cls ? cls.color : "#2F80ED" });
  const desc = h("textarea", { rows: 3 }, cls ? cls.description : "");
  modal({
    title: cls ? `Edit class ${cls.index}` : "Add class",
    body: h("div", { class: "stack" }, field("Name", name), field("Colour", color, "Only the on-screen and 'colour' mask colour. Changing it never changes the stored labels."),
      field("What to label", desc, "Shown in the class list while people annotate and review. Say what belongs to this class and what does not.")),
    actions: [{ label: "Cancel" }, {
      label: cls ? "Save" : "Add class",
      kind: "primary",
      onClick: async () => {
        const payload = { name: name.value.trim(), color: color.value.toUpperCase(), description: desc.value };
        try {
          if (cls) await api.patch(`api/v1/projects/${project.id}/classes/${cls.id}`, payload);
          else await api.post(`api/v1/projects/${project.id}/classes`, payload);
          toast("Saved.", "success");
          onDone();
        } catch (err) {
          toast(err.message, "error");
          return true;
        }
        return false;
      },
    }],
  });
}

// ------------------------------------------------------------------------------- export
async function exportTab(body, project) {
  const state = {
    include: "approved", layout: "hydride_pairs", mask_style: "binary", target_class: project.classes[0] ? project.classes[0].index : 1,
    split_mode: "assigned", train: 0.8, val: 0.1, test: 0.1, seed: 42, include_coco: true, include_yolo: false,
  };
  const previewBox = h("div", { class: "export-preview" });
  const historyBox = h("div");
  const radio = (name, value, title, text) => {
    const input = h("input", { type: "radio", name, value });
    input.checked = state[name] === value;
    input.addEventListener("change", () => {
      state[name] = value;
      sync();
    });
    return h("label", { class: "option" }, input, h("span", {}, h("strong", {}, title), h("span", { class: "muted small" }, text)));
  };
  const targetSel = h("select", {}, project.classes.map((c) => h("option", { value: c.index }, `${c.index} · ${c.name}`)));
  targetSel.addEventListener("change", () => {
    state.target_class = Number(targetSel.value);
    sync();
  });
  const ratio = (key) => {
    const input = h("input", { type: "number", min: 0, max: 100, step: 5, value: state[key] * 100, class: "num" });
    input.addEventListener("input", () => {
      state[key] = Math.max(0, Number(input.value) || 0) / 100;
      sync();
    });
    return h("label", { class: "inline-field" }, key, input, "%");
  };
  const seed = h("input", { type: "number", value: state.seed, class: "num" });
  seed.addEventListener("input", () => {
    state.seed = Number(seed.value) || 0;
    sync();
  });
  const autoBox = h("div", { class: "indent row" }, ratio("train"), ratio("val"), ratio("test"), h("label", { class: "inline-field" }, "seed", seed,
    helpTip("The same seed and images always give the same split, so an export can be reproduced exactly.")));
  const coco = h("input", { type: "checkbox", checked: state.include_coco });
  coco.addEventListener("change", () => {
    state.include_coco = coco.checked;
    sync();
  });
  const yolo = h("input", { type: "checkbox", disabled: !app.meta.yolo_export });
  yolo.addEventListener("change", () => {
    state.include_yolo = yolo.checked;
    sync();
  });
  const create = h("button", { class: "btn btn-primary btn-large", type: "button" }, icon("download"), "Create export");

  const form = h("div", { class: "export-form" },
    h("section", { class: "card" }, h("h3", {}, "1. Which annotations"),
      radio("include", "approved", "Approved only (recommended)", "Ground truth checked in review by a second person."),
      radio("include", "approved_and_submitted", "Approved and waiting for review", "For quick experiments only: unreviewed masks may contain mistakes.")),
    h("section", { class: "card" }, h("h3", {}, "2. Folder layout ", helpTip(layoutHelp(), { wide: true })),
      radio("layout", "hydride_pairs", "HydrideSegmentation pairs (recommended)", "One folder of image.png + image_mask.png pairs; point HydrideSegmentation's prepare_dataset at it."),
      radio("layout", "split_folders", "Train / val / test folders", "train|val|test/images and .../masks, for most other training code.")),
    h("section", { class: "card" }, h("h3", {}, "3. Mask format ", helpTip(maskHelp(), { wide: true })),
      radio("mask_style", "binary", "Black and white for one class", "255 where the chosen class is, 0 elsewhere. HydrideSegmentation default."),
      radio("mask_style", "red", "Red on black for one class", "For HydrideSegmentation's RGB mask mode."),
      h("div", { class: "indent" }, field("Class", targetSel)),
      radio("mask_style", "indexed", "Class numbers (all classes)", "Pixel value = class number, 0 = background. Best for multi-class training."),
      radio("mask_style", "colour", "Class colours (all classes)", "Easy to look at; not ideal for training.")),
    h("section", { class: "card" }, h("h3", {}, "4. Train / validation / test split ", helpTip("Training uses the train images, tunes itself on val, and is judged fairly on test images it never saw. Keep images of the same specimen area in the same split to avoid over-optimistic results.")),
      radio("split_mode", "assigned", "Use the split set on each image", "Set splits by selecting images on the Images tab. Images without a split go to 'unassigned'."),
      radio("split_mode", "auto", "Split automatically", "Random but reproducible, by percentage."),
      autoBox),
    h("section", { class: "card" }, h("h3", {}, "5. Extras"),
      h("label", { class: "check" }, coco, "COCO JSON (exact run-length masks per class) ", helpTip("For tools that read the COCO format, e.g. detectron2 and mmsegmentation. Masks are stored losslessly as run-length encoding.")),
      h("label", { class: "check" }, yolo, "YOLO segmentation polygons ", helpTip(app.meta.yolo_export ? "Outline polygons for YOLO-seg. Lossy: holes and tiny details are not represented."
        : "Needs OpenCV on the server (pip install opencv-python-headless)."))),
    h("div", { class: "export-action" }, previewBox, create));

  const statsBox = h("div", { class: "card stats-card" });
  body.append(h("div", { class: "export-layout" }, form, h("aside", { class: "export-side" }, statsBox, h("h3", {}, "Previous exports"), historyBox)));
  api.get(`api/v1/projects/${project.id}/summary`).then((s) => {
    clear(statsBox).append(h("h3", {}, "Approved ground truth ", helpTip("Area fraction of each class over all approved images: labelled pixels divided by total pixels. For hydrides this is the ground-truth hydride area fraction of the dataset.")),
      s.approved_pixels ? h("table", { class: "table compact-table" }, h("tbody", {}, s.classes.map((c) => h("tr", {},
        h("td", {}, h("span", { class: "swatch", style: { background: c.color } }), " ", c.name),
        h("td", { class: "right mono" }, fmtPct(s.class_fractions[String(c.index)] || 0, 2)))))) : h("p", { class: "muted small" }, "No approved images yet."),
      h("p", { class: "muted small" }, `${plural(s.counts.approved, "approved image")} of ${s.counts.total}.`));
  }).catch(() => statsBox.remove());

  let pending = 0;
  async function sync() {
    targetSel.parentElement.parentElement.hidden = !(state.mask_style === "binary" || state.mask_style === "red");
    autoBox.hidden = state.split_mode !== "auto";
    const my = ++pending;
    try {
      const p = await api.post(`api/v1/projects/${project.id}/exports/preview`, state);
      if (my !== pending) return;
      const splits = Object.entries(p.splits).map(([k, v]) => `${k} ${v}`).join(" · ");
      clear(previewBox).append(
        h("div", { class: "preview-count" }, h("strong", {}, p.image_count), ` ${p.image_count === 1 ? "image" : "images"} will be exported`),
        splits ? h("div", { class: "muted small" }, splits) : null,
        p.skipped.not_approved || p.skipped.no_annotation ? h("div", { class: "muted small" },
          `Left out: ${p.skipped.not_approved} not yet approved, ${p.skipped.no_annotation} never annotated.`) : null,
        p.warnings.map((w) => h("div", { class: "alert alert-warn small" }, w)),
        treePreview(state, project));
      create.disabled = !p.image_count;
    } catch (err) {
      clear(previewBox).append(h("div", { class: "alert alert-error" }, err.message));
    }
  }

  create.addEventListener("click", async () => {
    create.disabled = true;
    create.textContent = "Creating…";
    try {
      const { export: exp } = await api.post(`api/v1/projects/${project.id}/exports`, state);
      toast(`Export ready: ${plural(exp.image_count, "image")}, ${fmtBytes(exp.size_bytes)}. Downloading…`, "success");
      window.location.href = exp.download_url;
      await drawHistory();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      create.disabled = false;
      create.replaceChildren(icon("download"), "Create export");
    }
  });

  async function drawHistory() {
    const { exports } = await api.get(`api/v1/projects/${project.id}/exports`);
    clear(historyBox);
    if (!exports.length) historyBox.append(h("p", { class: "muted small" }, "None yet."));
    for (const e of exports) {
      const o = e.options;
      historyBox.append(h("div", { class: "export-item" },
        h("a", { href: e.download_url, class: "export-name" }, icon("download", 14), e.filename),
        h("div", { class: "muted small" }, `${fmtDate(e.created_at)} · ${e.created_by.split("@")[0]} · ${plural(e.image_count, "image")} · ${fmtBytes(e.size_bytes)}`),
        h("div", { class: "small" }, `${o.layout === "hydride_pairs" ? "pairs" : "split folders"}, ${o.mask_style} masks, ${o.include === "approved" ? "approved only" : "incl. unreviewed"}`),
        h("div", { class: "mono tiny", title: "SHA-256 of the ZIP file, to verify a copy" }, e.sha256.slice(0, 16), "…")));
    }
  }
  await Promise.all([sync(), drawHistory()]);
}

function layoutHelp() {
  return h("div", {}, h("p", {}, h("strong", {}, "HydrideSegmentation pairs:")),
    h("pre", { class: "tree" }, "pairs/\n  sample_01.png\n  sample_01_mask.png\n  …\nmanifest.json\nREADME.txt"),
    h("p", {}, h("strong", {}, "Train / val / test folders:")),
    h("pre", { class: "tree" }, "train/images/sample_01.png\ntrain/masks/sample_01_mask.png\nval/…\ntest/…\nmanifest.json"));
}

function maskHelp() {
  return h("div", {}, h("p", {}, "A mask is an image of the same size as the micrograph whose pixel values say which class each pixel belongs to."),
    h("ul", { class: "compact" }, h("li", {}, "Black and white: one class only, 255 = class, 0 = everything else."),
      h("li", {}, "Red on black: the same, stored as RGB (255, 0, 0)."),
      h("li", {}, "Class numbers: every class at once; open it with a script, it looks almost black in a viewer."),
      h("li", {}, "Class colours: every class in its colour; good for looking at, not for training.")));
}

function treePreview(state, project) {
  const stem = "sample_01";
  const img = `${stem}.png`, mask = `${stem}_mask.png`;
  const lines = state.layout === "hydride_pairs" ? [`pairs/${img}`, `pairs/${mask}`] : [`train/images/${img}`, `train/masks/${mask}`, "val/…", "test/…"];
  if (state.include_coco) lines.push("coco_annotations.json");
  if (state.include_yolo) lines.push(state.layout === "hydride_pairs" ? `pairs_yolo/${stem}.txt` : `train/labels/${stem}.txt`);
  lines.push("manifest.json", "README.txt");
  return h("details", { class: "tree-preview" }, h("summary", {}, "What the ZIP will contain"), h("pre", { class: "tree" }, lines.join("\n")));
}

// ----------------------------------------------------------------------------- activity
async function activityTab(body, project) {
  const { events } = await api.get(`api/v1/projects/${project.id}/activity?limit=200`);
  if (!events.length) {
    body.append(emptyState("history", "No activity yet", "Uploads, saves, submissions, reviews and exports appear here."));
    return;
  }
  const rows = events.map((e) => h("tr", {}, h("td", { class: "nowrap muted" }, fmtDate(e.timestamp)), h("td", { class: "nowrap" }, e.user_email),
    h("td", {}, h("span", { class: `badge action-${e.action}` }, e.action.replace(/_/g, " "))),
    h("td", {}, e.image_id ? h("a", { href: `#/p/${project.id}/i/${e.image_id}` }, e.summary) : e.summary)));
  body.append(h("div", { class: "card" }, h("p", { class: "muted small" }, "Every change is recorded with who and when, here and in the server's append-only audit log."),
    h("div", { class: "table-wrap" }, h("table", { class: "table" }, h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "Who"), h("th", {}, "What"), h("th", {}, "Details"))), h("tbody", {}, rows)))));
}

// ----------------------------------------------------------------------------- settings
function settingsTab(body, project, reload) {
  const name = h("input", { value: project.name, maxlength: 120 });
  const desc = h("textarea", { rows: 2 }, project.description);
  const guidelines = h("textarea", { rows: 10 }, project.guidelines);
  const save = h("button", { class: "btn btn-primary", type: "button" }, "Save changes");
  save.addEventListener("click", async () => {
    try {
      await api.patch(`api/v1/projects/${project.id}`, { name: name.value.trim(), description: desc.value, guidelines: guidelines.value });
      toast("Project updated.", "success");
      reload();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  const archive = h("button", { class: "btn", type: "button" }, project.archived ? "Restore project" : "Archive project");
  archive.addEventListener("click", async () => {
    const ok = await confirmDialog(project.archived ? "Restore project" : "Archive project",
      project.archived ? "Show this project in the main list again?" : "Archived projects are hidden from everyone except administrators but keep all images, annotations and exports. You can restore it later.");
    if (!ok) return;
    await api.patch(`api/v1/projects/${project.id}`, { archived: !project.archived });
    toast("Done.", "success");
    go("#/");
  });
  body.append(h("div", { class: "card narrow stack" }, field("Name", name), field("Description", desc),
    field("Annotation guidelines", guidelines, "Shown next to every image. Write concrete rules: what to include, what to leave out, what to do when unsure."),
    h("div", { class: "row" }, save, h("div", { class: "spacer" }), archive)));
}
