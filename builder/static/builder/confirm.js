// Formulare mit data-confirm fragen vor dem Absenden nach, im Dialog des Baukastens (modal.js).
// data-confirm-tone="danger" (Standard bei „löschen“) färbt ihn rot, data-confirm-ok beschriftet den Button.
document.addEventListener("submit", function (event) {
  var form = event.target;
  var message = form.dataset.confirm;
  if (!message || form.dataset.confirmed === "1") return;
  event.preventDefault();
  var submitter = event.submitter || null;
  var ask = window.BaukastenDialog
    ? window.BaukastenDialog.confirm({
        text: message,
        tone: form.dataset.confirmTone || (/lösch|delete|entfern/i.test(message) ? "danger" : "warning"),
        ok: form.dataset.confirmOk || (window.gettext ? window.gettext("Ja, fortfahren") : "Ja, fortfahren")
      })
    : Promise.resolve(window.confirm(message));
  ask.then(function (ok) {
    if (!ok) return;
    form.dataset.confirmed = "1";
    if (typeof form.requestSubmit === "function") form.requestSubmit(submitter);
    else form.submit();
    delete form.dataset.confirmed;
  });
});
