(function () {
  'use strict';
  var form = document.getElementById('f');
  var err = document.getElementById('err');
  var go = document.getElementById('go');
  function showError(text) { err.textContent = text; err.hidden = false; go.disabled = false; }
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    err.hidden = true;
    go.disabled = true;
    fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ name: document.getElementById('u').value, password: document.getElementById('p').value }),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.ok) { location.replace('./'); return; }
        showError(j.error || 'Die Anmeldung hat nicht geklappt.');
      });
    }).catch(function () { showError('Der Server ist nicht erreichbar.'); });
  });
})();
