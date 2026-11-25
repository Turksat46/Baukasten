/* Startbildschirm der installierten App (PWA). Wird im <head> geladen, damit er vor dem ersten
   Bild der Seite steht. Nur, wenn der Baukasten als App läuft (display-mode: standalone oder
   iOS-Startbildschirm), und nur einmal je Start (sessionStorage). Zum Ansehen im Browser:
   eine Adresse mit ?splash=1 aufrufen. Das Markup steht in builder/_splash.html. */
(function () {
  "use strict";
  var root = document.documentElement;
  var forced = /[?&]splash=1(&|$)/.test(window.location.search);
  var media = function (q) { return !!(window.matchMedia && window.matchMedia(q).matches); };
  try {
    var installed = media("(display-mode: standalone)") || window.navigator.standalone === true;
    if (!forced && (!installed || window.sessionStorage.getItem("bk-splash"))) return;
    window.sessionStorage.setItem("bk-splash", "1");
  } catch (e) {
    if (!forced) return;  // kein sessionStorage: lieber gar nicht als bei jedem Seitenwechsel
  }

  var MIN = media("(prefers-reduced-motion: reduce)") ? 300 : 900;  // ms: Animation darf auslaufen
  var MAX = 2500;  // ms: spätestens dann weg, auch wenn die Seite noch lädt
  var started = Date.now(), hidden = false;
  root.classList.add("bk-splash-on");

  function hide() {
    if (hidden) return;
    hidden = true;
    window.setTimeout(function () {
      root.classList.add("bk-splash-out");
      window.setTimeout(function () { root.classList.remove("bk-splash-on", "bk-splash-out"); }, 450);
    }, Math.max(0, MIN - (Date.now() - started)));
  }

  if (document.readyState === "complete") hide();
  else window.addEventListener("load", hide, { once: true });
  window.setTimeout(hide, MAX);
})();
