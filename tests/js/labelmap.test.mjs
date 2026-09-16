// Unit tests for the browser label-map engine. Run: node --test tests/js
import assert from "node:assert/strict";
import { test } from "node:test";

import { History, LabelMap, otsu, polygonRegion, thresholdMask } from "../../src/online_annotator/web/static/js/editor/labelmap.js";

const ALL = LabelMap.writeRule(1, false, 1);

test("disc paints exact integer labels only inside the radius", () => {
  const m = new LabelMap(10, 10);
  m.paintDisc(5, 5, 2, 3, LabelMap.writeRule(3, false, 3));
  const values = new Set(m.data);
  assert.deepEqual([...values].sort(), [0, 3]);
  assert.equal(m.at(5, 5), 3);
  assert.equal(m.at(0, 0), 0);
  assert.equal(m.counts()[3], 12); // pixel centres within r=2 of (5,5)
});

test("a brush diameter covers the same pixels wherever the pointer is", () => {
  const rule = LabelMap.writeRule(1, false, 1);
  for (const [diameter, expected] of [[1, 1], [2, 4], [3, 9], [4, 12]]) {
    for (const [x, y] of [[4, 4], [4.5, 4.5], [4.99, 4.01], [4.3, 4.7]]) {
      const m = new LabelMap(10, 10);
      m.paintDisc(x, y, diameter / 2, 1, rule);
      assert.equal(m.counts()[1], expected, `diameter ${diameter} at (${x}, ${y})`);
    }
  }
});

test("protect mode never overwrites another class", () => {
  const m = new LabelMap(10, 10);
  m.data.fill(2);
  m.paintDisc(5, 5, 3, 1, LabelMap.writeRule(1, true, 1));
  assert.equal(m.counts()[1], 0);
  m.paintDisc(5, 5, 3, 0, LabelMap.writeRule(0, true, 1)); // erasing class 1 only
  assert.equal(m.counts()[2], 100);
});

test("polygon fill samples pixel centres (axis-aligned square)", () => {
  const m = new LabelMap(10, 10);
  const n = m.fillPolygon([[2, 2], [6, 2], [6, 6], [2, 6]], 1, ALL);
  assert.equal(n, 16);
  assert.equal(m.at(2, 2), 1);
  assert.equal(m.at(6, 6), 0);
});

test("polygon region selects exactly the pixels a polygon fill writes", () => {
  const shapes = [
    [[2, 2], [6, 2], [6, 6], [2, 6]],
    [[1.3, 0.2], [17.8, 3.1], [9.4, 14.6]], // triangle
    [[0, 0], [18, 14], [18, 0], [0, 14]], // self-intersecting bow tie (even-odd)
    [[-5, -5], [30, -2], [12, 40]], // corners outside the image
    [[3, 3], [12, 4], [7, 7], [12, 11], [3, 11]], // concave
  ];
  for (const points of shapes) {
    const m = new LabelMap(20, 15);
    const filled = m.fillPolygon(points, 1, ALL);
    const region = polygonRegion(points, 20, 15);
    assert.equal(region.area, filled);
    for (let y = 0; y < 15; y++) {
      for (let x = 0; x < 20; x++) {
        const { rect, roi } = region;
        const inRect = x >= rect.x && y >= rect.y && x < rect.x + rect.w && y < rect.y + rect.h;
        const inside = inRect && roi[(y - rect.y) * rect.w + (x - rect.x)] === 1;
        assert.equal(inside, m.at(x, y) === 1, `(${x}, ${y}) of ${JSON.stringify(points)}`);
      }
    }
  }
  assert.equal(polygonRegion([[2.1, 2.1], [2.4, 2.1], [2.2, 2.3]], 20, 15), null); // no pixel centre inside
  assert.equal(polygonRegion([[0, 0], [5, 5]], 20, 15), null);
});

test("bucket fill stays inside a closed outline", () => {
  const m = new LabelMap(7, 7);
  for (let i = 1; i <= 5; i++) {
    m.data[1 * 7 + i] = m.data[5 * 7 + i] = m.data[i * 7 + 1] = m.data[i * 7 + 5] = 1;
  }
  assert.equal(m.bucketFill(3, 3, 1, ALL), 9);
  assert.equal(m.at(0, 0), 0);
});

test("magic wand takes the whole connected dark feature from an edge click", () => {
  const grey = new Uint8Array(25).fill(200);
  for (const i of [6, 7, 8]) grey[i] = 40; // dark core
  grey[12] = 80; // fainter edge pixel, connected to the core
  const m = new LabelMap(5, 5);
  const r = m.magicWand(grey, 2, 2, 10, 1, ALL, 1000); // click the faint edge
  assert.equal(r.count, 4);
  assert.equal(r.dark, true);
  const big = new LabelMap(5, 5).magicWand(grey, 0, 0, 10, 1, ALL, 5);
  assert.equal(big.overflow, true);
});

test("otsu separates a bimodal histogram and threshold mask drops specks", () => {
  const grey = new Uint8Array(100).fill(200);
  for (let i = 0; i < 30; i++) grey[i] = 30;
  grey[99] = 30; // isolated speck
  const rect = { x: 0, y: 0, w: 10, h: 10 };
  const t = otsu(grey, 10, rect);
  assert.ok(t >= 30 && t < 200);
  const { count } = thresholdMask(grey, 10, rect, t, true, 2);
  assert.equal(count, 30);
});

test("polygon threshold sees and selects only the pixels inside the outline", () => {
  // 20 x 10 image: left half is a dark feature (40) on grey matrix (120); the right half is
  // a very bright scale bar (250) that would drag a box threshold upwards.
  const w = 20, hgt = 10;
  const grey = new Uint8Array(w * hgt).fill(120);
  for (let y = 3; y < 7; y++) for (let x = 2; x < 8; x++) grey[y * w + x] = 40;
  for (let y = 0; y < hgt; y++) for (let x = 12; x < 20; x++) grey[y * w + x] = 250;
  const region = polygonRegion([[0, 0], [10, 0], [10, 10], [0, 10]], w, hgt);
  const t = otsu(grey, w, region.rect, region.roi);
  assert.ok(t >= 40 && t < 120, `threshold ${t} separates feature from matrix`);
  const box = { x: 0, y: 0, w, h: hgt };
  assert.ok(otsu(grey, w, box) >= 120, "the whole-box threshold is pulled up by the bright bar");
  const { count } = thresholdMask(grey, w, region.rect, t, true, 1, region.roi);
  assert.equal(count, 24);

  // A triangle cutting through the feature: nothing outside it is ever selected.
  const tri = polygonRegion([[0, 0], [9, 0], [0, 9]], w, hgt);
  const cut = thresholdMask(grey, w, tri.rect, 60, true, 1, tri.roi);
  for (let k = 0; k < cut.mask.length; k++) if (cut.mask[k]) assert.equal(tri.roi[k], 1);
  assert.ok(cut.count > 0 && cut.count < 24);
  // Slivers the cut leaves behind are removed like any other speck.
  const noSpecks = thresholdMask(grey, w, tri.rect, 60, true, 50, tri.roi);
  assert.equal(noSpecks.count, 0);
});

test("remove specks and fill holes", () => {
  const m = new LabelMap(8, 8);
  m.data[0] = 1; // speck
  for (let y = 2; y <= 6; y++) for (let x = 2; x <= 6; x++) m.data[y * 8 + x] = 1;
  m.data[4 * 8 + 4] = 0; // hole
  assert.deepEqual(m.removeSpecks(1, 2), { removed: 1, regions: 1 });
  assert.deepEqual(m.fillHoles(1, 5), { filled: 1, regions: 1 });
  assert.equal(m.counts()[1], 25);
});

test("history undoes and redoes exact patches", () => {
  const m = new LabelMap(6, 6);
  const hist = new History(m);
  m.paintDisc(2, 2, 1.5, 1, ALL);
  assert.ok(hist.commit("a"));
  const afterA = m.data.slice();
  m.fillPolygon([[0, 0], [6, 0], [6, 6], [0, 6]], 2, ALL);
  hist.commit("b");
  hist.undo();
  assert.deepEqual(m.data, afterA);
  hist.undo();
  assert.equal(m.counts()[1], 0);
  hist.redo();
  hist.redo();
  assert.equal(m.counts()[2], 36);
  // An edit that changes nothing is not recorded.
  m.markDirty(0, 0, 1, 1);
  assert.equal(hist.commit("noop"), false);
});
