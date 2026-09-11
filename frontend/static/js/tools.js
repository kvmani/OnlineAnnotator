/**
 * OnlineAnnotator Computer Vision Assistance Tools
 */
const CVTools = {
  async runOtsuOnROI(imageId, roiBbox) {
    try {
      showToast("Running hydride Otsu auto-thresholding on ROI...", "info");
      const res = await API.post("/api/v1/tools/otsu-threshold", {
        image_id: imageId,
        roi_bbox: roiBbox,
        invert: true,
        blur_kernel: 3,
        morphology_close: 2,
        remove_small_speckles: 15,
      });

      showToast(`Detected ${res.feature_count} hydride features (Area fraction: ${(res.area_fraction * 100).toFixed(2)}%)`, "success");
      return res;
    } catch (err) {
      showToast(`Otsu thresholding failed: ${err.message}`, "error");
      throw err;
    }
  },

  async runOtsuFull(imageId) {
    return this.runOtsuOnROI(imageId, null);
  },
};
