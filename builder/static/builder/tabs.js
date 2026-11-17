// Reiter ohne Neuladen: [data-tabs] mit Links [data-tab] und Bereichen [data-panel].
// Ohne JavaScript funktionieren die Links trotzdem (?neu=…), dann wählt der Server den Reiter.
(function () {
  "use strict";
  document.querySelectorAll("[data-tabs]").forEach(function (box) {
    var tabs = box.querySelectorAll("[data-tab]");
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function (e) {
        e.preventDefault();
        tabs.forEach(function (t) {
          var on = t === tab;
          t.classList.toggle("current", on);
          t.setAttribute("aria-selected", String(on));
        });
        box.querySelectorAll("[data-panel]").forEach(function (panel) {
          panel.hidden = panel.dataset.panel !== tab.dataset.tab;
        });
        var first = box.querySelector('[data-panel="' + tab.dataset.tab + '"] input:not([type=hidden])');
        if (first) first.focus({ preventScroll: true });
        try { window.history.replaceState(null, "", "?neu=" + tab.dataset.tab); } catch (err) { /* egal */ }
      });
    });
  });
})();
