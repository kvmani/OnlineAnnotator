/**
 * OnlineAnnotator API Client
 */
const API = {
  token: localStorage.getItem("annotator_token") || null,

  setToken(token) {
    this.token = token;
    if (token) {
      localStorage.setItem("annotator_token", token);
    } else {
      localStorage.removeItem("annotator_token");
    }
  },

  async request(endpoint, options = {}) {
    const headers = options.headers || {};
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    options.headers = headers;
    options.credentials = "include"; // Send and receive session cookies

    try {
      const response = await fetch(endpoint, options);
      if (response.status === 401) {
        // Unauthorized
        this.setToken(null);
        window.dispatchEvent(new CustomEvent("auth:required"));
        throw new Error("Session expired or unauthorized. Please log in.");
      }

      if (!response.ok) {
        let errMessage = `Error ${response.status}: ${response.statusText}`;
        try {
          const errData = await response.json();
          if (errData.detail) errMessage = errData.detail;
        } catch (_) {}
        throw new Error(errMessage);
      }

      const contentType = response.headers.get("content-type");
      if (contentType && contentType.includes("application/json")) {
        return await response.json();
      }
      return response;
    } catch (err) {
      console.error("API Request Failed:", err);
      throw err;
    }
  },

  get(endpoint) {
    return this.request(endpoint, { method: "GET" });
  },

  post(endpoint, data) {
    const isFormData = data instanceof FormData;
    return this.request(endpoint, {
      method: "POST",
      body: isFormData ? data : JSON.stringify(data),
    });
  },

  delete(endpoint) {
    return this.request(endpoint, { method: "DELETE" });
  },
};

// Global Toast Notifications
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}
