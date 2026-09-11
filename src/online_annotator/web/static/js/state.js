// Shared client state.
export const app = {
  me: null, // signed-in user
  meta: null, // /api/v1/meta
  prefs: loadPrefs(),
};

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem("oa.prefs") || "{}");
  } catch (_) {
    return {};
  }
}

export function savePref(key, value) {
  app.prefs[key] = value;
  try {
    localStorage.setItem("oa.prefs", JSON.stringify(app.prefs));
  } catch (_) {
    /* private mode */
  }
}

export const canReview = () => app.me && (app.me.role === "reviewer" || app.me.role === "admin");
export const isAdmin = () => app.me && app.me.role === "admin";

export const ROLE_HELP = {
  annotator: "Annotators label images and submit them for review.",
  reviewer: "Reviewers can also approve or return submissions, correct labels during review, set train/val/test splits and export datasets.",
  admin: "Administrators can also create projects and classes, manage user accounts and delete images.",
};
