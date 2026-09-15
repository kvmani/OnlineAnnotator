// Reading mask files made by other tools: the choice of how to read them, a preview of what the
// server detected, and the confirmation an ambiguous file needs. Shared by the single-image and
// the bulk import so both explain a file in the same words. All analysis happens on the server;
// this module only shows its result (labels.MaskAnalysis.to_dict) and sends the user's choices.
import { field, h, helpTip } from "../ui.js";

const MODES = [
  ["auto", "Auto detect (recommended)"],
  ["indexed", "Indexed class mask: pixel value = class number"],
  ["binary", "Binary mask: background 0, one foreground value"],
  ["threshold", "Grayscale threshold: greyscale or probability image"],
  ["colour", "Colour mask: class colours or red on black"],
];

const capitalise = (text) => (text ? text[0].toUpperCase() + text.slice(1) : text);
const arrows = (text) => text.replaceAll(" -> ", " → ");

export function maskImportControls(classes) {
  // Explicit names: each field's label also holds a (?) button, which would otherwise take the label.
  const mode = h("select", { "aria-label": "How to read the file" }, MODES.map(([value, label]) => h("option", { value }, label)));
  const cls = h("select", { "aria-label": "Class for black/white, red and threshold masks" },
    classes.map((c) => h("option", { value: c.index }, `${c.index} · ${c.name}`)));
  const threshold = h("input", { type: "number", step: "any", placeholder: "e.g. 128", "aria-label": "Threshold" });
  const invert = h("input", { type: "checkbox" });
  const confirm = h("input", { type: "checkbox" });
  const confirmText = h("span");
  const thresholdField = field("Threshold", threshold,
    "Pixels whose value is at or above the threshold become the chosen class; every other pixel becomes background. The preview suggests a threshold that separates the two main groups of grey levels. In a bulk import the same threshold applies to every file.");
  const invertField = h("label", { class: "check" }, invert, h("span", {}, "Foreground is black (features drawn black on white)"),
    helpTip("Tick this when the mask shows the features in black on a white background: foreground and background are swapped. It applies only to binary and threshold masks."));
  const confirmBox = h("label", { class: "check confirm-box", hidden: true }, confirm, confirmText);

  const listeners = [];
  const notify = () => listeners.forEach((fn) => fn());
  const show = () => {
    thresholdField.hidden = mode.value !== "threshold";
    invertField.hidden = !["auto", "binary", "threshold"].includes(mode.value);
  };
  let timer = null;
  mode.addEventListener("change", () => {
    show();
    notify();
  });
  cls.addEventListener("change", notify);
  invert.addEventListener("change", notify);
  threshold.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(notify, 400);
  });
  show();

  const fields = h("div", { class: "stack" },
    field("How to read the file", mode,
      "Auto detect keeps masks whose values are already class numbers exactly, turns 0/1 and 0/255 masks into the class you choose, reads the project's class colours, red-on-black masks and palette PNGs. It never guesses: a file that could mean two things asks you to confirm, and a greyscale image with many levels needs a threshold you choose. The other choices force one reading."),
    field("Black/white, red and threshold masks become class", cls,
      "These masks have a single foreground, so you choose which class it means. Masks of class numbers or class colours keep their own classes."),
    thresholdField, invertField);

  return {
    fields,
    confirmBox,
    get confirmed() {
      return confirm.checked;
    },
    onChange(fn) {
      listeners.push(fn);
    },
    // Switch to another reading suggested by the preview (and prefill a suggested threshold).
    useMode(value, suggestedThreshold = null) {
      mode.value = value;
      if (value === "threshold" && suggestedThreshold !== null && threshold.value === "") threshold.value = suggestedThreshold;
      show();
      notify();
    },
    // The question the user must confirm, or null. A changed question needs a fresh tick.
    setConfirmation(question) {
      const text = question ? `I checked the preview. ${question}` : "";
      if (confirmText.textContent !== text) confirm.checked = false;
      confirmText.textContent = text;
      confirmBox.hidden = !question;
    },
    append(fd, { withConfirm = false } = {}) {
      fd.append("mode", mode.value);
      fd.append("import_class", cls.value);
      fd.append("invert", invert.checked ? "true" : "false");
      if (mode.value === "threshold" && threshold.value.trim() !== "") fd.append("threshold", threshold.value.trim());
      if (withConfirm) fd.append("confirm", confirm.checked ? "true" : "false");
    },
  };
}

// Runs an async request whenever asked and renders only the newest answer.
export function previewer(request, render) {
  let seq = 0;
  return async () => {
    const mine = ++seq;
    try {
      const result = await request();
      if (mine === seq) render(result, null);
    } catch (err) {
      if (mine === seq) render(null, err);
    }
  };
}

function suggestionButton(analysis, onUseMode) {
  if (!onUseMode || analysis.ok || !analysis.suggested_mode) return null;
  const again = analysis.requested_mode === analysis.suggested_mode;
  if (again && analysis.suggested_threshold == null) return null;
  const label = analysis.suggested_mode === "threshold"
    ? (again ? `Use the suggested threshold ${analysis.suggested_threshold}` : `Read it with Grayscale threshold${analysis.suggested_threshold != null ? ` (suggested ${analysis.suggested_threshold})` : ""}`)
    : "Read it as a Colour mask";
  return h("button", { class: "btn btn-small", type: "button", onclick: () => onUseMode(analysis.suggested_mode, analysis.suggested_threshold) }, label);
}

// The preview of one file: what was detected, value -> class, foreground share, warnings.
export function analysisView(a, { onUseMode } = {}) {
  const tone = !a.ok ? "alert-error" : a.requires_confirmation || a.warnings.length ? "alert-warn" : "alert-ok";
  const [head, ...rest] = a.summary;
  return h("div", { class: `alert ${tone} mask-analysis`, "data-detected": a.detected, role: "status" },
    h("strong", {}, head),
    rest.length ? h("ul", { class: "compact small" }, rest.map((line) => h("li", {}, arrows(line)))) : null,
    a.ok ? null : h("p", { class: "small" }, h("strong", {}, "Nothing will be imported: "), a.error),
    a.warnings.map((w) => h("p", { class: "small" }, "⚠ ", w)),
    suggestionButton(a, onUseMode),
    a.normalization ? h("details", { class: "small" }, h("summary", {}, "How the values are converted"), h("p", {}, a.normalization)) : null);
}

// One line for an interpretation record or analysis: "Binary display mask (0/255): 255 → class 1 Hydride".
export function importSummary(record) {
  const moves = (record.mapping || []).filter((m) => m.class_index).map((m) => `${m.source} → ${m.target}`);
  const shown = moves.slice(0, 3).join("; ") + (moves.length > 3 ? "; …" : "");
  return `${record.encoding_name}${shown ? `: ${shown}` : ""}${record.confirmed ? " (confirmed)" : ""}`;
}

const STATUS = {
  ready: ["✓", "ready to import"],
  imported: ["✓", "imported"],
  needs_confirmation: ["!", "needs your confirmation"],
  refused: ["✗", "not imported"],
  unmatched: ["✗", "no matching image"],
};

// The preview (or outcome) of a bulk import, one row per file.
export function batchView(results, { onUseMode } = {}) {
  const count = (status) => results.filter((r) => r.status === status).length;
  const parts = [["ready", "ready"], ["imported", "imported"], ["needs_confirmation", "need confirmation"],
    ["refused", "cannot be imported"], ["unmatched", "match no image"]]
    .map(([status, label]) => [count(status), label]).filter(([n]) => n).map(([n, label]) => `${n} ${label}`);
  const suggesting = results.find((r) => r.analysis && suggestionButton(r.analysis, onUseMode));
  return h("div", { class: "stack mask-batch", role: "status" },
    h("p", { class: "small" }, h("strong", {}, `${results.length} file${results.length === 1 ? "" : "s"}: `), parts.join(", "), "."),
    suggesting ? suggestionButton(suggesting.analysis, onUseMode) : null,
    h("ul", { class: "mask-batch-list" }, results.map((r) => {
      const [mark, word] = STATUS[r.status] || ["", r.status];
      const a = r.analysis;
      return h("li", { class: `mask-batch-${r.status}`, "data-status": r.status },
        h("span", { class: "mask-batch-mark", "aria-hidden": "true" }, mark),
        h("div", {},
          h("div", {}, h("strong", {}, r.file), r.image ? ` → ${r.image}` : "", `: ${word}`),
          a && a.ok ? h("div", { class: "small" }, importSummary(a),
            a.foreground_fraction != null ? `; foreground ${(a.foreground_fraction * 100).toFixed(1)}%` : "") : null,
          r.status === "ready" || r.status === "imported" ? null : h("div", { class: "small" }, capitalise(r.message)),
          a ? a.warnings.map((w) => h("div", { class: "small" }, "⚠ ", w)) : null));
    })));
}
