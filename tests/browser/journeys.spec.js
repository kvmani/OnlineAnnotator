// End-to-end user journeys in a real browser (run: npm run test:browser).
// They replay, click for click, the manual acceptance tests: an annotator labels and
// submits, a reviewer approves and exports, two people collide on one image, an
// administrator sets up a project and uploads images, and a newcomer finds help.
import { expect, test } from "@playwright/test";

const ALLOWED_CONSOLE = [/status of 401/, /status of 423/];

function watchConsole(page) {
  const problems = [];
  page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !ALLOWED_CONSOLE.some((re) => re.test(msg.text()))) problems.push(msg.text());
  });
  return problems;
}

async function signIn(page, email) {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(email) }).click();
  await expect(page.locator(".user-chip")).toBeVisible();
}

async function openedImage(page) {
  await expect(page).toHaveURL(/#\/p\/\d+\/i\/\d+/);
  await expect(page.locator(".ws-loading")).toHaveCount(0, { timeout: 15_000 });
  return page.url();
}

async function paintStroke(page, dx = 80) {
  const box = await page.locator(".editor-canvas").boundingBox();
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.mouse.move(x - dx, y);
  await page.mouse.down();
  for (let k = 1; k <= 12; k++) await page.mouse.move(x - dx + (2 * dx * k) / 12, y + k);
  await page.mouse.up();
}

test("a newcomer can read the help centre before signing in", async ({ page }) => {
  const problems = watchConsole(page);
  await page.goto("/#/help");
  await expect(page.getByRole("heading", { name: "Getting started" })).toBeVisible();
  for (const section of ["Drawing tools", "Reviewing", "Exporting datasets", "Troubleshooting", "Keyboard shortcuts"]) {
    await page.locator(".help-nav").getByRole("link", { name: section }).click();
    await expect(page.locator(".help-content h1")).toHaveText(section);
  }
  await page.goto("/help"); // the portal links here
  await expect(page).toHaveURL(/#\/help/);
  expect(problems).toEqual([]);
});

test("an annotator labels an image, sees it saved, and submits it", async ({ page }) => {
  const problems = watchConsole(page);
  await signIn(page, "annotator@demo.local");
  await expect(page.getByRole("heading", { name: "How it works" })).toBeVisible();
  await page.locator(".project-card").getByRole("button", { name: "Annotate next" }).click();
  const first = await openedImage(page);
  await expect(page.locator(".ws-hint")).toContainText("Brush");

  await paintStroke(page);
  await expect(page.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  await expect(page.locator(".ws-title .badge")).toHaveText("In progress");
  await expect(page.locator('[data-cov="1"]')).not.toHaveText("");

  // A stroke paints a continuous band, not just the disc where it started.
  const covered = await page.locator('[data-cov="1"]').getAttribute("title");
  expect(Number(covered.replace(/\D/g, ""))).toBeGreaterThan(500);

  // Undo and redo are exact.
  await page.keyboard.press("Control+z");
  await expect(page.locator('[data-cov="1"]')).toHaveText("");
  await page.keyboard.press("Control+y");
  await expect(page.locator('[data-cov="1"]')).toHaveAttribute("title", covered);

  await page.getByRole("button", { name: "Submit for review" }).click();
  const dialog = page.getByRole("dialog", { name: "Submit for review" });
  await expect(dialog).toContainText("Labelled area on this image");
  await dialog.locator("textarea").fill("Main platelet traced; faint tips uncertain.");
  await dialog.getByRole("button", { name: "Submit", exact: true }).click();
  await expect(page.locator(".toast").first()).toContainText("Submitted for review");
  await expect.poll(() => page.url()).not.toBe(first);
  expect(problems).toEqual([]);
});

test("a reviewer corrects, approves and exports a HydrideSegmentation dataset", async ({ page }) => {
  const problems = watchConsole(page);
  await signIn(page, "reviewer@demo.local");
  await page.locator(".project-card").getByRole("button", { name: "Review next" }).click();
  await openedImage(page);
  await expect(page.locator(".ws-banner")).toContainText("Main platelet traced");

  await page.keyboard.press("b");
  await paintStroke(page, 40);
  await expect(page.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  await page.locator(".ws-actions").getByRole("button", { name: "Approve" }).click();
  const dialog = page.getByRole("dialog", { name: "Approve as ground truth" });
  await expect(dialog).toContainText("You corrected the labels");
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(page).toHaveURL(/#\/p\/1$/);

  await page.getByRole("tab", { name: "Export dataset" }).click();
  await expect(page.locator(".export-preview")).toContainText("1 image will be exported");
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Create export" }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/\.zip$/);
  const bytes = await (await import("node:fs/promises")).readFile(await download.path());
  const text = bytes.toString("latin1");
  for (const name of ["manifest.json", "README.txt", "_mask.png", "pairs/"]) expect(text).toContain(name);
  await expect(page.locator(".export-item")).toHaveCount(1);
  expect(problems).toEqual([]);
});

test("two people cannot edit the same image at once", async ({ browser }) => {
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();
  await signIn(a, "annotator@demo.local");
  await a.locator(".project-card").getByRole("button", { name: "Annotate next" }).click();
  const url = await openedImage(a);

  await signIn(b, "reviewer@demo.local");
  await b.goto(url);
  await openedImage(b);
  await expect(b.locator(".ws-banner")).toContainText("is editing this image");
  await expect(b.locator(".save-state")).toHaveText("View only");
  await expect(b.getByRole("button", { name: "Brush" })).toBeDisabled();

  // When the annotator leaves, the reviewer can take over.
  await a.locator(".ws-top").getByRole("link", { name: "Back to the project" }).click();
  await expect(a).toHaveURL(/#\/p\/1$/);
  await b.getByRole("button", { name: "Try again" }).click();
  await expect(b.getByRole("button", { name: "Brush" })).toBeEnabled();
});

test("an administrator creates a project, adds a user and uploads images", async ({ page }) => {
  const problems = watchConsole(page);
  await signIn(page, "admin@demo.local");
  // The portal link is host-relative (":5000/"), so it works from every desk.
  await expect(page.getByRole("link", { name: "All tools" })).toHaveAttribute("href", "http://127.0.0.1:5000/");

  await page.getByRole("link", { name: "Users" }).click();
  await page.getByRole("button", { name: "Add user" }).click();
  const add = page.getByRole("dialog", { name: "Add user" });
  await add.getByLabel("Office e-mail").fill("new.person@lab.example");
  await add.getByLabel("Full name").fill("New Person");
  await add.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("dialog", { name: "Temporary password" })).toContainText("new.person@lab.example");
  await page.getByRole("button", { name: "Done" }).click();

  await page.goto("/#/");
  await page.getByRole("button", { name: "New project" }).click();
  const wizard = page.getByRole("dialog", { name: "New project" });
  await wizard.getByLabel("Project name").fill("E2E grain boundaries");
  await wizard.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: "E2E grain boundaries" })).toBeVisible();
  await expect(page.locator(".empty")).toContainText("No images yet");

  await page.locator(".empty").getByRole("button", { name: "Upload images" }).click();
  await page.evaluate(async () => {
    const make = async (shade) => {
      const c = document.createElement("canvas");
      c.width = 120;
      c.height = 90;
      const g = c.getContext("2d");
      g.fillStyle = shade;
      g.fillRect(0, 0, 120, 90);
      g.fillStyle = "#222";
      g.fillRect(10, 40, 100, 4);
      return new Promise((r) => c.toBlob(r, "image/png"));
    };
    const dt = new DataTransfer();
    dt.items.add(new File([await make("#bbb")], "area 1.png", { type: "image/png" }));
    dt.items.add(new File([await make("#ccc")], "area_2_mask.png", { type: "image/png" }));
    dt.items.add(new File(["x"], "readme.txt", { type: "text/plain" }));
    document.querySelector(".dropzone").dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  const upload = page.getByRole("dialog", { name: /Upload images/ });
  await upload.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(upload.locator(".alert")).toContainText("2 images added");
  await expect(upload.locator(".alert")).toContainText("readme.txt: unsupported file type");
  await upload.getByRole("button", { name: "Close" }).first().click();
  await expect(page.locator(".image-card")).toHaveCount(2);
  await expect(page.locator(".image-card-title")).toContainText(["area_1", "area_2-mask"]);
  expect(problems).toEqual([]);
});

test("every button has an accessible name", async ({ page }) => {
  await signIn(page, "admin@demo.local");
  for (const hash of ["#/", "#/p/1", "#/p/1/export", "#/users", "#/help"]) {
    await page.goto(`/${hash}`);
    await page.waitForTimeout(600);
    const unnamed = await page.$$eval("button", (buttons) =>
      buttons.filter((b) => b.offsetParent !== null && !(b.getAttribute("aria-label") || b.textContent.trim() || b.title)).map((b) => b.outerHTML.slice(0, 80)));
    expect(unnamed, hash).toEqual([]);
  }
});

test("an annotator imports an existing mask, corrects it and the source is recorded", async ({ page }) => {
  const problems = watchConsole(page);
  await signIn(page, "admin@demo.local");

  // A project with one image of a size we control, so the mask can match it exactly.
  await page.goto("/#/");
  await page.getByRole("button", { name: "New project" }).click();
  const wizard = page.getByRole("dialog", { name: "New project" });
  await wizard.getByLabel("Project name").fill("E2E imported masks");
  await wizard.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: "E2E imported masks" })).toBeVisible();

  await page.locator(".empty").getByRole("button", { name: "Upload images" }).click();
  await page.evaluate(async () => {
    const c = document.createElement("canvas");
    c.width = 120;
    c.height = 90;
    const g = c.getContext("2d");
    g.fillStyle = "#bbb";
    g.fillRect(0, 0, 120, 90);
    g.fillStyle = "#222";
    g.fillRect(10, 40, 100, 6);
    const blob = await new Promise((r) => c.toBlob(r, "image/png"));
    const dt = new DataTransfer();
    dt.items.add(new File([blob], "hydride field.png", { type: "image/png" }));
    document.querySelector(".dropzone").dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
  });
  const upload = page.getByRole("dialog", { name: /Upload images/ });
  await upload.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(upload.locator(".alert")).toContainText("1 image added");
  await upload.getByRole("button", { name: "Close" }).first().click();

  // Open it: nothing is labelled yet and the panel says so.
  await page.locator(".image-card").first().click();
  await openedImage(page);
  await expect(page.locator(".ws-side")).toContainText("Drawn here from scratch");

  // Import a black-and-white mask produced by some other tool.
  await page.getByRole("button", { name: "Import a mask…" }).click();
  const dialog = page.getByRole("dialog", { name: "Import an existing mask" });
  await expect(dialog).toContainText("120 × 90");
  await dialog.evaluate(async (root) => {
    const c = document.createElement("canvas");
    c.width = 120;
    c.height = 90;
    const g = c.getContext("2d");
    g.fillStyle = "#000";
    g.fillRect(0, 0, 120, 90);
    g.fillStyle = "#fff";
    g.fillRect(10, 40, 100, 6);
    const blob = await new Promise((r) => c.toBlob(r, "image/png"));
    const input = root.querySelector('input[type="file"]');
    const dt = new DataTransfer();
    dt.items.add(new File([blob], "hydride field_mask.png", { type: "image/png" }));
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await dialog.locator('input[type="text"]').fill("HydrideSegmentation v2.3");
  await dialog.locator("textarea").fill("Model run of 2026-09-10; misses faint tips.");
  await dialog.getByRole("button", { name: "Import", exact: true }).click();

  // Match the toast by its text, not by position: an earlier toast ("Project created")
  // can still be on screen, and which one is first is a race.
  await expect(page.locator(".toast", { hasText: "binary mask" })).toBeVisible();
  await expect(page.locator(".ws-side")).toContainText("Imported mask, corrected here");
  await expect(page.locator(".ws-side")).toContainText("HydrideSegmentation v2.3");
  await expect(page.locator(".ws-side")).toContainText("misses faint tips");
  // The imported pixels are on the canvas, so there is coverage before any drawing.
  await expect(page.locator('[data-cov="1"]')).not.toHaveText("");
  const beforeCorrection = await page.locator('[data-cov="1"]').getAttribute("title");

  // Correcting it by hand must not turn it back into hand-drawn work.
  await paintStroke(page, 30);
  await expect(page.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  expect(await page.locator('[data-cov="1"]').getAttribute("title")).not.toEqual(beforeCorrection);
  await expect(page.locator(".ws-side")).toContainText("Imported mask, corrected here");

  // The remarks can be corrected afterwards.
  await page.getByRole("button", { name: "Edit remarks…" }).click();
  const remarksDialog = page.getByRole("dialog", { name: /Remarks about the imported mask/ });
  await remarksDialog.locator("textarea").fill("Re-run with the fixed threshold.");
  await remarksDialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator(".ws-side")).toContainText("Re-run with the fixed threshold");

  expect(problems).toEqual([]);
});
