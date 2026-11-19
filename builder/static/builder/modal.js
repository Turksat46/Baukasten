// Modaler Dialog für die ganze Oberfläche: BaukastenDialog.confirm(...) und BaukastenDialog.alert(...).
//
//   BaukastenDialog.confirm({title: "Überplanung", text: "…", items: ["…", "…"],
//                            ok: "Trotzdem einplanen", cancel: "Abbrechen", tone: "warning"})
//     .then(function (ok) { if (ok) … });
//
// tone: "info" (Standard), "warning" oder "danger". Escape und „Abbrechen“ liefern false.
// Baut auf <dialog> auf: Fokus bleibt im Dialog und kehrt danach zum auslösenden Element zurück.
(function () {
  "use strict";

  var gettext = window.gettext || function (text) { return text; };
  var ICONS = {info: "i", warning: "!", danger: "!", success: "✓"};
  var queue = Promise.resolve();

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function open(options, withCancel) {
    var o = options || {};
    var tone = ["info", "warning", "danger", "success"].indexOf(o.tone) >= 0 ? o.tone : "info";
    return new Promise(function (resolve) {
      var previous = document.activeElement;
      var dialog = el("dialog", "bk-modal bk-modal-" + tone);
      var titleId = "bk-modal-title-" + Math.random().toString(36).slice(2, 8);
      dialog.setAttribute("aria-labelledby", titleId);

      var head = el("div", "bk-modal-head");
      head.appendChild(el("span", "bk-modal-icon", ICONS[tone])).setAttribute("aria-hidden", "true");
      var title = el("h2", "bk-modal-title", o.title || (withCancel ? gettext("Bitte bestätigen") : gettext("Hinweis")));
      title.id = titleId;
      head.appendChild(title);
      dialog.appendChild(head);

      if (o.text) dialog.appendChild(el("p", "bk-modal-text", o.text));
      if (o.items && o.items.length) {
        var list = el("ul", "bk-modal-items");
        o.items.forEach(function (item) { list.appendChild(el("li", null, item)); });
        dialog.appendChild(list);
      }
      if (o.question) dialog.appendChild(el("p", "bk-modal-question", o.question));

      var actions = el("form", "bk-modal-actions");
      actions.method = "dialog";
      var cancel = null;
      if (withCancel) {
        cancel = el("button", "btn btn-secondary", o.cancel || gettext("Abbrechen"));
        cancel.value = "cancel";
        actions.appendChild(cancel);
      }
      var ok = el("button", "btn" + (tone === "danger" ? " btn-danger" : ""), o.ok || (withCancel ? gettext("OK") : gettext("Verstanden")));
      ok.value = "ok";
      actions.appendChild(ok);
      dialog.appendChild(actions);

      dialog.addEventListener("close", function () {
        var result = dialog.returnValue === "ok";
        dialog.remove();
        if (previous && typeof previous.focus === "function" && document.contains(previous)) previous.focus();
        resolve(result);
      });
      // Klick auf den abgedunkelten Hintergrund schließt wie „Abbrechen“.
      dialog.addEventListener("click", function (e) {
        if (e.target === dialog) { dialog.returnValue = "cancel"; dialog.close(); }
      });
      document.body.appendChild(dialog);
      dialog.returnValue = "cancel";
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {  // sehr alte Browser: einfache Rückfallebene
        dialog.remove();
        var text = [o.title, o.text].concat(o.items || []).filter(Boolean).join("\n");
        resolve(withCancel ? window.confirm(text) : (window.alert(text), true));
        return;
      }
      // Bei gefährlichen Aktionen liegt der Fokus auf „Abbrechen“.
      (tone === "danger" && cancel ? cancel : ok).focus();
    });
  }

  // Dialoge nacheinander zeigen, nie zwei übereinander.
  function enqueue(options, withCancel) {
    var next = queue.then(function () { return open(options, withCancel); });
    queue = next.catch(function () {});
    return next;
  }

  window.BaukastenDialog = {
    confirm: function (options) { return enqueue(options, true); },
    alert: function (options) { return enqueue(typeof options === "string" ? {text: options} : options, false); }
  };
})();
