/*
 * Verbindet die Seite mit dem eigenen Server. Die Seite spricht dieselbe Schnittstelle
 * wie in der Claude-Version (db, user, downloads), gespeichert wird aber über /api/ auf dem Server.
 * Änderungen anderer Geräte erscheinen nach spätestens 5 Sekunden.
 */
(function () {
  'use strict';
  var POLL_MS = 5000;
  var subs = [];
  var timer = null;
  var failures = 0;

  function connState(ok) {
    if (ok) {
      if (failures >= 2) window.dispatchEvent(new CustomEvent('trink-conn', { detail: { ok: true } }));
      failures = 0;
    } else {
      failures++;
      if (failures === 2) window.dispatchEvent(new CustomEvent('trink-conn', { detail: { ok: false } }));
    }
  }

  /* Welches Baby auf diesem Gerät angezeigt wird, merkt sich das Gerät selbst. */
  var BKEY = 'trink_baby', baby = null, babyList = [], babyFirst = null, babiesP = null;
  try { baby = localStorage.getItem(BKEY) || null; } catch (e) { baby = null; }
  function withBaby(path) {
    if (!baby || !/^\/api\/(events|settings)(\/|\?|$)/.test(path) || /[?&]baby=/.test(path)) return path;
    return path + (path.indexOf('?') < 0 ? '?' : '&') + 'baby=' + encodeURIComponent(baby);
  }

  function api(method, path, body) {
    path = withBaby(path);
    var opt = { method: method, headers: {}, credentials: 'same-origin', cache: 'no-cache' };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    return fetch(path, opt).then(function (r) {
      if (r.status === 204) return null;
      if (r.status === 401) location.replace('login.html'); // Sitzung abgelaufen oder abgemeldet
      if (!r.ok) { var e = new Error('HTTP ' + r.status); e.code = r.status; throw e; }
      return r.json();
    });
  }

  function match(d, f) {
    var v = d[f[0]], x = f[2];
    switch (f[1]) {
      case '==': return v === x;
      case '!=': return v !== x;
      case '<': return v < x;
      case '<=': return v <= x;
      case '>': return v > x;
      case '>=': return v >= x;
      case 'in': return x.indexOf(v) >= 0;
      case 'not-in': return x.indexOf(v) < 0;
      case 'array-contains': return Array.isArray(v) && v.indexOf(x) >= 0;
    }
    return true;
  }
  var META = { fromCache: false, hasPendingWrites: false };
  function docSnap(id, data) {
    return { id: id, exists: data != null, data: function () { return data == null ? undefined : data; }, metadata: META };
  }

  /* Ein Abonnement fragt den Server ab und meldet nur, wenn sich etwas geändert hat. */
  function subscribe(fetcher, deliver, next, error) {
    var s = { dead: false, busy: false, rev: null };
    s.run = function () {
      if (s.dead || s.busy) return;
      s.busy = true;
      fetcher().then(function (res) {
        s.busy = false;
        connState(true);
        if (s.dead || res.rev === s.rev) return;
        s.rev = res.rev;
        next(deliver(res));
      }).catch(function (e) {
        s.busy = false;
        connState(false);
        if (e && (e.code === 400 || e.code === 404) && error && !s.dead) { s.dead = true; error({ code: 'invalid_argument', message: String(e.message) }); }
      });
    };
    subs.push(s);
    start();
    s.run();
    return function () { s.dead = true; subs = subs.filter(function (x) { return x !== s; }); };
  }
  function refreshAll() { subs.slice().forEach(function (s) { s.run(); }); }
  function start() {
    if (timer) return;
    timer = setInterval(function () { if (!document.hidden) refreshAll(); }, POLL_MS);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refreshAll(); });
    window.addEventListener('online', refreshAll);
  }
  function after(p) { return p.then(function (r) { refreshAll(); return r; }); }

  /* ---------- Sammlungen und Dokumente ---------- */
  function DocRef(col, id) {
    var base = '/api/' + col + '/' + encodeURIComponent(id);
    return {
      id: id, path: col + '/' + id,
      set: function (data) { return after(api('PUT', base, data)).then(function () {}); },
      update: function (data) { return after(api('PUT', base, data)).then(function () {}); },
      delete: function () { return after(api('DELETE', base)).then(function () {}); },
      onSnapshot: function (next, error) {
        if (col !== 'settings') { if (error) error({ code: 'invalid_argument', message: 'Nicht unterstützt' }); return function () {}; }
        return subscribe(function () { return api('GET', base); },
          function (res) { return docSnap(id, res.exists ? res.data : null); }, next, error);
      },
    };
  }

  function Query(col, filters, order, lim) {
    var q = {};
    q.where = function (f, op, v) { return Query(col, filters.concat([[f, op, v]]), order, lim); };
    q.orderBy = function (f, d) { return Query(col, filters, [f, d || 'asc'], lim); };
    q.limit = function (n) { return Query(col, filters, order, n); };
    q.doc = function (id) { return DocRef(col, id); };
    q.add = function (data) {
      return after(api('POST', '/api/' + col, data)).then(function (r) { return DocRef(col, r.id); });
    };
    q.onSnapshot = function (next, error) {
      /* Zeitraum und Art gehen als Filter an den Server, damit nicht alles geladen wird. */
      var params = [];
      filters.forEach(function (f) {
        if (f[0] === 'ts' && (f[1] === '>=' || f[1] === '>')) params.push('from=' + encodeURIComponent(f[2]));
        if (f[0] === 'type' && f[1] === 'in') params.push('types=' + encodeURIComponent(f[2].join(',')));
        if (f[0] === 'type' && f[1] === '==') params.push('types=' + encodeURIComponent(f[2]));
      });
      var url = '/api/' + col + (params.length ? '?' + params.join('&') : '');
      return subscribe(function () { return api('GET', url); }, function (res) {
        var rows = res.docs.filter(function (d) { return filters.every(function (f) { return match(d.data, f); }); });
        if (order) {
          var k = order[0], dir = order[1] === 'desc' ? -1 : 1;
          rows.sort(function (a, b) { return (a.data[k] - b.data[k]) * dir; });
        }
        if (lim) rows = rows.slice(0, lim);
        var docs = rows.map(function (d) { return docSnap(d.id, d.data); });
        return { docs: docs, size: docs.length, empty: !docs.length, metadata: META, docChanges: function () { return []; } };
      }, next, error);
    };
    return q;
  }

  var db = {
    collection: function (name) { return Query(name, [], null, null); },
    doc: function (path) { var s = path.split('/'); return DocRef(s[0], s[1]); },
  };
  /* Rolle "Nur ansehen" darf nichts schreiben, die Seite blendet dann die Eingabe aus. */
  var meCall = null;
  var user = {
    can: function (name) {
      if (name !== 'data.write') return Promise.resolve(null);
      if (!meCall) meCall = api('GET', '/api/me');
      return meCall.then(function (m) { return m.role !== 'viewer'; }).catch(function () { return null; });
    },
  };
  function loadBabies() {
    if (!babiesP) {
      babiesP = api('GET', '/api/babies').then(function (r) {
        babyList = r.babies || []; babyFirst = r.first || null;
        if (baby && !babyList.some(function (b) { return b.id === baby; })) {
          baby = null;
          try { localStorage.removeItem(BKEY); } catch (e) {}
        }
        return babyList;
      });
    }
    return babiesP;
  }
  window.TrinkBabies = {
    ready: function () { return loadBabies(); },
    list: function () { return babyList; },
    current: function () { return baby || babyFirst; },
    set: function (id) { try { localStorage.setItem(BKEY, id); } catch (e) {} location.reload(); },
    refresh: function () { babiesP = null; return loadBabies(); },
    events: function (id, types) {
      return api('GET', '/api/events?baby=' + encodeURIComponent(id) + (types ? '&types=' + encodeURIComponent(types) : '')).then(function (r) {
        return r.docs.map(function (d) { var o = d.data; o.id = d.id; return o; });
      });
    },
  };
  var downloads = {
    save: function (o) {
      return new Promise(function (resolve, reject) {
        try {
          var blob = o.data instanceof Blob ? o.data : new Blob([o.data], { type: 'text/csv;charset=utf-8' });
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = o.filename;
          document.body.appendChild(a);
          a.click();
          setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
          resolve({ status: 'saved' });
        } catch (e) { reject({ code: 'unavailable', message: String(e) }); }
      });
    },
  };
  window.claude = {
    use: function (name) {
      return loadBabies().catch(function () {}).then(function () {
        return name === 'db' ? db : name === 'user' ? user : name === 'downloads' ? downloads : null;
      });
    },
  };
})();
