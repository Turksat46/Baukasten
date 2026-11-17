// Übergänge zwischen Seiten (View Transitions über Seitenwechsel hinweg).
// Der Browser übernimmt die Animation (siehe style.css, Abschnitt „Übergänge“). Dieses Skript
// legt nur die Richtung fest: weiter nach rechts in der Navigation oder tiefer in der Adresse
// heißt „vorwärts“, zurück oder höher heißt „rückwärts“. Browser ohne Unterstützung
// wechseln die Seite wie bisher.
(function () {
  "use strict";

  function pathOf(url) {
    try { return new URL(url, location.href).pathname; } catch (e) { return ""; }
  }

  function depth(path) {
    return path.split("/").filter(Boolean).length;
  }

  function direction(fromUrl, toUrl, navigationType) {
    if (navigationType === "traverse") {
      // Zurück- und Vorwärts-Taste: Richtung aus dem Verlauf.
      var previous = navigation.activation.from, current = navigation.activation.entry;
      if (previous && current && typeof previous.index === "number" && typeof current.index === "number") {
        return current.index < previous.index ? "backward" : "forward";
      }
      return "backward";
    }
    var from = pathOf(fromUrl), to = pathOf(toUrl);
    if (!from || !to || from === to) return "none";
    // Reiter einer App: Position in der Navigation entscheidet.
    var tabs = Array.prototype.map.call(document.querySelectorAll(".topnav a[href]"), function (a) {
      return pathOf(a.href);
    });
    var a = tabs.indexOf(from), b = tabs.indexOf(to);
    if (a >= 0 && b >= 0) return b > a ? "forward" : "backward";
    // Sonst: tiefer in der Adresse ist vorwärts (Designer → App → Tabelle).
    if (depth(to) !== depth(from)) return depth(to) > depth(from) ? "forward" : "backward";
    return "none";
  }

  window.addEventListener("pagereveal", function (event) {
    if (!event.viewTransition || !window.navigation || !navigation.activation) return;
    var activation = navigation.activation;
    var kind = direction(activation.from && activation.from.url, activation.entry.url, activation.navigationType);
    // Neu laden: kein Übergang, die Seite soll einfach stehen bleiben.
    if (activation.navigationType === "reload") {
      event.viewTransition.skipTransition();
      return;
    }
    event.viewTransition.types.add(kind);
  });
})();
