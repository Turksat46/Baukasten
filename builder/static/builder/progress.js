// Rückmeldung, während etwas lädt: dünner Ladebalken oben, Buttons im Wartezustand,
// Laufzeit-Hinweis bei längeren Skripten.
//
// Automatisch: Seitenwechsel per Link, abgeschickte Formulare (auch Python-Skript-Buttons) und
// Änderungen per fetch (POST/PUT/PATCH/DELETE an den eigenen Server). Lesende Abfragen und das
// regelmäßige Aktualisieren bleiben still, Bausteine zeigen dabei ihr eigenes Skelett.
// Von Hand: BaukastenProgress.start() / .done() und BaukastenProgress.busy(button, true|false).
// Ausnahmen: data-no-progress an Link, Formular oder Button; Downloads (download-Attribut,
// Export-Adressen) zeigen keinen Balken.
(function () {
  "use strict";

  var gettext = window.gettext || function (text) { return text; };
  var SHOW_AFTER = 250;     // ms: schnelle Antworten sollen nicht flackern
  var NOTE_AFTER = 2000;    // ms: ab dann „läuft … 3 s“ neben dem Button
  var GIVE_UP = 60000;      // ms: Seitenwechsel ohne Ende (z. B. unerkannter Download)
  var bar = null, pending = 0, showTimer = null, trickleTimer = null, giveUpTimer = null, value = 0;

  function ensureBar() {
    if (bar) return bar;
    bar = document.createElement("div");
    bar.className = "bk-progress";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-label", gettext("Wird geladen"));
    bar.setAttribute("aria-hidden", "true");
    bar.appendChild(document.createElement("span"));
    document.body.appendChild(bar);
    return bar;
  }

  function paint() {
    if (!bar) return;
    bar.firstChild.style.transform = "scaleX(" + value + ")";
  }

  function show() {
    ensureBar();
    value = Math.max(value, 0.08);
    bar.classList.add("is-active");
    bar.setAttribute("aria-hidden", "false");
    paint();
    window.clearInterval(trickleTimer);
    // Ohne echten Fortschritt: schnell vorwärts, dann immer langsamer, nie ganz voll.
    trickleTimer = window.setInterval(function () {
      value += (0.92 - value) * (value < 0.5 ? 0.12 : 0.04);
      paint();
    }, 250);
  }

  function start() {
    pending += 1;
    if (pending > 1 || showTimer || (bar && bar.classList.contains("is-active"))) return;
    showTimer = window.setTimeout(function () { showTimer = null; if (pending > 0) show(); }, SHOW_AFTER);
  }

  function done(all) {
    pending = all ? 0 : Math.max(0, pending - 1);
    if (pending > 0) return;
    window.clearTimeout(showTimer);
    showTimer = null;
    window.clearInterval(trickleTimer);
    window.clearTimeout(giveUpTimer);
    if (!bar || !bar.classList.contains("is-active")) { value = 0; return; }
    value = 1;
    paint();
    window.setTimeout(function () {
      bar.classList.remove("is-active");
      bar.setAttribute("aria-hidden", "true");
      window.setTimeout(function () { if (!pending) { value = 0; paint(); } }, 200);
    }, 180);
  }

  // ---------- Buttons im Wartezustand ----------
  var busyButtons = new Set();

  function busy(button, on) {
    if (!button) return;
    if (on) {
      if (busyButtons.has(button)) return;
      busyButtons.add(button);
      button.classList.add("is-loading");
      button.setAttribute("aria-busy", "true");
      button.dataset.wasDisabled = button.disabled ? "1" : "";
      button.disabled = true;  // kein doppeltes Absenden
      var started = Date.now();
      button._bkNoteTimer = window.setInterval(function () {
        var seconds = Math.round((Date.now() - started) / 1000);
        if (Date.now() - started < NOTE_AFTER) return;
        var note = button._bkNote;
        if (!note) {
          note = document.createElement("span");
          note.className = "busy-note";
          note.setAttribute("role", "status");
          button.insertAdjacentElement("afterend", note);
          button._bkNote = note;
        }
        note.textContent = gettext("läuft …") + " " + seconds + " s";
      }, 500);
    } else {
      if (!busyButtons.has(button)) return;
      busyButtons.delete(button);
      button.classList.remove("is-loading");
      button.removeAttribute("aria-busy");
      button.disabled = button.dataset.wasDisabled === "1";
      delete button.dataset.wasDisabled;
      window.clearInterval(button._bkNoteTimer);
      if (button._bkNote) { button._bkNote.remove(); button._bkNote = null; }
    }
  }

  function resetAll() {
    busyButtons.forEach(function (button) { busy(button, false); });
    done(true);
  }

  // ---------- Seitenwechsel ----------
  var DOWNLOAD = /(\.(csv|xlsx|json|pdf|zip|txt)$)|\/export(\/|$)|\/herunterladen(\/|$)/i;

  function leavesPage(url, target) {
    if (target && target !== "_self") return false;
    try {
      var to = new URL(url, window.location.href);
      if (to.origin !== window.location.origin) return false;
      if (DOWNLOAD.test(to.pathname) || /[?&]format=(csv|json)\b/.test(to.search)) return false;
      // Nur ein Sprung innerhalb der Seite (#anker): kein Laden
      return !(to.pathname === window.location.pathname && to.search === window.location.search && to.hash);
    } catch (e) {
      return false;
    }
  }

  function navigationStarted() {
    start();
    window.clearTimeout(giveUpTimer);
    giveUpTimer = window.setTimeout(resetAll, GIVE_UP);
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link = e.target.closest && e.target.closest("a[href]");
    if (!link || link.hasAttribute("download") || link.closest("[data-no-progress]")) return;
    if (leavesPage(link.href, link.getAttribute("target"))) navigationStarted();
  });

  // Erst nach dem Absenden prüfen (setTimeout): Hat ein anderes Skript das Absenden abgefangen
  // (confirm.js fragt nach, Formulare per fetch), ist defaultPrevented gesetzt und hier passiert
  // nichts. Zugleich stehen die Formulardaten dann fest, der Button darf gesperrt werden.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var submitter = e.submitter || null;
    window.setTimeout(function () {
      if (e.defaultPrevented) return;
      if ((form.getAttribute("method") || "").toLowerCase() === "dialog") return;
      if (form.closest("[data-no-progress]") || (submitter && submitter.closest("[data-no-progress]"))) return;
      var target = (submitter && submitter.getAttribute("formtarget")) || form.getAttribute("target");
      var action = (submitter && submitter.getAttribute("formaction")) || form.getAttribute("action") || window.location.href;
      if (!leavesPage(action, target)) return;
      navigationStarted();
      if (submitter && submitter.tagName === "BUTTON") busy(submitter, true);
    }, 0);
  });

  // Zurück-Taste aus dem Zwischenspeicher des Browsers: alles wieder normal.
  window.addEventListener("pageshow", function (e) { if (e.persisted) resetAll(); });

  // ---------- fetch: Änderungen zeigen den Balken ----------
  if (window.fetch) {
    var originalFetch = window.fetch;
    window.fetch = function (input, init) {
      var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var counted = method !== "GET" && method !== "HEAD" && leavesPageOrigin(url);
      if (counted) start();
      var request = originalFetch.apply(this, arguments);
      if (counted) request.then(function () { done(); }, function () { done(); });
      return request;
    };
  }

  function leavesPageOrigin(url) {
    try { return new URL(url, window.location.href).origin === window.location.origin; } catch (e) { return false; }
  }

  window.BaukastenProgress = { start: start, done: done, busy: busy };
})();
