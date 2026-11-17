// Laufzeit einer App-Seite: JavaScript-Skripte in der Sandbox ausführen, Bausteine füllen,
// Bausteine automatisch aktualisieren. Konfiguration kommt aus <script id="bk-runtime">.
(function () {
  "use strict";

  var gettext = window.gettext || function (text) { return text; };
  var interpolate = window.interpolate || function (text) { return text; };
  var configEl = document.getElementById("bk-runtime");
  var cfg = configEl ? JSON.parse(configEl.textContent) : null;
  var uiState = {};      // zuletzt gesetzte Werte je Baustein-Name (für aktualisierte Bausteine)
  var frame = null, frameReady = null, runCounter = 0;
  var runs = new Map();  // runId -> {script, handlers}
  var TABLE_OPS = ["table.filter", "table.get", "table.count", "table.aggregate", "table.create", "table.update", "table.delete", "query.run"];

  // ---------- Bausteine füllen (für Python und JavaScript gleich) ----------

  function formatValue(value) {
    if (typeof value === "number") {
      return new Intl.NumberFormat(document.documentElement.lang || undefined, {maximumFractionDigits: 2}).format(value);
    }
    return value === null || value === undefined ? "" : String(value);
  }

  function setSlot(root, key, value, hideEmpty) {
    root.querySelectorAll('[data-slot="' + key + '"]').forEach(function (el) {
      el.textContent = formatValue(value);
      if (hideEmpty) el.hidden = el.textContent === "";
    });
  }

  function buildRows(container, rows) {
    container.replaceChildren();
    if (!Array.isArray(rows) || !rows.length) { container.hidden = true; return; }
    var table = document.createElement("table");
    var columns = rows[0] && typeof rows[0] === "object" && !Array.isArray(rows[0]) ? Object.keys(rows[0]).slice(0, 12) : null;
    if (columns) {
      var head = table.createTHead().insertRow();
      columns.forEach(function (c) { var th = document.createElement("th"); th.textContent = c; head.appendChild(th); });
    }
    var body = table.createTBody();
    rows.slice(0, 500).forEach(function (row) {
      var tr = body.insertRow();
      var cells = columns ? columns.map(function (c) { return row[c]; }) : (Array.isArray(row) ? row : [row]);
      cells.forEach(function (cell) { tr.insertCell().textContent = formatValue(cell); });
    });
    container.appendChild(table);
    container.hidden = false;
  }

  function applyTo(root, values) {
    if ("hidden" in values) root.hidden = !!values.hidden;
    ["text", "label"].forEach(function (key) { if (key in values) setSlot(root, key, values[key], false); });
    ["subtitle", "title", "unit"].forEach(function (key) { if (key in values) setSlot(root, key, values[key], true); });
    if ("value" in values) {
      setSlot(root, "value", values.value, false);
      root.querySelectorAll('[data-slot-wrap="value"]').forEach(function (el) { el.hidden = false; });
    }
    if ("text" in values) root.querySelectorAll('.output [data-slot="text"]').forEach(function (el) { el.hidden = el.textContent === ""; });
    else if ("value" in values || "rows" in values) {
      // Der Platzhaltertext eines Ausgabe-Bausteins gilt nur, solange nichts gesetzt ist.
      root.querySelectorAll('.output [data-slot="text"]').forEach(function (el) { el.hidden = true; });
    }
    if ("rows" in values) root.querySelectorAll('[data-slot="rows"]').forEach(function (el) { buildRows(el, values.rows); });
    if ("tone" in values && ["info", "success", "warning", "danger"].indexOf(values.tone) >= 0) {
      root.querySelectorAll("[data-tone]").forEach(function (el) {
        el.className = el.className.replace(/notice-\w+/g, "").trim() + " notice-" + values.tone;
      });
    }
    if (values.values && typeof values.values === "object") {
      root.querySelectorAll("form[data-form-prefix]").forEach(function (form) {
        var prefix = form.dataset.formPrefix;
        Object.keys(values.values).forEach(function (key) {
          var input = form.elements[prefix + "-" + key];
          if (!input) return;
          if (input.type === "checkbox") input.checked = !!values.values[key];
          else input.value = values.values[key] === null ? "" : values.values[key];
        });
      });
    }
    if (["value", "text", "rows"].some(function (k) { return k in values; })) {
      root.querySelectorAll('[data-slot="placeholder"]').forEach(function (el) { el.hidden = true; });
    }
  }

  function applyUi(name, values) {
    uiState[name] = Object.assign(uiState[name] || {}, values);
    document.querySelectorAll('[data-name="' + CSS.escape(name) + '"]').forEach(function (root) { applyTo(root, values); });
  }

  function toast(text, kind) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var item = document.createElement("div");
    item.className = "toast" + (kind ? " toast-" + kind : "");
    item.textContent = text;
    box.appendChild(item);
    setTimeout(function () { item.remove(); }, 6000);
  }

  // ---------- Sandbox ----------

  function ensureFrame() {
    if (frameReady) return frameReady;
    frameReady = new Promise(function (resolve) {
      frame = document.createElement("iframe");
      frame.setAttribute("sandbox", "allow-scripts");
      frame.setAttribute("aria-hidden", "true");
      frame.tabIndex = -1;
      frame.style.display = "none";
      frame.src = cfg.sandbox;
      window.addEventListener("message", function onReady(e) {
        if (e.source === frame.contentWindow && e.data && e.data.type === "ready") {
          window.removeEventListener("message", onReady);
          resolve();
        }
      });
      document.body.appendChild(frame);
    });
    window.addEventListener("message", onSandboxMessage);
    return frameReady;
  }

  function bridge(op, args) {
    return fetch(cfg.bridge, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": cfg.csrf},
      body: JSON.stringify({op: op, args: args})
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.error) {
          var detail = data.fields ? " " + Object.keys(data.fields).map(function (k) {
            return k + ": " + data.fields[k].map(function (e) { return e.message; }).join(" ");
          }).join("; ") : "";
          throw new Error((data.error || response.statusText) + detail);
        }
        return data.result;
      });
    });
  }

  function onSandboxMessage(e) {
    if (!frame || e.source !== frame.contentWindow) return;
    var m = e.data || {};
    var run = runs.get(m.runId);
    if (!run) return;
    var h = run.handlers;
    if (m.type === "call") {
      if (TABLE_OPS.indexOf(m.op) < 0) {
        frame.contentWindow.postMessage({type: "result", runId: m.runId, id: m.id, error: gettext("Unbekannte Anfrage.")}, "*");
        return;
      }
      bridge(m.op, m.args || {}).then(function (result) {
        frame.contentWindow.postMessage({type: "result", runId: m.runId, id: m.id, result: result}, "*");
      }, function (err) {
        frame.contentWindow.postMessage({type: "result", runId: m.runId, id: m.id, error: err.message}, "*");
      });
    } else if (m.type === "ui") {
      h.ui(String(m.name), m.values || {});
    } else if (m.type === "message") {
      h.message(String(m.text));
    } else if (m.type === "log") {
      h.log(String(m.text));
    } else if (m.type === "done" || m.type === "error") {
      runs.delete(m.runId);
      if (m.type === "error") {
        var text = m.message === "timeout"
          ? interpolate(gettext("Zeitlimit von %s Sekunden überschritten."), [Math.round(cfg.timeout / 1000)])
          : m.message;
        h.done({ok: false, error: m.line ? interpolate(gettext("Zeile %s: %s"), [m.line, text]) : text});
      } else {
        h.done({ok: true});
      }
    }
  }

  function defaultHandlers(script) {
    return {
      ui: applyUi,
      message: function (text) { toast(text); },
      log: function (text) { if (window.console) window.console.info("[" + script.name + "]", text); },
      done: function (result) {
        if (!result.ok) {
          if (window.console) window.console.error("[" + script.name + "]", result.error);
          if (cfg.show_errors) toast(interpolate(gettext("Skript „%s“: %s"), [script.name, result.error]), "error");
        }
      }
    };
  }

  function run(script, extra, handlers) {
    return ensureFrame().then(function () {
      return new Promise(function (resolve) {
        var runId = "r" + (++runCounter);
        var h = handlers || defaultHandlers(script);
        var done = h.done;
        h.done = function (result) { done(result); resolve(result); };
        runs.set(runId, {script: script, handlers: h});
        frame.contentWindow.postMessage({
          type: "run", runId: runId, code: script.code, timeout: cfg.timeout,
          context: {user: cfg.user, event: Object.assign({page: cfg.page}, extra || {}),
                    params: Object.fromEntries(new URLSearchParams(window.location.search))}
        }, "*");
      });
    });
  }

  // ---------- Automatisch aktualisieren ----------

  // Lädt einen Baustein neu. Meldet der Server „noch nicht fertig“ (data-pending),
  // fragt er nach ein paar Sekunden wieder nach; höchstens ein Abruf je Baustein gleichzeitig.
  function refreshBlock(el, force, attempt) {
    if ((document.hidden && !force) || !cfg.block_url || el.dataset.loadingNow) return;
    el.dataset.loadingNow = "1";
    fetch(cfg.block_url.replace("BLOCK", el.dataset.block), {credentials: "same-origin"})
      .then(function (response) { return response.ok ? response.text() : null; })
      .then(function (html) {
        delete el.dataset.loadingNow;
        if (html === null) return;
        el.innerHTML = html;  // vom Server erzeugt und maskiert
        if (el.dataset.name && uiState[el.dataset.name]) applyTo(el, uiState[el.dataset.name]);
        var pending = el.querySelector("[data-pending]");
        var wait = pending ? parseInt(pending.getAttribute("data-pending"), 10) || 0 : 0;
        if (wait && (attempt || 0) < 40) {
          setTimeout(function () { refreshBlock(el, true, (attempt || 0) + 1); }, wait * 1000);
        }
      })
      .catch(function () {
        delete el.dataset.loadingNow;
        if ((attempt || 0) < 5) setTimeout(function () { refreshBlock(el, true, (attempt || 0) + 1); }, 5000);
      });
  }

  // ---------- Start ----------

  window.BaukastenRuntime = {run: run, applyUi: applyUi, configure: function (c) { cfg = c; }};
  if (!cfg) return;

  document.querySelectorAll("[data-lazy]").forEach(function (el) { refreshBlock(el, true); });
  document.querySelectorAll("[data-refresh]").forEach(function (el) {
    var seconds = Math.max(parseInt(el.dataset.refresh, 10) || 0, 10);
    setInterval(function () { refreshBlock(el); }, seconds * 1000);
  });
  (cfg.scripts || []).forEach(function (script) { run(script, {trigger: "page"}); });
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-js-script]");
    if (!button || !cfg.buttons) return;
    var script = cfg.buttons[button.dataset.jsScript];
    if (!script) return;
    button.disabled = true;
    run(script, {trigger: "button"}).then(function () { button.disabled = false; });
  });
})();
