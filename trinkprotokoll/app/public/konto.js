(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var ROLES = { admin: 'Admin', member: 'Mitglied', viewer: 'Nur ansehen' };
  var ROLE_HINT = { admin: 'verwaltet Benutzer und darf erfassen', member: 'darf erfassen', viewer: 'darf nur ansehen' };
  var me = null, armed = null, msgTimer = null;

  function h(tag, props) {
    var e = document.createElement(tag);
    if (props) for (var k in props) {
      var v = props[k];
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
      else if (k === 'value' || k === 'disabled' || k === 'hidden') e[k] = v;
      else e.setAttribute(k, v === true ? '' : v);
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      (Array.isArray(c) ? c : [c]).forEach(function (x) { e.append(x.nodeType ? x : document.createTextNode(x)); });
    }
    return e;
  }
  function say(text, bad) {
    var m = $('#msg');
    clearTimeout(msgTimer);
    m.textContent = text;
    m.hidden = !text;
    m.style.borderLeftColor = bad ? 'var(--crit)' : 'var(--ok)';
    if (text) msgTimer = setTimeout(function () { m.hidden = true; }, 7000);
  }
  function api(method, path, body) {
    var o = { method: method, headers: {}, credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
    return fetch(path, o).then(function (r) {
      if (r.status === 401) { location.replace('login.html'); throw new Error('login'); }
      if (r.status === 204) return null;
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || ('Fehler ' + r.status));
        return j;
      });
    });
  }
  var oops = function (e) { if (e && e.message !== 'login') say(e.message, true); };

  function renderUsers(list) {
    var ul = $('#ulist');
    ul.textContent = '';
    list.slice().sort(function (a, b) { return a.name.localeCompare(b.name, 'de'); }).forEach(function (u) {
      var self = u.id === me.id;
      var sel = h('select', { 'aria-label': 'Rolle von ' + u.name, disabled: self },
        Object.keys(ROLES).map(function (k) { return h('option', { value: k, text: ROLES[k] }); }));
      sel.value = u.role;
      sel.addEventListener('change', function () {
        api('PUT', '/api/users/' + u.id, { role: sel.value }).then(function () { say('Rolle von ' + u.name + ' gespeichert.'); return load(); }).catch(function (e) { oops(e); load(); });
      });
      var li = h('li', { class: 'urow' },
        h('div', { class: 'un' }, u.name, h('small', { text: ROLES[u.role] + (self ? ' · das bist du' : '') })), sel);
      if (!self) {
        var pwIn = h('input', { type: 'password', autocomplete: 'new-password', placeholder: 'Neues Passwort', 'aria-label': 'Neues Passwort für ' + u.name });
        var pwRow = h('div', { class: 'inline', hidden: true }, pwIn, h('button', {
          type: 'button', class: 'ghost', text: 'Speichern',
          onclick: function () {
            api('PUT', '/api/users/' + u.id, { password: pwIn.value }).then(function () { pwIn.value = ''; pwRow.hidden = true; say('Neues Passwort für ' + u.name + ' gesetzt. Seine Geräte sind abgemeldet.'); }).catch(oops);
          },
        }));
        li.append(
          h('button', { type: 'button', class: 'ghost', text: 'Passwort setzen', onclick: function () { pwRow.hidden = !pwRow.hidden; if (!pwRow.hidden) pwIn.focus(); } }),
          h('button', {
            type: 'button', class: 'ghost', text: armed === u.id ? 'Wirklich entfernen' : 'Entfernen',
            onclick: function () {
              if (armed !== u.id) { armed = u.id; renderUsers(list); setTimeout(function () { if (armed === u.id) { armed = null; renderUsers(list); } }, 4000); return; }
              armed = null;
              api('DELETE', '/api/users/' + u.id).then(function () { say(u.name + ' wurde entfernt.'); return load(); }).catch(function (e) { oops(e); load(); });
            },
          }),
          pwRow);
      }
      ul.append(li);
    });
  }

  var armedB = null;
  function renderBabyList(data) {
    var ul = $('#blist'), sel = $('#imp-baby'), keep = sel.value;
    ul.textContent = '';
    sel.textContent = '';
    data.babies.forEach(function (b) {
      var first = b.id === data.first;
      var info = [first ? 'erstes Baby' : '', b.birth ? 'geboren ' + b.birth.split('-').reverse().join('.') : '', b.events + (b.events === 1 ? ' Eintrag' : ' Einträge')].filter(Boolean).join(' · ');
      var li = h('li', { class: 'urow' }, h('div', { class: 'un' }, b.name || 'Baby ohne Namen', h('small', { text: info })));
      if (!first) {
        li.append(h('button', {
          type: 'button', class: 'ghost', text: armedB === b.id ? 'Wirklich entfernen' : 'Entfernen',
          onclick: function () {
            if (armedB !== b.id) { armedB = b.id; renderBabyList(data); setTimeout(function () { if (armedB === b.id) { armedB = null; renderBabyList(data); } }, 4000); return; }
            armedB = null;
            api('DELETE', '/api/babies/' + b.id).then(function () { say((b.name || 'Das Baby') + ' wurde mit allen Einträgen entfernt.'); return loadBabies(); }).catch(function (e) { oops(e); loadBabies(); });
          },
        }));
      }
      ul.append(li);
      sel.append(h('option', { value: b.id, text: b.name || 'Baby ohne Namen' }));
    });
    sel.append(h('option', { value: '__new', text: 'Neues Baby aus der Datei anlegen' }));
    if (keep && Array.prototype.some.call(sel.options, function (o) { return o.value === keep; })) sel.value = keep;
  }
  function loadBabies() { return api('GET', '/api/babies').then(renderBabyList); }

  function load() {
    return api('GET', '/api/me').then(function (m) {
      me = m;
      $('#meName').textContent = m.name;
      $('#meRole').textContent = ROLES[m.role] + ' – ' + ROLE_HINT[m.role];
      $('#admin').hidden = m.role !== 'admin';
      if (m.role === 'admin') return api('GET', '/api/users').then(function (r) { renderUsers(r.users); return loadBabies(); });
    }).catch(oops);
  }

  $('#logout').addEventListener('click', function () {
    var go = function () { location.replace('login.html'); };
    api('POST', '/api/logout').then(go, go);
  });
  $('#pwForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var cur = $('#pw-cur').value, n1 = $('#pw-new').value, n2 = $('#pw-new2').value;
    if (n1 !== n2) return say('Die beiden neuen Passwörter sind nicht gleich.', true);
    if (n1.length < 8) return say('Das neue Passwort braucht mindestens 8 Zeichen.', true);
    api('POST', '/api/me/password', { current: cur, password: n1 }).then(function () {
      $('#pw-cur').value = ''; $('#pw-new').value = ''; $('#pw-new2').value = '';
      say('Passwort geändert. Andere Geräte mit diesem Konto sind jetzt abgemeldet.');
    }).catch(oops);
  });
  $('#addForm').addEventListener('submit', function (e) {
    e.preventDefault();
    api('POST', '/api/users', { name: $('#nu-name').value, password: $('#nu-pw').value, role: $('#nu-role').value }).then(function () {
      say('Benutzer „' + $('#nu-name').value.trim() + '“ angelegt.');
      $('#nu-name').value = ''; $('#nu-pw').value = '';
      return load();
    }).catch(oops);
  });
  $('#babyForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var name = $('#nb-name').value.trim();
    if (!name) return say('Bitte einen Namen eingeben.', true);
    api('POST', '/api/babies', { name: name }).then(function () {
      $('#nb-name').value = '';
      say('„' + name + '“ wurde hinzugefügt. Zum Umschalten die App neu öffnen.');
      return loadBabies();
    }).catch(oops);
  });
  $('#impForm').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = $('#imp-file').files[0], btn = e.target.querySelector('button');
    if (!f) return say('Bitte zuerst eine Datei auswählen.', true);
    if (f.size > 4 * 1024 * 1024) return say('Die Datei ist zu groß (höchstens 4 MB).', true);
    btn.disabled = true;
    f.text().then(function (txt) {
      var j;
      try { j = JSON.parse(txt); } catch (x) { throw new Error('Die Datei ist keine gültige Importdatei.'); }
      var vals = function (o) { return Object.keys(o).map(function (k) { return o[k]; }); };
      var isObj = function (o) { return o && typeof o === 'object' && !Array.isArray(o); };
      /* Komplette Sicherung (Export) mit mehreren Babys, auch ältere Sicherung mit nur einem Baby */
      if (isObj(j) && (isObj(j.babies) || (isObj(j.events) && !Array.isArray(j.events)))) {
        var parts = [];
        if (isObj(j.babies)) {
          (Array.isArray(j.order) ? j.order : Object.keys(j.babies)).forEach(function (id) {
            var b = j.babies[id]; if (!isObj(b) || !isObj(b.events)) return;
            var st = (b.settings && b.settings.baby) || {};
            parts.push({ name: st.name || id, payload: { events: vals(b.events), settings: st } });
          });
        } else {
          var st1 = (j.settings && j.settings.baby) || {};
          parts.push({ name: st1.name || 'Baby', payload: { events: vals(j.events), settings: st1 } });
        }
        if (!parts.length) throw new Error('Die Datei enthält keine Einträge.');
        return api('GET', '/api/babies').then(function (r) {
          var list = (r.babies || r).slice(), used = {}, out = [];
          var chain = Promise.resolve();
          parts.forEach(function (pt) {
            chain = chain.then(function () {
              var low = String(pt.name).toLowerCase();
              var hit = list.filter(function (b) { return !used[b.id] && String(b.name || '').toLowerCase() === low; })[0] ||
                        list.filter(function (b) { return !used[b.id] && !b.events; })[0];
              var ready = hit ? Promise.resolve(hit.id) : api('POST', '/api/babies', { name: pt.name }).then(function (b) { return b.id; });
              return ready.then(function (id) {
                used[id] = 1;
                return api('POST', '/api/babies/' + id + '/import', pt.payload).then(function (res) { out.push(pt.name + ': ' + res.added + ' neu, ' + res.duplicates + ' schon vorhanden' + (res.invalid ? ', ' + res.invalid + ' ungültig' : '')); });
              });
            });
          });
          return chain.then(function () { return { summary: 'Sicherung eingelesen. ' + out.join(' · ') + '.' }; });
        });
      }
      if (!j || !Array.isArray(j.events)) throw new Error('Die Datei enthält keine Einträge.');
      var target = $('#imp-baby').value;
      var ready = target === '__new'
        ? api('POST', '/api/babies', { name: (j.settings && j.settings.name) || 'Neues Baby' }).then(function (b) { return b.id; })
        : Promise.resolve(target);
      return ready.then(function (id) { return api('POST', '/api/babies/' + id + '/import', j); });
    }).then(function (r) {
      $('#imp-file').value = '';
      if (r.summary) say(r.summary);
      else say('Import fertig: ' + r.added + ' neue Einträge, ' + r.duplicates + ' schon vorhanden' + (r.invalid ? ', ' + r.invalid + ' ungültig übersprungen' : '') + '.');
      return loadBabies();
    }).catch(oops).then(function () { btn.disabled = false; });
  });
  load();
})();
