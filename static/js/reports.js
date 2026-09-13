(function () {
  "use strict";
  var workspace = document.querySelector("[data-report-workspace]");
  document.querySelectorAll("[data-report-thumbnail]").forEach(function (image) {
    image.addEventListener("error", function () { image.hidden = true; });
    if (image.complete && !image.naturalWidth) image.hidden = true;
  });
  document.querySelectorAll("[data-report-open]").forEach(function (button) {
    button.addEventListener("click", function () {
      var dialog = document.getElementById(button.dataset.reportOpen);
      if (dialog && typeof dialog.showModal === "function") dialog.showModal();
    });
  });
  document.querySelectorAll("[data-report-close]").forEach(function (button) {
    button.addEventListener("click", function () { button.closest("dialog").close(); });
  });
  document.querySelectorAll(".report-dialog").forEach(function (dialog) {
    dialog.addEventListener("click", function (event) {
      if (event.target !== dialog) return;
      var bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });
  });
  var shareForm = document.querySelector("[data-report-share-form]");
  if (shareForm) shareForm.addEventListener("submit", function (event) {
    var first = shareForm.querySelector('input[name="columns"]');
    if (!shareForm.querySelector('input[name="columns"]:checked')) {
      event.preventDefault();
      if (first) { first.setCustomValidity(workspace.dataset.selectColumns); first.reportValidity(); }
    } else if (first) first.setCustomValidity("");
  });
  if (shareForm) shareForm.addEventListener("change", function () {
    var first = shareForm.querySelector('input[name="columns"]');
    if (first) first.setCustomValidity("");
  });
  document.querySelectorAll("[data-report-submit]").forEach(function (form) {
    form.addEventListener("submit", function () { form.setAttribute("aria-busy", "true"); });
  });
  document.addEventListener("click", function (event) {
    document.querySelectorAll(".report-export-menu[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") document.querySelectorAll(".report-export-menu[open]").forEach(function (menu) { menu.open = false; });
  });
  document.querySelectorAll("[data-report-summary-tabs]").forEach(function (widget) {
    var tabs = Array.prototype.slice.call(widget.querySelectorAll("[data-report-summary-tab]"));
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (candidate) {
          var selected = candidate === tab;
          var panel = widget.querySelector("#summary-panel-" + candidate.dataset.reportSummaryTab);
          candidate.setAttribute("aria-selected", selected ? "true" : "false");
          candidate.classList.toggle("report-summary-tab-active", selected);
          if (panel) panel.hidden = !selected;
        });
      });
      tab.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        var offset = event.key === "ArrowRight" ? 1 : -1;
        if (document.documentElement.dir === "rtl") offset *= -1;
        var next = tabs[(tabs.indexOf(tab) + offset + tabs.length) % tabs.length];
        next.focus();
        next.click();
      });
    });
  });
  var filterForm = document.querySelector("[data-report-filter]");
  var dateFrom = filterForm && filterForm.elements.namedItem("date_from");
  var dateTo = filterForm && filterForm.elements.namedItem("date_to");
  function localISO(date) {
    return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
  }
  if (dateFrom && dateTo) {
    document.querySelector("[data-report-presets]").hidden = false;
    document.querySelectorAll("[data-report-period]").forEach(function (button) {
      button.addEventListener("click", function () {
        var today = new Date(), start = new Date(today);
        var period = button.dataset.reportPeriod;
        if (period === "month") start.setDate(1);
        if (period === "year") { start.setMonth(0); start.setDate(1); }
        if (period === "30") start.setDate(today.getDate() - 29);
        dateFrom.value = period === "all" ? "" : localISO(start);
        dateTo.value = period === "all" ? "" : localISO(today);
        filterForm.requestSubmit();
      });
    });
  }
  var saved = document.querySelector("[data-report-saved]");
  if (workspace && saved) {
    var storageKey = "amoxruns-report-views:" + workspace.dataset.storageKey;
    var list = saved.querySelector("[data-report-saved-list]");
    var nameField = saved.querySelector("[data-report-view-name]");
    var status = saved.querySelector("[data-report-save-status]");
    function readViews() {
      var views = JSON.parse(localStorage.getItem(storageKey) || "[]");
      return Array.isArray(views) ? views.filter(function (item) {
        if (!item || typeof item.name !== "string" || typeof item.url !== "string") return false;
        var url = new URL(item.url, window.location.origin);
        return url.origin === window.location.origin && url.pathname === window.location.pathname;
      }).slice(0, 10) : [];
    }
    function renderViews() {
      list.replaceChildren();
      readViews().forEach(function (item) {
        var li = document.createElement("li"), link = document.createElement("a");
        link.textContent = item.name;
        link.href = item.url;
        li.appendChild(link);
        list.appendChild(li);
      });
    }
    try { renderViews(); saved.hidden = false; } catch (error) { /* Filters work without browser storage. */ }
    saved.querySelector("[data-report-save]").addEventListener("click", function () {
      if (!nameField.value.trim()) { nameField.focus(); return; }
      try {
        var views = readViews(), url = new URL(window.location.href);
        url.searchParams.delete("page");
        views.unshift({ name: nameField.value.trim().slice(0, 60), url: url.pathname + url.search });
        localStorage.setItem(storageKey, JSON.stringify(views.slice(0, 10)));
        renderViews(); nameField.value = ""; status.textContent = workspace.dataset.savedMessage;
      } catch (error) { status.textContent = workspace.dataset.saveError; }
    });
    saved.querySelector("[data-report-clear-saved]").addEventListener("click", function () {
      try { localStorage.removeItem(storageKey); renderViews(); status.textContent = ""; } catch (error) { status.textContent = workspace.dataset.saveError; }
    });
  }
  document.querySelectorAll("[data-report-copy]").forEach(function (button) {
    button.addEventListener("click", async function () {
      var input = document.getElementById(button.dataset.reportCopy);
      if (!input) return;
      input.select();
      try {
        await navigator.clipboard.writeText(input.value);
        var notice = document.querySelector("[data-report-copy-status]");
        if (notice) notice.textContent = button.dataset.copied;
      } catch (error) { /* Selected text remains available for manual copying. */ }
    });
  });
  var refresh = document.querySelector("[data-report-poll]");
  if (refresh) {
    var attempts = 0;
    var poll = window.setInterval(async function () {
      if (document.hidden || attempts >= 30) return;
      attempts += 1;
      try {
        var response = await fetch(refresh.dataset.reportPoll, { headers: { "Accept": "application/json" }, credentials: "same-origin", cache: "no-store" });
        if (!response.ok) return;
        var result = await response.json();
        if (["ready", "failed", "expired"].indexOf(result.status) !== -1) { clearInterval(poll); window.location.reload(); }
      } catch (error) { /* A manual refresh link remains available. */ }
      if (attempts >= 30) clearInterval(poll);
    }, 5000);
  }
})();
