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

  function load(box, url) {
    fetch(url)
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        if (html.trim()) box.innerHTML = html;  // vom Server erzeugt und maskiert
        else note(box, gettext("Keine Vorschau"));
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
