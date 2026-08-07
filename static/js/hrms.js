// ---------------------------------------------------------------------------
// HRMS Enterprise UI — theme, toasts, DataTables, Select2, AJAX modals
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
  initTheme();
  initSidebar();
  initAjaxModals();
  initDataTables();
  initSelect2();
  initToasts();
  initLiveClock();
  initConfirmDeletes();
  initMarkAllRead();
  initNotificationClicks();
  initIdleSessionWatch();
});

// Theme toggle
function initTheme() {
  const saved = localStorage.getItem("hrms-theme") || "light";
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeIcon(saved);

  const btn = document.getElementById("themeToggle");
  if (btn) {
    btn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme");
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("hrms-theme", next);
      updateThemeIcon(next);
    });
  }
}

function updateThemeIcon(theme) {
  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  btn.innerHTML = theme === "dark"
    ? '<i class="bi bi-sun-fill"></i>'
    : '<i class="bi bi-moon-stars-fill"></i>';
}

// Sidebar toggle (mobile)
function initSidebar() {
  const toggle = document.getElementById("sidebarToggle");
  const sidebar = document.getElementById("appSidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", () => sidebar.classList.toggle("show"));
  }
}

// DataTables auto-init
function initDataTables() {
  if (typeof $ !== "undefined" && $.fn.DataTable) {
    document.querySelectorAll("table.datatable").forEach((table) => {
      if ($.fn.DataTable.isDataTable(table)) return;

      // Skip tables with colspan empty-state rows (causes DataTables tn/18).
      const headerCols = table.querySelectorAll("thead tr:first-child th, thead tr:first-child td").length;
      let badRow = false;
      table.querySelectorAll("tbody tr").forEach((row) => {
        let cols = 0;
        row.querySelectorAll("th, td").forEach((cell) => {
          cols += parseInt(cell.getAttribute("colspan") || "1", 10);
        });
        if (headerCols && cols !== headerCols) badRow = true;
      });
      if (badRow) return;

      $(table).DataTable({
        pageLength: 15,
        responsive: true,
        dom: '<"row"<"col-sm-6"l><"col-sm-6"f>>rtip',
        language: {
          search: "",
          searchPlaceholder: "Filter…",
          emptyTable: "No records to show.",
          zeroRecords: "No matching records.",
        },
      });
    });
  }
}

// Select2 auto-init
function initSelect2() {
  if (typeof $ !== "undefined" && $.fn.select2) {
    $("select.select2").select2({ width: "100%", theme: "default" });
  }
}

// Django messages → Bootstrap toasts
function initToasts() {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  document.querySelectorAll(".alert").forEach((alert) => {
    const tag = alert.className.match(/alert-(\w+)/);
    const type = tag ? tag[1] : "info";
    if (type === "danger") showToast(alert.textContent.trim(), "error");
    else showToast(alert.textContent.trim(), type === "success" ? "success" : "info");
    alert.remove();
  });
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const id = "toast-" + Date.now();
  const bg = type === "success" ? "bg-success" : type === "error" ? "bg-danger" : "bg-dark";
  container.insertAdjacentHTML("beforeend", `
    <div id="${id}" class="toast align-items-center text-white ${bg} border-0" role="alert">
      <div class="d-flex"><div class="toast-body">${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>
    </div>`);
  const toast = new bootstrap.Toast(document.getElementById(id), { delay: 4000 });
  toast.show();
}

// Live clock
function initLiveClock() {
  const el = document.getElementById("liveClock");
  if (!el) return;
  function tick() {
    const now = new Date();
    el.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  tick();
  setInterval(tick, 30000);
}

// SweetAlert2 confirm for delete forms
function initConfirmDeletes() {
  document.querySelectorAll("[data-confirm]").forEach((el) => {
    el.addEventListener("click", function (e) {
      e.preventDefault();
      const msg = this.dataset.confirm || "Are you sure?";
      const href = this.href || this.dataset.href;
      if (typeof Swal !== "undefined") {
        Swal.fire({
          title: "Confirm",
          text: msg,
          icon: "warning",
          showCancelButton: true,
          confirmButtonColor: "#f5a524",
          cancelButtonColor: "#64748b",
          confirmButtonText: "Yes, proceed",
        }).then((result) => {
          if (result.isConfirmed) {
            if (this.tagName === "A") window.location.href = href;
            else if (this.form) this.form.submit();
          }
        });
      } else if (confirm(msg)) {
        if (this.tagName === "A") window.location.href = href;
      }
    });
  });
}

function updateNotifBadge(count) {
  const badge = document.getElementById("notifBadge");
  if (!badge) return;
  const n = Math.max(0, Number(count) || 0);
  badge.dataset.count = String(n);
  if (n > 0) {
    badge.textContent = n > 99 ? "99+" : String(n);
    badge.classList.remove("d-none");
  } else {
    badge.textContent = "";
    badge.classList.add("d-none");
  }
}

function getCsrfToken() {
  const input = document.querySelector("[name=csrfmiddlewaretoken]");
  if (input) return input.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

function initMarkAllRead() {
  const form = document.getElementById("markAllReadForm");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    fetch(form.action, {
      method: "POST",
      headers: {
        "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
      },
    })
      .then((r) => r.json())
      .then((data) => {
        updateNotifBadge(data.unread_count ?? 0);
        document.querySelectorAll(".notif-item.unread").forEach((el) => {
          el.classList.remove("unread");
          el.dataset.notifRead = "1";
        });
        if (typeof showToast === "function") showToast("All notifications marked as read.", "success");
      })
      .catch(() => window.location.reload());
  });
}

function initNotificationClicks() {
  document.querySelectorAll("a.notif-item[data-notif-id]").forEach((el) => {
    el.addEventListener("click", function () {
      if (el.dataset.notifRead === "1") return;
      // Optimistic UI: drop unread styling and decrement badge before navigation
      el.classList.remove("unread");
      el.dataset.notifRead = "1";
      const badge = document.getElementById("notifBadge");
      const current = Number(badge?.dataset.count || 0);
      if (current > 0) updateNotifBadge(current - 1);
    });
  });
}

// AJAX modal forms
function openAjaxModal(url, title) {
  const modalEl = document.getElementById("ajaxModal");
  const contentEl = document.getElementById("ajaxModalContent");
  contentEl.innerHTML = `<div class="modal-header"><h5 class="modal-title font-display">${title || ""}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body text-center py-5"><div class="spinner-border"></div></div>`;
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  modal.show();

  fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
    .then((r) => r.json())
    .then((data) => {
      contentEl.innerHTML = `<div class="modal-header"><h5 class="modal-title font-display">${title || ""}</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body">${data.html}</div>`;
      bindAjaxModalForm(url);
      initSelect2();
    })
    .catch(() => {
      contentEl.innerHTML = `<div class="modal-body p-4 text-danger">Couldn't load this form.</div>`;
    });
}

function bindAjaxModalForm(fallbackUrl) {
  const form = document.querySelector("#ajaxModalContent form");
  if (!form) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const submitBtn = form.querySelector('[type="submit"]');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…'; }
    const formData = new FormData(form);
    fetch(form.action || fallbackUrl, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: formData,
    })
      .then(async (r) => {
        const ct = r.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          const data = await r.json();
          if (data.html) {
            document.querySelector("#ajaxModalContent .modal-body").innerHTML = data.html;
            bindAjaxModalForm(fallbackUrl);
            if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = "Save"; }
            return;
          }
        }
        const modal = bootstrap.Modal.getInstance(document.getElementById("ajaxModal"));
        if (modal) modal.hide();
        showToast("Saved successfully.", "success");
        setTimeout(() => window.location.reload(), 600);
      })
      .catch(() => {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = "Save"; }
        showToast("Something went wrong.", "error");
      });
  });
}

function initAjaxModals() {
  document.addEventListener("click", function (e) {
    const trigger = e.target.closest("[data-modal-url]");
    if (trigger) {
      e.preventDefault();
      openAjaxModal(trigger.dataset.modalUrl, trigger.dataset.modalTitle);
    }
  });
}

// Chart.js defaults
if (typeof Chart !== "undefined") {
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.color = "#5b6781";
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
}

// Keyboard shortcuts
document.addEventListener("keydown", function (e) {
  if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
    e.preventDefault();
    const search = document.getElementById("globalSearchInput");
    if (search) search.focus();
  }
});

// ---------------------------------------------------------------------------
// Idle session watch — log out after inactivity (default 120s)
// ---------------------------------------------------------------------------
function initIdleSessionWatch() {
  const cfg = window.HRMS_IDLE;
  if (!cfg || !cfg.logoutUrl) return;

  const timeoutMs = Math.max(15, Number(cfg.timeoutSeconds) || 120) * 1000;
  const warnMs = Math.min(Math.max(5, Number(cfg.warnSeconds) || 20) * 1000, timeoutMs - 1000);
  const banner = document.getElementById("idleSessionBanner");
  const countdownEl = document.getElementById("idleSessionCountdown");

  let lastActivity = Date.now();
  let logoutTimer = null;
  let tickTimer = null;
  let warningShown = false;
  let loggingOut = false;

  function hideWarning() {
    warningShown = false;
    if (banner) banner.classList.add("d-none");
    if (tickTimer) {
      clearInterval(tickTimer);
      tickTimer = null;
    }
  }

  function showWarning() {
    if (warningShown || !banner) return;
    warningShown = true;
    banner.classList.remove("d-none");
    tickTimer = setInterval(function () {
      const remaining = Math.max(0, Math.ceil((timeoutMs - (Date.now() - lastActivity)) / 1000));
      if (countdownEl) countdownEl.textContent = remaining + "s";
      if (remaining <= 0) clearInterval(tickTimer);
    }, 250);
  }

  function forceLogout() {
    if (loggingOut) return;
    loggingOut = true;
    window.location.href = cfg.logoutUrl;
  }

  function scheduleLogout() {
    if (logoutTimer) clearTimeout(logoutTimer);
    logoutTimer = setTimeout(forceLogout, timeoutMs);
  }

  function onActivity() {
    if (loggingOut) return;
    lastActivity = Date.now();
    hideWarning();
    scheduleLogout();
  }

  const activityEvents = [
    "mousemove", "mousedown", "keydown", "scroll", "touchstart", "click", "wheel",
  ];
  activityEvents.forEach(function (evt) {
    document.addEventListener(evt, onActivity, { passive: true, capture: true });
  });
  window.addEventListener("focus", onActivity);

  // Poll for warning threshold (avoids resetting timers on every mousemove for warn UI)
  setInterval(function () {
    if (loggingOut) return;
    const idleFor = Date.now() - lastActivity;
    if (idleFor >= timeoutMs) {
      forceLogout();
    } else if (idleFor >= timeoutMs - warnMs) {
      showWarning();
    }
  }, 1000);

  scheduleLogout();
}
