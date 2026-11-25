// Checkliste und Schieberegler: speichern sofort über den Endpunkt des Bausteins.
// Senden, Rückfragen und Neuladen kommen aus planning.js (BaukastenBlocks).
(function () {
  "use strict";

  var gettext = window.gettext || function (text) { return text; };
  var blocks = window.BaukastenBlocks;
  if (!blocks) return;

  // Checkliste: Häkchen setzen oder entfernen
  document.addEventListener("change", function (e) {
    var box = e.target.closest && e.target.closest("[data-check]");
    var root = box && box.closest("[data-widget='checklist']");
    if (!root) return;
    var label = (box.closest("label").querySelector(".checklist-label") || box).textContent.trim();
    blocks.act(root, {op: "toggle", record: box.dataset.check, value: box.checked}, {
      done: label + " " + (box.checked ? gettext("erledigt.") : gettext("wieder offen."))
    });
  });

  // Schieberegler: Wert beim Ziehen zeigen und kurz nach dem letzten Bewegen speichern,
  // damit abhängige Bausteine (Skript-Ausgaben, Diagramme) schon während des Ziehens
  // mitlaufen. Beim Loslassen wird endgültig gespeichert und der Regler neu geladen.
  var LIVE_DELAY = 250;
  var pending = {};   // Regler-ID -> Timer
  var running = {};   // Regler-ID -> läuft gerade eine Anfrage
  var queued = {};    // Regler-ID -> Wert, der nach der laufenden Anfrage noch gesendet wird

  function sliderRoot(slider) { return slider.closest("[data-widget='sliders']"); }

  // Andere Bausteine derselben Seite neu laden, die vom gespeicherten Wert abhängen können.
  // Ausgelassen werden Bausteine mit Eingaben (Formulare, Filter, andere Regler), damit
  // nichts verloren geht, was jemand gerade tippt.
  function refreshDependents(own, base) {
    if (!own || !base) return Promise.resolve();
    var grid = own.parentElement;
    var jobs = [];
    Array.prototype.forEach.call(grid.querySelectorAll(":scope > [data-block]"), function (el) {
      if (el === own || el.dataset.loadingNow) return;
      if (el.querySelector("form, input, select, textarea, [data-action-url]")) return;
      var url = base.replace("/b/" + own.dataset.block + "/", "/b/" + encodeURIComponent(el.dataset.block) + "/");
      el.dataset.loadingNow = "1";
      jobs.push(fetch(url + window.location.search, {credentials: "same-origin"})
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) {
          if (html !== null) el.innerHTML = html;  // vom Server erzeugt und maskiert
          document.dispatchEvent(new CustomEvent("baukasten:block-updated", {detail: {block: el}}));
        })
        .catch(function () { /* beim nächsten Wert wieder */ })
        .then(function () { delete el.dataset.loadingNow; }));
    });
    return Promise.all(jobs);
  }

  // Während des Ziehens: speichern ohne den Regler selbst neu zu zeichnen (sonst reißt das Ziehen ab).
  function saveLive(slider) {
    var root = sliderRoot(slider);
    var id = slider.dataset.slide;
    if (!root) return;
    if (running[id]) { queued[id] = slider.value; return; }
    running[id] = true;
    fetch(root.dataset.actionUrl, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": root.dataset.csrf || ""},
      body: JSON.stringify({op: "set", record: id, value: slider.value})
    }).then(function (r) { return r.ok ? refreshDependents(root.closest("[data-block]"), root.dataset.reloadUrl) : null; })
      .catch(function () { /* Fehler zeigt das endgültige Speichern beim Loslassen */ })
      .then(function () {
        running[id] = false;
        if (queued[id] !== undefined && document.body.contains(slider)) {
          delete queued[id];
          saveLive(slider);
        }
      });
  }

  document.addEventListener("input", function (e) {
    var slider = e.target.closest && e.target.closest("[data-slide]");
    if (!slider) return;
    var out = slider.parentElement.querySelector("[data-value]");
    if (out) { out.textContent = slider.value; out.parentElement.classList.remove("muted"); }
    slider.setAttribute("aria-valuetext", slider.value);
    if (!sliderRoot(slider)) return;
    var id = slider.dataset.slide;
    clearTimeout(pending[id]);
    pending[id] = setTimeout(function () { saveLive(slider); }, LIVE_DELAY);
  });

  document.addEventListener("change", function (e) {
    var slider = e.target.closest && e.target.closest("[data-slide]");
    var root = slider && sliderRoot(slider);
    if (!root) return;
    clearTimeout(pending[slider.dataset.slide]);
    delete queued[slider.dataset.slide];
    // Vor dem Speichern merken: Danach ersetzt das Neuladen den Regler samt root.
    var own = root.closest("[data-block]"), base = root.dataset.reloadUrl;
    var label = (slider.parentElement.querySelector(".slider-label") || slider).textContent.trim();
    blocks.act(root, {op: "set", record: slider.dataset.slide, value: slider.value}, {
      done: label + ": " + slider.value + " " + gettext("gespeichert.")
    }).then(function () { return refreshDependents(own, base); });
  });

  // Status-Leiste: Schritt direkt per Klick speichern
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-step]");
    var root = btn && btn.closest("[data-widget='stepper']");
    if (!root) return;
    blocks.act(root, {op: "step", record: root.dataset.record, value: btn.dataset.step}, {
      done: gettext("Status gespeichert.")
    });
  });

  // Bidirektionale Tableau-Anbindung (Embedding API v3):
  // Klick auf einen Datenpunkt im Dashboard setzt die zugeordneten URL-Parameter auf der Seite.
  document.querySelectorAll("tableau-viz[data-selection-map]").forEach(function (viz) {
    var map = {};
    try { map = JSON.parse(viz.dataset.selectionMap || "{}"); } catch (err) { return; }
    viz.addEventListener("markselectionchanged", function (e) {
      if (!e.detail || typeof e.detail.getMarksAsync !== "function") return;
      e.detail.getMarksAsync().then(function (marks) {
        var rows = (marks && marks.data && marks.data[0] && marks.data[0].data) || [];
        var cols = (marks && marks.data && marks.data[0] && marks.data[0].columns) || [];
        if (!rows.length || !cols.length) return;
        var first = rows[0];
        var url = new URL(window.location.href);
        var changed = false;
        cols.forEach(function (col, idx) {
          var param = map[col.fieldName];
          if (param && first[idx]) {
            url.searchParams.set(param, String(first[idx].formattedValue || first[idx].value || ""));
            changed = true;
          }
        });
        if (changed) window.location.assign(url.toString());
      }).catch(function () {});
    });
  });
})();
