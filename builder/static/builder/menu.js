/* Menü der Kopfzeile auf schmalen Bildschirmen: auf- und zuklappen, Esc schließt,
   ein Klick daneben schließt. Auf breiten Bildschirmen ist der Knopf ausgeblendet. */
(function () {
  "use strict";
  var header = document.querySelector(".topbar");
  var toggle = header && header.querySelector(".menu-toggle");
  if (!toggle) return;
  var menu = document.getElementById(toggle.getAttribute("aria-controls"));

  function set(open) {
    header.classList.toggle("menu-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
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
