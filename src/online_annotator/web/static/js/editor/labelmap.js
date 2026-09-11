// Exact label-map operations. Every edit writes integer class indices into a
// Uint8Array the size of the image: no anti-aliasing, no colour blending, so what the
// annotator sees is exactly what is saved and exported.

export class LabelMap {
  constructor(width, height, data = null) {
    this.width = width;
    this.height = height;
    this.data = data || new Uint8Array(width * height);
    this.resetDirty();
  }

  resetDirty() {
    this.dirty = null; // {x0, y0, x1, y1} inclusive
  }

  markDirty(x0, y0, x1, y1) {
    x0 = Math.max(0, x0);
    y0 = Math.max(0, y0);
    x1 = Math.min(this.width - 1, x1);
    y1 = Math.min(this.height - 1, y1);
    if (x1 < x0 || y1 < y0) return;
    const d = this.dirty;
    if (!d) this.dirty = { x0, y0, x1, y1 };
    else {
      d.x0 = Math.min(d.x0, x0);
      d.y0 = Math.min(d.y0, y0);
      d.x1 = Math.max(d.x1, x1);
      d.y1 = Math.max(d.y1, y1);
    }
  }

  at(x, y) {
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return -1;
    return this.data[y * this.width + x];
  }

  // Which existing labels may be overwritten by `value`.
  // protect=false: anything. protect=true while painting: background or the same class;
  // protect=true while erasing (value 0): only the active class.
  static writeRule(value, protect, activeClass) {
    const rule = new Uint8Array(256);
    if (!protect) rule.fill(1);
    else if (value === 0) rule[activeClass] = 1;
    else {
      rule[0] = 1;
      rule[value] = 1;
    }
    return rule;
  }

  paintDisc(cx, cy, r, value, rule) {
    const { width: w, height: h, data } = this;
    const x0 = Math.max(0, Math.floor(cx - r)), x1 = Math.min(w - 1, Math.ceil(cx + r));
    const y0 = Math.max(0, Math.floor(cy - r)), y1 = Math.min(h - 1, Math.ceil(cy + r));
    const r2 = r * r;
    let changed = false;
    for (let y = y0; y <= y1; y++) {
      const dy = y + 0.5 - cy;
      const row = y * w;
      for (let x = x0; x <= x1; x++) {
        const dx = x + 0.5 - cx;
        if (dx * dx + dy * dy <= r2) {
          const i = row + x;
          if (data[i] !== value && rule[data[i]]) {
            data[i] = value;
            changed = true;
          }
        }
      }
    }
    if (changed) this.markDirty(x0, y0, x1, y1);
  }

  paintSegment(ax, ay, bx, by, r, value, rule) {
    const len = Math.hypot(bx - ax, by - ay);
    const step = Math.max(0.5, r / 3);
    const n = Math.max(1, Math.ceil(len / step));
    for (let k = 0; k <= n; k++) {
      const t = k / n;
      this.paintDisc(ax + (bx - ax) * t, ay + (by - ay) * t, r, value, rule);
    }
  }

  // Even-odd scanline fill, sampling pixel centres. `points` = [[x, y], ...] in image px.
  fillPolygon(points, value, rule) {
    if (points.length < 3) return 0;
    const { width: w, height: h, data } = this;
    let minY = Infinity, maxY = -Infinity, minX = Infinity, maxX = -Infinity;
    for (const [x, y] of points) {
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
    }
    const y0 = Math.max(0, Math.floor(minY)), y1 = Math.min(h - 1, Math.ceil(maxY));
    const n = points.length;
    const xs = [];
    let count = 0;
    for (let y = y0; y <= y1; y++) {
      const sy = y + 0.5;
      xs.length = 0;
      for (let i = 0, j = n - 1; i < n; j = i++) {
        const [xi, yi] = points[i];
        const [xj, yj] = points[j];
        if ((yi > sy) !== (yj > sy)) xs.push(xi + ((sy - yi) / (yj - yi)) * (xj - xi));
      }
      xs.sort((a, b) => a - b);
      for (let k = 0; k + 1 < xs.length; k += 2) {
        const xa = Math.max(0, Math.ceil(xs[k] - 0.5));
        const xb = Math.min(w - 1, Math.floor(xs[k + 1] - 0.5));
        const row = y * w;
        for (let x = xa; x <= xb; x++) {
          const i = row + x;
          if (data[i] !== value && rule[data[i]]) {
            data[i] = value;
            count++;
          }
        }
      }
    }
    if (count) this.markDirty(Math.floor(minX), y0, Math.ceil(maxX), y1);
    return count;
  }

  // Generic 4-connected flood from a seed; `accept(i)` decides membership.
  // `buffers` = {seen, stack} lets whole-image passes reuse one allocation; visited
  // pixels stay marked in `seen`, which those passes rely on.
  _flood(sx, sy, accept, maxPixels = Infinity, buffers = null) {
    const { width: w, height: h } = this;
    const seen = buffers ? buffers.seen : new Uint8Array(w * h);
    const stack = buffers ? buffers.stack : new Int32Array(w * h);
    const start = sy * w + sx;
    if (!accept(start)) return null;
    let top = 0, count = 0;
    stack[top++] = start;
    seen[start] = 1;
    const members = [];
    let x0 = sx, x1 = sx, y0 = sy, y1 = sy;
    while (top > 0) {
      const i = stack[--top];
      members.push(i);
      if (++count > maxPixels) return { members, overflow: true };
      const x = i % w, y = (i - x) / w;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
      if (x > 0 && !seen[i - 1] && accept(i - 1)) { seen[i - 1] = 1; stack[top++] = i - 1; }
      if (x < w - 1 && !seen[i + 1] && accept(i + 1)) { seen[i + 1] = 1; stack[top++] = i + 1; }
      if (y > 0 && !seen[i - w] && accept(i - w)) { seen[i - w] = 1; stack[top++] = i - w; }
      if (y < h - 1 && !seen[i + w] && accept(i + w)) { seen[i + w] = 1; stack[top++] = i + w; }
    }
    return { members, overflow: false, bbox: { x0, y0, x1, y1 } };
  }

  _writeMembers(result, value, rule) {
    let count = 0;
    for (const i of result.members) {
      if (this.data[i] !== value && rule[this.data[i]]) {
        this.data[i] = value;
        count++;
      }
    }
    if (count) this.markDirty(result.bbox.x0, result.bbox.y0, result.bbox.x1, result.bbox.y1);
    return count;
  }

  // Bucket: recolour the connected region of identical label under the seed.
  bucketFill(x, y, value, rule) {
    const target = this.at(x, y);
    if (target < 0 || target === value) return 0;
    const data = this.data;
    const result = this._flood(x, y, (i) => data[i] === target);
    return result ? this._writeMembers(result, value, rule) : 0;
  }

  // Magic wand for microstructures. The clicked pixel is classed as a dark or bright
  // feature by comparing it with the mean of its 31 x 31 neighbourhood; the wand then
  // grows over connected pixels at least as dark (or bright) as the seed, allowing
  // `tolerance` grey levels of slack. Clicking anywhere on a platelet - edge or core -
  // therefore selects the whole connected platelet and stops at the brighter matrix.
  magicWand(grey, x, y, tolerance, value, rule, maxPixels) {
    if (this.at(x, y) < 0) return { count: 0 };
    const { width: w, height: h } = this;
    const seed = grey[y * w + x];
    let sum = 0, n = 0;
    for (let yy = Math.max(0, y - 15); yy <= Math.min(h - 1, y + 15); yy++) {
      for (let xx = Math.max(0, x - 15); xx <= Math.min(w - 1, x + 15); xx++) {
        sum += grey[yy * w + xx];
        n++;
      }
    }
    const dark = seed <= sum / n;
    const limit = dark ? seed + tolerance : seed - tolerance;
    const accept = dark ? (i) => grey[i] <= limit : (i) => grey[i] >= limit;
    const result = this._flood(x, y, accept, maxPixels);
    if (!result) return { count: 0 };
    if (result.overflow) return { count: 0, overflow: true, dark };
    return { count: this._writeMembers(result, value, rule), seed, dark };
  }

  // Write `value` wherever mask[k] is set inside the rectangle.
  applyMask(mask, rect, value, rule) {
    const { width: w, data } = this;
    let count = 0;
    for (let yy = 0; yy < rect.h; yy++) {
      const row = (rect.y + yy) * w + rect.x;
      for (let xx = 0; xx < rect.w; xx++) {
        if (!mask[yy * rect.w + xx]) continue;
        const i = row + xx;
        if (data[i] !== value && rule[data[i]]) {
          data[i] = value;
          count++;
        }
      }
    }
    if (count) this.markDirty(rect.x, rect.y, rect.x + rect.w - 1, rect.y + rect.h - 1);
    return count;
  }

  // Connected components of `cls` smaller than minSize become background.
  removeSpecks(cls, minSize) {
    const { width: w, height: h, data } = this;
    const buffers = { seen: new Uint8Array(w * h), stack: new Int32Array(w * h) };
    let removed = 0, regions = 0;
    for (let i = 0; i < data.length; i++) {
      if (data[i] !== cls || buffers.seen[i]) continue;
      const res = this._flood(i % w, Math.floor(i / w), (j) => data[j] === cls, Infinity, buffers);
      if (res.members.length < minSize) {
        for (const j of res.members) data[j] = 0;
        removed += res.members.length;
        regions++;
        this.markDirty(res.bbox.x0, res.bbox.y0, res.bbox.x1, res.bbox.y1);
      }
    }
    return { removed, regions };
  }

  // Background holes completely enclosed by `cls` and no larger than maxSize are filled.
  fillHoles(cls, maxSize) {
    const { width: w, height: h, data } = this;
    const buffers = { seen: new Uint8Array(w * h), stack: new Int32Array(w * h) };
    let filled = 0, regions = 0;
    for (let i = 0; i < data.length; i++) {
      if (data[i] !== 0 || buffers.seen[i]) continue;
      let enclosed = true;
      const res = this._flood(i % w, Math.floor(i / w), (j) => {
        const v = data[j];
        if (v === 0) return true;
        if (v !== cls) enclosed = false;
        return false;
      }, Infinity, buffers);
      const b = res.bbox;
      if (b.x0 === 0 || b.y0 === 0 || b.x1 === w - 1 || b.y1 === h - 1) enclosed = false;
      if (enclosed && res.members.length <= maxSize) {
        for (const j of res.members) data[j] = cls;
        filled += res.members.length;
        regions++;
        this.markDirty(b.x0, b.y0, b.x1, b.y1);
      }
    }
    return { filled, regions };
  }

  counts() {
    const c = new Uint32Array(256);
    const d = this.data;
    for (let i = 0; i < d.length; i++) c[d[i]]++;
    return c;
  }
}

// Otsu's threshold over the grey levels inside a rectangle.
export function otsu(grey, width, rect) {
  const hist = new Float64Array(256);
  for (let y = rect.y; y < rect.y + rect.h; y++) {
    const row = y * width;
    for (let x = rect.x; x < rect.x + rect.w; x++) hist[grey[row + x]]++;
  }
  const total = rect.w * rect.h;
  let sum = 0;
  for (let t = 0; t < 256; t++) sum += t * hist[t];
  let sumB = 0, wB = 0, best = 0, threshold = 127;
  for (let t = 0; t < 256; t++) {
    wB += hist[t];
    if (!wB) continue;
    const wF = total - wB;
    if (!wF) break;
    sumB += t * hist[t];
    const mB = sumB / wB, mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > best) {
      best = between;
      threshold = t;
    }
  }
  return threshold;
}

// Candidate mask for the box-threshold tool, with small specks removed.
export function thresholdMask(grey, width, rect, threshold, dark, minSize) {
  const mask = new Uint8Array(rect.w * rect.h);
  for (let yy = 0; yy < rect.h; yy++) {
    const row = (rect.y + yy) * width + rect.x;
    for (let xx = 0; xx < rect.w; xx++) {
      const v = grey[row + xx];
      mask[yy * rect.w + xx] = dark ? (v <= threshold ? 1 : 0) : (v > threshold ? 1 : 0);
    }
  }
  if (minSize > 1) {
    const tmp = new LabelMap(rect.w, rect.h, mask);
    tmp.removeSpecks(1, minSize);
  }
  let count = 0;
  for (let k = 0; k < mask.length; k++) count += mask[k];
  return { mask, count };
}

// Patch-based undo/redo: stores only the changed rectangle before and after each edit.
export class History {
  constructor(map, { maxSteps = 100, maxBytes = 256 * 1024 * 1024 } = {}) {
    this.map = map;
    this.shadow = map.data.slice();
    this.undoStack = [];
    this.redoStack = [];
    this.maxSteps = maxSteps;
    this.maxBytes = maxBytes;
    this.bytes = 0;
  }

  _extract(src, r) {
    const out = new Uint8Array(r.w * r.h);
    for (let y = 0; y < r.h; y++) {
      const start = (r.y + y) * this.map.width + r.x;
      out.set(src.subarray(start, start + r.w), y * r.w);
    }
    return out;
  }

  _write(dst, r, patch) {
    for (let y = 0; y < r.h; y++) dst.set(patch.subarray(y * r.w, (y + 1) * r.w), (r.y + y) * this.map.width + r.x);
  }

  // Call after an edit; returns false if nothing changed.
  commit(label) {
    const d = this.map.dirty;
    if (!d) return false;
    const r = { x: d.x0, y: d.y0, w: d.x1 - d.x0 + 1, h: d.y1 - d.y0 + 1 };
    const before = this._extract(this.shadow, r);
    const after = this._extract(this.map.data, r);
    let same = true;
    for (let k = 0; k < before.length; k++) if (before[k] !== after[k]) { same = false; break; }
    this.map.resetDirty();
    if (same) return false;
    this._write(this.shadow, r, after);
    this.undoStack.push({ r, before, after, label });
    this.bytes += before.length * 2;
    this.redoStack = [];
    while (this.undoStack.length > this.maxSteps || this.bytes > this.maxBytes) {
      const old = this.undoStack.shift();
      this.bytes -= old.before.length * 2;
    }
    return true;
  }

  // Discard uncommitted changes (e.g. a cancelled stroke).
  revert() {
    const d = this.map.dirty;
    if (!d) return;
    const r = { x: d.x0, y: d.y0, w: d.x1 - d.x0 + 1, h: d.y1 - d.y0 + 1 };
    this._write(this.map.data, r, this._extract(this.shadow, r));
    this.map.resetDirty();
    this.map.markDirty(d.x0, d.y0, d.x1, d.y1);
  }

  undo() {
    const step = this.undoStack.pop();
    if (!step) return null;
    this._write(this.map.data, step.r, step.before);
    this._write(this.shadow, step.r, step.before);
    this.bytes -= step.before.length * 2;
    this.redoStack.push(step);
    return step;
  }

  redo() {
    const step = this.redoStack.pop();
    if (!step) return null;
    this._write(this.map.data, step.r, step.after);
    this._write(this.shadow, step.r, step.after);
    this.bytes += step.before.length * 2;
    this.undoStack.push(step);
    return step;
  }

  reset() {
    this.shadow = this.map.data.slice();
    this.undoStack = [];
    this.redoStack = [];
    this.bytes = 0;
    this.map.resetDirty();
  }
}
