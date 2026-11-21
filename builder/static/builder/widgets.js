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

  // Schieberegler: Wert beim Ziehen zeigen, beim Loslassen speichern
  document.addEventListener("input", function (e) {
    var slider = e.target.closest && e.target.closest("[data-slide]");
    if (!slider) return;
    var out = slider.parentElement.querySelector("[data-value]");
    if (out) { out.textContent = slider.value; out.parentElement.classList.remove("muted"); }
    slider.setAttribute("aria-valuetext", slider.value);
  });

  document.addEventListener("change", function (e) {
    var slider = e.target.closest && e.target.closest("[data-slide]");
    var root = slider && slider.closest("[data-widget='sliders']");
    if (!root) return;
    var label = (slider.parentElement.querySelector(".slider-label") || slider).textContent.trim();
    blocks.act(root, {op: "set", record: slider.dataset.slide, value: slider.value}, {
      done: label + ": " + slider.value + " " + gettext("gespeichert.")
    });
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
