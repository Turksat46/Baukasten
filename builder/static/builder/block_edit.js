// Live-Vorschau, klickbare Platzhalter, Snippets und Sanitizer-Hinweise für eigene HTML-Bausteine.
(function () {
  "use strict";

  var root = document.getElementById("block-editor");
  if (!root) return;

  var settingsEl = document.getElementById("id_settings");
  var htmlEl = document.getElementById("id_html");
  var nameEl = document.getElementById("id_name");
  var previewEl = document.getElementById("block-preview-target");
  var placeholdersEl = document.getElementById("block-placeholders");
  var warningsEl = document.getElementById("block-warnings");
  var warningsList = document.getElementById("block-warnings-list");

  var SNIPPETS = {
    card: {
      settings: "Titel = Hinweis\nText = Kurze Beschreibung für Nutzer.",
      html: '<div class="card">\n  <h3>{{ titel }}</h3>\n  <p>{{ text }}</p>\n  <p class="muted small">{{ nutzer }} · {{ datum }}</p>\n</div>'
    },
    kpi: {
      settings: "Bezeichnung = Offene Aufgaben\nWert = 12\nEinheit : select(offen, erledigt, kritisch) = offen",
      html: '<div class="card">\n  <p class="muted small">{{ bezeichnung }}</p>\n  <h2>{{ wert }} <span class="badge">{{ einheit }}</span></h2>\n</div>'
    },
    notice: {
      settings: "Titel = Wartungsfenster\nText = Am Freitag ab 16 Uhr eingeschränkt.",
      html: '<div class="notice notice-warning">\n  <strong>{{ titel }}</strong>\n  <span>{{ text }}</span>\n</div>'
    },
    split: {
      settings: "Links = Kennzahl A\nRechts = Kennzahl B",
      html: '<div class="grid">\n  <div class="col col-6 card"><h4>{{ links }}</h4></div>\n  <div class="col col-6 card"><h4>{{ rechts }}</h4></div>\n</div>'
    }
  };

  function insertAtCursor(textarea, text) {
    if (!textarea) return;
    var start = textarea.selectionStart || 0;
    var end = textarea.selectionEnd || 0;
    var val = textarea.value;
    textarea.value = val.slice(0, start) + text + val.slice(end);
    textarea.selectionStart = textarea.selectionEnd = start + text.length;
    textarea.focus();
  }

  function renderPlaceholders(names) {
    if (!placeholdersEl) return;
    placeholdersEl.replaceChildren();
    (names || []).forEach(function (name) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "key placeholder-chip";
      btn.textContent = "{{ " + name + " }}";
      btn.addEventListener("click", function () {
        insertAtCursor(htmlEl, "{{ " + name + " }}");
        schedulePreview();
      });
      placeholdersEl.appendChild(btn);
      placeholdersEl.appendChild(document.createTextNode(" "));
    });
  }

  function renderWarnings(list) {
    if (!warningsEl || !warningsList) return;
    warningsList.replaceChildren();
    if (!list || !list.length) {
      warningsEl.hidden = true;
      return;
    }
    list.forEach(function (msg) {
      var li = document.createElement("li");
      li.textContent = msg;
      warningsList.appendChild(li);
    });
    warningsEl.hidden = false;
  }

  var timer = null;
  function loadPreview() {
    fetch(root.dataset.previewUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": root.dataset.csrf },
      body: JSON.stringify({
        name: nameEl ? nameEl.value : "",
        settings: settingsEl ? settingsEl.value : "",
        html: htmlEl ? htmlEl.value : ""
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.ok) return;
        if (previewEl) previewEl.innerHTML = data.html || "";
        renderPlaceholders(data.placeholders);
        renderWarnings(data.warnings);
      })
      .catch(function () {});
  }

  function schedulePreview() {
    window.clearTimeout(timer);
    timer = window.setTimeout(loadPreview, 250);
  }

  root.querySelectorAll("[data-snippet]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var s = SNIPPETS[btn.dataset.snippet];
      if (!s) return;
      if (settingsEl && !settingsEl.value.trim()) settingsEl.value = s.settings;
      if (htmlEl) htmlEl.value = s.html;
      loadPreview();
    });
  });

  [settingsEl, htmlEl].forEach(function (el) {
    if (el) el.addEventListener("input", schedulePreview);
  });

  if (placeholdersEl) {
    var initial = [];
    placeholdersEl.querySelectorAll("[data-placeholder]").forEach(function (n) {
      initial.push(n.dataset.placeholder);
    });
    if (initial.length) renderPlaceholders(initial);
  }
})();
