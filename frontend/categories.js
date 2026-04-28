const API_BASE = "http://localhost:5000/api";

// ── DOM refs ──────────────────────────────────────────────────────────────────
const addForm      = document.getElementById("add-category-form");
const slugInput    = document.getElementById("new-slug");
const labelInput   = document.getElementById("new-label");
const iconInput    = document.getElementById("new-icon");
const addBtn       = document.getElementById("add-btn");
const addFormError = document.getElementById("add-form-error");
const catLoading   = document.getElementById("cat-loading");
const catEmpty     = document.getElementById("cat-empty");
const catList      = document.getElementById("cat-list");

// ── Helpers ───────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}

function showFieldError(id, msg) {
  const el = document.getElementById(`${id}-error`);
  const input = document.getElementById(id);
  if (el) el.textContent = msg;
  if (input) input.classList.toggle("invalid", !!msg);
}

function clearAddFormErrors() {
  showFieldError("new-slug", "");
  showFieldError("new-label", "");
  addFormError.textContent = "";
  addFormError.classList.add("hidden");
}

// ── API ───────────────────────────────────────────────────────────────────────

async function apiFetch(url, options = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

// ── Load & Render ─────────────────────────────────────────────────────────────

async function loadCategories() {
  catLoading.classList.remove("hidden");
  catList.innerHTML = "";
  catEmpty.classList.add("hidden");

  try {
    const categories = await apiFetch(`${API_BASE}/categories`);
    renderCategories(categories);
  } catch {
    catEmpty.textContent = "Could not load categories. Is the server running?";
    catEmpty.classList.remove("hidden");
  } finally {
    catLoading.classList.add("hidden");
  }
}

function renderCategories(categories) {
  if (categories.length === 0) {
    catEmpty.textContent = "No categories yet. Add one above!";
    catEmpty.classList.remove("hidden");
    return;
  }

  catEmpty.classList.add("hidden");
  catList.innerHTML = categories.map((c) => `
    <div class="cat-row" data-slug="${c.slug}">
      <div class="cat-slug">${escapeHtml(c.slug)}</div>
      <div class="cat-icon-field">
        <input class="cat-edit-icon" type="text" value="${escapeHtml(c.icon || "")}" maxlength="10" placeholder="emoji" />
      </div>
      <div class="cat-label-field">
        <input class="cat-edit-label" type="text" value="${escapeHtml(c.display_label)}" maxlength="100" />
        <span class="cat-edit-error"></span>
      </div>
      <div class="cat-actions">
        <button class="btn-save-cat" title="Save changes">Save</button>
      </div>
    </div>
  `).join("");

  // Wire save buttons
  catList.querySelectorAll(".cat-row").forEach((row) => {
    const slug     = row.dataset.slug;
    const labelEl  = row.querySelector(".cat-edit-label");
    const iconEl   = row.querySelector(".cat-edit-icon");
    const errEl    = row.querySelector(".cat-edit-error");
    const saveBtn  = row.querySelector(".btn-save-cat");

    saveBtn.addEventListener("click", async () => {
      errEl.textContent = "";
      labelEl.classList.remove("invalid");

      const display_label = labelEl.value.trim();
      const icon = iconEl.value.trim();

      if (!display_label) {
        errEl.textContent = "Label is required";
        labelEl.classList.add("invalid");
        return;
      }

      saveBtn.disabled = true;
      saveBtn.textContent = "Saving…";

      try {
        await apiFetch(`${API_BASE}/categories/${slug}`, {
          method: "PUT",
          body: JSON.stringify({ display_label, icon }),
        });
        saveBtn.textContent = "Saved ✓";
        setTimeout(() => { saveBtn.textContent = "Save"; saveBtn.disabled = false; }, 1200);
      } catch (err) {
        errEl.textContent = err.message;
        saveBtn.disabled = false;
        saveBtn.textContent = "Save";
      }
    });
  });
}

// ── Add Category ──────────────────────────────────────────────────────────────

addForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearAddFormErrors();

  const slug          = slugInput.value.trim().toLowerCase();
  const display_label = labelInput.value.trim();
  const icon          = iconInput.value.trim();

  let hasError = false;

  if (!slug) {
    showFieldError("new-slug", "Slug is required");
    hasError = true;
  } else if (!/^[a-z][a-z0-9_]*$/.test(slug)) {
    showFieldError("new-slug", "Must start with a letter; only lowercase letters, numbers, underscores");
    hasError = true;
  }

  if (!display_label) {
    showFieldError("new-label", "Display label is required");
    hasError = true;
  }

  if (hasError) return;

  addBtn.disabled = true;
  addBtn.textContent = "Adding…";

  try {
    await apiFetch(`${API_BASE}/categories`, {
      method: "POST",
      body: JSON.stringify({ slug, display_label, icon }),
    });
    addForm.reset();
    await loadCategories();
  } catch (err) {
    addFormError.textContent = err.message;
    addFormError.classList.remove("hidden");
  } finally {
    addBtn.disabled = false;
    addBtn.textContent = "Add Category";
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────

loadCategories();
