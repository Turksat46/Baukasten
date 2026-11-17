// Formulare mit data-confirm fragen vor dem Absenden nach.
document.addEventListener("submit", function (event) {
  var message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});
