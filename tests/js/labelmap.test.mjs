// Unit tests for the browser label-map engine. Run: node --test tests/js
import assert from "node:assert/strict";
import { test } from "node:test";

import { History, LabelMap, otsu, thresholdMask } from "../../src/online_annotator/web/static/js/editor/labelmap.js";

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
