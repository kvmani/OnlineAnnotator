// Interactive canvas editor: pan/zoom view, overlay rendering and the drawing tools.
// All edits go through LabelMap (exact integer labels) and History (undo/redo).
import { History, LabelMap, otsu, polygonRegion, thresholdMask } from "./labelmap.js";

export const TOOLS = {
  pan: { key: "V", label: "Pan", icon: "pan", hint: "Drag to move the image. Scroll to zoom. You can also hold Space or drag with the middle mouse button in any tool." },
  brush: { key: "B", label: "Brush", icon: "brush", hint: "Drag to paint the selected class. Hold Shift to erase instead. [ and ] change the size (Shift+[ and ] halve or double it); you can also type the diameter on the right." },
  eraser: { key: "E", label: "Eraser", icon: "eraser", hint: "Drag to return pixels to background (unlabelled). Same size as the brush: [ and ] change it (Shift+[ and ] halve or double it)." },
  polygon: { key: "P", label: "Polygon", icon: "polygon", hint: "Click to place corners. Double-click, press Enter or click the first corner to fill. Backspace removes the last corner, Esc cancels. Shift while closing erases." },
  lasso: { key: "L", label: "Lasso", icon: "lasso", hint: "Drag around a region; releasing the mouse fills everything inside. Hold Shift to erase the region instead." },
  wand: { key: "W", label: "Magic wand", icon: "wand", hint: "Click a dark (or bright) feature: the whole connected feature is labelled. If it spreads into the matrix lower the tolerance; if it misses faint edges raise it ([ and ] change it). Shift+click erases." },
  threshold: { key: "T", label: "Box threshold", icon: "threshold", hint: "Drag a box over a region. Pixels darker (or brighter) than an automatic threshold are previewed; adjust on the right ([ and ] nudge it), then press Enter or Apply." },
  polythreshold: { key: "R", label: "Polygon threshold", icon: "polythreshold", hint: "Click corners around a region; double-click, Enter or the first corner closes it. Pixels inside that are darker (or brighter) than an automatic threshold are previewed; adjust on the right ([ and ] nudge it), then press Enter or Apply. Backspace removes a corner, Esc cancels." },
  fill: { key: "G", label: "Fill", icon: "fill", hint: "Click inside an area to fill all connected pixels that currently have the same label, e.g. the inside of an outline you drew." },
};

const MIN_SCALE = 0.05;
const MIN_THRESHOLD_AREA = 16; // pixels; the box threshold's minimum is a 4 x 4 box
const MAX_SCALE = 40;

function hexToRgb(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

export class Editor {
  constructor(host, callbacks = {}) {
    this.host = host;
    this.cb = callbacks; // onChange, onHover, onPickClass, onThreshold, onMessage, onViewChange
    this.canvas = document.createElement("canvas");
    this.canvas.className = "editor-canvas";
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute("aria-label", "Annotation canvas");
    host.append(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.tool = "brush";
    this.brushSize = 6; // radius in image pixels: half the diameter, so it may end in .5
    this.protect = false;
    this.tolerance = 18;
    this.opacity = 0.5;
    this.showOverlay = true;
    this.outline = false;
    this.adjust = { brightness: 100, contrast: 100, invert: false };
    this.readOnly = true;
    this.activeClass = 1;
    this.classes = [];
    this.scale = 1;
    this.ox = 0;
    this.oy = 0;
    this.hover = null;
    this.drag = null;
    this.poly = [];
    this.thresholdState = null;
    this.spaceDown = false;
    this._frame = 0;
    this._bind();
    this._resizeObserver = new ResizeObserver(() => this.resize());
    this._resizeObserver.observe(host);
  }

  destroy() {
    this._resizeObserver.disconnect();
    window.removeEventListener("keydown", this._onKeyDown);
    window.removeEventListener("keyup", this._onKeyUp);
    this.canvas.remove();
  }

  // ------------------------------------------------------------------------ loading
  async load({ imageUrl, width, height, labels }) {
    this.width = width;
    this.height = height;
    this.map = new LabelMap(width, height, labels);
    this.history = new History(this.map);
    this.image = await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("The micrograph could not be loaded."));
      img.src = imageUrl;
    });
    this.overlay = document.createElement("canvas");
    this.overlay.width = width;
    this.overlay.height = height;
    this.overlayCtx = this.overlay.getContext("2d");
    this.overlayData = this.overlayCtx.createImageData(width, height);
    this.overlayU32 = new Uint32Array(this.overlayData.data.buffer);
    this._buildLut();
    this.refreshOverlay();
    this.resize();
    this.fit();
  }

  setGrey(grey) {
    this.grey = grey;
  }

  replaceLabels(labels) {
    this.map.data.set(labels);
    this.history.reset();
    this.refreshOverlay();
    this.requestDraw();
  }

  setClasses(classes) {
    this.classes = classes;
    if (this.overlayU32) {
      this._buildLut();
      this.refreshOverlay();
      this.requestDraw();
    }
  }

  _buildLut() {
    this.lut = new Uint32Array(256);
    this.outlineLut = new Uint32Array(256);
    const little = new Uint8Array(new Uint32Array([1]).buffer)[0] === 1;
    for (const c of this.classes) {
      const [r, g, b] = hexToRgb(c.color);
      this.lut[c.index] = little ? (255 << 24) | (b << 16) | (g << 8) | r : (r << 24) | (g << 16) | (b << 8) | 255;
    }
  }

  // Recompute overlay pixels for a rectangle (or all) from the label map.
  refreshOverlay(rect = null) {
    if (!this.overlayU32) return;
    const w = this.width;
    const r = rect || { x: 0, y: 0, w: this.width, h: this.height };
    const data = this.map.data, out = this.overlayU32, lut = this.lut;
    if (this.outline) {
      const h = this.height;
      for (let y = r.y; y < r.y + r.h; y++) {
        for (let x = r.x; x < r.x + r.w; x++) {
          const i = y * w + x, v = data[i];
          const edge = v && ((x > 0 && data[i - 1] !== v) || (x < w - 1 && data[i + 1] !== v) ||
            (y > 0 && data[i - w] !== v) || (y < h - 1 && data[i + w] !== v));
          out[i] = edge ? lut[v] : 0;
        }
      }
    } else {
      for (let y = r.y; y < r.y + r.h; y++) {
        const row = y * w;
        for (let x = r.x; x < r.x + r.w; x++) out[row + x] = lut[data[row + x]];
      }
    }
    this.overlayCtx.putImageData(this.overlayData, 0, 0, r.x, r.y, r.w, r.h);
  }

  _refreshDirty() {
    const d = this.map.dirty;
    if (!d) return;
    const pad = this.outline ? 1 : 0;
    const x0 = Math.max(0, d.x0 - pad), y0 = Math.max(0, d.y0 - pad);
    const x1 = Math.min(this.width - 1, d.x1 + pad), y1 = Math.min(this.height - 1, d.y1 + pad);
    this.refreshOverlay({ x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 });
  }

  // ------------------------------------------------------------------------ view
  resize() {
    const rect = this.host.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.viewW = Math.max(1, rect.width);
    this.viewH = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.viewW * dpr);
    this.canvas.height = Math.round(this.viewH * dpr);
    this.canvas.style.width = `${this.viewW}px`;
    this.canvas.style.height = `${this.viewH}px`;
    this.dpr = dpr;
    this.requestDraw();
  }

  fit() {
    if (!this.width) return;
    const pad = 24;
    this.scale = Math.min((this.viewW - pad * 2) / this.width, (this.viewH - pad * 2) / this.height);
    this.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.scale));
    this.ox = (this.viewW - this.width * this.scale) / 2;
    this.oy = (this.viewH - this.height * this.scale) / 2;
    this._viewChanged();
  }

  zoomAt(factor, sx = this.viewW / 2, sy = this.viewH / 2) {
    const next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.scale * factor));
    this.ox = sx - ((sx - this.ox) * next) / this.scale;
    this.oy = sy - ((sy - this.oy) * next) / this.scale;
    this.scale = next;
    this._viewChanged();
  }

  actualSize() {
    this.zoomAt(1 / this.scale);
  }

  _viewChanged() {
    this.requestDraw();
    if (this.cb.onViewChange) this.cb.onViewChange(this.scale);
  }

  toImage(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    return { x: (clientX - r.left - this.ox) / this.scale, y: (clientY - r.top - this.oy) / this.scale,
      sx: clientX - r.left, sy: clientY - r.top };
  }

  requestDraw() {
    if (this._frame) return;
    this._frame = requestAnimationFrame(() => {
      this._frame = 0;
      this.draw();
    });
  }

  draw() {
    const ctx = this.ctx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.viewW, this.viewH);
    if (!this.image) return;
    ctx.save();
    ctx.translate(this.ox, this.oy);
    ctx.scale(this.scale, this.scale);
    ctx.imageSmoothingEnabled = this.scale < 1;
    const { brightness, contrast, invert } = this.adjust;
    if (brightness !== 100 || contrast !== 100 || invert) {
      ctx.filter = `brightness(${brightness}%) contrast(${contrast}%)${invert ? " invert(1)" : ""}`;
    }
    ctx.drawImage(this.image, 0, 0, this.width, this.height);
    ctx.filter = "none";
    if (this.showOverlay) {
      ctx.imageSmoothingEnabled = false;
      ctx.globalAlpha = this.outline ? 1 : this.opacity;
      ctx.drawImage(this.overlay, 0, 0);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    this._drawToolPreview(ctx);
  }

  _classColor(index) {
    const c = this.classes.find((k) => k.index === index);
    return c ? c.color : "#ffffff";
  }

  _drawToolPreview(ctx) {
    const s = this.scale;
    const toS = (x, y) => [this.ox + x * s, this.oy + y * s];
    ctx.lineWidth = 1.5;
    // Threshold preview
    const t = this.thresholdState;
    if (t) {
      const [x, y] = toS(t.rect.x, t.rect.y);
      if (t.preview) {
        ctx.save();
        ctx.imageSmoothingEnabled = false;
        ctx.globalAlpha = 0.65;
        ctx.drawImage(t.preview, x, y, t.rect.w * s, t.rect.h * s);
        ctx.restore();
      }
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = "#ffd54a";
      if (t.shape === "polygon") {
        ctx.beginPath();
        t.points.forEach(([px, py], k) => (k ? ctx.lineTo(...toS(px, py)) : ctx.moveTo(...toS(px, py))));
        ctx.closePath();
        ctx.stroke();
      } else ctx.strokeRect(x, y, t.rect.w * s, t.rect.h * s);
      ctx.setLineDash([]);
    }
    // Box being dragged
    if (this.drag && this.drag.kind === "box") {
      const [x0, y0] = toS(this.drag.start.x, this.drag.start.y);
      const [x1, y1] = toS(this.drag.cur.x, this.drag.cur.y);
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = "#ffd54a";
      ctx.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
      ctx.setLineDash([]);
    }
    // Lasso path
    if (this.drag && this.drag.kind === "lasso" && this.drag.points.length > 1) {
      ctx.beginPath();
      this.drag.points.forEach(([x, y], k) => (k ? ctx.lineTo(...toS(x, y)) : ctx.moveTo(...toS(x, y))));
      ctx.strokeStyle = this.drag.erase ? "#ffffff" : this._classColor(this.activeClass);
      ctx.setLineDash([5, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Polygon in progress
    if (this.poly.length) {
      ctx.beginPath();
      this.poly.forEach(([x, y], k) => (k ? ctx.lineTo(...toS(x, y)) : ctx.moveTo(...toS(x, y))));
      if (this.hover) ctx.lineTo(this.hover.sx, this.hover.sy);
      ctx.strokeStyle = this.tool === "polythreshold" ? "#ffd54a" : this._classColor(this.activeClass);
      ctx.stroke();
      for (const [k, [x, y]] of this.poly.entries()) {
        const [px, py] = toS(x, y);
        ctx.beginPath();
        ctx.arc(px, py, k === 0 ? 6 : 3.5, 0, Math.PI * 2);
        ctx.fillStyle = k === 0 ? "#ffd54a" : "#ffffff";
        ctx.fill();
        ctx.strokeStyle = "#000";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
    // Brush cursor
    if (this.hover && !this.readOnly && (this.tool === "brush" || this.tool === "eraser")) {
      const r = Math.max(1, this.brushSize * s);
      ctx.beginPath();
      ctx.arc(this.hover.sx, this.hover.sy, r, 0, Math.PI * 2);
      const erasing = this.tool === "eraser" || this.hover.shift;
      ctx.strokeStyle = "rgba(0,0,0,0.8)";
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.strokeStyle = erasing ? "#ffffff" : this._classColor(this.activeClass);
      ctx.lineWidth = 1.5;
      if (erasing) ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // ------------------------------------------------------------------------ tools
  setTool(name) {
    if (this.poly.length && name !== this.tool) this.poly = [];
    if (this.thresholdState && name !== this.tool) this.cancelThreshold();
    this.tool = name;
    this._updateCursor();
    this.requestDraw();
  }

  _updateCursor() {
    const panning = this.tool === "pan" || this.spaceDown || this.readOnly;
    this.canvas.style.cursor = this.drag && this.drag.kind === "pan" ? "grabbing" :
      panning ? "grab" : (this.tool === "brush" || this.tool === "eraser") ? "none" : "crosshair";
  }

  _rule(value) {
    return LabelMap.writeRule(value, this.protect, this.activeClass);
  }

  _commit(label) {
    this._refreshDirty();
    const changed = this.history.commit(label);
    this.requestDraw();
    if (changed && this.cb.onChange) this.cb.onChange(label);
    return changed;
  }

  undo() {
    const step = this.history.undo();
    if (step) this._afterHistory(step);
    return step;
  }

  redo() {
    const step = this.history.redo();
    if (step) this._afterHistory(step);
    return step;
  }

  _afterHistory(step) {
    const pad = this.outline ? 1 : 0;
    const x = Math.max(0, step.r.x - pad), y = Math.max(0, step.r.y - pad);
    this.refreshOverlay({ x, y, w: Math.min(this.width - x, step.r.w + 2 * pad), h: Math.min(this.height - y, step.r.h + 2 * pad) });
    this.requestDraw();
    if (this.cb.onChange) this.cb.onChange("history");
  }

  // Enter, a double-click or a click on the first corner closes the outline. The polygon
  // threshold tool then previews a threshold inside it; the polygon tool fills it.
  closePolygon(erase = false) {
    if (this.tool === "polythreshold") return this._closeThresholdPolygon();
    if (this.poly.length < 3) {
      this.poly = [];
      this.requestDraw();
      return;
    }
    const value = erase ? 0 : this.activeClass;
    const n = this.map.fillPolygon(this.poly, value, this._rule(value));
    this.poly = [];
    this._commit(erase ? "polygon erase" : "polygon");
    if (!n && this.cb.onMessage) this.cb.onMessage("Nothing changed: the polygon covered no pixels that may be written (see 'Protect other classes').");
  }

  popPolygonPoint() {
    this.poly.pop();
    this.requestDraw();
  }

  cancelPolygon() {
    this.poly = [];
    this.requestDraw();
  }

  _closeThresholdPolygon() {
    if (!this.poly.length) return;
    const say = (msg) => this.cb.onMessage && this.cb.onMessage(msg);
    if (this.poly.length < 3) {
      say("Place at least three corners around the region before closing it.");
      return;
    }
    if (!this.grey) {
      say("Grey levels are still loading; press Enter again in a moment.");
      return;
    }
    const points = this.poly;
    this.poly = [];
    const region = polygonRegion(points, this.width, this.height);
    if (!region || region.area < MIN_THRESHOLD_AREA) {
      this.requestDraw();
      say(`The outline encloses too few pixels. Draw a larger region (at least ${MIN_THRESHOLD_AREA} pixels) inside the image.`);
      return;
    }
    this._startThreshold({ shape: "polygon", points, ...region });
  }

  // Threshold tools: preview state shared with the side panel. `region` is
  // {shape: "box", rect} or {shape: "polygon", points, rect, roi, area}; the automatic
  // threshold and the selection only ever use the pixels inside the region.
  _startThreshold(region) {
    if (!this.grey) {
      if (this.cb.onMessage) this.cb.onMessage("Grey levels are still loading; try again in a moment.");
      return;
    }
    const roi = region.roi || null;
    const threshold = otsu(this.grey, this.width, region.rect, roi);
    this.thresholdState = { roi, area: region.rect.w * region.rect.h, ...region, threshold, otsu: threshold, dark: true, minSize: 4 };
    this.updateThreshold({});
  }

  updateThreshold(changes) {
    const t = this.thresholdState;
    if (!t) return;
    Object.assign(t, changes);
    const { mask, count } = thresholdMask(this.grey, this.width, t.rect, t.threshold, t.dark, t.minSize, t.roi);
    t.mask = mask;
    t.count = count;
    const c = document.createElement("canvas");
    c.width = t.rect.w;
    c.height = t.rect.h;
    const cctx = c.getContext("2d");
    const img = cctx.createImageData(t.rect.w, t.rect.h);
    const u32 = new Uint32Array(img.data.buffer);
    const colour = this.lut[this.activeClass] || 0xff0000ff;
    for (let k = 0; k < mask.length; k++) if (mask[k]) u32[k] = colour;
    cctx.putImageData(img, 0, 0);
    t.preview = c;
    this.requestDraw();
    if (this.cb.onThreshold) this.cb.onThreshold(t);
  }

  applyThreshold() {
    const t = this.thresholdState;
    if (!t) return 0;
    const n = this.map.applyMask(t.mask, t.rect, this.activeClass, this._rule(this.activeClass));
    this.thresholdState = null;
    this._commit(t.shape === "polygon" ? "polygon threshold" : "box threshold");
    if (this.cb.onThreshold) this.cb.onThreshold(null);
    return n;
  }

  cancelThreshold() {
    this.thresholdState = null;
    this.requestDraw();
    if (this.cb.onThreshold) this.cb.onThreshold(null);
  }

  cleanup(kind, size) {
    const result = kind === "specks" ? this.map.removeSpecks(this.activeClass, size) : this.map.fillHoles(this.activeClass, size);
    this._commit(kind === "specks" ? "remove specks" : "fill holes");
    return result;
  }

  setOutline(on) {
    this.outline = on;
    this.refreshOverlay();
    this.requestDraw();
  }

  // ------------------------------------------------------------------------ input
  _bind() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => this._down(e));
    c.addEventListener("pointermove", (e) => this._move(e));
    c.addEventListener("pointerup", (e) => this._up(e));
    c.addEventListener("pointercancel", (e) => this._up(e, true));
    c.addEventListener("pointerleave", () => {
      this.hover = null;
      this.requestDraw();
      if (this.cb.onHover) this.cb.onHover(null);
    });
    c.addEventListener("dblclick", (e) => {
      if ((this.tool === "polygon" || this.tool === "polythreshold") && !this.readOnly && this.poly.length) {
        e.preventDefault();
        this.poly.pop(); // the second click of the double-click added a duplicate corner
        this.closePolygon(e.shiftKey);
      }
    });
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const p = this.toImage(e.clientX, e.clientY);
      const factor = Math.exp(-Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY), 100) / 400);
      this.zoomAt(factor, p.sx, p.sy);
    }, { passive: false });
    c.addEventListener("contextmenu", (e) => e.preventDefault());
    this._onKeyDown = (e) => {
      if (e.code === "Space" && !isTyping(e)) {
        if (!this.spaceDown) {
          this.spaceDown = true;
          this._updateCursor();
        }
        e.preventDefault();
      }
      if (e.key === "Shift" && this.hover) {
        this.hover.shift = true;
        this.requestDraw();
      }
    };
    this._onKeyUp = (e) => {
      if (e.code === "Space") {
        this.spaceDown = false;
        this._updateCursor();
      }
      if (e.key === "Shift" && this.hover) {
        this.hover.shift = false;
        this.requestDraw();
      }
    };
    window.addEventListener("keydown", this._onKeyDown);
    window.addEventListener("keyup", this._onKeyUp);
  }

  _down(e) {
    if (!this.map) return;
    this.canvas.focus({ preventScroll: true });
    const p = this.toImage(e.clientX, e.clientY);
    const panning = e.button === 1 || e.button === 2 || this.tool === "pan" || this.spaceDown || this.readOnly;
    if (panning) {
      this.drag = { kind: "pan", sx: p.sx, sy: p.sy, ox: this.ox, oy: this.oy };
      this.canvas.setPointerCapture(e.pointerId);
      this._updateCursor();
      return;
    }
    if (e.button !== 0) return;
    const ix = Math.floor(p.x), iy = Math.floor(p.y);
    if (e.altKey) {
      const v = this.map.at(ix, iy);
      if (v > 0 && this.cb.onPickClass) this.cb.onPickClass(v);
      return;
    }
    const erase = e.shiftKey;
    switch (this.tool) {
      case "brush":
      case "eraser": {
        const value = this.tool === "eraser" || erase ? 0 : this.activeClass;
        this.drag = { kind: "paint", value, rule: this._rule(value), last: p };
        this.map.paintDisc(p.x, p.y, this.brushSize, value, this.drag.rule);
        this._refreshDirty();
        this.requestDraw();
        this.canvas.setPointerCapture(e.pointerId);
        break;
      }
      case "polygon": {
        if (this.poly.length >= 3) {
          const [fx, fy] = this.poly[0];
          if (Math.hypot((fx - p.x) * this.scale, (fy - p.y) * this.scale) < 10) {
            this.closePolygon(erase);
            return;
          }
        }
        this.poly.push([p.x, p.y]);
        this.requestDraw();
        break;
      }
      case "polythreshold": {
        if (this.thresholdState) {
          // A stray click must not throw away a tuned preview (e.detail > 1: the rest of a
          // double-click that just closed the outline).
          if (e.detail < 2 && this.cb.onMessage) this.cb.onMessage("Apply the preview (Enter) or cancel it (Esc) before outlining a new region.");
          return;
        }
        if (this.poly.length >= 3) {
          const [fx, fy] = this.poly[0];
          if (Math.hypot((fx - p.x) * this.scale, (fy - p.y) * this.scale) < 10) {
            this._closeThresholdPolygon();
            return;
          }
        }
        this.poly.push([p.x, p.y]);
        this.requestDraw();
        break;
      }
      case "lasso":
        this.drag = { kind: "lasso", points: [[p.x, p.y]], erase };
        this.canvas.setPointerCapture(e.pointerId);
        break;
      case "threshold":
        if (this.thresholdState) this.cancelThreshold();
        this.drag = { kind: "box", start: p, cur: p };
        this.canvas.setPointerCapture(e.pointerId);
        break;
      case "wand": {
        if (!this.grey) {
          if (this.cb.onMessage) this.cb.onMessage("Grey levels are still loading; try again in a moment.");
          return;
        }
        const value = erase ? 0 : this.activeClass;
        const limit = Math.max(2000, Math.floor(this.width * this.height * 0.25));
        const r = this.map.magicWand(this.grey, ix, iy, this.tolerance, value, this._rule(value), limit);
        if (r.overflow) {
          if (this.cb.onMessage) this.cb.onMessage("That region spreads over more than a quarter of the image, so nothing was changed. Lower the tolerance or use the box threshold.");
          return;
        }
        this._commit(erase ? "wand erase" : "magic wand");
        if (this.cb.onMessage) this.cb.onMessage(r.count ? `${erase ? "Erased" : "Labelled"} ${r.count.toLocaleString()} pixels of a ${r.dark ? "dark" : "bright"} feature. Ctrl+Z undoes.` : "Nothing changed (already labelled, or protected).");
        break;
      }
      case "fill": {
        const value = erase ? 0 : this.activeClass;
        const n = this.map.bucketFill(ix, iy, value, this._rule(value));
        this._commit("fill");
        if (this.cb.onMessage && n > this.width * this.height * 0.5) this.cb.onMessage(`Filled ${n.toLocaleString()} pixels. Press Ctrl+Z if that was not intended.`);
        break;
      }
      default:
        break;
    }
  }

  _move(e) {
    if (!this.map) return;
    const p = this.toImage(e.clientX, e.clientY);
    this.hover = { ...p, shift: e.shiftKey };
    const d = this.drag;
    if (d && d.kind === "pan") {
      this.ox = d.ox + (p.sx - d.sx);
      this.oy = d.oy + (p.sy - d.sy);
      this.requestDraw();
    } else if (d && d.kind === "paint") {
      // Coalesced events give smooth strokes on fast pointers, but the list can be
      // empty (synthetic events, some browsers); then the event itself is used.
      const coalesced = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
      const events = coalesced.length ? coalesced : [e];
      for (const ev of events) {
        const q = this.toImage(ev.clientX, ev.clientY);
        this.map.paintSegment(d.last.x, d.last.y, q.x, q.y, this.brushSize, d.value, d.rule);
        d.last = q;
      }
      this._refreshDirty();
      this.requestDraw();
    } else if (d && d.kind === "lasso") {
      const last = d.points[d.points.length - 1];
      if (Math.hypot((p.x - last[0]) * this.scale, (p.y - last[1]) * this.scale) > 2) d.points.push([p.x, p.y]);
      this.requestDraw();
    } else if (d && d.kind === "box") {
      d.cur = p;
      this.requestDraw();
    } else {
      this.requestDraw();
    }
    if (this.cb.onHover) {
      const ix = Math.floor(p.x), iy = Math.floor(p.y);
      const inside = ix >= 0 && iy >= 0 && ix < this.width && iy < this.height;
      this.cb.onHover(inside ? { x: ix, y: iy, label: this.map.at(ix, iy), grey: this.grey ? this.grey[iy * this.width + ix] : null } : null);
    }
  }

  _up(e, cancelled = false) {
    const d = this.drag;
    this.drag = null;
    if (this.canvas.hasPointerCapture && this.canvas.hasPointerCapture(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId);
    this._updateCursor();
    if (!d) return;
    if (d.kind === "paint") {
      if (cancelled) {
        this.history.revert();
        this._refreshDirty();
        this.map.resetDirty();
        this.requestDraw();
      } else this._commit(d.value === 0 ? "erase" : "brush");
    } else if (d.kind === "lasso" && !cancelled) {
      if (d.points.length >= 3) {
        const value = d.erase ? 0 : this.activeClass;
        this.map.fillPolygon(d.points, value, this._rule(value));
        this._commit(d.erase ? "lasso erase" : "lasso");
      }
      this.requestDraw();
    } else if (d.kind === "box" && !cancelled) {
      const x0 = Math.max(0, Math.floor(Math.min(d.start.x, d.cur.x)));
      const y0 = Math.max(0, Math.floor(Math.min(d.start.y, d.cur.y)));
      const x1 = Math.min(this.width, Math.ceil(Math.max(d.start.x, d.cur.x)));
      const y1 = Math.min(this.height, Math.ceil(Math.max(d.start.y, d.cur.y)));
      if (x1 - x0 >= 4 && y1 - y0 >= 4) this._startThreshold({ shape: "box", rect: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } });
      else if (this.cb.onMessage) this.cb.onMessage("Drag a larger box (at least 4 x 4 pixels).");
      this.requestDraw();
    }
  }
}

// A slider takes no text, so shortcuts keep working right after dragging one.
export function isTyping(e) {
  const t = e.target;
  return t && ((t.tagName === "INPUT" && t.type !== "range") || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}
