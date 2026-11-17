// Automatisierungen im Designer: Zustand der Skripte und Live-Protokoll laufend aktualisieren.
(function () {
  "use strict";

  var gettext = window.gettext || function (text) { return text; };
  var overview = document.getElementById("automation-scripts");
  var live = document.getElementById("live-run");
  var url = (overview && overview.dataset.statusUrl) || (live && live.dataset.liveUrl);
  if (!url) return;

  var hint = document.getElementById("worker-hint");
  var dirty = false;
  var form = document.getElementById("script-form");
  if (form) form.addEventListener("input", function () { dirty = true; });

  function formatTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return d.toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function setState(badge, state, label) {
    if (!badge) return;
    badge.className = badge.className.replace(/\bstate-[\w-]+/g, "").trim() + " state-" + state;
    badge.textContent = label;
  }

  function updateButtons(container, data) {
    if (!container) return;
    var start = container.querySelector('[data-action="start"]');
    var stop = container.querySelector('[data-action="stop"]');
    if (start) start.hidden = !data.can_start;
    if (stop) stop.hidden = !data.can_stop;
  }

  function waitingTooLong(data) {
    return data.requested_at && Date.now() - new Date(data.requested_at).getTime() > 20000;
  }

  function updateRow(data) {
    var row = overview.querySelector('[data-script="' + data.id + '"]');
    if (!row) return;
    setState(row.querySelector('[data-field="state"]'), data.state, data.label);
    var since = row.querySelector('[data-field="since"]');
    if (since) since.hidden = !data.running_since;
    var next = row.querySelector('[data-field="next"]');
    if (next && data.next_run_at) next.textContent = formatTime(data.next_run_at);
    var last = row.querySelector('[data-field="last"]');
    if (last && data.last) {
      last.innerHTML = "";
      var badge = document.createElement("span");
      badge.className = "badge state state-run-" + data.last.status;
      badge.textContent = data.last.label;
      var when = document.createElement("span");
      when.className = "muted block";
      when.textContent = formatTime(data.last.started);
      last.appendChild(badge);
      last.appendChild(when);
    }
    updateButtons(row, data);
  }

  var wasRunning = null;

  function updateLive(data) {
    setState(document.getElementById("script-state"), data.state, data.label);
    updateButtons(document.querySelector(".head-row [data-script]"), data);
    var run = data.last;
    if (!run) return;
    var status = document.getElementById("live-status");
    setState(status, "run-" + run.status, run.label);
    var meta = document.getElementById("live-meta");
    meta.textContent = formatTime(run.started) + " · " + run.trigger +
      (run.status === "running" ? " · " + gettext("läuft …") : "");
    var error = document.getElementById("live-error");
    error.hidden = !run.error;
    error.querySelector("span").textContent = run.error || "";
    var log = document.getElementById("live-log");
    var atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    if (log.textContent !== run.log) {
      log.textContent = run.log;
      if (atEnd) log.scrollTop = log.scrollHeight;
    }
    var running = data.state === "running";
    // Lauf ist gerade zu Ende: Seite neu laden, damit die Liste der Läufe stimmt (nicht bei offenen Änderungen).
    if (wasRunning && !running && !dirty) window.location.reload();
    wasRunning = running;
  }

  function poll() {
    fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        var busy = false;
        if (data) {
          var items = data.scripts || [data];
          var slow = false;
          items.forEach(function (item) {
            if (overview) updateRow(item); else updateLive(item);
            busy = busy || item.state === "running" || item.state === "requested";
            slow = slow || waitingTooLong(item);
          });
          if (hint) hint.hidden = !slow;
        }
        window.setTimeout(poll, busy ? 2000 : 10000);
      })
      .catch(function () { window.setTimeout(poll, 15000); });
  }
  poll();
})();
