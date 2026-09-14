// User administration (administrators only).
import { api } from "../api.js";
import { setCrumbs } from "../nav.js";
import { ACCOUNT_HELP, MODE_HELP, MODE_LABELS, app } from "../state.js";
import { clear, confirmDialog, copyButton, field, fmtRelative, h, helpTip, icon, modal, toast } from "../ui.js";

export async function renderUsers(view) {
  setCrumbs([{ label: "Projects", href: "#/" }, { label: "Users" }]);
  const page = h("div", { class: "page" });
  view.append(page);
  const tableHost = h("div", { class: "card" });
  const add = h("button", { class: "btn btn-primary", type: "button" }, icon("plus"), "Add user");
  add.addEventListener("click", () => addUser(draw));
  page.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Users"),
    h("p", { class: "muted" }, "Everyone signs in with their office e-mail address, and every user can both annotate and review. New accounts get a temporary password that must be changed at first sign-in.")), add),
  tableHost);

  async function draw() {
    const { users } = await api.get("api/v1/users");
    const rows = users.map((u) => {
      const adminBox = h("input", { type: "checkbox", "aria-label": `${u.full_name} is an administrator` });
      adminBox.checked = u.is_admin;
      adminBox.disabled = u.id === app.me.id;
      adminBox.title = u.id === app.me.id ? "You cannot remove your own administrator access." : ACCOUNT_HELP.admin;
      adminBox.addEventListener("change", async () => {
        try {
          await api.patch(`api/v1/users/${u.id}`, { is_admin: adminBox.checked });
          u.is_admin = adminBox.checked;
          toast(adminBox.checked ? `${u.email} is now an administrator.` : `${u.email} is no longer an administrator (they still annotate and review).`, "success");
        } catch (err) {
          toast(err.message, "error");
          adminBox.checked = u.is_admin;
        }
      });
      const toggle = h("button", { class: "btn btn-small", type: "button", disabled: u.id === app.me.id }, u.is_active ? "Disable" : "Enable");
      toggle.addEventListener("click", async () => {
        if (u.is_active && !(await confirmDialog("Disable account", `${u.email} is signed out and cannot sign in until re-enabled. Their work is kept.`, { confirmLabel: "Disable", kind: "danger" }))) return;
        await api.patch(`api/v1/users/${u.id}`, { is_active: !u.is_active });
        draw();
      });
      const reset = h("button", { class: "btn btn-small", type: "button" }, "Reset password");
      reset.addEventListener("click", async () => {
        if (!(await confirmDialog("Reset password", `Give ${u.email} a new temporary password? Their current password stops working immediately.`, { confirmLabel: "Reset" }))) return;
        const res = await api.post(`api/v1/users/${u.id}/reset-password`);
        showPassword(u.email, res.temporary_password);
      });
      return h("tr", { class: u.is_active ? "" : "inactive" },
        h("td", {}, h("strong", {}, u.full_name), h("div", { class: "muted small" }, u.email)),
        h("td", {}, h("label", { class: "check small" }, adminBox, "Administrator")),
        h("td", {}, h("span", { class: `mode-tag mode-tag-${u.active_mode}`, title: MODE_HELP[u.active_mode] }, MODE_LABELS[u.active_mode] || u.active_mode)),
        h("td", { class: "small" }, u.is_active ? (u.must_change_password ? "Temporary password" : "Active") : "Disabled"),
        h("td", { class: "small muted" }, u.last_login_at ? fmtRelative(u.last_login_at) : "never"),
        h("td", { class: "right nowrap" }, reset, " ", toggle));
    });
    clear(tableHost).append(h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Person"),
        h("th", {}, "Privilege ", helpTip(h("ul", { class: "compact" }, h("li", {}, ACCOUNT_HELP.user), h("li", {}, ACCOUNT_HELP.admin)), { wide: true })),
        h("th", {}, "Working mode ", helpTip("What the person is doing right now. Each person switches between Annotate and Review themselves, at the top of the page; it is not a permission and administrators do not set it.")),
        h("th", {}, "Status"), h("th", {}, "Last sign-in"), h("th", {}, ""))),
      h("tbody", {}, rows))));
  }
  await draw();
  return {};
}

function addUser(onDone) {
  const email = h("input", { type: "email", required: true, placeholder: "name@lab.example" });
  const name = h("input", { required: true, placeholder: "Full name" });
  const isAdmin = h("input", { type: "checkbox" });
  modal({
    title: "Add user",
    body: h("div", { class: "stack" }, field("Office e-mail", email), field("Full name", name),
      h("p", { class: "small muted" }, ACCOUNT_HELP.user),
      h("label", { class: "check" }, isAdmin, "Administrator ", helpTip(ACCOUNT_HELP.admin))),
    actions: [{ label: "Cancel" }, {
      label: "Create account",
      kind: "primary",
      onClick: async () => {
        try {
          const res = await api.post("api/v1/users", { email: email.value, full_name: name.value, is_admin: isAdmin.checked });
          onDone();
          showPassword(res.user.email, res.temporary_password);
        } catch (err) {
          toast(err.message, "error");
          return true;
        }
        return false;
      },
    }],
  });
}

function showPassword(email, password) {
  modal({
    title: "Temporary password",
    body: h("div", { class: "stack" },
      h("p", {}, "Give this password to ", h("strong", {}, email), " personally (not by e-mail if you can avoid it). It is shown only now; they must choose their own at first sign-in."),
      h("div", { class: "password-box" }, h("code", {}, password), copyButton(password)),
      h("p", { class: "small muted" }, `Sign-in address: ${location.origin}${location.pathname}`)),
    actions: [{ label: "Done", kind: "primary" }],
  });
}
