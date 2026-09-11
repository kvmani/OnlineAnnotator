/**
 * OnlineAnnotator Working Ledger and Session Resumption Controller
 */
const LedgerView = {
  init() {
    this.bindEvents();
  },

  bindEvents() {
    const btnResume = document.getElementById("btn-resume-session");
    if (btnResume) {
      btnResume.addEventListener("click", () => this.resumeLastSession());
    }

    // Load ledger feed on auth success or dashboard active
    window.addEventListener("auth:success", () => {
      this.loadLedgerFeed();
    });
  },

  async loadLedgerFeed() {
    const listContainer = document.getElementById("ledger-records-list");
    if (!listContainer) return;

    try {
      const records = await API.get("/api/v1/ledger/recent?limit=25");
      if (!records || records.length === 0) {
        listContainer.innerHTML = `<span class="text-muted text-sm">No activity recorded in ledger yet.</span>`;
        return;
      }

      listContainer.innerHTML = records
        .map((r) => {
          const dateStr = r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : "";
          return `
          <div class="ledger-row">
            <div class="ledger-row-left">
              <span class="ledger-tag">${r.event_type}</span>
              <span class="ledger-summary">${r.summary}</span>
            </div>
            <div class="ledger-row-right">
              <span class="ledger-time">${r.user_email} • ${dateStr}</span>
            </div>
          </div>
        `;
        })
        .join("");
    } catch (_) {
      // Ignore if unauthenticated or network drop
    }
  },

  async resumeLastSession() {
    try {
      const state = await API.get("/api/v1/ledger/resume");
      if (!state || !state.can_resume) {
        showToast("No active session found to resume.", "info");
        return;
      }

      showToast(`Resuming session on ${state.filename}...`, "success");
      window.dispatchEvent(
        new CustomEvent("session:resume", {
          detail: {
            projectId: state.project_id,
            imageId: state.image_id,
            zoomLevel: state.zoom_level,
            panX: state.pan_x,
            panY: state.pan_y,
            activeClassIndex: state.active_class_index,
          },
        })
      );
    } catch (err) {
      showToast(`Could not resume session: ${err.message}`, "warning");
    }
  },
};

window.addEventListener("DOMContentLoaded", () => LedgerView.init());
