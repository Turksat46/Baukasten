// Startseite: Apps filtern und angepinnte Widgets asynchron nachladen.
(function () {
  var gettext = window.gettext || function (text) { return text; };
  var input = document.getElementById("app-search");
  if (input) {
    var tiles = document.querySelectorAll(".tiles .tile");
    var empty = document.getElementById("app-search-empty");
    input.addEventListener("input", function () {
      var words = input.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      var shown = 0;
      tiles.forEach(function (tile) {
        var text = tile.getAttribute("data-search") || "";
        var match = words.every(function (w) { return text.indexOf(w) !== -1; });
        tile.hidden = !match;
        if (match) shown++;
      });
      if (empty) empty.hidden = shown > 0;
    });
  }

  function load(box, url, attempt) {
    fetch(url, {credentials: "same-origin"})
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        if (html.trim()) box.innerHTML = html;  // vom Server erzeugt und maskiert
        else note(box, gettext("Keine Vorschau"));
        // Läuft die Abfrage des Bausteins noch, meldet der Server „wird geladen“ (data-pending):
        // nach ein paar Sekunden erneut fragen, höchstens 20-mal.
        var pending = box.querySelector("[data-pending]");
        var wait = pending ? parseInt(pending.getAttribute("data-pending"), 10) || 2 : 0;
        if (wait && (attempt || 0) < 20) setTimeout(function () { load(box, url, (attempt || 0) + 1); }, wait * 1000);
      })
      .catch(function () { note(box, gettext("Konnte nicht geladen werden.")); });
  }

  function note(box, text) {
    var span = document.createElement("span");
    span.className = "muted small";
    span.textContent = text;
    box.replaceChildren(span);
  }

  document.querySelectorAll("[data-widget-url]").forEach(function (box) {
    load(box, box.dataset.widgetUrl);
  });

  // Widget-Auswahl als Sheet (wie unter Android): je App aufklappbar, Vorschau erst beim Aufklappen.
  var sheet = document.getElementById("widget-sheet");
  if (!sheet) return;
  var opener = document.querySelector("[data-widget-sheet-open]");
  var search = sheet.querySelector(".widget-sheet-search");
  var groups = sheet.querySelectorAll("[data-widget-app]");
  var emptyNote = sheet.querySelector("[data-widget-sheet-empty]");

  function loadPreviews(group) {
    group.querySelectorAll("[data-preview-url]").forEach(function (box) {
      if (box.dataset.loaded) return;
      box.dataset.loaded = "1";
      load(box, box.dataset.previewUrl);
    });
  }

  groups.forEach(function (group) {
    group.addEventListener("toggle", function () { if (group.open) loadPreviews(group); });
  });

  if (opener) {
    opener.addEventListener("click", function () {
      if (groups.length === 1) { groups[0].open = true; loadPreviews(groups[0]); }
      if (typeof sheet.showModal === "function") sheet.showModal(); else sheet.setAttribute("open", "");
      document.documentElement.classList.add("sheet-open");  // Seite dahinter scrollt nicht mit
      sheet.scrollTop = 0;
      // Mit Maus direkt ins Suchfeld; am Handy nicht, sonst klappt sofort die Tastatur auf.
      if (search && window.matchMedia("(hover: hover)").matches) search.focus({preventScroll: true});
    });
  }
  sheet.addEventListener("close", function () {
    document.documentElement.classList.remove("sheet-open");
    if (opener) opener.focus();
  });
  sheet.querySelectorAll("[data-widget-sheet-close]").forEach(function (b) {
    b.addEventListener("click", function () { sheet.close(); });
  });
  // Klick auf den abgedunkelten Hintergrund schließt das Sheet.
  sheet.addEventListener("click", function (e) { if (e.target === sheet) sheet.close(); });

  if (search) {
    search.addEventListener("input", function () {
      var words = search.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      var total = 0;
      groups.forEach(function (group) {
        var shown = 0;
        group.querySelectorAll(".widget-option").forEach(function (opt) {
          var text = opt.getAttribute("data-search") || "";
          var match = words.every(function (w) { return text.indexOf(w) !== -1; });
          opt.hidden = !match;
          if (match) shown++;
        });
        group.hidden = shown === 0;
        if (words.length && shown) { group.open = true; loadPreviews(group); }
        total += shown;
      });
      if (emptyNote) emptyNote.hidden = total > 0;
    });
  }
})();

// Widgets anordnen: Reihenfolge (Ziehen mit der Maus oder Pfeil-Buttons) und Breite ändern.
// Gespeichert wird erst mit „Fertig“; „Abbrechen“ stellt den Zustand von vorher wieder her.
(function () {
  var gettext = window.gettext || function (text) { return text; };
  var grid = document.querySelector("[data-widget-grid]");
  var toggle = document.querySelector("[data-widget-arrange]");
  var bar = document.querySelector("[data-widget-arrange-bar]");
  if (!grid || !toggle || !bar) return;
  var status = bar.querySelector("[data-widget-status]");
  var hint = status ? status.textContent : "";
  var WIDTHS = ["4", "6", "8", "12"];
  var before = [];
  var dragged = null;

  function cards() { return Array.prototype.slice.call(grid.querySelectorAll("[data-widget-id]")); }

  function setWidth(card, width) {
    WIDTHS.forEach(function (w) { card.classList.remove("col-" + w); });
    card.classList.add("col-" + width);
    card.dataset.width = String(width);
    card.querySelectorAll("[data-size]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.size === String(width) ? "true" : "false");
    });
  }

  function say(text) { if (status) status.textContent = text; }

  function setArranging(on) {
    grid.classList.toggle("is-arranging", on);
    toggle.hidden = on;
    bar.hidden = !on;
    cards().forEach(function (card) {
      card.draggable = on;
      var tools = card.querySelector(".home-widget-tools");
      if (tools) tools.hidden = !on;
    });
    if (on) {
      before = cards().map(function (card) { return {card: card, width: card.dataset.width}; });
      say(hint);
      var first = grid.querySelector("[data-move]");
      if (first) first.focus();
    } else {
      toggle.focus();
    }
  }

  function csrf() {
    var input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  toggle.addEventListener("click", function () { setArranging(true); });

  bar.querySelector("[data-widget-cancel]").addEventListener("click", function () {
    before.forEach(function (s) { grid.appendChild(s.card); setWidth(s.card, s.width); });
    setArranging(false);
  });

  bar.querySelector("[data-widget-save]").addEventListener("click", function () {
    var button = this;
    var widgets = cards().map(function (card) {
      return {id: parseInt(card.dataset.widgetId, 10), width: parseInt(card.dataset.width, 10)};
    });
    button.disabled = true;
    fetch(grid.dataset.saveUrl, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrf()},
      body: JSON.stringify({widgets: widgets})
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); setArranging(false); })
      .catch(function () { say(gettext("Konnte nicht gespeichert werden. Bitte noch einmal versuchen.")); })
      .then(function () { button.disabled = false; });
  });

  grid.addEventListener("click", function (e) {
    if (!grid.classList.contains("is-arranging")) return;
    var button = e.target.closest("[data-move], [data-size]");
    if (!button) return;
    var card = button.closest("[data-widget-id]");
    if (button.dataset.size) {
      setWidth(card, button.dataset.size);
      say(button.getAttribute("aria-label"));
      return;
    }
    var list = cards();
    var target = list[list.indexOf(card) + parseInt(button.dataset.move, 10)];
    if (!target) return;
    grid.insertBefore(card, button.dataset.move === "-1" ? target : target.nextSibling);
    button.focus();
    say(gettext("Position %(n)s von %(total)s")
      .replace("%(n)s", cards().indexOf(card) + 1).replace("%(total)s", list.length));
  });

  // Ziehen mit der Maus: Das Widget rutscht vor oder hinter die Karte unter dem Mauszeiger.
  grid.addEventListener("dragstart", function (e) {
    var card = e.target.closest && e.target.closest("[data-widget-id]");
    if (!card || !grid.classList.contains("is-arranging")) return;
    dragged = card;
    card.classList.add("is-dragged");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.dataset.widgetId);
  });
  grid.addEventListener("dragover", function (e) {
    if (!dragged) return;
    e.preventDefault();
    var over = e.target.closest("[data-widget-id]");
    if (!over || over === dragged) return;
    var rect = over.getBoundingClientRect();
    grid.insertBefore(dragged, e.clientX > rect.left + rect.width / 2 ? over.nextSibling : over);
  });
  grid.addEventListener("drop", function (e) { if (dragged) e.preventDefault(); });
  grid.addEventListener("dragend", function () {
    if (dragged) dragged.classList.remove("is-dragged");
    dragged = null;
  });
})();
