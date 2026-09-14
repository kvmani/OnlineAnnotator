// Two ordinary users alternately annotate and review each other's work, each switching the
// working mode from the top bar. Neither of them is an "annotator" or a "reviewer":
//
//   Arun annotates -> saves -> submits -> Riya switches to Review -> corrects -> approves
//   Arun annotates -> submits -> Riya requests changes -> Arun fixes, resubmits -> Riya approves
//   Riya annotates -> submits -> Arun switches to Review -> approves
//
// plus own-submission protection, the remembered mode, switching mode with unsaved work in
// the workspace, and administrator rights that do not depend on the mode.
// The journeys share one project and run in order (run: npm run test:browser).
import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const ALLOWED_CONSOLE = [/status of 401/, /status of 423/];
const PROJECT = `E2E two people ${Date.now()}`;

let arun, riya, projectId, projectUrl;
const problems = [];
const image = {}; // name -> workspace URL

function watchConsole(page, who) {
  page.on("pageerror", (err) => problems.push(`${who} pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !ALLOWED_CONSOLE.some((re) => re.test(msg.text()))) problems.push(`${who}: ${msg.text()}`);
  });
}

async function signIn(page, email) {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(email) }).click();
  await expect(page.locator(".user-chip")).toBeVisible();
}

async function setMode(page, label) {
  const radio = page.getByRole("radio", { name: label });
  if ((await radio.getAttribute("aria-checked")) !== "true") await radio.click();
  await expect(radio).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("body")).toHaveClass(new RegExp(`mode-${label.toLowerCase()}`));
}

async function openProject(page) {
  // A fresh load, so the page shows what the other person has just done even when it is
  // already the current URL (going to the same hash would not redraw it).
  await page.goto(projectUrl);
  await page.reload();
  await expect(page.getByRole("heading", { name: PROJECT })).toBeVisible();
}

async function openedImage(page) {
  await expect(page).toHaveURL(/#\/p\/\d+\/i\/\d+/);
  await expect(page.locator(".ws-loading")).toHaveCount(0, { timeout: 15_000 });
  return page.url();
}

async function paintStroke(page, { dx = 80, dy = 0 } = {}) {
  const box = await page.locator(".editor-canvas").boundingBox();
  const x = box.x + box.width / 2, y = box.y + box.height / 2 + dy;
  await page.mouse.move(x - dx, y);
  await page.mouse.down();
  for (let k = 1; k <= 12; k++) await page.mouse.move(x - dx + (2 * dx * k) / 12, y + k);
  await page.mouse.up();
}

async function submit(page, note) {
  await page.getByRole("button", { name: "Submit for review" }).click();
  const dialog = page.getByRole("dialog", { name: "Submit for review" });
  await dialog.locator("textarea").fill(note);
  await dialog.getByRole("button", { name: "Submit", exact: true }).click();
  await expect(page.locator(".toast", { hasText: "Submitted for review" })).toBeVisible();
}

async function backToProject(page) {
  await page.locator(".ws-top").getByRole("link", { name: "Back to the project" }).click();
  await expect(page.getByRole("heading", { name: PROJECT })).toBeVisible();
}

// What the server says about an image, read through the signed-in page's own session.
async function serverImage(page, url) {
  const id = Number(url.split("/i/")[1]);
  return page.evaluate(async (i) => (await (await fetch(`api/v1/images/${i}`)).json()).image, id);
}

test.beforeAll(async ({ browser }) => {
  arun = await (await browser.newContext()).newPage();
  riya = await (await browser.newContext()).newPage();
  watchConsole(arun, "arun");
  watchConsole(riya, "riya");

  // An administrator prepares a project with three images of its own, so these journeys
  // do not depend on the demo project.
  const admin = await (await browser.newContext()).newPage();
  await signIn(admin, "admin@demo.local");
  projectId = await admin.evaluate(async (name) => {
    const headers = { "X-Requested-With": "OnlineAnnotator" };
    const created = await fetch("api/v1/projects", {
      method: "POST", headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ name, classes: [{ name: "Hydride", color: "#FF0000" }] }),
    });
    const { project } = await created.json();
    const fd = new FormData();
    for (const [stem, shade] of [["pair_a", "#b0b0b0"], ["pair_b", "#c0c0c0"], ["pair_c", "#d0d0d0"]]) {
      const c = document.createElement("canvas");
      c.width = 160;
      c.height = 120;
      const g = c.getContext("2d");
      g.fillStyle = shade;
      g.fillRect(0, 0, 160, 120);
      g.fillStyle = "#222";
      g.fillRect(10, 55, 140, 5);
      fd.append("files", new File([await new Promise((r) => c.toBlob(r, "image/png"))], `${stem}.png`, { type: "image/png" }));
    }
    const uploaded = await (await fetch(`api/v1/projects/${project.id}/images`, { method: "POST", headers, body: fd })).json();
    if (uploaded.added !== 3) throw new Error(JSON.stringify(uploaded));
    return project.id;
  }, PROJECT);
  projectUrl = `/#/p/${projectId}`;
  await admin.context().close();

  await signIn(arun, "arun@demo.local");
  await signIn(riya, "riya@demo.local");
});

test.afterAll(async () => {
  await arun.context().close();
  await riya.context().close();
});

test("an ordinary user switches between Annotate and Review and the choice is remembered", async ({ browser }) => {
  await setMode(arun, "Annotate");
  await openProject(arun);
  await expect(arun.locator(".mode-note")).toContainText("Annotate mode");
  await expect(arun.locator(".head-actions").getByRole("button", { name: "Annotate next" })).toBeEnabled();
  await expect(arun.getByRole("link", { name: "Users" })).toHaveCount(0); // no administration

  // The page redraws for the new mode without signing out.
  await setMode(arun, "Review");
  await expect(arun.locator(".mode-note")).toContainText("Review mode");
  await expect(arun.locator(".head-actions").getByRole("button", { name: /Review next/ })).toBeDisabled();
  await expect(arun.getByRole("button", { name: "Import masks" })).toBeDisabled();
  await expect(arun.locator(".chip.active")).toContainText("For me to review");

  // Remembered after a reload, and on a fresh sign-in somewhere else.
  await arun.reload();
  await expect(arun.getByRole("radio", { name: "Review" })).toHaveAttribute("aria-checked", "true");
  const elsewhere = await (await browser.newContext()).newPage();
  await signIn(elsewhere, "arun@demo.local");
  await expect(elsewhere.getByRole("radio", { name: "Review" })).toHaveAttribute("aria-checked", "true");
  await elsewhere.context().close();

  await setMode(arun, "Annotate");
  await expect(arun.locator(".head-actions").getByRole("button", { name: "Annotate next" })).toBeVisible();
});

test("Arun annotates and submits; Riya switches to Review, corrects and approves", async () => {
  await openProject(arun);
  await arun.locator(".head-actions").getByRole("button", { name: "Annotate next" }).click();
  image.a = await openedImage(arun);
  await paintStroke(arun);
  await expect(arun.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  await submit(arun, "Arun: first image, main platelet traced.");
  await expect.poll(() => arun.url()).not.toBe(image.a); // the next image opens
  await openedImage(arun);
  await backToProject(arun);

  // Arun cannot review his own submission: it is not offered, and opening it is view-only.
  await setMode(arun, "Review");
  await expect(arun.locator(".mode-note")).toContainText("1 submission of yours is waiting for someone else");
  await expect(arun.locator(".head-actions").getByRole("button", { name: /Review next/ })).toBeDisabled();
  await expect(arun.locator(".image-grid")).toContainText("Nothing from other people is waiting for your review");
  await arun.locator(".filter-chips").getByRole("button", { name: /^All/ }).click();
  await expect(arun.locator(".image-card .tag", { hasText: "yours" })).toHaveCount(1);
  await arun.goto(image.a);
  await openedImage(arun);
  await expect(arun.locator(".ws-banner")).toContainText("This is your own submission");
  await expect(arun.locator(".ws-actions").getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(arun.getByRole("button", { name: "Brush" })).toBeDisabled();

  // Riya reviews it.
  await setMode(riya, "Review");
  await openProject(riya);
  const reviewNext = riya.locator(".head-actions").getByRole("button", { name: "Review next (1)" });
  await expect(reviewNext).toBeEnabled();
  await expect(riya.locator(".chip.active")).toContainText("For me to review");
  await expect(riya.locator(".image-card")).toHaveCount(1);
  await reviewNext.click();
  await expect(riya).toHaveURL(image.a);
  await openedImage(riya);
  await expect(riya.locator(".ws-banner")).toContainText("Arun: first image");

  await riya.keyboard.press("b");
  await paintStroke(riya, { dx: 50, dy: 70 }); // a real correction, away from Arun's stroke
  await expect(riya.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  await riya.locator(".ws-actions").getByRole("button", { name: "Approve" }).click();
  const dialog = riya.getByRole("dialog", { name: "Approve as ground truth" });
  await expect(dialog).toContainText("You corrected the labels");
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(riya).toHaveURL(new RegExp(`#/p/${projectId}$`)); // nothing else waits for her

  const approved = await serverImage(riya, image.a);
  expect(approved.status).toBe("approved");
  expect([approved.versions[0].kind, approved.versions[0].created_by, approved.versions[0].reviewed_by])
    .toEqual(["reviewer_edit", "riya@demo.local", "riya@demo.local"]);
  expect([approved.versions[1].status, approved.versions[1].created_by]).toEqual(["superseded", "arun@demo.local"]);
});

test("Riya requests changes; Arun fixes and resubmits; Riya approves", async () => {
  await setMode(arun, "Annotate");
  await openProject(arun);
  await arun.locator(".head-actions").getByRole("button", { name: "Annotate next" }).click();
  image.b = await openedImage(arun);
  await paintStroke(arun);
  await expect(arun.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  await submit(arun, "Arun: second image.");
  await openedImage(arun);
  await backToProject(arun);

  await openProject(riya);
  await riya.locator(".head-actions").getByRole("button", { name: "Review next (1)" }).click();
  await expect(riya).toHaveURL(image.b);
  await openedImage(riya);
  await expect(riya.locator(".ws-banner")).toContainText("Arun: second image");
  await riya.locator(".ws-actions").getByRole("button", { name: "Request changes" }).click();
  const returnDialog = riya.getByRole("dialog", { name: "Request changes" });
  await returnDialog.locator("textarea").fill("Please also label the lower platelet.");
  await returnDialog.getByRole("button", { name: "Send back" }).click();
  await expect(riya).toHaveURL(new RegExp(`#/p/${projectId}$`));

  // Returned work comes first in Arun's Annotate next, with Riya's comment.
  await openProject(arun);
  await arun.locator(".head-actions").getByRole("button", { name: "Annotate next" }).click();
  await expect(arun).toHaveURL(image.b);
  await openedImage(arun);
  await expect(arun.locator(".ws-banner")).toContainText("Please also label the lower platelet.");
  await paintStroke(arun, { dx: 60, dy: 70 });
  await expect(arun.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  await submit(arun, "Arun: lower platelet added.");
  await openedImage(arun);
  await backToProject(arun);

  await openProject(riya);
  await riya.locator(".head-actions").getByRole("button", { name: "Review next (1)" }).click();
  await openedImage(riya);
  await expect(riya.locator(".ws-banner")).toContainText("lower platelet added");
  await riya.locator(".ws-actions").getByRole("button", { name: "Approve" }).click();
  const dialog = riya.getByRole("dialog", { name: "Approve as ground truth" });
  await expect(dialog).toContainText("The submitted labels become ground truth");
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(riya).toHaveURL(new RegExp(`#/p/${projectId}$`));

  const approved = await serverImage(riya, image.b);
  expect(approved.status).toBe("approved");
  expect(approved.versions.map((v) => [v.status, v.created_by, v.reviewed_by])).toEqual([
    ["approved", "arun@demo.local", "riya@demo.local"],
    ["changes_requested", "arun@demo.local", "riya@demo.local"],
  ]);
});

test("the other way round: Riya annotates and submits, Arun switches to Review and approves", async () => {
  await setMode(riya, "Annotate");
  await expect(riya.locator(".head-actions").getByRole("button", { name: "Annotate next" })).toBeVisible();
  await riya.locator(".head-actions").getByRole("button", { name: "Annotate next" }).click();
  image.c = await openedImage(riya);
  await paintStroke(riya);
  await expect(riya.locator(".save-state")).toContainText("Saved", { timeout: 10_000 });
  await submit(riya, "Riya: third image.");
  await expect(riya).toHaveURL(new RegExp(`#/p/${projectId}$`)); // nothing left to annotate

  await openProject(arun);
  await setMode(arun, "Review");
  await arun.locator(".head-actions").getByRole("button", { name: "Review next (1)" }).click();
  await expect(arun).toHaveURL(image.c);
  await openedImage(arun);
  await expect(arun.locator(".ws-banner")).toContainText("Riya: third image");
  await arun.locator(".ws-actions").getByRole("button", { name: "Approve" }).click();
  await arun.getByRole("dialog", { name: "Approve as ground truth" }).getByRole("button", { name: "Approve" }).click();
  await expect(arun).toHaveURL(new RegExp(`#/p/${projectId}$`));

  const approved = await serverImage(arun, image.c);
  expect([approved.status, approved.versions[0].created_by, approved.versions[0].reviewed_by])
    .toEqual(["approved", "riya@demo.local", "arun@demo.local"]);
});

test("switching mode in the workspace saves unsaved work, releases the image and redraws it", async () => {
  // Arun is in Review mode: an approved image is view-only and offers the way to Annotate.
  await arun.goto(image.c);
  await openedImage(arun);
  await expect(arun.locator(".ws-banner")).toContainText("not waiting for review");
  await arun.locator(".ws-banner").getByRole("button", { name: "Switch to Annotate mode" }).click();
  await expect(arun.getByRole("radio", { name: "Annotate" })).toHaveAttribute("aria-checked", "true");
  await expect(arun.locator(".ws-banner")).toContainText("Edit anyway");

  await arun.locator(".ws-banner").getByRole("button", { name: "Edit anyway" }).click();
  await arun.getByRole("dialog", { name: "Edit an approved image?" }).getByRole("button", { name: "Edit anyway" }).click();
  await expect(arun.getByRole("button", { name: "Brush" })).toBeEnabled();
  const before = await serverImage(arun, image.c);
  await paintStroke(arun, { dx: 40, dy: -70 });
  await expect(arun.locator(".save-state")).toContainText("Unsaved changes");

  // Switch straight away, before autosave: the stroke is saved and the reservation released.
  await arun.getByRole("radio", { name: "Review" }).click();
  await expect(arun.getByRole("radio", { name: "Review" })).toHaveAttribute("aria-checked", "true");
  await expect(arun.locator(".ws-banner")).toContainText("not waiting for review");
  await expect(arun.locator(".save-state")).toHaveText("View only");
  const after = await serverImage(arun, image.c);
  expect(after.working_revision).toBe(before.working_revision + 1);
  expect(after.status).toBe("in_progress");
  expect(after.versions.find((v) => v.status === "approved")).toBeTruthy(); // ground truth kept
  // The release is sent as the page leaves, so wait for it rather than reading once.
  await expect.poll(async () => (await serverImage(arun, image.c)).lock.locked).toBe(false);
  expect(problems).toEqual([]);
});

test("an administrator keeps administration in both modes", async ({ browser }) => {
  const admin = await (await browser.newContext()).newPage();
  await signIn(admin, "admin@demo.local");
  for (const label of ["Review", "Annotate"]) {
    await setMode(admin, label);
    await admin.goto("/#/");
    await expect(admin.getByRole("link", { name: "Users" })).toBeVisible();
    await expect(admin.getByRole("button", { name: "New project" })).toBeVisible();
    await admin.goto(`${projectUrl}/settings`);
    await expect(admin.getByRole("button", { name: "Save changes" })).toBeVisible();
  }
  await admin.goto("/#/users");
  const arunRow = admin.locator("tr", { hasText: "arun@demo.local" });
  await expect(arunRow.locator(".mode-tag")).toHaveText("Review"); // each person's own choice, shown
  await expect(arunRow.getByRole("checkbox")).not.toBeChecked();
  await admin.context().close();
});
