// Help centre (#/help) and the keyboard-shortcut sheet. Written for people who have
// never used an annotation tool; every section answers "what do I do, and why".
import { setCrumbs } from "../nav.js";
import { app } from "../state.js";
import { clear, h, icon } from "../ui.js";

export const SHORTCUTS = [
  ["Tools", [
    ["V", "Pan (move the image)"], ["B", "Brush"], ["E", "Eraser"], ["P", "Polygon"], ["L", "Lasso"],
    ["W", "Magic wand"], ["T", "Box threshold"], ["G", "Fill"],
  ]],
  ["Drawing", [
    ["1 … 9", "Select class 1 to 9"], ["Shift + draw", "Erase with any tool"], ["Alt + click", "Pick the class under the cursor"],
    ["[  /  ]", "Smaller / larger brush"], ["Enter", "Close polygon / apply box threshold"], ["Backspace", "Remove the last polygon corner"],
    ["Esc", "Cancel polygon or box threshold"],
  ]],
  ["View", [
    ["Scroll", "Zoom at the cursor"], ["Space + drag", "Pan in any tool (also middle or right mouse button)"], ["F", "Fit image to window"],
    ["+  /  -", "Zoom in / out"], ["H", "Show / hide labels"], ["O", "Outlines only"],
  ]],
  ["Work", [
    ["Ctrl + Z", "Undo"], ["Ctrl + Y  or  Ctrl + Shift + Z", "Redo"], ["Ctrl + S", "Save now (saving is also automatic)"],
    ["Ctrl + →  /  Ctrl + ←", "Next / previous image"], ["?", "This list"],
  ]],
];

export function shortcutsTable() {
  const grid = h("div", { class: "shortcut-grid" });
  for (const [group, rows] of SHORTCUTS) {
    grid.append(h("section", {}, h("h3", {}, group), h("table", { class: "shortcut-table" },
      h("tbody", {}, rows.map(([k, d]) => h("tr", {}, h("td", {}, k.split("  ").map((part) => (part.trim() === "/" || part.trim() === "or" ? ` ${part.trim()} ` : h("kbd", {}, part.trim())))), h("td", {}, d)))))));
  }
  return grid;
}

const P = (...c) => h("p", {}, ...c);
const UL = (...items) => h("ul", {}, items.map((i) => h("li", {}, i)));
const OL = (...items) => h("ol", {}, items.map((i) => h("li", {}, i)));
const TIP = (...c) => h("div", { class: "callout" }, icon("info", 16), h("div", {}, ...c));
const K = (k) => h("kbd", {}, k);
const B = (text) => h("strong", {}, text);

const SECTIONS = [
  {
    id: "start",
    title: "Getting started",
    body: () => [
      P("Online Annotator is where you draw ", B("ground truth"), ": you mark, pixel by pixel, which parts of a microstructure image are hydrides, pores, grain boundaries or whatever your project defines. Reviewed images become training data for segmentation models such as HydrideSegmentation."),
      h("h3", {}, "Your first image in five steps"),
      OL(
        h("span", {}, "Check that ", B("Annotate"), " is selected in the switch at the top of the page."),
        h("span", {}, "Open a project and press ", B("Annotate next"), ". You get the next image that needs work; it is reserved for you while you have it open."),
        h("span", {}, "Choose a class on the right (or press ", K("1"), ", ", K("2"), " …) and paint with the ", B("Brush"), " (", K("B"), "). Hold ", K("Shift"), " to erase."),
        h("span", {}, "Zoom with the mouse wheel, move with ", K("Space"), " + drag. Your work saves by itself; the top bar says ", h("em", {}, "Saved"), "."),
        h("span", {}, "When every feature is labelled, press ", B("Submit for review"), ". The next image opens.")),
      TIP("Read the project's ", B("Annotation guidelines"), " (right-hand panel) before you start. Consistent labels between people matter more than speed."),
      h("h3", {}, "Everyone annotates and reviews"),
      P("Nobody is permanently an annotator or a reviewer. You choose what you are doing with the ", B("Annotate / Review"), " switch at the top of every page, and a second person always reviews your submissions. See ", h("a", { href: "#/help/modes" }, "Annotate and Review modes"), "."),
      UL(h("span", {}, B("Every user"), ": annotates, reviews other people's work, uploads images, sets splits and exports datasets."),
        h("span", {}, B("Administrators"), ": the same, plus projects, classes and user accounts.")),
    ],
  },
  {
    id: "modes",
    title: "Annotate and Review modes",
    body: () => [
      P("Every user can both annotate and review. The ", B("Annotate / Review"), " switch at the top of every page says which of the two you are doing now; the coloured line under the top bar repeats it (blue for Annotate, purple for Review)."),
      h("h3", {}, "Annotate mode"),
      UL(h("span", {}, B("Annotate next"), " opens the next image that needs work: images returned to you first, then your work in progress, then new images (those assigned to you before the rest)."),
        "Label, import existing masks, save, and submit your work for review.",
        "Take back one of your submissions with Withdraw to edit, as long as nobody has reviewed it yet."),
      h("h3", {}, "Review mode"),
      UL(h("span", {}, B("Review next"), " opens the oldest submission from someone else. Project cards and the project page show how many are waiting for you."),
        h("span", {}, "Correct small mistakes with the normal tools, then ", B("Approve"), ", or ", B("Request changes"), " with a comment."),
        "Images that are not waiting for review are view-only in this mode. Switch back to Annotate to edit them."),
      h("h3", {}, "Your own work is reviewed by someone else"),
      P("Your own submissions never appear in your review queue, and you cannot approve or return them, so a second person checks all ground truth. If you notice a mistake in something you submitted, switch to Annotate and withdraw it. A server administrator can allow self-approval for one-person teams."),
      h("h3", {}, "Switching"),
      P("Switch whenever you like. If an image is open, your work is saved and the image is released first; then the page reappears in the new mode. Your mode is remembered for your account, so it is the same the next time you sign in, on any computer."),
      h("h3", {}, "What does not depend on the mode"),
      UL("Uploading images, setting train/val/test splits, assigning images to people and exporting datasets work in either mode.",
        "Administrators can manage projects, classes and accounts, delete images and release someone else's reservation in either mode. They annotate and review like everyone else."),
    ],
  },
  {
    id: "concepts",
    title: "Key ideas",
    body: () => [
      h("h3", {}, "Labels are exact pixels"),
      P("Every pixel carries exactly one class number. ", B("0 means background"), " (unlabelled); 1, 2, … are the project's classes. There is no blending or smoothing: what you see on screen is exactly what is saved and exported."),
      h("h3", {}, "Image status"),
      UL(h("span", {}, B("New"), ": nobody has started."), h("span", {}, B("In progress"), ": saved work, not yet submitted."),
        h("span", {}, B("Waiting for review"), ": submitted; read-only for the person who submitted it."),
        h("span", {}, B("Changes requested"), ": the person who reviewed it sent it back with a comment."),
        h("span", {}, B("Approved"), ": accepted as ground truth.")),
      h("h3", {}, "Reservations (editing locks)"),
      P("Only one person edits an image at a time, so nobody overwrites anyone else. Opening an image reserves it; the reservation renews while the tab is open and is released when you leave. If someone else has it, you see who, and can still look."),
      h("h3", {}, "Versions and history"),
      P("Each submission is frozen as a numbered version with its SHA-256 fingerprint and the review decision and comment. Nothing is ever silently overwritten; any version can be restored into the working copy."),
    ],
  },
  {
    id: "tools",
    title: "Drawing tools",
    body: () => [
      P("Pick a tool on the left or with its key. The bar at the bottom of the screen always tells you what the current tool does."),
      toolRow("brush", "Brush (B)", "Paint the selected class. [ and ] change the diameter. Zoom in for edges; paint big areas with a large brush."),
      toolRow("eraser", "Eraser (E)", "Turn pixels back into background. With any other tool, holding Shift erases too."),
      toolRow("polygon", "Polygon (P)", "Click the corners of a feature; double-click, Enter, or click the first corner to fill it. Best for straight-edged or large features."),
      toolRow("lasso", "Lasso (L)", "Draw freehand around a region; it fills when you let go. Fast for irregular features."),
      toolRow("wand", "Magic wand (W)", "Click anywhere on a dark (or bright) feature: every connected pixel at least as dark as the clicked one is labelled at once, so one click takes a whole hydride platelet and stops at the brighter matrix. Tolerance adds slack for faint edges; lower it if the selection leaks into the matrix."),
      toolRow("threshold", "Box threshold (T)", "Drag a box over a crowded region. The tool picks a brightness threshold automatically (Otsu's method) and previews what it would label. Adjust the threshold, choose dark or bright features, ignore specks, then press Enter."),
      toolRow("fill", "Fill (G)", "Click inside an outline you drew to fill the enclosed area, or click a labelled region to change its class."),
      toolRow("pan", "Pan (V)", "Move the image. You rarely need it: Space + drag, the middle or right mouse button pan in every tool."),
      h("h3", {}, "Useful extras"),
      UL(h("span", {}, B("Protect other classes"), ": painting then only changes unlabelled pixels, so you cannot damage a neighbouring class."),
        h("span", {}, B("Alt + click"), " picks the class under the cursor."),
        h("span", {}, B("Clean up"), " removes tiny specks or fills small holes of the selected class over the whole image."),
        h("span", {}, B("View"), ": label opacity, outlines only (", K("O"), "), hide labels (", K("H"), "), brightness, contrast and invert. These change only the screen, never the data."),
        h("span", {}, B("Undo"), " (", K("Ctrl+Z"), ") works for every tool, many steps back.")),
    ],
  },
  {
    id: "review",
    title: "Reviewing",
    body: () => [
      P("Everyone can review. Reviewing makes sure labels follow the guidelines before they become training data."),
      OL(h("span", {}, "Switch to ", B("Review"), " at the top of the page."),
        h("span", {}, "On a project, press ", B("Review next"), ". The oldest submission from someone else opens, with the note its author wrote."),
        h("span", {}, "Compare labels and image: toggle ", K("H"), " to hide the labels and ", K("O"), " for outlines, zoom into edges."),
        h("span", {}, "Small mistakes? Correct them yourself with the normal tools, then ", B("Approve"), ". Your corrected version is approved as a new version; the original submission stays in history."),
        h("span", {}, "Bigger problems? ", B("Request changes"), " with a specific comment. The person who submitted it sees the comment on the image and in the gallery, fixes it in Annotate mode and submits again.")),
      TIP("You never review your own submissions: they are not in your queue, and you cannot approve or return them. Another person checks them. An administrator can change this rule in the server configuration."),
    ],
  },
  {
    id: "export",
    title: "Exporting datasets",
    body: () => [
      P("Anyone can open the project's ", B("Export dataset"), " tab, in either mode. The page shows, before anything is created, how many images will be exported and what the ZIP will contain."),
      h("h3", {}, "Choices"),
      UL(h("span", {}, B("Which annotations"), ": approved only (ground truth), or also those waiting for review (experiments only)."),
        h("span", {}, B("Layout"), ": HydrideSegmentation pairs (", h("code", {}, "pairs/x.png + pairs/x_mask.png"), ") or train/val/test folders."),
        h("span", {}, B("Mask format"), ": black-and-white for one class, red-on-black, class numbers (all classes) or class colours."),
        h("span", {}, B("Split"), ": the split set on each image, or an automatic, reproducible split by percentage and seed."),
        h("span", {}, B("Extras"), ": COCO JSON with exact run-length masks; YOLO polygons (outlines only).")),
      h("h3", {}, "Using the export with HydrideSegmentation"),
      h("pre", { class: "code" }, "# prepare_dataset config\ninput_dir: <unzipped export>/pairs\nrgb_mask_mode: false      # true if you exported 'red on black'\nmask_foreground_value: 255"),
      P("Every ZIP contains ", h("code", {}, "manifest.json"), " (who annotated and approved each image, which version, SHA-256 of every file, class pixel counts) and a plain-language ", h("code", {}, "README.txt"), "."),
    ],
  },
  {
    id: "projects",
    title: "Projects, images and classes",
    body: () => [
      h("h3", {}, "Creating a project (administrators)"),
      P("Projects → New project. Give it a name, the classes (name, colour, a sentence on what counts) and guidelines. Class numbers are the mask values and cannot be renumbered later, but names and colours can change."),
      h("h3", {}, "Uploading images"),
      P("Images tab → Upload images. PNG, JPEG, TIFF (8- or 16-bit) and BMP are accepted. Duplicates are recognised by content and skipped. The original file is kept byte-for-byte; 16-bit or TIFF images get a display copy whose contrast scaling is recorded."),
      h("h3", {}, "Starting from masks you already have"),
      P("You do not have to label from scratch. If a mask for an image already exists — from another segmentation tool, an in-house script such as your own hydride segmentation program, or a model prediction — import it in Annotate mode and correct its mistakes instead."),
      P("For a whole folder: Images tab → Import masks. Name masks after their images (", h("code", {}, "x_mask.png"), ", or HydrideSegmentation's ", h("code", {}, "x_mask_labels.png"), " and ", h("code", {}, "x_mask_preview.png"), "). For the single image you are annotating: side panel → Mask source → Import a mask."),
      P("A mask must be exactly the size of its image. One of a different size is refused rather than resized, because resizing would change the ground truth."),
      h("h3", {}, "How a mask file is read"),
      P("Class numbers and display values are different things. A label map stores the class number in every pixel (0 = background, 1 = the first class, …). A black-and-white PNG usually stores 255 for the foreground only so that people can see it. As soon as you choose a file, the import dialog shows what it detected, which values become which class, the foreground share and any warning, before anything is stored."),
      h("ul", {},
        h("li", {}, B("Auto detect"), " (the default), in this order: a mask whose values are all class numbers of the project is kept exactly (0 and 2 stays class 2); 0/1 and 0/255 masks become the class you choose; the project's exact class colours become those classes; red on black becomes the class you choose; a palette PNG is read by its indices when they are class numbers, otherwise by its colours."),
        h("li", {}, B("It asks first"), " when a file could mean two things: only 0 and one other value such as 128 or 7 (a foreground, or a class number from another project?), a red mask with soft edges, or a palette PNG whose colours tell a different story than its indices. Tick the confirmation after checking the preview."),
        h("li", {}, B("It never guesses"), " for greyscale or probability images with many levels. Choose ", B("Grayscale threshold"), ", check the suggested threshold and the foreground share in the preview, then confirm."),
        h("li", {}, B("Indexed"), ", ", B("Binary"), " and ", B("Colour"), " force one reading. ", B("Foreground is black"), " swaps foreground and background for masks drawn black on white.")),
      P("A refusal says what was found and what to do next: a value that is not one of the project's classes, a photograph or overlay instead of a mask, a mask of the wrong size, or the image itself chosen by mistake."),
      h("h3", {}, "Recording where a mask came from"),
      P("When you import, say which tool produced the mask and add any remarks worth keeping — the model version, the settings, known weaknesses such as missed faint tips. The image is then marked ", B("Imported"), " instead of drawn here."),
      P("That record is deliberately sticky: correcting an imported mask by hand does not turn it into hand-drawn work. It is frozen into every version you submit and written into the export manifest as ", h("code", {}, "mask_source"), ", ", h("code", {}, "mask_source_tool"), ", ", h("code", {}, "mask_source_remarks"), " and ", h("code", {}, "mask_import"), " (how the file was read: detected encoding, value-to-class mapping, threshold, warnings and whether you confirmed), so anyone training on the dataset later can tell corrected machine output from ground truth drawn from scratch. You can fix the wording at any time with Edit remarks."),
      h("h3", {}, "Splits and assignments"),
      P("Tick images in the gallery to set their train/val/test split or assign them to a person. Assigned images come first in that person's Annotate next. Anyone can do this, in either mode."),
    ],
  },
  {
    id: "admin",
    title: "Accounts and administration",
    body: () => [
      P("Administrators manage accounts under ", B("Users"), ". A new account gets a temporary password, shown once, which the person must change at first sign-in. Resetting a password works the same way."),
      P("Every account can annotate and review. Tick ", B("Administrator"), " to also let someone manage projects, classes and accounts. The Users page shows each person's current working mode, but only the person themselves switches it: it is not a permission."),
      P("Disabling an account signs the person out everywhere but keeps all their work and history."),
      P("Every action is recorded in the project's Activity tab and in the server's append-only audit file."),
      h("p", { class: "muted small" }, "Server operators: see README.md and docs/DEPLOYMENT.md in the repository for configuration, backups and upgrades."),
    ],
  },
  {
    id: "faq",
    title: "Troubleshooting",
    body: () => [
      faq("I cannot find the Approve button.", "Approve and Request changes appear in Review mode, on images someone else submitted. Switch to Review at the top of the page and press Review next."),
      faq("My own submission is not in Review next.", "That is on purpose: another person reviews your work. It is listed as yours waiting for someone else. To change it, switch to Annotate, open it and press Withdraw to edit."),
      faq("The drawing tools are greyed out.", "In Review mode only submissions from other people can be edited, as review corrections; switch to Annotate to edit anything else. Tools are also disabled while someone else is editing the image, and on approved images until you press Edit anyway."),
      faq("It says someone else is editing the image.", "They have it open. Pick another image; the reservation expires a few minutes after they leave or close the tab."),
      faq("'Your editing session expired'.", "The reservation lapsed, for example after the computer slept. Click Re-open for editing; unsaved strokes are kept in the tab and saved as soon as you can edit again."),
      faq("'The saved annotation changed since you opened it'.", "Someone saved this image after you opened it (for example an administrator released your reservation). Load the latest version and redo your last changes."),
      faq("The magic wand fills far too much.", "Lower the tolerance, zoom in and click a darker part of the feature, or use the box threshold instead."),
      faq("I submitted too early.", "In Annotate mode, open the image and press Withdraw to edit, as long as nobody has reviewed it yet."),
      faq("Why is my image not in the export?", "By default only approved images are exported. The export page lists how many were left out and why."),
      faq("The picture looks too dark or low-contrast.", "Use Brightness and Contrast in the View panel. They change only the screen, never the image or the labels."),
    ],
  },
  {
    id: "shortcuts",
    title: "Keyboard shortcuts",
    body: () => [shortcutsTable()],
  },
];

function toolRow(iconName, title, text) {
  return h("div", { class: "tool-row" }, h("span", { class: "tool-icon" }, icon(iconName, 22)), h("div", {}, h("strong", {}, title), h("p", {}, text)));
}

function faq(q, a) {
  return h("details", { class: "faq" }, h("summary", {}, q), h("p", {}, a));
}

export function renderHelp(view, sectionId) {
  const section = SECTIONS.find((s) => s.id === sectionId) || SECTIONS[0];
  setCrumbs([{ label: "Help", href: "#/help" }, { label: section.title }]);
  const nav = h("nav", { class: "help-nav", "aria-label": "Help sections" },
    SECTIONS.map((s) => h("a", { href: `#/help/${s.id}`, class: s.id === section.id ? "active" : "" }, s.title)),
    h("div", { class: "muted small help-version" }, app.meta ? `Version ${app.meta.version}` : ""));
  const content = h("article", { class: "help-content" }, h("h1", {}, section.title), ...section.body());
  const back = app.me ? null : h("p", {}, h("a", { href: "#/login" }, "← Back to sign in"));
  clear(view).append(h("div", { class: "page help-page" }, back, h("div", { class: "help-layout" }, nav, content)));
  return {};
}
