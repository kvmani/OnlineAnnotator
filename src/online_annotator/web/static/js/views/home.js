// Projects dashboard: what waits for me in my current working mode, a first-run quick start
// and the new-project wizard.
import { api } from "../api.js";
import { go, modeButton, setCrumbs } from "../nav.js";
import { MODE_HELP, app, inReview, isAdmin, savePref } from "../state.js";
import { emptyState, field, h, helpTip, icon, modal, plural, toast } from "../ui.js";

export async function renderHome(view) {
  setCrumbs([{ label: "Projects" }]);
  const { projects } = await api.get("api/v1/projects?include_archived=" + (isAdmin() ? "true" : "false"));
  const page = h("div", { class: "page" });
  view.append(page);

  if (!app.prefs.hideQuickStart) page.append(quickStart());

  const head = h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "Projects"),
      h("p", { class: "muted" }, "Each project is one dataset: a set of images and the classes you label in them.")));
  if (isAdmin()) {
    const btn = h("button", { class: "btn btn-primary" }, icon("plus"), "New project");
    btn.addEventListener("click", () => newProjectWizard());
    head.append(btn);
  }
  page.append(head);

  const active = projects.filter((p) => !p.archived);
  const archived = projects.filter((p) => p.archived);
  if (active.length) {
    const sum = (key) => active.reduce((n, p) => n + ((p.queue && p.queue[key]) || 0), 0);
    page.append(modeNote(sum("review"), sum("own_pending")));
  } else {
    page.append(emptyState("folder", "No projects yet",
      isAdmin() ? "Create the first project: give it a name and the classes you want to label (for example Hydride)."
        : "An administrator needs to create a project and add you to the work. Ask them, or read the Help centre meanwhile.",
      isAdmin() ? h("button", { class: "btn btn-primary", onclick: () => newProjectWizard() }, icon("plus"), "Create a project") : null));
  }
  const grid = h("div", { class: "project-grid" });
  for (const p of active) grid.append(projectCard(p));
  page.append(grid);
  if (archived.length) {
    page.append(h("h2", { class: "section-title" }, "Archived"));
    const g2 = h("div", { class: "project-grid archived" });
    for (const p of archived) g2.append(projectCard(p));
    page.append(g2);
  }
  return {};
}

// One line that says which mode is on, what is waiting in it, and how to get to the other one.
export function modeNote(waitingForMe, ownPending = 0) {
  const review = inReview();
  const own = ownPending ? ` ${plural(ownPending, "submission")} of yours ${ownPending === 1 ? "is" : "are"} waiting for someone else.` : "";
  const text = review
    ? (waitingForMe ? `${plural(waitingForMe, "submission")} from other people ${waitingForMe === 1 ? "is" : "are"} waiting for your review.` : "Nothing from other people is waiting for review right now.") + own
    : "Label images and submit them for review." + (waitingForMe ? ` ${plural(waitingForMe, "submission")} from other people ${waitingForMe === 1 ? "is" : "are"} waiting for review.` : "");
  const other = review
    ? (waitingForMe ? null : modeButton("annotate"))
    : (waitingForMe ? modeButton("review") : null);
  return h("div", { class: `mode-note mode-note-${review ? "review" : "annotate"}`, role: "status" },
    icon(review ? "review" : "edit", 16),
    h("span", {}, h("strong", {}, review ? "Review mode. " : "Annotate mode. "), text),
    helpTip(`${MODE_HELP[review ? "review" : "annotate"]} Switch at any time with Annotate / Review at the top of the page.`),
    h("span", { class: "spacer" }), other);
}

function progressBar(counts) {
  const total = counts.total || 0;
  const seg = (key, cls) => {
    const n = counts[key] || 0;
    return n ? h("span", { class: `seg ${cls}`, style: { width: `${(100 * n) / total}%` }, title: `${n} ${key.replace("_", " ")}` }) : null;
  };
  return h("div", { class: "progress", role: "img", "aria-label": `${counts.approved || 0} of ${total} approved` },
    seg("approved", "seg-approved"), seg("submitted", "seg-submitted"), seg("changes_requested", "seg-changes"),
    seg("in_progress", "seg-progress"));
}

function projectCard(p) {
  const c = p.counts;
  const q = p.queue || { annotate: 0, review: 0, own_pending: 0 };
  const pct = c.total ? Math.round((100 * c.approved) / c.total) : 0;
  const review = inReview();
  const card = h("article", { class: "project-card" },
    h("div", { class: "project-card-head" },
      h("h3", {}, h("a", { href: `#/p/${p.id}` }, p.name)),
      p.archived ? h("span", { class: "badge" }, "archived") : null),
    h("p", { class: "muted clamp" }, p.description || "No description."),
    h("div", { class: "class-chips" }, p.classes.map((k) => h("span", { class: "class-chip" },
      h("span", { class: "swatch", style: { background: k.color } }), k.name))),
    progressBar(c),
    h("div", { class: "project-stats" },
      h("span", {}, h("strong", {}, c.total), " images"),
      h("span", {}, h("strong", {}, c.approved), ` approved (${pct}%)`),
      review
        ? h("span", { class: "text-submitted" }, h("strong", {}, q.review), " for you to review")
        : (c.submitted ? h("span", { class: "text-submitted" }, h("strong", {}, c.submitted), " waiting for review") : null),
      !review && c.changes_requested ? h("span", { class: "text-changes" }, h("strong", {}, c.changes_requested), " returned") : null));
  const actions = h("div", { class: "card-actions" },
    h("a", { class: "btn btn-small", href: `#/p/${p.id}` }, "Open"),
    review
      ? h("button", { class: "btn btn-primary btn-small", type: "button", disabled: !q.review, onclick: () => startNext(p.id, "review"),
        title: q.review ? "Open the oldest submission from someone else" : "Nothing from other people is waiting for review" },
      icon("review", 14), `Review next${q.review ? ` (${q.review})` : ""}`)
      : (c.total ? h("button", { class: "btn btn-primary btn-small", type: "button", onclick: () => startNext(p.id, "annotate") }, icon("play", 14), "Annotate next") : null));
  card.append(actions);
  return card;
}

export async function startNext(projectId, mode, after = null) {
  try {
    const url = `api/v1/projects/${projectId}/next?mode=${mode}` + (after ? `&after=${after}` : "");
    const { image_id } = await api.get(url);
    if (image_id) go(`#/p/${projectId}/i/${image_id}`);
    else toast(mode === "review" ? "Nothing from other people is waiting for review right now. Your own submissions are reviewed by someone else." : "No free image needs annotating right now. Everything is submitted, approved, or being edited by someone else.", "info", 6000);
  } catch (err) {
    toast(err.message, "error");
  }
}

function quickStart() {
  const close = h("button", { class: "icon-btn", title: "Hide this introduction (it stays in Help > Getting started)", "aria-label": "Hide" }, icon("x", 16));
  const box = h("section", { class: "quickstart" },
    h("div", { class: "quickstart-head" }, h("h2", {}, "How it works"), close),
    h("ol", { class: "steps" },
      step(1, "Open a project and press Annotate next", "You get the next image nobody else is working on. It is reserved for you while it is open."),
      step(2, "Label the pixels", "Pick a class, then paint with the Brush or use Polygon, Lasso, Magic wand or Box threshold. Work is saved automatically."),
      step(3, "Submit for review", "Someone else checks it and approves it or returns it with a comment. Only approved images become training data."),
      step(4, "Review other people's work", "Switch to Review at the top of the page and press Review next. Correct small mistakes, then approve or request changes. Nobody reviews their own submissions."),
      step(5, "Export the dataset", "Download a ZIP ready for HydrideSegmentation or other training code, with full provenance.")),
    h("p", { class: "small" }, "Everyone can annotate and review. Stuck? Every screen has ", h("span", { class: "help-tip inline" }, "?"), " buttons, and ", h("a", { href: "#/help" }, "the Help centre"), " explains everything in detail. Press ", h("kbd", {}, "?"), " for keyboard shortcuts."));
  close.addEventListener("click", () => {
    savePref("hideQuickStart", true);
    box.remove();
  });
  return box;
}

function step(n, title, text) {
  return h("li", {}, h("span", { class: "step-n" }, n), h("div", {}, h("strong", {}, title), h("p", {}, text)));
}

// ------------------------------------------------------------------ new project wizard
export function newProjectWizard() {
  const name = h("input", { required: true, maxlength: 120, placeholder: "e.g. Hydrides in Zr-2.5Nb, batch 3" });
  const description = h("textarea", { rows: 2, placeholder: "Material, imaging conditions, purpose of the dataset" });
  const guidelines = h("textarea", { rows: 5, placeholder: "1. Label every platelet including faint tips.\n2. Leave grain boundaries unlabelled.\n3. When unsure, leave it and add a note." });
  const rows = h("div", { class: "class-rows" });
  const palette = ["#FF0000", "#2F80ED", "#27AE60", "#F2C94C", "#9B51E0", "#F2994A"];
  const addRow = (nameVal = "", desc = "") => {
    const idx = rows.children.length + 1;
    const color = h("input", { type: "color", value: palette[(idx - 1) % palette.length], title: "Class colour" });
    const cname = h("input", { placeholder: `Class ${idx} name`, value: nameVal, required: true });
    const cdesc = h("input", { placeholder: "What counts as this class? (shown while annotating)", value: desc });
    const del = h("button", { class: "icon-btn", type: "button", title: "Remove class", "aria-label": "Remove class" }, icon("trash", 16));
    const row = h("div", { class: "class-row" }, h("span", { class: "class-index", title: "Pixel value in indexed masks" }, idx), color, cname, cdesc, del);
    del.addEventListener("click", () => {
      if (rows.children.length > 1) {
        row.remove();
        [...rows.children].forEach((r, k) => (r.querySelector(".class-index").textContent = k + 1));
      }
    });
    rows.append(row);
  };
  addRow("Hydride", "Dark, thin, elongated platelets");
  const addBtn = h("button", { class: "btn btn-small", type: "button" }, icon("plus", 14), "Add class");
  addBtn.addEventListener("click", () => addRow());
  const body = h("div", { class: "stack" },
    field("Project name", name),
    field("Description", description),
    h("div", { class: "field" },
      h("span", { class: "field-label" }, "Classes ", helpTip("A class is one kind of feature you label. Each class gets a number: that number is the pixel value in 'indexed' masks, and 0 always means background (unlabelled). You can add classes later, but not renumber them.")),
      rows, addBtn),
    field("Annotation guidelines", guidelines, "Shown next to every image while people annotate and review. Clear rules make labels consistent between people.", "Optional, but strongly recommended."));
  modal({
    title: "New project",
    body,
    wide: true,
    actions: [
      { label: "Cancel" },
      {
        label: "Create project",
        kind: "primary",
        onClick: async (close) => {
          const classes = [...rows.children].map((r) => ({
            name: r.querySelector("input[placeholder^='Class']").value.trim(),
            color: r.querySelector("input[type=color]").value.toUpperCase(),
            description: r.querySelectorAll("input")[2].value.trim(),
          }));
          if (!name.value.trim() || classes.some((c) => !c.name)) {
            toast("Give the project and every class a name.", "error");
            return true;
          }
          try {
            const { project } = await api.post("api/v1/projects", {
              name: name.value.trim(), description: description.value, guidelines: guidelines.value, classes,
            });
            close();
            toast("Project created. Next: upload images.", "success");
            go(`#/p/${project.id}`);
          } catch (err) {
            toast(err.message, "error");
            return true;
          }
          return false;
        },
      },
    ],
  });
}
