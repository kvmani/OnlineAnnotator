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

// Account privilege and working mode are separate things. Every user can annotate and review;
// the working mode says which of the two they are doing now. The server keeps the mode and
// enforces it: these helpers only decide what to show.
export const isAdmin = () => Boolean(app.me && app.me.is_admin);
export const mode = () => (app.me && app.me.active_mode === "review" ? "review" : "annotate");
export const inReview = () => mode() === "review";

export const MODES = [
  { id: "annotate", label: "Annotate", icon: "edit" },
  { id: "review", label: "Review", icon: "review" },
];
export const MODE_LABELS = { annotate: "Annotate", review: "Review" };

export const MODE_HELP = {
  annotate: "Annotate mode: label images, import existing masks and submit your work for review.",
  review: "Review mode: check work that other people submitted, correct it if needed, then approve it or request changes.",
};

export const ACCOUNT_HELP = {
  user: "Every user can annotate and review, switching with the Annotate / Review control at the top of the page. Nobody reviews their own submissions, so a second person always checks the ground truth.",
  admin: "Administrators can also create projects and classes, manage user accounts, delete images and release other people's editing reservations. These rights do not depend on the working mode.",
};
