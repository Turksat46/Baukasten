// Interaktive Bausteine: Einsatzplanung und Kanban-Board; stellt BaukastenBlocks.act/reload bereit.
// Ziehen und Ablegen kommt aus dnd.js, Rückfragen aus modal.js. Gespeichert wird über
// den Endpunkt des Bausteins (data-action-url); danach lädt der Baustein sich neu.
(function () {
  "use strict";

  var gettext = window.gettext || function (text) { return text; };
  var Dialog = window.BaukastenDialog;

  function post(root, payload) {
    return fetch(root.dataset.actionUrl, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": root.dataset.csrf || ""},
      body: JSON.stringify(payload)
    }).then(function (response) {
      return response.json().catch(function () { return {error: response.statusText}; }).then(function (data) {
        data.status = response.status;
        return data;
      });
    });
  }

  function errorText(data) {
    var text = data.error || gettext("Das hat nicht geklappt.");
    if (data.fields) {
      text += " " + Object.keys(data.fields).map(function (k) {
        return k + ": " + data.fields[k].map(function (e) { return e.message; }).join(" ");
      }).join("; ");
    }
    return text;
  }

  // Aktion senden; bei einer Warnung (409, confirm) im Dialog nachfragen und mit force wiederholen.
  function act(root, payload, labels) {
    root.classList.add("is-busy");
    return post(root, payload).then(function (data) {
      if (data.ok) return reload(root, labels && labels.done);
      root.classList.remove("is-busy");
      if (data.status === 409 && data.confirm) {
        return Dialog.confirm({
          title: data.error, items: data.problems, tone: "warning",
          question: labels && labels.question, ok: (labels && labels.force) || gettext("Trotzdem ausführen")
        }).then(function (ok) {
          if (!ok) return announce(root, gettext("Abgebrochen."));
          return act(root, Object.assign({}, payload, {force: true}), labels);
        });
      }
      return Dialog.alert({title: data.problems ? data.error : gettext("Nicht gespeichert"),
                           text: data.problems ? null : errorText(data), items: data.problems, tone: "danger"});
    }, function () {
      root.classList.remove("is-busy");
      return Dialog.alert({title: gettext("Keine Verbindung"), text: gettext("Bitte prüfe die Verbindung und versuche es noch einmal."), tone: "danger"});
    });
  }

  function announce(root, text) {
    var status = root.querySelector("[data-plan-status]");
    if (status) status.textContent = text || "";
  }

  // Baustein neu laden, Filtertext und Bildlage behalten.
  function reload(root, message) {
    var url = root.dataset.reloadUrl + window.location.search;
    var filter = root.querySelector("[data-plan-filter]");
    var filterText = filter ? filter.value : "";
    var holder = root.parentElement;
    return fetch(url, {credentials: "same-origin"}).then(function (r) { return r.ok ? r.text() : null; }).then(function (html) {
      if (html === null) { window.location.reload(); return; }
      holder.innerHTML = html;  // vom Server erzeugt und maskiert
      var fresh = holder.querySelector("[data-action-url]");
      var input = fresh && fresh.querySelector("[data-plan-filter]");
      if (input && filterText) { input.value = filterText; applyFilter(input); }
      if (fresh) announce(fresh, message || gettext("Gespeichert."));
      document.dispatchEvent(new CustomEvent("baukasten:block-updated", {detail: {block: holder}}));
    });
  }

  function slotOf(el) { return el.closest("[data-drop='slot']"); }

  window.BaukastenDnD.register("[data-plan='assign']", {
    accepts: function (item, zone) {
      var kind = item.dataset.drag, target = zone.dataset.drop;
      if (kind === "source") return target === "slot";
      if (kind === "link") return target === "pool" || (target === "slot" && zone !== slotOf(item));
      return false;
    },
    drop: function (item, zone, root) {
      var name = (item.querySelector(".plan-chip-name") || item).textContent.trim();
      if (zone.dataset.drop === "pool") {
        return act(root, {op: "unassign", link: item.dataset.link}, {done: name + " " + gettext("entfernt.")});
      }
      var payload = item.dataset.drag === "link"
        ? {op: "move", link: item.dataset.link, target: zone.dataset.target}
        : {op: "assign", source: item.dataset.id, target: zone.dataset.target, day: root.dataset.day || null};
      return act(root, payload, {
        force: gettext("Trotzdem einplanen"),
        question: interpolateName(gettext("%s trotzdem einplanen?"), name),
        done: name + " " + gettext("eingeplant.")
      });
    }
  });

  window.BaukastenDnD.register("[data-plan='kanban']", {
    accepts: function (item, zone) {
      return item.dataset.drag === "card" && zone.dataset.drop === "column" && !zone.contains(item);
    },
    drop: function (item, zone, root) {
      return act(root, {op: "move", record: item.dataset.id, value: zone.dataset.value}, {
        force: gettext("Trotzdem verschieben"), done: gettext("Verschoben.")
      });
    }
  });

  function interpolateName(text, name) {
    return window.interpolate ? window.interpolate(text, [name]) : text.replace("%s", name);
  }

  // Entfernen per ×
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-unassign]");
    var root = button && button.closest("[data-plan='assign']");
    if (!root) return;
    var name = (button.closest(".plan-chip").querySelector(".plan-chip-name") || button).textContent.trim();
    act(root, {op: "unassign", link: button.dataset.unassign}, {done: name + " " + gettext("entfernt.")});
  });

  // Liste filtern
  function applyFilter(input) {
    var root = input.closest(".plan-pool");
    var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
    root.querySelectorAll("[data-filter-text]").forEach(function (chip) {
      var text = chip.dataset.filterText;
      chip.hidden = !words.every(function (w) { return text.indexOf(w) >= 0; });
    });
  }
  document.addEventListener("input", function (e) {
    if (e.target.matches("[data-plan-filter]")) applyFilter(e.target);
  });

  // Für weitere interaktive Bausteine (widgets.js): Aktion mit Rückfrage senden, Baustein neu laden.
  window.BaukastenBlocks = {act: act, reload: reload, announce: announce};
})();
