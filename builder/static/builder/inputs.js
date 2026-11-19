// Eingabefelder einer Seite (Baustein „Eingabefeld“) gehen mit jedem Skript- oder Aktions-Button
// derselben Seite an den Server: Das Skript liest sie als params["<Name>"].
// Außerdem: Anzeige neben Schiebereglern und Felder, die beim Ändern sofort absenden
// (data-autosubmit, z. B. in der Filterleiste und bei Datumswahl).
(function () {
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.closest || !form.closest(".button-block")) return;
    var inputs = document.querySelectorAll("[data-page-input]");
    for (var i = 0; i < inputs.length; i++) {
      if (!inputs[i].checkValidity()) {
        event.preventDefault();
        inputs[i].reportValidity();
        return;
      }
    }
    form.querySelectorAll("input[data-copied]").forEach(function (old) { old.remove(); });
    inputs.forEach(function (input) {
      var hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = input.name;
      // Ja/Nein: "1" oder leer, nicht der feste Wert des Häkchens
      hidden.value = input.type === "checkbox" ? (input.checked ? "1" : "") : input.value;
      hidden.setAttribute("data-copied", "");
      form.appendChild(hidden);
    });
  }, true);

  // Wert neben einem Schieberegler mitführen
  document.addEventListener("input", function (event) {
    var input = event.target;
    if (input.type !== "range") return;
    var low = parseFloat(input.min) || 0, high = parseFloat(input.max) || 100;
    input.style.setProperty("--fill", (100 * (parseFloat(input.value) - low) / (high - low || 1)) + "%");
    var out = input.dataset.rangeOutput ? document.getElementById(input.dataset.rangeOutput) : null;
    if (out) out.textContent = input.value;
  });

  // Filterleiste: leere Felder nicht in die Adresse schreiben
  function dropEmpty(form) {
    if (!form.classList.contains("filter-form")) return;
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.name && el.value === "") el.disabled = true;
    });
  }
  document.addEventListener("submit", function (event) { dropEmpty(event.target); });

  // Felder, die beim Ändern sofort absenden
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (input.matches && input.matches("[data-autosubmit]") && input.form) {
      dropEmpty(input.form);
      input.form.submit();
    }
  });
  // Zurück zur Seite (bfcache): ausgeschaltete Felder wieder freigeben
  window.addEventListener("pageshow", function () {
    document.querySelectorAll(".filter-form [disabled]").forEach(function (el) { el.disabled = false; });
  });
})();
