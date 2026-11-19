// Drag-and-drop für Bausteine, wiederverwendbar und ohne Bibliothek.
//
// Ziehbare Elemente tragen data-drag="<art>", Ablageflächen data-drop="<art>". Beides liegt in
// einem Wurzelelement; was wohin darf und was dann passiert, sagt ein registrierter Handler:
//
//   BaukastenDnD.register("[data-plan]", {
//     accepts: function (item, zone, root) { return true; },   // darf item auf zone?
//     drop:    function (item, zone, root) { … }               // ausführen
//   });
//
// Funktioniert mit der Maus (HTML5 Drag-and-drop) und ohne Maus: Element antippen oder mit
// Enter/Leertaste auswählen, dann in einer Ablagefläche den Button [data-place] drücken.
// Escape bricht ab. Die Listener hängen am Dokument; neu geladenes HTML braucht kein Einrichten.
(function () {
  "use strict";

  var handlers = [];
  var dragged = null;   // {item, root, handler} während Maus-Ziehen
  var picked = null;    // dasselbe im Auswahl-Modus (Tippen/Tastatur)

  function find(el) {
    for (var i = 0; i < handlers.length; i++) {
      var root = el && el.closest(handlers[i].selector);
      if (root) return {root: root, handler: handlers[i]};
    }
    return null;
  }

  function zoneOf(target, root) {
    var zone = target.closest("[data-drop]");
    return zone && root.contains(zone) ? zone : null;
  }

  function clearOver(root) {
    root.querySelectorAll(".is-drop-over").forEach(function (z) { z.classList.remove("is-drop-over"); });
  }

  function markTargets(state, on) {
    state.root.classList.toggle("is-dragging", on);
    state.root.querySelectorAll("[data-drop]").forEach(function (zone) {
      var ok = on && state.handler.accepts(state.item, zone, state.root);
      zone.classList.toggle("is-drop-target", !!ok);
    });
  }

  // ---------- Maus ----------

  document.addEventListener("dragstart", function (e) {
    var item = e.target.closest && e.target.closest("[data-drag]");
    var found = item && find(item);
    if (!found) return;
    unpick();
    dragged = {item: item, root: found.root, handler: found.handler};
    item.classList.add("is-drag-source");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", item.textContent.trim()); } catch (err) { /* IE */ }
    // Erst im nächsten Bild markieren, sonst übernimmt das Drag-Bild die Markierung.
    window.requestAnimationFrame(function () { if (dragged) markTargets(dragged, true); });
  });

  document.addEventListener("dragover", function (e) {
    if (!dragged) return;
    var zone = zoneOf(e.target, dragged.root);
    if (!zone || !dragged.handler.accepts(dragged.item, zone, dragged.root)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (!zone.classList.contains("is-drop-over")) {
      clearOver(dragged.root);
      zone.classList.add("is-drop-over");
    }
  });

  document.addEventListener("dragleave", function (e) {
    if (!dragged) return;
    var zone = zoneOf(e.target, dragged.root);
    if (zone && !zone.contains(e.relatedTarget)) zone.classList.remove("is-drop-over");
  });

  document.addEventListener("drop", function (e) {
    if (!dragged) return;
    var zone = zoneOf(e.target, dragged.root);
    if (!zone || !dragged.handler.accepts(dragged.item, zone, dragged.root)) return;
    e.preventDefault();
    var state = dragged;
    end();
    state.handler.drop(state.item, zone, state.root);
  });

  document.addEventListener("dragend", end);

  function end() {
    if (!dragged) return;
    dragged.item.classList.remove("is-drag-source");
    markTargets(dragged, false);
    clearOver(dragged.root);
    dragged = null;
  }

  // ---------- Ohne Maus: auswählen und ablegen ----------

  function pick(item, found) {
    unpick();
    picked = {item: item, root: found.root, handler: found.handler};
    item.classList.add("is-picked");
    item.setAttribute("aria-pressed", "true");
    markTargets(picked, true);
    picked.root.querySelectorAll("[data-drop]").forEach(function (zone) {
      var button = zone.querySelector("[data-place]");
      if (button) button.hidden = !zone.classList.contains("is-drop-target");
    });
    var status = picked.root.querySelector("[data-plan-status]");
    if (status) status.textContent = (window.gettext || String)("Ausgewählt. Jetzt ein Ziel wählen oder Escape zum Abbrechen.");
  }

  function unpick() {
    if (!picked) return;
    picked.item.classList.remove("is-picked");
    picked.item.setAttribute("aria-pressed", "false");
    markTargets(picked, false);
    picked.root.querySelectorAll("[data-place]").forEach(function (b) { b.hidden = true; });
    picked = null;
  }

  document.addEventListener("click", function (e) {
    var place = e.target.closest("[data-place]");
    if (place && picked && picked.root.contains(place)) {
      var zone = place.closest("[data-drop]");
      var state = picked;
      unpick();
      if (zone && state.handler.accepts(state.item, zone, state.root)) state.handler.drop(state.item, zone, state.root);
      return;
    }
    if (e.target.closest("a, button, input, select, textarea")) return;
    var item = e.target.closest("[data-drag]");
    var found = item && find(item);
    if (!found) return;
    if (picked && picked.item === item) unpick(); else pick(item, found);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && picked) { unpick(); return; }
    if (e.key !== "Enter" && e.key !== " ") return;
    var item = e.target.closest && e.target.closest("[data-drag]");
    if (!item || e.target !== item) return;
    var found = find(item);
    if (!found) return;
    e.preventDefault();
    if (picked && picked.item === item) unpick(); else pick(item, found);
  });

  window.BaukastenDnD = {
    register: function (selector, handler) { handlers.push({selector: selector, accepts: handler.accepts, drop: handler.drop}); },
    cancel: function () { unpick(); end(); }
  };
})();
