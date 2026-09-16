// Tool values and the polygon threshold in a real browser (run: npm run test:browser).
// A user types an exact brush size, changes it with [ and ] without leaving the image, paints a
// single pixel, and labels a dark feature with the polygon threshold while a bright bar next to
// it stays outside the outline. The image is drawn here, so every pixel count is known.
import { expect, test } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const ALLOWED_CONSOLE = [/status of 401/, /status of 423/];
const PROJECT = `E2E tools ${Date.now()}`;
const W = 320, H = 240;
// Matrix grey 150, a dark feature (grey 40) of 100 x 40 px, a bright bar (grey 250) on the right.
const FEATURE = { x: 40, y: 100, w: 100, h: 40 };

let page;
const problems = [];

test.beforeAll(async ({ browser }) => {
  page = await (await browser.newContext()).newPage();
  page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !ALLOWED_CONSOLE.some((re) => re.test(msg.text()))) problems.push(msg.text());
  });
  await page.goto("/");
  await page.getByRole("button", { name: /admin@demo.local/ }).click();
  await expect(page.locator(".user-chip")).toBeVisible();
  const annotate = page.getByRole("radio", { name: "Annotate" });
  if ((await annotate.getAttribute("aria-checked")) !== "true") await annotate.click();
  await expect(annotate).toHaveAttribute("aria-checked", "true");
  const url = await page.evaluate(async ({ name, W, H, F }) => {
    const headers = { "X-Requested-With": "OnlineAnnotator" };
    const created = await fetch("api/v1/projects", {
      method: "POST", headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ name, classes: [{ name: "Hydride", color: "#FF0000" }] }),
    });
    const { project } = await created.json();
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const g = c.getContext("2d");
    g.fillStyle = "#969696";
    g.fillRect(0, 0, W, H);
    g.fillStyle = "#282828";
    g.fillRect(F.x, F.y, F.w, F.h);
    g.fillStyle = "#fafafa";
    g.fillRect(220, 0, 100, H);
    const fd = new FormData();
    fd.append("files", new File([await new Promise((r) => c.toBlob(r, "image/png"))], "tools.png", { type: "image/png" }));
    const uploaded = await (await fetch(`api/v1/projects/${project.id}/images`, { method: "POST", headers, body: fd })).json();
    if (uploaded.added !== 1) throw new Error(JSON.stringify(uploaded));
    const { images } = await (await fetch(`api/v1/projects/${project.id}/images`)).json();
    return `/#/p/${project.id}/i/${images[0].id}`;
  }, { name: PROJECT, W, H, F: FEATURE });
  await page.goto(url);
  await expect(page.locator(".ws-loading")).toHaveCount(0, { timeout: 15_000 });
});

test.afterAll(async () => {
  await page.context().close();
});

// Screen position of an image pixel coordinate (the workspace opens fitted to the window).
async function screen(x, y) {
  const box = await page.locator(".editor-canvas").boundingBox();
  const s = Math.min((box.width - 48) / W, (box.height - 48) / H);
  return [box.x + (box.width - W * s) / 2 + x * s, box.y + (box.height - H * s) / 2 + y * s];
}

async function labelledPixels() {
  const title = await page.locator('[data-cov="1"]').getAttribute("title");
  return Number((title || "0").replace(/\D/g, ""));
}

test("brush size can be typed, changed with [ and ], and is shared with the eraser", async () => {
  await page.keyboard.press("b");
  await expect(page.locator(".ws-hint")).toContainText("Brush");
  const size = page.getByRole("spinbutton", { name: "Brush diameter in pixels" });
  const slider = page.getByRole("slider", { name: "Brush diameter" });

  await size.fill("15");
  await size.press("Enter");
  await expect(slider).toHaveValue("15");
  // Enter hands the keyboard back to the image: shortcuts work straight away.
  await page.keyboard.press("]");
  await expect(size).toHaveValue("17");
  await page.keyboard.press("Shift+BracketRight");
  await expect(size).toHaveValue("34");
  await page.keyboard.press("[");
  await expect(size).toHaveValue("29");

  await size.fill("9999");
  await size.press("Enter");
  await expect(size).toHaveValue("160"); // clamped, not refused
  await size.fill("");
  await size.press("Enter");
  await expect(size).toHaveValue("160"); // unreadable input reverts

  await slider.fill("29");
  await expect(size).toHaveValue("29");
  await page.keyboard.press("e");
  await expect(page.locator(".ws-hint")).toContainText("Eraser");
  await expect(page.getByRole("spinbutton", { name: "Brush diameter in pixels" })).toHaveValue("29");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("oa.prefs")).brushDiameter)).toBe(29);
});

test("a 1 px brush labels exactly one pixel", async () => {
  await page.keyboard.press("b");
  const size = page.getByRole("spinbutton", { name: "Brush diameter in pixels" });
  await size.fill("1");
  await size.press("Enter");
  const [x, y] = await screen(10.4, 10.6);
  await page.mouse.click(x, y);
  await expect.poll(labelledPixels).toBe(1);
  await page.keyboard.press("Control+z");
  await expect(page.locator('[data-cov="1"]')).toHaveText("");
});

test("the polygon threshold labels the dark feature inside the outline and nothing else", async () => {
  await page.keyboard.press("r");
  await expect(page.locator(".ws-hint")).toContainText("Polygon threshold");
  await expect(page.getByRole("button", { name: "Polygon threshold" })).toHaveClass(/active/);
  for (const [x, y] of [[20, 60], [190, 60], [190, 190], [20, 190]]) {
    const [sx, sy] = await screen(x, y);
    await page.mouse.click(sx, sy);
  }
  await page.keyboard.press("Enter");
  const options = page.locator(".tool-options");
  await expect(options).toContainText("4,000 of");
  await expect(options).toContainText("pixels selected in the outline");
  await expect(options.locator(".alert-warn")).toBeHidden();

  // [ and ] nudge the previewed threshold; the panel is updated, not rebuilt.
  const threshold = page.getByRole("spinbutton", { name: "Threshold value" });
  const before = Number(await threshold.inputValue());
  expect(before).toBeGreaterThanOrEqual(40);
  expect(before).toBeLessThan(150);
  await page.keyboard.press("]");
  await expect(threshold).toHaveValue(String(before + 1));
  await expect(options).toContainText("4,000 of");

  // A stray click keeps the tuned preview.
  const [cx, cy] = await screen(100, 20);
  await page.mouse.click(cx, cy);
  await expect(page.locator(".toast", { hasText: "Apply the preview (Enter) or cancel it (Esc)" })).toBeVisible();
  await expect(threshold).toHaveValue(String(before + 1));

  await page.keyboard.press("Enter");
  await expect(page.locator(".toast", { hasText: "Labelled 4,000 pixels." })).toBeVisible();
  await expect.poll(labelledPixels).toBe(4000);
  await page.keyboard.press("Control+z");
  await expect(page.locator('[data-cov="1"]')).toHaveText("");
});

test("an outline traced tightly around a feature warns that the threshold lacks background", async () => {
  await page.keyboard.press("r");
  for (const [x, y] of [[FEATURE.x, FEATURE.y], [FEATURE.x + FEATURE.w, FEATURE.y], [FEATURE.x + FEATURE.w, FEATURE.y + FEATURE.h]]) {
    const [sx, sy] = await screen(x, y);
    await page.mouse.click(sx, sy);
  }
  const [lx, ly] = await screen(FEATURE.x, FEATURE.y + FEATURE.h);
  await page.mouse.dblclick(lx, ly);
  const options = page.locator(".tool-options");
  await expect(options.locator(".alert-warn")).toBeVisible();
  await expect(options).toContainText("Most of the outline is selected");
  await page.keyboard.press("Escape");
  await expect(options.locator(".alert-warn")).toHaveCount(0);
  await expect(options).toContainText("Click corners around a region");
  expect(problems).toEqual([]);
});
