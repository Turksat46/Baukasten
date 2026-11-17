// Begleiter der Einführung „Deine erste App“ (unten rechts).
// Blockiert die Seite nicht: Man arbeitet ganz normal weiter, der Begleiter zeigt nur,
// wo es weitergeht. Ob ein Schritt erledigt ist, entscheidet der Server.
(function () {
  "use strict";

  var coach = document.getElementById("coach");
  if (!coach) return;
  var toggle = coach.querySelector(".coach-toggle");
  var storageKey = "baukasten-coach-zu";

  function setCollapsed(collapsed) {
    coach.classList.toggle("collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    try { window.localStorage.setItem(storageKey, collapsed ? "1" : "0"); } catch (e) { /* egal */ }
  }
  try { setCollapsed(window.localStorage.getItem(storageKey) === "1"); } catch (e) { setCollapsed(false); }
  toggle.addEventListener("click", function () { setCollapsed(!coach.classList.contains("collapsed")); });

  // „Zeig mir wo“: Ziel in den Blick holen und kurz aufleuchten lassen.
  function highlight() {
    var selector = coach.dataset.target;
    var target = selector && document.querySelector(selector);
    if (!target || !target.getClientRects().length) return false;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("coach-glow");
    void target.offsetWidth; // Animation neu starten
    target.classList.add("coach-glow");
    window.setTimeout(function () { target.classList.remove("coach-glow"); }, 4200);
    var focusable = target.matches("input, select, textarea, button, a") ? target
      : target.querySelector("input:not([type=hidden]), select, textarea");
    if (focusable) window.setTimeout(function () { focusable.focus({ preventScroll: true }); }, 400);
    // Verdeckt der Begleiter die gezeigte Stelle, klappt er sich ein (nach dem Scrollen prüfen).
    window.setTimeout(function () {
      var a = target.getBoundingClientRect(), b = coach.getBoundingClientRect();
      var overlaps = a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
      if (overlaps) setCollapsed(true);
    }, 700);
    return true;
  }
  var show = coach.querySelector("[data-coach-show]");
  if (show) {
    show.addEventListener("click", highlight);
    // Direkt nach dem Wechsel auf die richtige Seite einmal von selbst zeigen.
    if (!coach.classList.contains("collapsed")) window.setTimeout(highlight, 600);
  }

  var copy = coach.querySelector("[data-coach-copy]");
  if (copy) {
    copy.addEventListener("click", function () {
      var code = document.getElementById("coach-code").textContent;
      var done = function () {
        var old = copy.textContent;
        copy.textContent = (window.gettext || String)("Kopiert ✓");
        window.setTimeout(function () { copy.textContent = old; }, 1800);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(code).then(done, function () {});
      else {
        var area = document.createElement("textarea");
        area.value = code; document.body.appendChild(area); area.select();
        try { document.execCommand("copy"); done(); } catch (e) { /* dann eben markieren und selbst kopieren */ }
        area.remove();
      }
    });
  }
})();
