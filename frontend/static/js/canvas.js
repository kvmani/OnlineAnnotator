/**
 * OnlineAnnotator Interactive 2D Canvas Engine
 */
const CanvasEngine = {
  canvas: null,
  ctx: null,
  container: null,
  cursorPreview: null,

  // Image & Transformation state
  image: null,
  imageWidth: 0,
  imageHeight: 0,
  scale: 1.0,
  panX: 0,
  panY: 0,
  isPanning: false,
  lastMouseX: 0,
  lastMouseY: 0,

  // Tool state
  activeTool: "brush", // brush, eraser, polygon, otsu_wand, pan
  brushSize: 12,
  activeClass: { class_index: 1, name: "Hydride", color_hex: "#FF0000" },
  maskOpacity: 0.5,
  maskRenderMode: "filled", // filled, outline, hidden
  contrast: 100,
  brightness: 100,
  invertImage: false,

  // Drawing state
  shapes: [], // [{ id, type, class_index, color, points: [[x,y]...], brush_size, closed }]
  currentShape: null,
  isDrawing: false,
  polyVertices: [], // for polygon in progress
  roiBox: null, // for Otsu Wand drag

  // History stack
  undoStack: [],
  redoStack: [],
  maxHistory: 30,

  // Change tracking
  isDirty: false,

  init(canvasId, containerId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext("2d");
    this.container = document.getElementById(containerId);
    this.cursorPreview = document.getElementById("canvas-cursor-preview");

    this.bindEvents();
    this.resizeCanvas();
  },

  bindEvents() {
    window.addEventListener("resize", () => this.resizeCanvas());

    // Canvas Mouse Events
    this.canvas.addEventListener("mousedown", (e) => this.onMouseDown(e));
    window.addEventListener("mousemove", (e) => this.onMouseMove(e));
    window.addEventListener("mouseup", (e) => this.onMouseUp(e));
    this.canvas.addEventListener("wheel", (e) => this.onWheel(e), { passive: false });
    this.canvas.addEventListener("dblclick", (e) => this.onDoubleClick(e));

    // Prevent context menu on canvas
    this.canvas.addEventListener("contextmenu", (e) => e.preventDefault());

    // Keyboard shortcuts
    window.addEventListener("keydown", (e) => this.onKeyDown(e));
  },

  resizeCanvas() {
    if (!this.container) return;
    this.canvas.width = this.container.clientWidth;
    this.canvas.height = this.container.clientHeight;
    this.render();
  },

  loadImage(url, onLoaded = null) {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      this.image = img;
      this.imageWidth = img.naturalWidth || img.width;
      this.imageHeight = img.naturalHeight || img.height;
      this.fitToScreen();
      this.render();
      if (onLoaded) onLoaded();
    };
    img.src = url;
  },

  fitToScreen() {
    if (!this.image || !this.canvas) return;
    const padding = 40;
    const availW = this.canvas.width - padding;
    const availH = this.canvas.height - padding;

    const scaleX = availW / this.imageWidth;
    const scaleY = availH / this.imageHeight;
    this.scale = Math.min(scaleX, scaleY, 1.0); // don't over-stretch small images by default

    this.panX = (this.canvas.width - this.imageWidth * this.scale) / 2;
    this.panY = (this.canvas.height - this.imageHeight * this.scale) / 2;

    this.updateZoomLabel();
  },

  resetZoom() {
    this.scale = 1.0;
    if (this.image) {
      this.panX = (this.canvas.width - this.imageWidth) / 2;
      this.panY = (this.canvas.height - this.imageHeight) / 2;
    }
    this.updateZoomLabel();
    this.render();
  },

  updateZoomLabel() {
    const label = document.getElementById("label-zoom-level");
    if (label) label.textContent = `${Math.round(this.scale * 100)}%`;
  },

  // Coordinate transformations
  screenToImageCoords(screenX, screenY) {
    const rect = this.canvas.getBoundingClientRect();
    const cx = screenX - rect.left;
    const cy = screenY - rect.top;

    const imgX = (cx - this.panX) / this.scale;
    const imgY = (cy - this.panY) / this.scale;
    return { x: imgX, y: imgY };
  },

  imageToScreenCoords(imgX, imgY) {
    const cx = imgX * this.scale + this.panX;
    const cy = imgY * this.scale + this.panY;
    return { x: cx, y: cy };
  },

  // Event handlers
  onMouseDown(e) {
    if (e.button === 1 || this.activeTool === "pan" || e.spaceKey) {
      // Middle click or Pan tool
      this.isPanning = true;
      this.lastMouseX = e.clientX;
      this.lastMouseY = e.clientY;
      this.canvas.style.cursor = "grabbing";
      return;
    }

    if (e.button === 0) {
      // Left click
      const pt = this.screenToImageCoords(e.clientX, e.clientY);

      if (this.activeTool === "brush") {
        this.saveHistoryState();
        this.isDrawing = true;
        this.currentShape = {
          id: `shape_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
          type: "brush_stroke",
          class_index: this.activeClass.class_index,
          color: this.activeClass.color_hex,
          brush_size: this.brushSize,
          points: [[pt.x, pt.y]],
        };
        this.shapes.push(this.currentShape);
        this.isDirty = true;
        this.render();
      } else if (this.activeTool === "eraser") {
        this.saveHistoryState();
        this.isDrawing = true;
        this.eraseAt(pt.x, pt.y, this.brushSize);
        this.isDirty = true;
        this.render();
      } else if (this.activeTool === "polygon") {
        // Add vertex
        if (this.polyVertices.length > 2) {
          // Check if clicked near start point to close
          const startPt = this.polyVertices[0];
          const dist = Math.hypot(pt.x - startPt[0], pt.y - startPt[1]);
          if (dist * this.scale < 15) {
            this.closePolygon();
            return;
          }
        }
        this.polyVertices.push([pt.x, pt.y]);
        this.render();
      } else if (this.activeTool === "otsu_wand") {
        // Start ROI drag box
        this.isDrawing = true;
        this.roiBox = { startX: pt.x, startY: pt.y, endX: pt.x, endY: pt.y };
        this.render();
      }
    }
  },

  onMouseMove(e) {
    const pt = this.screenToImageCoords(e.clientX, e.clientY);

    // Update coordinate display
    const coordsEl = document.getElementById("canvas-coords");
    if (coordsEl && pt.x >= 0 && pt.y >= 0 && pt.x <= this.imageWidth && pt.y <= this.imageHeight) {
      coordsEl.textContent = `X: ${Math.round(pt.x)}, Y: ${Math.round(pt.y)}`;
    }

    // Cursor preview
    if (this.cursorPreview && (this.activeTool === "brush" || this.activeTool === "eraser")) {
      const rect = this.canvas.getBoundingClientRect();
      const radius = this.brushSize * this.scale;
      this.cursorPreview.style.display = "block";
      this.cursorPreview.style.width = `${radius * 2}px`;
      this.cursorPreview.style.height = `${radius * 2}px`;
      this.cursorPreview.style.left = `${e.clientX}px`;
      this.cursorPreview.style.top = `${e.clientY}px`;
      this.cursorPreview.style.borderColor = this.activeTool === "eraser" ? "#f43f5e" : (this.activeClass.color_hex || "#ffffff");
    } else if (this.cursorPreview) {
      this.cursorPreview.style.display = "none";
    }

    if (this.isPanning) {
      const dx = e.clientX - this.lastMouseX;
      const dy = e.clientY - this.lastMouseY;
      this.panX += dx;
      this.panY += dy;
      this.lastMouseX = e.clientX;
      this.lastMouseY = e.clientY;
      this.render();
      return;
    }

    if (this.isDrawing) {
      if (this.activeTool === "brush" && this.currentShape) {
        this.currentShape.points.push([pt.x, pt.y]);
        this.render();
      } else if (this.activeTool === "eraser") {
        this.eraseAt(pt.x, pt.y, this.brushSize);
        this.render();
      } else if (this.activeTool === "otsu_wand" && this.roiBox) {
        this.roiBox.endX = pt.x;
        this.roiBox.endY = pt.y;
        this.render();
      }
    } else if (this.activeTool === "polygon" && this.polyVertices.length > 0) {
      // Live rubber band preview
      this.render(pt);
    }
  },

  onMouseUp(e) {
    if (this.isPanning) {
      this.isPanning = false;
      this.canvas.style.cursor = this.activeTool === "pan" ? "grab" : "crosshair";
    }

    if (this.isDrawing) {
      this.isDrawing = false;
      if (this.activeTool === "otsu_wand" && this.roiBox) {
        // Trigger ROI Otsu thresholding
        const x = Math.min(this.roiBox.startX, this.roiBox.endX);
        const y = Math.min(this.roiBox.startY, this.roiBox.endY);
        const w = Math.abs(this.roiBox.endX - this.roiBox.startX);
        const h = Math.abs(this.roiBox.endY - this.roiBox.startY);
        this.roiBox = null;

        if (w > 10 && h > 10) {
          window.dispatchEvent(new CustomEvent("canvas:otsu_roi", {
            detail: [Math.round(x), Math.round(y), Math.round(w), Math.round(h)],
          }));
        }
        this.render();
      }
      this.currentShape = null;
    }
  },

  onDoubleClick(e) {
    if (this.activeTool === "polygon" && this.polyVertices.length >= 3) {
      this.closePolygon();
    }
  },

  closePolygon() {
    if (this.polyVertices.length < 3) return;
    this.saveHistoryState();
    this.shapes.push({
      id: `shape_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
      type: "polygon",
      class_index: this.activeClass.class_index,
      color: this.activeClass.color_hex,
      closed: true,
      points: [...this.polyVertices],
    });
    this.polyVertices = [];
    this.isDirty = true;
    this.render();
  },

  onWheel(e) {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
    const newScale = Math.max(0.1, Math.min(15.0, this.scale * zoomFactor));

    // Anchor zoom to cursor position
    const rect = this.canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    this.panX = mouseX - (mouseX - this.panX) * (newScale / this.scale);
    this.panY = mouseY - (mouseY - this.panY) * (newScale / this.scale);
    this.scale = newScale;

    this.updateZoomLabel();
    this.render();
  },

  onKeyDown(e) {
    // Shortcuts
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.key === "b" || e.key === "B") {
      this.setTool("brush");
    } else if (e.key === "e" || e.key === "E") {
      this.setTool("eraser");
    } else if (e.key === "p" || e.key === "P") {
      this.setTool("polygon");
    } else if (e.key === "w" || e.key === "W") {
      this.setTool("otsu_wand");
    } else if (e.key === " " && !this.isPanning) {
      this.setTool("pan");
    } else if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z")) {
      e.preventDefault();
      if (e.shiftKey) this.redo();
      else this.undo();
    } else if ((e.ctrlKey || e.metaKey) && (e.key === "y" || e.key === "Y")) {
      e.preventDefault();
      this.redo();
    } else if (e.key === "[") {
      this.setBrushSize(Math.max(2, this.brushSize - 2));
    } else if (e.key === "]") {
      this.setBrushSize(Math.min(80, this.brushSize + 2));
    }
  },

  setTool(toolName) {
    this.activeTool = toolName;
    if (this.polyVertices.length > 0 && toolName !== "polygon") {
      this.polyVertices = [];
    }
    const toolBtns = document.querySelectorAll(".tool-btn");
    toolBtns.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tool === toolName);
    });
    this.canvas.style.cursor = toolName === "pan" ? "grab" : "crosshair";
    this.render();
  },

  setBrushSize(size) {
    this.brushSize = size;
    const slider = document.getElementById("slider-brush-size");
    const label = document.getElementById("label-brush-size");
    if (slider) slider.value = size;
    if (label) label.textContent = `${size}px`;
  },

  eraseAt(imgX, imgY, radius) {
    // Simple shape filtering: delete shapes whose vertices are completely within erase circle
    // or trim points for brush strokes
    const newShapes = [];
    for (const shape of this.shapes) {
      if (shape.type === "brush_stroke") {
        const remainingPoints = shape.points.filter((pt) => Math.hypot(pt[0] - imgX, pt[1] - imgY) > radius);
        if (remainingPoints.length > 1) {
          shape.points = remainingPoints;
          newShapes.push(shape);
        }
      } else {
        // Polygons: if center or any point is hit, remove or keep
        const hit = shape.points.some((pt) => Math.hypot(pt[0] - imgX, pt[1] - imgY) <= radius);
        if (!hit) {
          newShapes.push(shape);
        }
      }
    }
    this.shapes = newShapes;
  },

  // History Undo / Redo
  saveHistoryState() {
    this.undoStack.push(JSON.stringify(this.shapes));
    if (this.undoStack.length > this.maxHistory) {
      this.undoStack.shift();
    }
    this.redoStack = []; // Clear redo stack on new action
  },

  undo() {
    if (this.undoStack.length === 0) return;
    this.redoStack.push(JSON.stringify(this.shapes));
    const previousState = this.undoStack.pop();
    this.shapes = JSON.parse(previousState);
    this.isDirty = true;
    this.render();
    showToast("Undo", "info");
  },

  redo() {
    if (this.redoStack.length === 0) return;
    this.undoStack.push(JSON.stringify(this.shapes));
    const nextState = this.redoStack.pop();
    this.shapes = JSON.parse(nextState);
    this.isDirty = true;
    this.render();
    showToast("Redo", "info");
  },

  // Integration with Otsu Detection
  addContoursFromOtsu(contours, classIndex = 1, color = "#FF0000") {
    this.saveHistoryState();
    for (const pts of contours) {
      if (pts.length >= 3) {
        this.shapes.push({
          id: `otsu_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
          type: "polygon",
          class_index: classIndex,
          color: color,
          closed: true,
          points: pts,
        });
      }
    }
    this.isDirty = true;
    this.render();
  },

  // Render loop
  render(liveCursorPt = null) {
    if (!this.ctx || !this.canvas) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    // 1. Draw Background Micrograph
    if (this.image) {
      ctx.save();
      // Apply image filters
      let filterStr = `brightness(${this.brightness}%) contrast(${this.contrast}%)`;
      if (this.invertImage) filterStr += " invert(100%)";
      ctx.filter = filterStr;
      ctx.drawImage(this.image, 0, 0, this.imageWidth, this.imageHeight);
      ctx.restore();
    }

    // 2. Draw Vector Annotations / Mask Overlay
    if (this.maskRenderMode !== "hidden") {
      ctx.save();
      ctx.globalAlpha = this.maskRenderMode === "outline" ? 1.0 : this.maskOpacity;

      for (const shape of this.shapes) {
        ctx.fillStyle = shape.color || "#FF0000";
        ctx.strokeStyle = shape.color || "#FF0000";

        if (shape.type === "polygon") {
          const pts = shape.points;
          if (pts.length >= 2) {
            ctx.beginPath();
            ctx.moveTo(pts[0][0], pts[0][1]);
            for (let i = 1; i < pts.length; i++) {
              ctx.lineTo(pts[i][0], pts[i][1]);
            }
            if (shape.closed) ctx.closePath();

            if (this.maskRenderMode === "filled") {
              ctx.fill();
            }
            ctx.lineWidth = Math.max(1.5, 2 / this.scale);
            ctx.stroke();
          }
        } else if (shape.type === "brush_stroke") {
          const pts = shape.points;
          const radius = shape.brush_size || 10;
          ctx.lineCap = "round";
          ctx.lineJoin = "round";
          ctx.lineWidth = radius * 2;

          if (pts.length === 1) {
            ctx.beginPath();
            ctx.arc(pts[0][0], pts[0][1], radius, 0, Math.PI * 2);
            ctx.fill();
          } else if (pts.length > 1) {
            ctx.beginPath();
            ctx.moveTo(pts[0][0], pts[0][1]);
            for (let i = 1; i < pts.length; i++) {
              ctx.lineTo(pts[i][0], pts[i][1]);
            }
            ctx.stroke();
          }
        }
      }
      ctx.restore();
    }

    // 3. Draw In-Progress Polygon
    if (this.polyVertices.length > 0) {
      ctx.save();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2 / this.scale;
      ctx.setLineDash([4 / this.scale, 4 / this.scale]);

      ctx.beginPath();
      ctx.moveTo(this.polyVertices[0][0], this.polyVertices[0][1]);
      for (let i = 1; i < this.polyVertices.length; i++) {
        ctx.lineTo(this.polyVertices[i][0], this.polyVertices[i][1]);
      }
      if (liveCursorPt) {
        ctx.lineTo(liveCursorPt.x, liveCursorPt.y);
      }
      ctx.stroke();

      // Vertex dots
      ctx.setLineDash([]);
      ctx.fillStyle = "#f43f5e";
      for (const pt of this.polyVertices) {
        ctx.beginPath();
        ctx.arc(pt[0], pt[1], 4 / this.scale, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    // 4. Draw In-Progress ROI Drag Box
    if (this.roiBox) {
      ctx.save();
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2 / this.scale;
      ctx.setLineDash([6 / this.scale, 6 / this.scale]);
      const x = Math.min(this.roiBox.startX, this.roiBox.endX);
      const y = Math.min(this.roiBox.startY, this.roiBox.endY);
      const w = Math.abs(this.roiBox.endX - this.roiBox.startX);
      const h = Math.abs(this.roiBox.endY - this.roiBox.startY);
      ctx.strokeRect(x, y, w, h);
      ctx.restore();
    }

    ctx.restore();
  },

  // Export raster mask to data URL
  exportRasterMaskBase64() {
    if (!this.imageWidth || !this.imageHeight) return null;
    const offCanvas = document.createElement("canvas");
    offCanvas.width = this.imageWidth;
    offCanvas.height = this.imageHeight;
    const offCtx = offCanvas.getContext("2d");

    // Pure black background
    offCtx.fillStyle = "#000000";
    offCtx.fillRect(0, 0, this.imageWidth, this.imageHeight);

    // Draw all shapes
    for (const shape of this.shapes) {
      offCtx.fillStyle = shape.color || "#FF0000";
      offCtx.strokeStyle = shape.color || "#FF0000";

      if (shape.type === "polygon" && shape.points.length >= 3) {
        offCtx.beginPath();
        offCtx.moveTo(shape.points[0][0], shape.points[0][1]);
        for (let i = 1; i < shape.points.length; i++) {
          offCtx.lineTo(shape.points[i][0], shape.points[i][1]);
        }
        offCtx.closePath();
        offCtx.fill();
      } else if (shape.type === "brush_stroke") {
        const radius = shape.brush_size || 10;
        offCtx.lineCap = "round";
        offCtx.lineJoin = "round";
        offCtx.lineWidth = radius * 2;

        if (shape.points.length === 1) {
          offCtx.beginPath();
          offCtx.arc(shape.points[0][0], shape.points[0][1], radius, 0, Math.PI * 2);
          offCtx.fill();
        } else if (shape.points.length > 1) {
          offCtx.beginPath();
          offCtx.moveTo(shape.points[0][0], shape.points[0][1]);
          for (let i = 1; i < shape.points.length; i++) {
            offCtx.lineTo(shape.points[i][0], shape.points[i][1]);
          }
          offCtx.stroke();
        }
      }
    }

    return offCanvas.toDataURL("image/png");
  },
};
