// Editor für Skripte und Abfragen: Tabulator im Code, abhängige Felder, Testlauf für JavaScript.
(function () {
  "use strict";

  var gettext = window.gettext || function (text) { return text; };

  // Tabulator rückt im Code ein, statt das Feld zu verlassen. Esc und dann Tab verlässt das Feld.
  document.querySelectorAll("textarea.code").forEach(function (area) {
    var escaped = false;
    area.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { escaped = true; return; }
      if (e.key !== "Tab" || escaped || e.ctrlKey || e.altKey || e.metaKey) { escaped = false; return; }
      e.preventDefault();
      var start = area.selectionStart, end = area.selectionEnd, value = area.value;
      if (e.shiftKey) {
        var lineStart = value.lastIndexOf("\n", start - 1) + 1;
        if (value.substr(lineStart, 4) === "    ") {
          area.value = value.slice(0, lineStart) + value.slice(lineStart + 4);
          area.selectionStart = area.selectionEnd = Math.max(lineStart, start - 4);
        }
      } else {
        area.value = value.slice(0, start) + "    " + value.slice(end);
        area.selectionStart = area.selectionEnd = start + 4;
      }
    });
  });

  // Felder je nach Auslöser ein- und ausblenden.
  var trigger = document.getElementById("id_trigger");
  var language = document.getElementById("id_language");
  function updateFields() {
    if (!trigger) return;
    document.querySelectorAll("[data-show-trigger]").forEach(function (el) {
      el.hidden = el.dataset.showTrigger.split(" ").indexOf(trigger.value) < 0;  // mehrere Auslöser mit Leerzeichen
    });
    if (language) {
      Array.prototype.forEach.call(trigger.options, function (option) {
        var pythonOnly = option.value === "save" || option.value === "schedule";
        option.disabled = language.value === "javascript" && pythonOnly;
      });
    }
  }
  if (trigger) {
    trigger.addEventListener("change", updateFields);
    updateFields();
  }

  // Testlauf eines JavaScript-Skripts im Browser.
  var testButton = document.getElementById("js-test");
  if (testButton && window.BaukastenRuntime) {
    var cfgEl = document.getElementById("bk-runtime");
    window.BaukastenRuntime.configure(JSON.parse(cfgEl.textContent));
    testButton.addEventListener("click", function () {
      var panel = document.getElementById("js-result");
      var logEl = document.getElementById("js-log"), uiEl = document.getElementById("js-ui");
      var status = document.getElementById("js-status"), errorEl = document.getElementById("js-error");
      var lines = [], ui = {};
      panel.hidden = false;
      logEl.textContent = uiEl.textContent = "";
      errorEl.hidden = true;
      status.className = "badge";
      status.textContent = gettext("läuft …");
      testButton.disabled = true;
      var code = document.getElementById("id_code").value;
      window.BaukastenRuntime.run({name: "test", code: code}, {trigger: "test"}, {
        ui: function (name, values) { ui[name] = Object.assign(ui[name] || {}, values); uiEl.textContent = JSON.stringify(ui, null, 2); },
        message: function (text) { lines.push("» " + text); logEl.textContent = lines.join("\n"); },
        log: function (text) { lines.push(text); logEl.textContent = lines.join("\n"); },
        done: function (result) {
          testButton.disabled = false;
          status.className = "badge " + (result.ok ? "badge-ok" : "badge-error");
          status.textContent = result.ok ? gettext("erfolgreich") : gettext("fehlgeschlagen");
          if (!result.ok) { errorEl.hidden = false; errorEl.querySelector("span").textContent = result.error; }
        }
      });
    });
  }
})();
