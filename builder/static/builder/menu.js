/* Menü der Kopfzeile auf schmalen Bildschirmen: auf- und zuklappen, Esc schließt,
   ein Klick daneben schließt. Auf breiten Bildschirmen ist der Knopf ausgeblendet. */
(function () {
  "use strict";
  var header = document.querySelector(".topbar");
  var toggle = header && header.querySelector(".menu-toggle");
  if (!toggle) return;
  var menu = document.getElementById(toggle.getAttribute("aria-controls"));

  // Zum Animieren: Das Menü ist zu ganz ausgeblendet. Vor dem Öffnen wird es zugeklappt eingeblendet
  // (menu-active), einen Bildaufbau später aufgeklappt (menu-open). Nach dem Schließen wird es wieder
  // ausgeblendet, sobald die Bewegung vorbei ist.
  var hideTimer = null;
  function set(open) {
    window.clearTimeout(hideTimer);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      header.classList.add("menu-active");
      void menu.offsetHeight; // Ausgangszustand übernehmen, sonst springt der Browser direkt ans Ende
      header.classList.add("menu-open");
    } else {
      header.classList.remove("menu-open");
      hideTimer = window.setTimeout(function () { header.classList.remove("menu-active"); }, 300);
    }
  }
  toggle.addEventListener("click", function () {
    var open = !header.classList.contains("menu-open");
    set(open);
    if (open) {
      var first = menu && menu.querySelector("a, button");
      if (first) first.focus();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && header.classList.contains("menu-open")) { set(false); toggle.focus(); }
  });
  document.addEventListener("click", function (e) {
    if (header.classList.contains("menu-open") && !header.contains(e.target)) set(false);
  });
  // Die aktive Seite in der wischbaren Seitenleiste sichtbar machen.
  var active = header.querySelector(".topnav a.active");
  if (active && active.scrollIntoView) active.scrollIntoView({block: "nearest", inline: "nearest"});
})();
