// Hinweis „neu“ im Fuß: leuchtet, bis die Person die neueste Release Note auf /ueber/ gesehen hat.
// Gemerkt wird das im Browser (localStorage); ohne Speicher bleibt der Hinweis einfach aus.
(function () {
  "use strict";
  var key = "baukasten-neuigkeiten-gesehen";
  function seen() { try { return window.localStorage.getItem(key) || ""; } catch (e) { return null; } }

  var page = document.getElementById("neuigkeiten");
  if (page && page.dataset.latest) {
    try { window.localStorage.setItem(key, page.dataset.latest); } catch (e) { /* egal */ }
  }
  var link = document.querySelector("[data-news]");
  if (!link) return;
  var latest = link.dataset.news, last = seen();
  if (latest && last !== null && last !== latest && !page) link.classList.add("has-news");
})();
