const API_BASE = "http://localhost:5000/api";

// Categories loaded from API — populated at init
let CATEGORIES = []; // [{slug, display_label, icon, sort_order}, ...]

// ── DOM refs ──────────────────────────────────────────────────────────────────
const reportForm      = document.getElementById("report-form");
const descInput       = document.getElementById("description");
const dateInput       = document.getElementById("date");
const reportSubmitBtn = document.getElementById("report-submit-btn");
const reportFormError = document.getElementById("report-form-error");
const loadingEl       = document.getElementById("loading");
const emptyState      = document.getElementById("empty-state");
const reportsList     = document.getElementById("reports-list");
const totalAmountEl   = document.getElementById("total-amount");
const totalCountEl    = document.getElementById("total-count");

const modalOverlay   = document.getElementById("modal-overlay");
const modalReportId  = document.getElementById("modal-report-id");
const modalTitle     = document.getElementById("modal-title");
const subForm        = document.getElementById("sub-expense-form");
const subCategory    = document.getElementById("sub-category");
const subNote        = document.getElementById("sub-note");
const subAmount      = document.getElementById("sub-amount");
const subSubmitBtn   = document.getElementById("sub-submit-btn");
const subFormError   = document.getElementById("sub-form-error");
const modalCloseBtn  = document.getElementById("modal-close-btn");
const modalCancelBtn = document.getElementById("modal-cancel-btn");

const expandedReports = new Set();
const editingReports  = new Set();

dateInput.value = new Date().toISOString().split("T")[0];

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatCurrency(v) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v);
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatTimestamp(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}

function categoryLabel(slug) {
  const cat = CATEGORIES.find((c) => c.slug === slug);
  return cat ? `${cat.icon} ${cat.display_label}`.trim() : slug;
}

function buildCategoryOptions(selectedSlug) {
  return CATEGORIES.map((c) =>
    `<option value="${c.slug}" ${c.slug === selectedSlug ? "selected" : ""}>${c.icon} ${escapeHtml(c.display_label)}</option>`
  ).join("");
}

function showFieldError(id, msg) {
  const errEl = document.getElementById(`${id}-error`);
  const input = document.getElementById(id);
  if (errEl) errEl.textContent = msg;
  if (input) input.classList.toggle("invalid", !!msg);
}

function clearReportFormErrors() {
  showFieldError("description", "");
  showFieldError("date", "");
  reportFormError.textContent = "";
  reportFormError.classList.add("hidden");
}

function clearSubFormErrors() {
  showFieldError("sub-category", "");
  showFieldError("sub-amount", "");
  subFormError.textContent = "";
  subFormError.classList.add("hidden");
}

// ── API ───────────────────────────────────────────────────────────────────────

async function apiFetch(url, options = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

const api = {
  getCategories: ()              => apiFetch(`${API_BASE}/categories`),
  getExpenses:   ()              => apiFetch(`${API_BASE}/expenses`),
  getSummary:    ()              => apiFetch(`${API_BASE}/summary`),
  createReport:  (body)          => apiFetch(`${API_BASE}/expenses`, { method: "POST", body: JSON.stringify(body) }),
  updateReport:  (id, body)      => apiFetch(`${API_BASE}/expenses/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteReport:  (id)            => apiFetch(`${API_BASE}/expenses/${id}`, { method: "DELETE" }),
  addSub:        (rid, body)     => apiFetch(`${API_BASE}/expenses/${rid}/sub_expenses`, { method: "POST", body: JSON.stringify(body) }),
  deleteSub:     (rid, sid)      => apiFetch(`${API_BASE}/expenses/${rid}/sub_expenses/${sid}`, { method: "DELETE" }),
};

// ── Categories ────────────────────────────────────────────────────────────────

async function loadCategories() {
  try {
    CATEGORIES = await api.getCategories();
    populateModalCategorySelect();
  } catch { /* will use empty list — selects will be empty */ }
}

function populateModalCategorySelect() {
  subCategory.innerHTML = `<option value="">— Select a category —</option>` + buildCategoryOptions("");
}

// ── Data refresh ──────────────────────────────────────────────────────────────

async function fetchExpenses() {
  loadingEl.classList.remove("hidden");
  reportsList.innerHTML = "";
  emptyState.classList.add("hidden");
  try {
    const reports = await api.getExpenses();
    renderReports(reports);
  } catch {
    emptyState.textContent = "Could not load expenses. Is the server running?";
    emptyState.classList.remove("hidden");
  } finally {
    loadingEl.classList.add("hidden");
  }
}

async function fetchSummary() {
  try {
    const { total, count } = await api.getSummary();
    totalAmountEl.textContent = formatCurrency(total);
    totalCountEl.textContent  = count;
  } catch {}
}

// ── Render ────────────────────────────────────────────────────────────────────

function renderReports(reports) {
  reportsList.innerHTML = "";
  if (reports.length === 0) {
    emptyState.textContent = "No expense reports yet. Create one above!";
    emptyState.classList.remove("hidden");
    return;
  }
  emptyState.classList.add("hidden");
  reports.forEach((r) => reportsList.appendChild(buildCard(r)));
}

function buildCard(report) {
  const isOpen = expandedReports.has(report.id);
  const isEditing = editingReports.has(report.id);
  const card = document.createElement("div");
  card.className = "report-card";
  card.dataset.reportId = report.id;
  card.innerHTML =
    (isEditing ? buildEditHeader(report) : buildViewHeader(report, isOpen)) +
    `<div class="sub-expenses-panel ${isOpen || isEditing ? "open" : ""}">
       ${isEditing ? buildEditSubPanel(report) : buildViewSubPanel(report)}
     </div>`;
  wireCard(card, report);
  return card;
}

function buildViewHeader(report, isOpen) {
  return `
    <div class="report-header" role="button" tabindex="0" aria-expanded="${isOpen}">
      <span class="report-toggle ${isOpen ? "open" : ""}">▶</span>
      <div class="report-meta">
        <div class="report-description">${escapeHtml(report.description)}</div>
        <div class="report-date">${formatDate(report.date)}</div>
      </div>
      <span class="report-total">${formatCurrency(report.total)}</span>
      <div class="report-actions">
        <button class="btn-add-sub" title="Add sub-expense">+ Add</button>
        <button class="btn-edit-report" title="Edit report">Edit</button>
        <button class="btn-delete-report" title="Delete report">Delete</button>
      </div>
    </div>`;
}

function buildEditHeader(report) {
  return `
    <div class="report-header report-header--editing">
      <div class="edit-header-fields">
        <div class="edit-field-group">
          <label class="edit-label" for="edit-desc-${report.id}">Description</label>
          <input class="edit-input" id="edit-desc-${report.id}" type="text" value="${escapeHtml(report.description)}" maxlength="200" />
          <span class="edit-field-error" id="edit-desc-error-${report.id}"></span>
        </div>
        <div class="edit-field-group edit-field-group--date">
          <label class="edit-label" for="edit-date-${report.id}">Date</label>
          <input class="edit-input" id="edit-date-${report.id}" type="date" value="${report.date}" />
          <span class="edit-field-error" id="edit-date-error-${report.id}"></span>
        </div>
      </div>
      <div class="report-actions">
        <button class="btn-save-report" title="Save all changes">Save</button>
        <button class="btn-cancel-edit" title="Cancel editing">Cancel</button>
      </div>
    </div>`;
}

function buildViewSubPanel(report) {
  const subs = report.sub_expenses || [];
  const tableHtml = subs.length === 0
    ? `<div class="sub-expenses-empty">No sub-expenses yet — click "+ Add" to add one.</div>`
    : `<table class="sub-expenses-table"><thead><tr><th>Category</th><th>Note</th><th>Amount</th><th>Action</th></tr></thead><tbody>
        ${subs.map((s) => `<tr data-sub-id="${s.id}"><td><span class="category-badge">${escapeHtml(categoryLabel(s.category))}</span></td><td>${escapeHtml(s.note || "—")}</td><td class="amount-cell">${formatCurrency(s.amount)}</td><td><button class="btn-delete-sub" data-sub-id="${s.id}" aria-label="Delete">Delete</button></td></tr>`).join("")}
      </tbody><tfoot><tr class="sub-total-row"><td colspan="2">Report Total</td><td colspan="2">${formatCurrency(report.total)}</td></tr></tfoot></table>`;
  return tableHtml + `<div class="timestamp-footer"><span>Created: ${formatTimestamp(report.created_date)}</span><span>Modified: ${formatTimestamp(report.modified_date)}</span></div>`;
}

function buildEditSubPanel(report) {
  const subs = report.sub_expenses || [];
  const tableHtml = subs.length === 0
    ? `<div class="sub-expenses-empty">No sub-expenses yet — save this report then click "+ Add".</div>`
    : `<table class="sub-expenses-table"><thead><tr><th>Category</th><th>Note</th><th>Amount</th><th>Action</th></tr></thead><tbody>
        ${subs.map((s) => `<tr data-sub-id="${s.id}" class="sub-edit-row"><td><select class="sub-edit-category edit-input-sm" data-sub-id="${s.id}">${buildCategoryOptions(s.category)}</select></td><td><input class="sub-edit-note edit-input-sm" type="text" data-sub-id="${s.id}" value="${escapeHtml(s.note || "")}" placeholder="Note" maxlength="200" /></td><td><input class="sub-edit-amount edit-input-sm" type="number" data-sub-id="${s.id}" value="${s.amount}" min="0.01" step="0.01" placeholder="0.00" /><span class="sub-edit-amount-error" id="sub-edit-amount-error-${s.id}"></span></td><td><button class="btn-delete-sub" data-sub-id="${s.id}" title="Delete row">Delete</button></td></tr>`).join("")}
      </tbody><tfoot><tr class="sub-total-row"><td colspan="2">Report Total</td><td colspan="2">${formatCurrency(report.total)}</td></tr></tfoot></table>`;
  return tableHtml + `<div class="timestamp-footer"><span>Created: ${formatTimestamp(report.created_date)}</span><span>Modified: ${formatTimestamp(report.modified_date)}</span></div>`;
}

// ── Wire events ───────────────────────────────────────────────────────────────

function wireCard(card, report) {
  editingReports.has(report.id) ? wireEditCard(card, report) : wireViewCard(card, report);
}

function wireViewCard(card, report) {
  const header = card.querySelector(".report-header");
  const toggle = card.querySelector(".report-toggle");
  const panel  = card.querySelector(".sub-expenses-panel");
  function togglePanel(e) {
    if (e.target.closest("button")) return;
    const open = panel.classList.toggle("open");
    toggle.classList.toggle("open", open);
    header.setAttribute("aria-expanded", open);
    open ? expandedReports.add(report.id) : expandedReports.delete(report.id);
  }
  header.addEventListener("click", togglePanel);
  header.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); togglePanel(e); } });
  card.querySelector(".btn-add-sub").addEventListener("click", () => openModal(report));
  card.querySelector(".btn-edit-report").addEventListener("click", () => { editingReports.add(report.id); expandedReports.add(report.id); replaceCard(card, report); });
  card.querySelector(".btn-delete-report").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    if (!confirm(`Delete "${report.description}" and all its sub-expenses?`)) return;
    btn.disabled = true; btn.textContent = "Deleting…";
    try { await api.deleteReport(report.id); expandedReports.delete(report.id); editingReports.delete(report.id); await Promise.all([fetchExpenses(), fetchSummary()]); }
    catch (err) { alert(`Error: ${err.message}`); btn.disabled = false; btn.textContent = "Delete"; }
  });
  card.querySelectorAll(".btn-delete-sub").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const subId = Number(btn.dataset.subId); btn.disabled = true; btn.textContent = "…";
      try { const updated = await api.deleteSub(report.id, subId); replaceCard(card, updated); await fetchSummary(); }
      catch (err) { alert(`Error: ${err.message}`); btn.disabled = false; btn.textContent = "Delete"; }
    });
  });
}

function wireEditCard(card, report) {
  card.querySelector(".btn-save-report").addEventListener("click", async () => {
    const saveBtn = card.querySelector(".btn-save-report");
    const descEl = card.querySelector(`#edit-desc-${report.id}`), dateEl = card.querySelector(`#edit-date-${report.id}`);
    const descErr = card.querySelector(`#edit-desc-error-${report.id}`), dateErr = card.querySelector(`#edit-date-error-${report.id}`);
    descErr.textContent = ""; dateErr.textContent = ""; descEl.classList.remove("invalid"); dateEl.classList.remove("invalid");
    card.querySelectorAll(".sub-edit-amount-error").forEach((el) => el.textContent = "");
    card.querySelectorAll(".sub-edit-amount").forEach((el) => el.classList.remove("invalid"));
    const description = descEl.value.trim(), date = dateEl.value.trim();
    let hasError = false;
    if (!description) { descErr.textContent = "Description is required"; descEl.classList.add("invalid"); hasError = true; }
    if (!date) { dateErr.textContent = "Date is required"; dateEl.classList.add("invalid"); hasError = true; }
    const subUpdates = [];
    card.querySelectorAll(".sub-edit-row").forEach((row) => {
      const subId = Number(row.dataset.subId), amtEl = row.querySelector(".sub-edit-amount"), amtErr = row.querySelector(".sub-edit-amount-error");
      const amount = amtEl.value.trim();
      if (!amount || isNaN(Number(amount)) || Number(amount) <= 0) { amtErr.textContent = "Enter a valid amount > $0"; amtEl.classList.add("invalid"); hasError = true; }
      else { subUpdates.push({ id: subId, category: row.querySelector(".sub-edit-category").value, note: row.querySelector(".sub-edit-note").value.trim(), amount: parseFloat(amount) }); }
    });
    if (hasError) return;
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";
    try { const updated = await api.updateReport(report.id, { description, date, sub_expenses: subUpdates }); editingReports.delete(report.id); replaceCard(card, updated); await fetchSummary(); }
    catch (err) { alert(`Error: ${err.message}`); saveBtn.disabled = false; saveBtn.textContent = "Save"; }
  });
  card.querySelector(".btn-cancel-edit").addEventListener("click", () => { editingReports.delete(report.id); replaceCard(card, report); });
  card.querySelectorAll(".btn-delete-sub").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const subId = Number(btn.dataset.subId); btn.disabled = true; btn.textContent = "…";
      try { const updated = await api.deleteSub(report.id, subId); replaceCard(card, updated); await fetchSummary(); }
      catch (err) { alert(`Error: ${err.message}`); btn.disabled = false; btn.textContent = "Delete"; }
    });
  });
}

function replaceCard(oldCard, report) { oldCard.replaceWith(buildCard(report)); }

// ── Modal ─────────────────────────────────────────────────────────────────────

function openModal(report) {
  modalReportId.value = report.id;
  modalTitle.textContent = `Add Sub-Expense — ${report.description}`;
  subCategory.value = ""; subNote.value = ""; subAmount.value = "";
  clearSubFormErrors();
  modalOverlay.classList.remove("hidden");
  subCategory.focus();
}
function closeModal() { modalOverlay.classList.add("hidden"); }
modalCloseBtn.addEventListener("click", closeModal);
modalCancelBtn.addEventListener("click", closeModal);
modalOverlay.addEventListener("click", (e) => { if (e.target === modalOverlay) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

subForm.addEventListener("submit", async (e) => {
  e.preventDefault(); clearSubFormErrors();
  const reportId = Number(modalReportId.value), category = subCategory.value, note = subNote.value.trim(), amount = subAmount.value.trim();
  let hasError = false;
  if (!category) { showFieldError("sub-category", "Please select a category"); hasError = true; }
  if (!amount || isNaN(Number(amount)) || Number(amount) <= 0) { showFieldError("sub-amount", "Enter a valid amount greater than $0"); hasError = true; }
  if (hasError) return;
  subSubmitBtn.disabled = true; subSubmitBtn.textContent = "Adding…";
  try {
    const updated = await api.addSub(reportId, { category, note, amount: parseFloat(amount) });
    closeModal();
    const existingCard = document.querySelector(`[data-report-id="${reportId}"]`);
    if (existingCard) replaceCard(existingCard, updated);
    await fetchSummary();
  } catch (err) { subFormError.textContent = err.message; subFormError.classList.remove("hidden"); }
  finally { subSubmitBtn.disabled = false; subSubmitBtn.textContent = "Add"; }
});

// ── New report form ───────────────────────────────────────────────────────────

reportForm.addEventListener("submit", async (e) => {
  e.preventDefault(); clearReportFormErrors();
  const description = descInput.value.trim(), date = dateInput.value.trim();
  let hasError = false;
  if (!description) { showFieldError("description", "Description is required"); hasError = true; }
  if (!date) { showFieldError("date", "Date is required"); hasError = true; }
  if (hasError) return;
  reportSubmitBtn.disabled = true; reportSubmitBtn.textContent = "Creating…";
  try {
    const newReport = await api.createReport({ description, date });
    reportForm.reset(); dateInput.value = new Date().toISOString().split("T")[0];
    expandedReports.add(newReport.id);
    reportsList.prepend(buildCard(newReport));
    emptyState.classList.add("hidden");
    await fetchSummary();
  } catch (err) { reportFormError.textContent = err.message; reportFormError.classList.remove("hidden"); }
  finally { reportSubmitBtn.disabled = false; reportSubmitBtn.textContent = "Create Report"; }
});

// ── Init ──────────────────────────────────────────────────────────────────────

(async () => {
  await loadCategories();
  fetchExpenses();
  fetchSummary();
})();
