// Startseite: Apps beim Tippen filtern (nur bei mehr als sechs Apps eingeblendet).
(function () {
  var input = document.getElementById("app-search");
  if (!input) return;
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
})();
