// Sign-in (password or e-mail code) and password change.
import { api } from "../api.js";
import { app } from "../state.js";
import { h, helpTip, toast } from "../ui.js";

const DEMO_ACCOUNTS = [
  ["arun@demo.local", "arun-demo-1", "Arun: annotates and reviews"],
  ["riya@demo.local", "riya-demo-1", "Riya: annotates and reviews"],
  ["admin@demo.local", "admin-demo-1", "Administrator: also projects, classes, users"],
];

export function loginForm({ onDone, presetEmail = "" }) {
  const email = h("input", { type: "email", name: "email", autocomplete: "username", required: true, value: presetEmail, placeholder: "name@lab.example" });
  const password = h("input", { type: "password", name: "password", autocomplete: "current-password", required: true });
  const error = h("div", { class: "alert alert-error", hidden: true, role: "alert" });
  const submit = h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Sign in");
  const form = h("form", { class: "stack" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Office e-mail"), email),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Password"), password),
    error, submit);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    submit.disabled = true;
    submit.textContent = "Signing in…";
    try {
      const res = await api.post("api/v1/auth/login", { email: email.value, password: password.value });
      app.me = res.user;
      onDone(res.user);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      password.select();
    } finally {
      submit.disabled = false;
      submit.textContent = "Sign in";
    }
  });
  const wrap = h("div", {}, form);
  if (app.meta && app.meta.otp_login) wrap.append(otpSection(email, onDone));
  else {
    wrap.append(h("p", { class: "muted small center" }, "Forgot your password? Ask an administrator to reset it; you will get a temporary one."));
  }
  return wrap;
}

function otpSection(emailInput, onDone) {
  const box = h("div", { class: "otp-box" });
  const start = h("button", { class: "btn btn-link", type: "button" }, "E-mail me a one-time sign-in code instead");
  start.addEventListener("click", async () => {
    if (!emailInput.value) {
      emailInput.focus();
      toast("Type your office e-mail address first.", "info");
      return;
    }
    try {
      const res = await api.post("api/v1/auth/otp/request", { email: emailInput.value });
      const code = h("input", { inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", placeholder: "6-digit code", class: "otp-input" });
      const verify = h("button", { class: "btn btn-primary", type: "button" }, "Verify code");
      const err = h("div", { class: "alert alert-error", hidden: true });
      verify.addEventListener("click", async () => {
        try {
          const r = await api.post("api/v1/auth/otp/verify", { challenge_id: res.challenge_id, code: code.value });
          app.me = r.user;
          onDone(r.user);
        } catch (e2) {
          err.textContent = e2.message;
          err.hidden = false;
        }
      });
      box.replaceChildren(h("p", { class: "small" }, res.message), h("div", { class: "row" }, code, verify), err);
      code.focus();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  box.append(start);
  return box;
}

export function renderLogin(view, { onDone }) {
  const demo = app.meta && app.meta.demo;
  const card = h("div", { class: "login-card" },
    h("div", { class: "login-head" },
      h("img", { src: "static/img/favicon.svg", width: 44, height: 44, alt: "" }),
      h("div", {}, h("h1", {}, app.meta ? app.meta.site_name : "Online Annotator"),
        h("p", { class: "muted" }, "Pixel-exact ground truth for microstructure images: annotate, review, export."))),
    loginForm({ onDone }));
  if (demo) {
    const list = h("div", { class: "demo-accounts" }, h("div", { class: "field-label" }, "Demo accounts ",
      helpTip("This server runs in demo mode. Arun and Riya are ordinary users who can each annotate and review: submit work as one of them, then sign in as the other (for example in a private window) and review it in Review mode. Never use demo mode for real work.")));
    for (const [email, pw, desc] of DEMO_ACCOUNTS) {
      const b = h("button", { class: "demo-account", type: "button" }, h("strong", {}, email), h("span", {}, desc));
      b.addEventListener("click", () => {
        card.querySelector("input[name=email]").value = email;
        card.querySelector("input[name=password]").value = pw;
        card.querySelector("form").requestSubmit();
      });
      list.append(b);
    }
    card.append(list);
  }
  view.append(h("div", { class: "login-page" }, card,
    h("p", { class: "muted small center" }, h("a", { href: "#/help" }, "Help centre"), app.meta ? ` · version ${app.meta.version}` : "")));
  setTimeout(() => card.querySelector("input[name=email]").focus(), 30);
}

export function renderPasswordChange(view, { forced, onDone }) {
  const current = h("input", { type: "password", autocomplete: "current-password", required: true });
  const next = h("input", { type: "password", autocomplete: "new-password", required: true, minlength: 8 });
  const again = h("input", { type: "password", autocomplete: "new-password", required: true });
  const error = h("div", { class: "alert alert-error", hidden: true, role: "alert" });
  const form = h("form", { class: "stack" },
    h("label", { class: "field" }, h("span", { class: "field-label" }, forced ? "Temporary password" : "Current password"), current),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "New password"), next,
      h("span", { class: "field-hint" }, "At least 8 characters, mixing letters with numbers or symbols.")),
    h("label", { class: "field" }, h("span", { class: "field-label" }, "Repeat new password"), again),
    error, h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Save new password"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    if (next.value !== again.value) {
      error.textContent = "The two new passwords are different.";
      error.hidden = false;
      return;
    }
    try {
      const res = await api.post("api/v1/auth/change-password", { current_password: current.value, new_password: next.value });
      app.me = res.user;
      toast("Password changed.", "success");
      onDone();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });
  view.append(h("div", { class: "login-page" }, h("div", { class: "login-card" },
    h("h1", {}, forced ? "Choose your own password" : "Change password"),
    forced ? h("p", { class: "muted" }, "You signed in with a temporary password. Choose a new one that only you know before continuing.") : null,
    form)));
  setTimeout(() => current.focus(), 30);
}
