const API_BASE = "http://localhost:5000/api";

let CATEGORIES = [];

// ── DOM refs ──────────────────────────────────────────────────────────────────
const queryForm        = document.getElementById("query-form");
const runBtn           = document.getElementById("run-query-btn");
const clearBtn         = document.getElementById("clear-btn");
const categoryGroup    = document.getElementById("category-group");
const qCategory        = document.getElementById("q-category");
const qDateFrom        = document.getElementById("q-date-from");
const qDateTo          = document.getElementById("q-date-to");
const queryFormError   = document.getElementById("query-form-error");
const queryLoading     = document.getElementById("query-loading");
const queryEmpty       = document.getElementById("query-empty");
const resultsMeta      = document.getElementById("results-meta");
const resultsCount     = document.getElementById("results-count");
const resultsTotal     = document.getElementById("results-total");
const subResultsWrap   = document.getElementById("sub-results-wrap");
const subResultsBody   = document.getElementById("sub-results-body");
const subResultsTotal  = document.getElementById("sub-results-total");
const breakdownChips   = document.getElementById("breakdown-chips");
const reportResultsWrap     = document.getElementById("report-results-wrap");
const reportResultsList     = document.getElementById("report-results-list");
const reportGrandTotalRow   = document.getElementById("report-grand-total-row");
const reportGrandTotalValue = document.getElementById("report-grand-total-value");

let activeType = "sub_expenses";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatCurrency(v) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v);
}

function formatDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
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

function setError(id, msg) { const el = document.getElementById(id); if (el) el.textContent = msg; }
function clearErrors() { setError("q-date-from-error", ""); setError("q-date-to-error", ""); queryFormError.textContent = ""; queryFormError.classList.add("hidden"); }

// ── Categories ────────────────────────────────────────────────────────────────

async function loadCategories() {
  try {
    const res = await fetch(`${API_BASE}/categories`);
    CATEGORIES = await res.json();
    qCategory.innerHTML = `<option value="">All categories</option>` +
      CATEGORIES.map((c) => `<option value="${c.slug}">${c.icon} ${escapeHtml(c.display_label)}</option>`).join("");
  } catch {}
}

// ── Type toggle ───────────────────────────────────────────────────────────────

document.querySelectorAll(".toggle-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".toggle-btn").forEach((b) => b.classList.remove("toggle-btn--active"));
    btn.classList.add("toggle-btn--active");
    activeType = btn.dataset.type;
    categoryGroup.classList.toggle("hidden", activeType === "reports");
  });
});

// ── Clear ─────────────────────────────────────────────────────────────────────

clearBtn.addEventListener("click", () => {
  qCategory.value = ""; qDateFrom.value = ""; qDateTo.value = "";
  clearErrors(); hideResults();
  queryEmpty.textContent = "Set filters above and click \"Run Query\" to see results.";
  queryEmpty.classList.remove("hidden");
});

function hideResults() {
  subResultsWrap.classList.add("hidden"); reportResultsWrap.classList.add("hidden");
  resultsMeta.classList.add("hidden"); reportGrandTotalRow.classList.add("hidden");
}

// ── Query ─────────────────────────────────────────────────────────────────────

queryForm.addEventListener("submit", async (e) => {
  e.preventDefault(); clearErrors();
  const dateFrom = qDateFrom.value.trim(), dateTo = qDateTo.value.trim();
  if (dateFrom && dateTo && dateFrom > dateTo) { setError("q-date-to-error", "\"To\" date must be on or after \"From\" date"); return; }

  const params = new URLSearchParams({ type: activeType });
  if (activeType === "sub_expenses" && qCategory.value) params.set("category", qCategory.value);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo)   params.set("date_to",   dateTo);

  runBtn.disabled = true; runBtn.textContent = "Running…";
  queryLoading.classList.remove("hidden"); queryEmpty.classList.add("hidden"); hideResults();

  try {
    const res = await fetch(`${API_BASE}/query?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Query failed");
    data.type === "sub_expenses" ? renderSubResults(data) : renderReportResults(data);
  } catch (err) {
    queryFormError.textContent = err.message; queryFormError.classList.remove("hidden");
    queryEmpty.textContent = "Query failed. Is the server running?"; queryEmpty.classList.remove("hidden");
  } finally { runBtn.disabled = false; runBtn.textContent = "Run Query"; queryLoading.classList.add("hidden"); }
});

// ── Render ────────────────────────────────────────────────────────────────────

function renderSubResults(data) {
  const rows = data.results || [];
  if (rows.length === 0) { queryEmpty.textContent = "No sub-expenses match the selected filters."; queryEmpty.classList.remove("hidden"); return; }
  resultsCount.textContent = `${rows.length} line item${rows.length !== 1 ? "s" : ""}`;
  resultsTotal.textContent = formatCurrency(data.grand_total);
  resultsMeta.classList.remove("hidden");
  breakdownChips.innerHTML = Object.entries(data.breakdown || {}).sort((a, b) => b[1] - a[1])
    .map(([cat, amt]) => `<div class="chip"><span class="chip-label">${escapeHtml(categoryLabel(cat))}</span><span class="chip-amount">${formatCurrency(amt)}</span></div>`).join("");
  subResultsBody.innerHTML = rows.map((r) => `<tr><td>${formatDate(r.report_date)}</td><td class="col-report">${escapeHtml(r.report_description)}</td><td><span class="category-badge">${escapeHtml(categoryLabel(r.category))}</span></td><td>${escapeHtml(r.note || "—")}</td><td class="amount-cell col-amount">${formatCurrency(r.amount)}</td></tr>`).join("");
  subResultsTotal.textContent = formatCurrency(data.grand_total);
  subResultsWrap.classList.remove("hidden");
}

function renderReportResults(data) {
  const reports = data.results || [];
  if (reports.length === 0) { queryEmpty.textContent = "No expense reports match the selected filters."; queryEmpty.classList.remove("hidden"); return; }
  resultsCount.textContent = `${reports.length} report${reports.length !== 1 ? "s" : ""}`;
  resultsTotal.textContent = formatCurrency(data.grand_total);
  resultsMeta.classList.remove("hidden");
  reportResultsList.innerHTML = reports.map((report) => {
    const subs = report.sub_expenses || [];
    const subRows = subs.length === 0 ? "" : subs.map((s) => `<tr><td><span class="category-badge">${escapeHtml(categoryLabel(s.category))}</span></td><td>${escapeHtml(s.note || "—")}</td><td class="amount-cell">${formatCurrency(s.amount)}</td></tr>`).join("");
    return `<div class="result-report-card"><div class="result-report-header"><div><div class="result-report-desc">${escapeHtml(report.description)}</div><div class="result-report-date">${formatDate(report.date)}</div></div><div class="result-report-total">${formatCurrency(report.total)}</div></div>${subs.length > 0 ? `<table class="sub-expenses-table result-sub-table"><thead><tr><th>Category</th><th>Note</th><th>Amount</th></tr></thead><tbody>${subRows}</tbody></table>` : `<div class="sub-expenses-empty">No sub-expenses</div>`}</div>`;
  }).join("");
  reportGrandTotalValue.textContent = formatCurrency(data.grand_total);
  reportGrandTotalRow.classList.remove("hidden"); reportResultsWrap.classList.remove("hidden");
}

// ── Init ──────────────────────────────────────────────────────────────────────

loadCategories();
