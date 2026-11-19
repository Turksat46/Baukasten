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
})();
