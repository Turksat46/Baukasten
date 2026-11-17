/* Hell/Dunkel. Wird im <head> geladen, damit die Seite nicht erst hell aufblitzt.
   Die Wahl liegt im Browser unter "theme" ("auto", "light" oder "dark") – derselbe
   Schlüssel, den die Django-Verwaltung unter /admin/ benutzt. So gilt eine Wahl überall. */
(function () {
  "use strict";
  var KEY = "theme";
  var MODES = ["auto", "light", "dark"];
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function stored() {
    try { var m = localStorage.getItem(KEY); return MODES.indexOf(m) >= 0 ? m : "auto"; }
    catch (e) { return "auto"; }
  }
  function isDark(mode) { return mode === "dark" || (mode === "auto" && !!media && media.matches); }

  function apply(mode) {
    root.dataset.theme = mode;
    root.dataset.dark = isDark(mode) ? "1" : "0";
    document.querySelectorAll("[data-theme-choice]").forEach(function (b) {
      var on = b.getAttribute("data-theme-choice") === mode;
      b.classList.toggle("current", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      var label = b.getAttribute("data-label-" + mode) || "";
      b.title = label; b.setAttribute("aria-label", label);
    });
  }
  function set(mode) {
    try { localStorage.setItem(KEY, mode); } catch (e) { /* privater Modus */ }
    apply(mode);
  }

  apply(stored());
  if (media && media.addEventListener) media.addEventListener("change", function () { apply(stored()); });
  // Andere Tabs und eingebettete Seiten (Swagger) ziehen mit.
  window.addEventListener("storage", function (e) { if (e.key === KEY) apply(stored()); });

  document.addEventListener("click", function (e) {
    var toggle = e.target.closest && e.target.closest("[data-theme-toggle]");
    if (toggle) {
      // Reihenfolge wie in /admin/: Automatisch → Hell → Dunkel → Automatisch
      set(MODES[(MODES.indexOf(stored()) + 1) % MODES.length]);
      return;
    }
    var choice = e.target.closest && e.target.closest("[data-theme-choice]");
    if (choice) set(choice.getAttribute("data-theme-choice"));
  });
  document.addEventListener("DOMContentLoaded", function () { apply(stored()); });
  window.BaukastenTheme = { set: set, get: stored };
})();
