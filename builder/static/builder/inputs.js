// Eingabefelder einer Seite (Baustein „Eingabefeld“) gehen mit jedem Skript- oder Aktions-Button
// derselben Seite an den Server: Das Skript liest sie als params["<Name>"].
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
      hidden.value = input.value;
      hidden.setAttribute("data-copied", "");
      form.appendChild(hidden);
    });
  }, true);
})();
