/**
 * OnlineAnnotator Dataset Export Controller
 */
const ExportModal = {
  currentProjectId: null,

  init() {
    this.bindEvents();
  },

  bindEvents() {
    const modal = document.getElementById("modal-export");
    const btnOpen = document.getElementById("btn-export-modal");
    const btnClose = document.getElementById("btn-close-export");
    const btnCancel = document.getElementById("btn-cancel-export");
    const btnGenerate = document.getElementById("btn-generate-export");

    if (btnOpen) {
      btnOpen.addEventListener("click", () => {
        const sel = document.getElementById("project-select");
        this.currentProjectId = sel ? parseInt(sel.value) : null;
        if (!this.currentProjectId) {
          showToast("Please select an active project to export.", "warning");
          return;
        }
        document.getElementById("export-download-result").style.display = "none";
        modal.classList.add("active");
      });
    }

    if (btnClose) btnClose.addEventListener("click", () => modal.classList.remove("active"));
    if (btnCancel) btnCancel.addEventListener("click", () => modal.classList.remove("active"));

    if (btnGenerate) {
      btnGenerate.addEventListener("click", async () => {
        const format = document.getElementById("export-format-select").value;
        const maskType = document.querySelector('input[name="export-mask-type"]:checked').value;
        const trainPct = parseFloat(document.getElementById("split-train").value) / 100.0;
        const valPct = parseFloat(document.getElementById("split-val").value) / 100.0;
        const testPct = parseFloat(document.getElementById("split-test").value) / 100.0;
        const includeUnreviewed = document.getElementById("chk-include-unreviewed").checked;

        try {
          btnGenerate.disabled = true;
          btnGenerate.textContent = "Packaging Dataset...";

          const res = await API.post(`/api/v1/export/${this.currentProjectId}`, {
            format,
            mask_type: maskType,
            train_pct: trainPct,
            val_pct: valPct,
            test_pct: testPct,
            include_unreviewed: includeUnreviewed,
          });

          const resultBox = document.getElementById("export-download-result");
          const dlLink = document.getElementById("btn-export-download-link");
          const successMsg = document.getElementById("export-success-msg");

          successMsg.textContent = `Export Package Created! (${res.total_images_exported} images: ${res.train_count} train, ${res.val_count} val, ${res.test_count} test)`;
          dlLink.href = res.download_url;
          dlLink.download = res.filename;
          resultBox.style.display = "flex";

          showToast("Dataset bundle generated successfully!", "success");
        } catch (err) {
          showToast(`Export failed: ${err.message}`, "error");
        } finally {
          btnGenerate.disabled = false;
          btnGenerate.textContent = "Generate Export Archive";
        }
      });
    }
  },
};

window.addEventListener("DOMContentLoaded", () => ExportModal.init());
