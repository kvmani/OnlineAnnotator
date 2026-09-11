/**
 * OnlineAnnotator Master Application Controller
 */
const App = {
  activeProjectId: null,
  activeImageId: null,
  projectList: [],
  projectImages: [],
  activeFilter: "all",
  classes: [],
  autoSaveTimer: null,
  lockHeartbeatTimer: null,

  init() {
    CanvasEngine.init("annotation-canvas", "canvas-container");
    this.bindEvents();
    this.bindWorkspaceControls();
  },

  bindEvents() {
    // Auth success listener
    window.addEventListener("auth:success", () => {
      this.loadProjects();
    });

    // Project selection dropdown
    const projSelect = document.getElementById("project-select");
    projSelect.addEventListener("change", (e) => {
      this.activeProjectId = parseInt(e.target.value);
      this.loadProjectImages();
    });

    // Gallery filter pills
    const pills = document.querySelectorAll(".filter-pill");
    pills.forEach((pill) => {
      pill.addEventListener("click", () => {
        pills.forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        this.activeFilter = pill.dataset.filter;
        this.renderGallery();
      });
    });

    // Back to Dashboard
    document.getElementById("btn-back-to-gallery").addEventListener("click", () => {
      this.returnToDashboard();
    });

    // Upload Modal
    const uploadModal = document.getElementById("modal-upload");
    const btnUploadOpen = document.getElementById("btn-upload-modal");
    const btnUploadClose = document.getElementById("btn-close-upload");
    const btnUploadCancel = document.getElementById("btn-cancel-upload");
    const btnChooseFiles = document.getElementById("btn-choose-files");
    const fileInput = document.getElementById("upload-file-input");
    const btnStartUpload = document.getElementById("btn-start-upload");

    btnUploadOpen.addEventListener("click", () => {
      this.populateUploadModalProjects();
      uploadModal.classList.add("active");
    });
    btnUploadClose.addEventListener("click", () => uploadModal.classList.remove("active"));
    btnUploadCancel.addEventListener("click", () => uploadModal.classList.remove("active"));
    btnChooseFiles.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
      const listEl = document.getElementById("upload-file-list");
      listEl.innerHTML = Array.from(fileInput.files)
        .map((f) => `<span class="text-xs text-muted">📄 ${f.name} (${Math.round(f.size / 1024)} KB)</span>`)
        .join("");
    });

    btnStartUpload.addEventListener("click", async () => {
      const pId = document.getElementById("upload-project-select").value;
      const split = document.getElementById("upload-split-select").value;
      const files = fileInput.files;

      if (!files || files.length === 0) {
        showToast("Please choose at least one micrograph image to upload.", "warning");
        return;
      }

      const formData = new FormData();
      formData.append("split_assignment", split);
      for (const f of files) {
        formData.append("files", f);
      }

      try {
        btnStartUpload.disabled = true;
        btnStartUpload.textContent = "Uploading...";
        const res = await API.post(`/api/v1/projects/${pId}/images`, formData);
        showToast(res.message, "success");
        uploadModal.classList.remove("active");
        fileInput.value = "";
        document.getElementById("upload-file-list").innerHTML = "";
        this.loadProjectImages();
      } catch (err) {
        showToast(`Upload failed: ${err.message}`, "error");
      } finally {
        btnStartUpload.disabled = false;
        btnStartUpload.textContent = "Upload to Dataset";
      }
    });

    // Session Resume Event
    window.addEventListener("session:resume", (e) => {
      const { projectId, imageId } = e.detail;
      this.activeProjectId = projectId;
      document.getElementById("project-select").value = projectId;
      this.openImageWorkspace(imageId);
    });

    // WebSocket collaborator updates
    window.addEventListener("ws:event", (e) => {
      const data = e.detail;
      if (data.event === "LOCK_ACQUIRED" || data.event === "LOCK_RELEASED" || data.event === "STATUS_CHANGED") {
        this.loadProjectImages(false); // silent reload
      }
    });

    // Release lock on tab close / unload
    window.addEventListener("beforeunload", () => {
      if (this.activeImageId) {
        navigator.sendBeacon(`/api/v1/images/${this.activeImageId}/lock`, new Blob([], { type: "text/plain" }));
      }
    });

    // Auto-save interval (every 20s)
    this.autoSaveTimer = setInterval(() => {
      if (this.activeImageId && CanvasEngine.isDirty) {
        this.saveDraft(true);
      }
    }, 20000);
  },

  bindWorkspaceControls() {
    // Zoom buttons
    document.getElementById("btn-zoom-in").addEventListener("click", () => {
      CanvasEngine.scale = Math.min(15.0, CanvasEngine.scale * 1.2);
      CanvasEngine.updateZoomLabel();
      CanvasEngine.render();
    });

    document.getElementById("btn-zoom-out").addEventListener("click", () => {
      CanvasEngine.scale = Math.max(0.1, CanvasEngine.scale * 0.8);
      CanvasEngine.updateZoomLabel();
      CanvasEngine.render();
    });

    document.getElementById("btn-zoom-fit").addEventListener("click", () => CanvasEngine.fitToScreen());
    document.getElementById("btn-zoom-reset").addEventListener("click", () => CanvasEngine.resetZoom());

    // Tool buttons
    const toolBtns = document.querySelectorAll(".tool-btn");
    toolBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        CanvasEngine.setTool(btn.dataset.tool);
      });
    });

    // Sliders
    const brushSlider = document.getElementById("slider-brush-size");
    brushSlider.addEventListener("input", (e) => {
      CanvasEngine.setBrushSize(parseInt(e.target.value));
    });

    const opacitySlider = document.getElementById("slider-mask-opacity");
    opacitySlider.addEventListener("input", (e) => {
      CanvasEngine.maskOpacity = parseInt(e.target.value) / 100.0;
      document.getElementById("label-mask-opacity").textContent = `${e.target.value}%`;
      CanvasEngine.render();
    });

    const contrastSlider = document.getElementById("slider-contrast");
    contrastSlider.addEventListener("input", (e) => {
      CanvasEngine.contrast = parseInt(e.target.value);
      document.getElementById("label-contrast").textContent = `${e.target.value}%`;
      CanvasEngine.render();
    });

    const brightnessSlider = document.getElementById("slider-brightness");
    brightnessSlider.addEventListener("input", (e) => {
      CanvasEngine.brightness = parseInt(e.target.value);
      document.getElementById("label-brightness").textContent = `${e.target.value}%`;
      CanvasEngine.render();
    });

    const chkInvert = document.getElementById("chk-invert-image");
    chkInvert.addEventListener("change", (e) => {
      CanvasEngine.invertImage = e.target.checked;
      CanvasEngine.render();
    });

    // Render mode segmented control
    const segBtns = document.querySelectorAll(".seg-btn");
    segBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        segBtns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        CanvasEngine.maskRenderMode = btn.dataset.mode;
        CanvasEngine.render();
      });
    });

    // History undo/redo
    document.getElementById("btn-undo").addEventListener("click", () => CanvasEngine.undo());
    document.getElementById("btn-redo").addEventListener("click", () => CanvasEngine.redo());

    // Save Draft button
    document.getElementById("btn-save-draft").addEventListener("click", () => this.saveDraft(false));

    // Submit for Review button
    document.getElementById("btn-submit-review").addEventListener("click", () => this.submitVersion());

    // Reviewer actions
    document.getElementById("btn-approve-annotation").addEventListener("click", () => this.reviewAnnotation("approve"));
    document.getElementById("btn-reject-annotation").addEventListener("click", () => this.reviewAnnotation("reject"));

    // Download Mask PNG
    document.getElementById("btn-download-mask-png").addEventListener("click", () => {
      if (!this.activeImageId) return;
      window.open(`/api/v1/annotations/${this.activeImageId}/mask`, "_blank");
    });

    // Navigation next/prev
    document.getElementById("btn-prev-image").addEventListener("click", () => this.navigateImage(-1));
    document.getElementById("btn-next-image").addEventListener("click", () => this.navigateImage(1));

    // Otsu Assistants
    document.getElementById("btn-run-otsu-full").addEventListener("click", async () => {
      if (!this.activeImageId) return;
      try {
        const res = await CVTools.runOtsuFull(this.activeImageId);
        CanvasEngine.addContoursFromOtsu(res.contours, CanvasEngine.activeClass.class_index, CanvasEngine.activeClass.color_hex);
      } catch (_) {}
    });

    document.getElementById("btn-run-otsu-roi").addEventListener("click", () => {
      CanvasEngine.setTool("otsu_wand");
      showToast("Click and drag a box across the hydrides to threshold.", "info");
    });

    window.addEventListener("canvas:otsu_roi", async (e) => {
      if (!this.activeImageId) return;
      const roi = e.detail;
      try {
        const res = await CVTools.runOtsuOnROI(this.activeImageId, roi);
        CanvasEngine.addContoursFromOtsu(res.contours, CanvasEngine.activeClass.class_index, CanvasEngine.activeClass.color_hex);
      } catch (_) {}
    });
  },

  async loadProjects() {
    try {
      const projects = await API.get("/api/v1/projects");
      this.projectList = projects;
      const select = document.getElementById("project-select");

      if (projects.length === 0) {
        select.innerHTML = `<option value="">No projects found</option>`;
        return;
      }

      select.innerHTML = projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");

      if (!this.activeProjectId && projects.length > 0) {
        this.activeProjectId = projects[0].id;
      } else {
        select.value = this.activeProjectId;
      }

      this.loadProjectImages();
    } catch (err) {
      showToast(`Failed to load projects: ${err.message}`, "error");
    }
  },

  populateUploadModalProjects() {
    const sel = document.getElementById("upload-project-select");
    sel.innerHTML = this.projectList.map((p) => `<option value="${p.id}" ${p.id === this.activeProjectId ? "selected" : ""}>${p.name}</option>`).join("");
  },

  async loadProjectImages(renderStats = true) {
    if (!this.activeProjectId) return;
    try {
      const [images, projectDetail] = await Promise.all([
        API.get(`/api/v1/projects/${this.activeProjectId}/images`),
        API.get(`/api/v1/projects/${this.activeProjectId}`),
      ]);

      this.projectImages = images;
      this.classes = projectDetail.classes || [];

      if (renderStats) {
        this.updateStatsStrip(projectDetail);
      }
      this.renderGallery();
    } catch (err) {
      showToast(`Failed to load images: ${err.message}`, "error");
    }
  },

  updateStatsStrip(detail) {
    document.getElementById("stat-total-images").textContent = detail.total_images;
    document.getElementById("stat-completed-images").textContent = detail.annotated_images;
    document.getElementById("stat-progress-images").textContent = detail.in_progress_images;
    document.getElementById("stat-review-images").textContent = detail.under_review_images;

    // Filter counts
    const images = this.projectImages;
    document.getElementById("count-filter-all").textContent = images.length;
    document.getElementById("count-filter-unannotated").textContent = images.filter((i) => i.status === "unannotated").length;
    document.getElementById("count-filter-in_progress").textContent = images.filter((i) => i.status === "in_progress").length;
    document.getElementById("count-filter-under_review").textContent = images.filter((i) => i.status === "under_review").length;
    document.getElementById("count-filter-completed").textContent = images.filter((i) => i.status === "completed").length;
  },

  renderGallery() {
    const grid = document.getElementById("image-gallery-grid");
    if (!grid) return;

    let filtered = this.projectImages;
    if (this.activeFilter !== "all") {
      filtered = filtered.filter((img) => img.status === this.activeFilter);
    }

    if (filtered.length === 0) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 48px; color: var(--text-muted);">
          No micrographs match the selected filter.
        </div>
      `;
      return;
    }

    grid.innerHTML = filtered
      .map((img) => {
        let statusBadge = `<span class="badge badge-gray">${img.status}</span>`;
        if (img.status === "completed") statusBadge = `<span class="badge badge-emerald">Approved</span>`;
        else if (img.status === "under_review") statusBadge = `<span class="badge badge-indigo">Review</span>`;
        else if (img.status === "in_progress") statusBadge = `<span class="badge badge-amber">Draft</span>`;

        let lockBanner = "";
        if (img.lock_info && img.lock_info.is_locked) {
          const lockedText = img.lock_info.locked_by_me ? "Locked by you" : `Locked by ${img.lock_info.locked_by}`;
          lockBanner = `<div class="image-card-lock-banner">🔒 ${lockedText}</div>`;
        }

        return `
        <div class="image-card" data-id="${img.id}">
          <img class="image-card-thumb" src="${img.image_url}" alt="${img.filename}" loading="lazy" />
          <div class="image-card-body">
            <div>
              <div class="image-card-filename" title="${img.filename}">${img.original_filename || img.filename}</div>
              <div class="image-card-meta">
                <span>${img.width} × ${img.height}</span>
                ${statusBadge}
              </div>
            </div>
            ${lockBanner}
          </div>
        </div>
      `;
      })
      .join("");

    // Bind card click
    grid.querySelectorAll(".image-card").forEach((card) => {
      card.addEventListener("click", () => {
        const id = parseInt(card.dataset.id);
        this.openImageWorkspace(id);
      });
    });
  },

  async openImageWorkspace(imageId) {
    try {
      // 1. Acquire lease lock
      const lockRes = await API.post(`/api/v1/images/${imageId}/lock`);
      showToast(lockRes.message, "info");

      // 2. Fetch image metadata & draft
      const [img, draft, versions] = await Promise.all([
        API.get(`/api/v1/images/${imageId}`),
        API.get(`/api/v1/annotations/${imageId}/draft`),
        API.get(`/api/v1/annotations/${imageId}/versions`),
      ]);

      this.activeImageId = imageId;

      // 3. Switch view
      document.getElementById("view-dashboard").classList.remove("active");
      document.getElementById("view-workspace").classList.add("active");

      // 4. Update topbar
      document.getElementById("workspace-image-name").textContent = img.original_filename || img.filename;
      const statusBadge = document.getElementById("workspace-image-status");
      statusBadge.textContent = img.status;
      statusBadge.className = `badge ${img.status === "completed" ? "badge-emerald" : img.status === "under_review" ? "badge-indigo" : "badge-amber"}`;

      // Reviewer actions visibility
      const reviewerActions = document.getElementById("reviewer-actions");
      const isReviewer = reviewerActions.dataset.allowed === "true";
      reviewerActions.style.display = (isReviewer && img.status === "under_review") ? "flex" : "none";

      // Counter
      const currentIndex = this.projectImages.findIndex((i) => i.id === imageId);
      document.getElementById("workspace-image-counter").textContent = `${currentIndex + 1} / ${this.projectImages.length}`;

      // 5. Load Image into Canvas
      CanvasEngine.shapes = draft.vector_data || [];
      CanvasEngine.activeTool = draft.active_tool || "brush";
      CanvasEngine.setBrushSize(draft.brush_size || 12);
      CanvasEngine.isDirty = false;

      CanvasEngine.loadImage(img.image_url, () => {
        if (draft.zoom_level && draft.zoom_level > 0.1) {
          CanvasEngine.scale = draft.zoom_level;
          CanvasEngine.panX = draft.pan_x || 0;
          CanvasEngine.panY = draft.pan_y || 0;
          CanvasEngine.updateZoomLabel();
          CanvasEngine.render();
        }
      });

      // 6. Setup Classes palette
      this.renderClassesList();

      // 7. Setup Revisions list
      this.renderRevisionsList(versions);

      // 8. Start lock renewal heartbeat (every 60s)
      clearInterval(this.lockHeartbeatTimer);
      this.lockHeartbeatTimer = setInterval(async () => {
        if (this.activeImageId) {
          try {
            await API.post(`/api/v1/images/${this.activeImageId}/lock`);
          } catch (_) {}
        }
      }, 60000);

      // Broadcast lock to peers
      WS.send({ event: "LOCK_ACQUIRED", image_id: imageId, email: Auth.currentUser.email });
    } catch (err) {
      showToast(`Cannot open image: ${err.message}`, "error");
    }
  },

  renderClassesList() {
    const listEl = document.getElementById("classes-list");
    if (!listEl) return;

    listEl.innerHTML = this.classes
      .map((c, i) => {
        const isActive = c.class_index === CanvasEngine.activeClass.class_index;
        return `
        <div class="class-item ${isActive ? "active" : ""}" data-idx="${c.class_index}">
          <div class="class-item-left">
            <span class="class-color-dot" style="background-color: ${c.color_hex};"></span>
            <span class="class-name">${c.name}</span>
          </div>
          <span class="class-shortcut">${i + 1}</span>
        </div>
      `;
      })
      .join("");

    listEl.querySelectorAll(".class-item").forEach((item) => {
      item.addEventListener("click", () => {
        const idx = parseInt(item.dataset.idx);
        const cls = this.classes.find((c) => c.class_index === idx);
        if (cls) {
          CanvasEngine.activeClass = cls;
          this.renderClassesList();
          CanvasEngine.render();
        }
      });
    });
  },

  renderRevisionsList(versions) {
    const listEl = document.getElementById("revisions-list");
    if (!listEl) return;

    if (!versions || versions.length === 0) {
      listEl.innerHTML = `<span class="text-muted text-sm">No committed versions yet.</span>`;
      return;
    }

    listEl.innerHTML = versions
      .map((v) => {
        const dateStr = v.created_at ? new Date(v.created_at).toLocaleDateString() : "";
        return `
        <div class="revision-card">
          <div class="revision-header">
            <strong>v${v.version_number} (${v.status})</strong>
            <button class="btn btn-outline-indigo btn-xs btn-restore-ver" data-id="${v.id}">Restore</button>
          </div>
          <span class="text-muted text-xs">By ${v.created_by} • ${dateStr}</span>
          ${v.review_comment ? `<span class="text-amber text-xs">"${v.review_comment}"</span>` : ""}
        </div>
      `;
      })
      .join("");

    listEl.querySelectorAll(".btn-restore-ver").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const verId = parseInt(btn.dataset.id);
        try {
          const restored = await API.post(`/api/v1/annotations/${this.activeImageId}/restore/${verId}`);
          CanvasEngine.shapes = restored.vector_data || [];
          CanvasEngine.render();
          showToast(`Restored version as active draft.`, "success");
        } catch (err) {
          showToast(`Restore failed: ${err.message}`, "error");
        }
      });
    });
  },

  async saveDraft(isSilent = false) {
    if (!this.activeImageId) return;

    const autosaveEl = document.getElementById("autosave-status");
    if (autosaveEl) autosaveEl.textContent = "Saving draft...";

    const maskB64 = CanvasEngine.exportRasterMaskBase64();

    try {
      await API.post(`/api/v1/annotations/${this.activeImageId}/draft`, {
        vector_data: CanvasEngine.shapes,
        mask_png_base64: maskB64,
        zoom_level: CanvasEngine.scale,
        pan_x: CanvasEngine.panX,
        pan_y: CanvasEngine.panY,
        active_class_index: CanvasEngine.activeClass.class_index,
        active_tool: CanvasEngine.activeTool,
        brush_size: CanvasEngine.brushSize,
      });

      CanvasEngine.isDirty = false;
      if (autosaveEl) autosaveEl.textContent = "Draft saved";
      if (!isSilent) showToast("Draft saved successfully.", "success");

      WS.send({ event: "DRAFT_SAVED", image_id: this.activeImageId });
    } catch (err) {
      if (autosaveEl) autosaveEl.textContent = "Draft save failed";
      if (!isSilent) showToast(`Failed to save draft: ${err.message}`, "error");
    }
  },

  async submitVersion() {
    if (!this.activeImageId) return;
    try {
      const maskB64 = CanvasEngine.exportRasterMaskBase64();
      const res = await API.post(`/api/v1/annotations/${this.activeImageId}/commit`, {
        vector_data: CanvasEngine.shapes,
        mask_png_base64: maskB64,
        submit_for_review: true,
      });

      showToast(`Version ${res.version_number} submitted for review!`, "success");
      CanvasEngine.isDirty = false;
      document.getElementById("workspace-image-status").textContent = "under_review";
      document.getElementById("workspace-image-status").className = "badge badge-indigo";

      // Refresh versions
      const versions = await API.get(`/api/v1/annotations/${this.activeImageId}/versions`);
      this.renderRevisionsList(versions);

      WS.send({ event: "STATUS_CHANGED", image_id: this.activeImageId, status: "under_review" });
    } catch (err) {
      showToast(`Submit failed: ${err.message}`, "error");
    }
  },

  async reviewAnnotation(action) {
    if (!this.activeImageId) return;
    const comment = prompt(`Enter ${action} remarks (optional):`) || "";
    try {
      const res = await API.post(`/api/v1/annotations/${this.activeImageId}/review`, {
        action,
        comment,
      });

      showToast(res.message, "success");
      document.getElementById("workspace-image-status").textContent = res.status;
      document.getElementById("workspace-image-status").className = `badge ${res.status === "completed" ? "badge-emerald" : "badge-amber"}`;
      document.getElementById("reviewer-actions").style.display = "none";

      WS.send({ event: "STATUS_CHANGED", image_id: this.activeImageId, status: res.status });
    } catch (err) {
      showToast(`Review action failed: ${err.message}`, "error");
    }
  },

  async navigateImage(direction) {
    if (!this.activeImageId || this.projectImages.length === 0) return;
    const currentIndex = this.projectImages.findIndex((i) => i.id === this.activeImageId);
    let newIndex = currentIndex + direction;
    if (newIndex < 0) newIndex = this.projectImages.length - 1;
    if (newIndex >= this.projectImages.length) newIndex = 0;

    // Auto-save current image before navigating
    if (CanvasEngine.isDirty) {
      await this.saveDraft(true);
    }

    // Release current lock
    await this.releaseCurrentLock();

    // Open next image
    this.openImageWorkspace(this.projectImages[newIndex].id);
  },

  async returnToDashboard() {
    if (CanvasEngine.isDirty) {
      await this.saveDraft(true);
    }
    await this.releaseCurrentLock();

    this.activeImageId = null;
    clearInterval(this.lockHeartbeatTimer);

    document.getElementById("view-workspace").classList.remove("active");
    document.getElementById("view-dashboard").classList.add("active");

    this.loadProjectImages();
    LedgerView.loadLedgerFeed();
  },

  async releaseCurrentLock() {
    if (this.activeImageId) {
      try {
        await API.delete(`/api/v1/images/${this.activeImageId}/lock`);
        WS.send({ event: "LOCK_RELEASED", image_id: this.activeImageId });
      } catch (_) {}
    }
  },
};

window.addEventListener("DOMContentLoaded", () => App.init());
