// Führung für neue Nutzer.
// Eine Seite liefert ihre Schritte als JSON in <script id="tour-steps" data-tour-id="…">.
// Beim ersten Besuch startet die Führung von selbst, danach über das Fragezeichen oben rechts.
(function () {
  "use strict";

  var source = document.getElementById("tour-steps");
  var startButton = document.getElementById("tour-start");
  if (!source) return;

  var allSteps = JSON.parse(source.textContent);
  var tourId = (document.getElementById("tour-id") || source).dataset.tourId;
  var storageKey = "baukasten-tour-" + tourId + "-" + (document.body.dataset.user || "");
  var gettext = window.gettext || function (text) { return text; };
  var interpolate = window.interpolate || function (text) { return text; };
  var blocker, hole, popup, steps, index, lastFocus;

  function alreadySeen() {
    // Ohne Zugriff auf den Speicher lieber nicht bei jedem Besuch erneut starten.
    try { return window.localStorage.getItem(storageKey) === "1"; } catch (e) { return true; }
  }
  function markSeen() {
    try { window.localStorage.setItem(storageKey, "1"); } catch (e) { /* dann eben beim nächsten Mal wieder */ }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function targetOf(step) {
    if (!step.target) return null;
    var node = document.querySelector(step.target);
    if (node && node.getClientRects().length) return node;
    // Auf dem Handy steckt das Ziel im eingeklappten Menü: dann auf den Menü-Knopf zeigen.
    var toggle = document.querySelector(".menu-toggle");
    if (node && toggle && node.closest("#topbar-menu") && toggle.getClientRects().length) return toggle;
    return null;
  }

  function place() {
    var step = steps[index];
    var target = targetOf(step);
    var pad = 6;
    if (target) {
      var rect = target.getBoundingClientRect();
      hole.style.cssText = "top:" + (rect.top - pad) + "px;left:" + (rect.left - pad) + "px;width:" +
        (rect.width + 2 * pad) + "px;height:" + (rect.height + 2 * pad) + "px";
      var width = popup.offsetWidth, height = popup.offsetHeight;
      var top, left;
      if (rect.height > window.innerHeight * 0.6) {
        // Hohes Ziel (z. B. eine Seitenleiste): Hinweis daneben statt darüber oder darunter.
        top = Math.max(rect.top, 76);
        left = rect.right + pad + 12;
        if (left + width > window.innerWidth - 8) left = rect.left - pad - 12 - width;
        if (left < 8) { left = rect.left + 16; top = Math.max(76, window.innerHeight - height - 16); }
      } else {
        top = rect.bottom + pad + 12;
        if (top + height > window.innerHeight - 8) top = rect.top - pad - 12 - height;
        if (top < 8) top = Math.max(8, window.innerHeight - height - 8);
        left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
      }
      popup.style.top = top + "px";
      popup.style.left = Math.max(8, left) + "px";
    } else {
      hole.style.cssText = "top:50%;left:50%;width:0;height:0";
      popup.style.top = Math.max(8, (window.innerHeight - popup.offsetHeight) / 2) + "px";
      popup.style.left = Math.max(8, (window.innerWidth - popup.offsetWidth) / 2) + "px";
    }
  }

  function show(newIndex) {
    index = newIndex;
    var step = steps[index];
    var last = index === steps.length - 1;
    popup.replaceChildren();
    popup.appendChild(el("p", "tour-count",
      interpolate(gettext("Schritt %s von %s"), [index + 1, steps.length])));
    var title = el("h2", "tour-title", step.title);
    title.id = "tour-title";
    popup.appendChild(title);
    popup.appendChild(el("p", "tour-text", step.text));

    var actions = el("div", "tour-actions");
    var skip = el("button", "link", last ? "" : gettext("Führung beenden"));
    skip.type = "button";
    skip.addEventListener("click", end);
    if (!last) actions.appendChild(skip);
    var spacer = el("span", "tour-spacer");
    actions.appendChild(spacer);
    if (index > 0) {
      var back = el("button", "btn btn-secondary", gettext("Zurück"));
      back.type = "button";
      back.addEventListener("click", function () { show(index - 1); });
      actions.appendChild(back);
    }
    var next = el("button", "btn", last ? gettext("Fertig") : gettext("Weiter"));
    next.type = "button";
    next.addEventListener("click", function () { if (last) end(); else show(index + 1); });
    actions.appendChild(next);
    popup.appendChild(actions);

    var target = targetOf(step);
    if (target) target.scrollIntoView({ block: "center", inline: "nearest" });
    window.requestAnimationFrame(function () {
      place();
      next.focus({ preventScroll: true });
    });
  }

  function onKey(event) {
    if (event.key === "Escape") end();
    else if (event.key === "ArrowRight" && index < steps.length - 1) show(index + 1);
    else if (event.key === "ArrowLeft" && index > 0) show(index - 1);
    else if (event.key === "Tab") {
      // Fokus bleibt in der Führung.
      var buttons = popup.querySelectorAll("button");
      var first = buttons[0], lastButton = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); lastButton.focus(); }
      else if (!event.shiftKey && document.activeElement === lastButton) { event.preventDefault(); first.focus(); }
    }
  }

  function start() {
    if (popup) return;
    steps = allSteps.filter(function (step) { return !step.target || targetOf(step); });
    if (!steps.length) return;
    lastFocus = document.activeElement;
    blocker = el("div", "tour-blocker");
    hole = el("div", "tour-hole");
    popup = el("div", "tour-popup");
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-modal", "true");
    popup.setAttribute("aria-labelledby", "tour-title");
    document.body.appendChild(blocker);
    document.body.appendChild(hole);
    document.body.appendChild(popup);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    show(0);
  }

  function end() {
    if (!popup) return;
    markSeen();
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", place);
    window.removeEventListener("scroll", place, true);
    [blocker, hole, popup].forEach(function (node) { node.remove(); });
    blocker = hole = popup = null;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  if (startButton) {
    startButton.hidden = false;
    startButton.addEventListener("click", start);
  }
  // Läuft die Einführung „Deine erste App“, startet die Führung nicht von selbst dazwischen.
  if (!alreadySeen() && !document.getElementById("coach")) window.setTimeout(start, 500);
})();
