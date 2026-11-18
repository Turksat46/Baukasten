// Als App installieren: Service Worker anmelden und den Knopf „Als App installieren“ bedienen.
// Wo der Browser selbst installieren kann (Chrome, Edge über HTTPS), öffnet der Knopf dessen Dialog;
// sonst (iPhone, Firefox, http://) erklärt er den Weg über das Browsermenü.
(function () {
  "use strict";
  var gettext = window.gettext || function (t) { return t; };

  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/sw.js").catch(function () { /* ohne Service Worker geht es auch */ });
  }

  var button = document.querySelector("[data-install]");
  var dialog = document.getElementById("install-help");
  if (!button) return;
  var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  if (standalone) return; // läuft schon als App

  var deferred = null;
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault(); // eigener Knopf statt Leiste des Browsers
    deferred = event;
  });
  window.addEventListener("appinstalled", function () { button.hidden = true; });
  button.hidden = false;

  function helpText() {
    var ua = navigator.userAgent;
    if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) {
      return gettext("Tippe in Safari unten auf das Teilen-Symbol (Quadrat mit Pfeil) und dann auf „Zum Home-Bildschirm“.");
    }
    if (/Android/.test(ua)) {
      var text = gettext("Tippe im Browser oben rechts auf das Menü (⋮) und dann auf „Zum Startbildschirm hinzufügen“ bzw. „App installieren“.");
      if (!window.isSecureContext) {
        text += " " + gettext("Über eine http-Adresse legt der Browser nur eine Verknüpfung an; als echte App installieren lässt sich der Baukasten über https.");
      }
      return text;
    }
    return gettext("Klicke in der Adressleiste rechts auf das Symbol „App installieren“ oder im Browsermenü auf „Installieren“. Firefox und Safari am Mac bieten das nicht an.");
  }

  button.addEventListener("click", function () {
    if (deferred) {
      deferred.prompt();
      deferred.userChoice.finally(function () { deferred = null; });
      return;
    }
    if (dialog && dialog.showModal) {
      dialog.querySelector("[data-install-text]").textContent = helpText();
      dialog.showModal();
    } else {
      window.alert(helpText());
    }
  });
})();
