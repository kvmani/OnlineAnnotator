/**
 * OnlineAnnotator Authentication Controller
 */
const Auth = {
  currentUser: null,
  otpChallengeId: null,
  otpTimerInterval: null,

  init() {
    this.bindEvents();
    this.checkSession();
  },

  bindEvents() {
    // Tab switching
    const tabPwd = document.getElementById("tab-auth-password");
    const tabOtp = document.getElementById("tab-auth-otp");
    const formPwd = document.getElementById("form-auth-password");
    const formOtp = document.getElementById("form-auth-otp");

    tabPwd.addEventListener("click", () => {
      tabPwd.classList.add("active");
      tabOtp.classList.remove("active");
      formPwd.classList.add("active");
      formOtp.classList.remove("active");
    });

    tabOtp.addEventListener("click", () => {
      tabOtp.classList.add("active");
      tabPwd.classList.remove("active");
      formOtp.classList.add("active");
      formPwd.classList.remove("active");
    });

    // Password Login Form Submission
    formPwd.addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = document.getElementById("auth-email-pwd").value;
      const password = document.getElementById("auth-password").value;

      try {
        const res = await API.post("/api/v1/auth/login", { email, password });
        API.setToken(res.token);
        this.currentUser = res.user;
        this.updateUserUI();
        this.closeModal();
        showToast("Logged in successfully!", "success");
        window.dispatchEvent(new CustomEvent("auth:success", { detail: res.user }));
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    // OTP Step 1: Request OTP
    const btnReqOtp = document.getElementById("btn-request-otp");
    btnReqOtp.addEventListener("click", async () => {
      const email = document.getElementById("auth-email-otp").value;
      if (!email || !email.includes("@")) {
        showToast("Please enter a valid office email address.", "warning");
        return;
      }

      try {
        btnReqOtp.disabled = true;
        btnReqOtp.textContent = "Sending OTP...";
        const res = await API.post("/api/v1/auth/email-otp/request", { email });
        this.otpChallengeId = res.challenge_id;

        document.getElementById("otp-step-1").style.display = "none";
        document.getElementById("otp-step-2").style.display = "block";

        if (res.dev_otp) {
          const devBox = document.getElementById("dev-otp-display");
          devBox.textContent = `DEV / INTRANET CODE: ${res.dev_otp}`;
          devBox.style.display = "block";
          document.getElementById("auth-otp-code").value = res.dev_otp;
        }

        this.startOtpTimer(res.expires_in_seconds || 600);
        showToast(res.message, "info");
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnReqOtp.disabled = false;
        btnReqOtp.textContent = "Request 6-Digit OTP";
      }
    });

    // OTP Step 2: Confirm OTP
    formOtp.addEventListener("submit", async (e) => {
      e.preventDefault();
      const otp = document.getElementById("auth-otp-code").value;
      if (!otp || otp.length !== 6) {
        showToast("Please enter the complete 6-digit code.", "warning");
        return;
      }

      try {
        const res = await API.post("/api/v1/auth/email-otp/confirm", {
          challenge_id: this.otpChallengeId,
          otp,
        });

        API.setToken(res.token);
        this.currentUser = res.user;
        this.updateUserUI();
        this.closeModal();
        clearInterval(this.otpTimerInterval);
        showToast("Email OTP verified successfully!", "success");
        window.dispatchEvent(new CustomEvent("auth:success", { detail: res.user }));
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    // Resend OTP
    document.getElementById("btn-resend-otp").addEventListener("click", () => {
      document.getElementById("otp-step-2").style.display = "none";
      document.getElementById("otp-step-1").style.display = "block";
      clearInterval(this.otpTimerInterval);
    });

    // Logout
    document.getElementById("btn-logout").addEventListener("click", async () => {
      try {
        await API.post("/api/v1/auth/logout");
      } catch (_) {}
      API.setToken(null);
      this.currentUser = null;
      this.showModal();
      showToast("Logged out.", "info");
    });

    // Listen for auth required event
    window.addEventListener("auth:required", () => {
      this.showModal();
    });
  },

  async checkSession() {
    try {
      const user = await API.get("/api/v1/auth/me");
      this.currentUser = user;
      this.updateUserUI();
      this.closeModal();
      window.dispatchEvent(new CustomEvent("auth:success", { detail: user }));
    } catch (_) {
      this.showModal();
    }
  },

  updateUserUI() {
    if (!this.currentUser) return;
    const emailEl = document.getElementById("header-user-email");
    const initialsEl = document.getElementById("header-user-initials");

    emailEl.textContent = this.currentUser.email;
    const initial = this.currentUser.email.charAt(0).toUpperCase();
    initialsEl.textContent = initial;

    // Role visibility
    const reviewerActions = document.getElementById("reviewer-actions");
    if (reviewerActions) {
      const isReviewer = ["admin", "lead_annotator", "reviewer"].includes(this.currentUser.role);
      reviewerActions.dataset.allowed = isReviewer ? "true" : "false";
    }
  },

  startOtpTimer(seconds) {
    let remaining = seconds;
    const timerEl = document.getElementById("otp-timer-text");
    clearInterval(this.otpTimerInterval);

    this.otpTimerInterval = setInterval(() => {
      remaining--;
      if (remaining <= 0) {
        clearInterval(this.otpTimerInterval);
        timerEl.textContent = "Code expired. Please request a new code.";
      } else {
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        timerEl.textContent = `Code expires in ${mins}:${secs < 10 ? "0" : ""}${secs}`;
      }
    }, 1000);
  },

  showModal() {
    document.getElementById("modal-auth").classList.add("active");
  },

  closeModal() {
    document.getElementById("modal-auth").classList.remove("active");
  },
};

window.addEventListener("DOMContentLoaded", () => Auth.init());
