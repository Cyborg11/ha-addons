'use strict';
/*
 * Trinkprotokoll – kleiner Server ohne Abhängigkeiten (Node 18 oder neuer).
 * Liefert die Seite aus public/ aus, verwaltet Benutzer und speichert die Einträge in einer JSON-Datei.
 *
 * Einstellungen per Umgebungsvariable:
 *   TRINK_ADMIN_USER      Name des ersten Admins, Standard: admin
 *   TRINK_ADMIN_PASSWORD  Passwort des ersten Admins. Wirkt nur beim allerersten Start, solange es noch keine Benutzer gibt.
 *                         Ohne Angabe erzeugt der Server ein Passwort und schreibt es einmalig ins Protokoll.
 *   PORT                  Standard: 3000
 *   HOST                  Standard: 0.0.0.0
 *   DATA_DIR              Ordner für alle Daten und Sicherungen, Standard: ./data
 * (TRINK_USER und TRINK_PASSWORD der ersten Version werden als Ersatz für die beiden ersten Angaben akzeptiert.)
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = Number(process.env.PORT) || 3000;
const HOST = process.env.HOST || '0.0.0.0';
const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(__dirname, 'data'));
const PUBLIC_DIR = path.join(__dirname, 'public');
const ADMIN_USER = (process.env.TRINK_ADMIN_USER || process.env.TRINK_USER || 'admin').trim();
const ADMIN_PASSWORD = process.env.TRINK_ADMIN_PASSWORD || process.env.TRINK_PASSWORD || '';
const BACKUP_DIR = path.join(DATA_DIR, 'backups');
const FILE = path.join(DATA_DIR, 'data.json');
const USERS_FILE = path.join(DATA_DIR, 'users.json');
const SECRET_FILE = path.join(DATA_DIR, 'secret.key');
const BACKUP_KEEP = 30;
const MAX_BODY = 64 * 1024;
const SESSION_DAYS = 90;
const DAY = 864e5;

const TYPES = new Set(['stillen', 'flasche', 'windel', 'gewicht', 'wachstum', 'spucken', 'vitd', 'schlaf', 'beikost', 'temp', 'medi']);
const NUM_FIELDS = ['min', 'ml', 'g', 'len', 'head', 'wach', 'n', 'c'];
const STR_FIELDS = { side: 20, kind: 20, diaper: 20, amount: 20, where: 20, name: 60, dose: 40, note: 200 };
const ROLES = ['admin', 'member', 'viewer'];
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const UID_RE = /^[0-9a-f]{16}$/;
const BABY_RE = /^[a-z0-9]{1,12}$/;
const MAX_BABIES = 6;
const MAX_IMPORT = 4 * 1024 * 1024;
const NAME_RE = /^[\p{L}\p{N}][\p{L}\p{N} ._-]{1,29}$/u;

/* ---------- Dateien ---------- */
fs.mkdirSync(BACKUP_DIR, { recursive: true });
function atomicWrite(file, text, mode) {
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, text, mode ? { mode } : undefined);
  fs.renameSync(tmp, file);
}
function readJsonFile(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    if (e.code === 'ENOENT') return fallback;
    // Lieber nicht starten, als eine beschädigte Datei zu überschreiben.
    console.error(file + ' kann nicht gelesen werden: ' + e.message);
    console.error('Datei prüfen oder aus ' + BACKUP_DIR + ' wiederherstellen.');
    process.exit(1);
  }
}

/* ---------- Einträge ---------- */
const isObj = (x) => x && typeof x === 'object' && !Array.isArray(x);
const raw = readJsonFile(FILE, {});
// Ab Version 2 gibt es mehrere Babys. Alte Dateien (ein Baby) werden beim Laden zum Baby "main".
const state = { version: 2, rev: Number(raw.rev) || 0, order: [], babies: {} };
if (isObj(raw.babies)) {
  for (const id of Object.keys(raw.babies)) {
    const b = raw.babies[id];
    if (BABY_RE.test(id) && isObj(b)) state.babies[id] = { events: isObj(b.events) ? b.events : {}, settings: isObj(b.settings) ? b.settings : {} };
  }
  state.order = (Array.isArray(raw.order) ? raw.order : []).filter((id) => state.babies[id]);
  for (const id of Object.keys(state.babies)) if (!state.order.includes(id)) state.order.push(id);
}
if (!state.order.length) {
  if (fs.existsSync(FILE) && !isObj(raw.babies)) {
    const keep = path.join(BACKUP_DIR, 'umstellung-v1-data.json');
    if (!fs.existsSync(keep)) fs.copyFileSync(FILE, keep);
  }
  state.babies.main = { events: isObj(raw.events) ? raw.events : {}, settings: isObj(raw.settings) ? raw.settings : {} };
  state.order = ['main'];
}
const eventCount = () => state.order.reduce((n, id) => n + Object.keys(state.babies[id].events).length, 0);
let saveTimer = null;
let lastBackupRev = -1;
function flush() {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
  atomicWrite(FILE, JSON.stringify(state));
}
function touch() {
  state.rev++;
  if (!saveTimer) saveTimer = setTimeout(flush, 150);
}

/* ---------- Benutzer ---------- */
let users = readJsonFile(USERS_FILE, { users: [] }).users || [];
let usersDirty = false;
function saveUsers() {
  atomicWrite(USERS_FILE, JSON.stringify({ version: 1, users }), 0o600);
  usersDirty = true;
}
let SECRET;
try {
  SECRET = fs.readFileSync(SECRET_FILE);
} catch (e) {
  if (e.code !== 'ENOENT') throw e;
  SECRET = crypto.randomBytes(32);
  fs.writeFileSync(SECRET_FILE, SECRET, { mode: 0o600 });
}

const SCRYPT = { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };
function hashPassword(pw) {
  return new Promise((resolve, reject) => {
    const salt = crypto.randomBytes(16);
    crypto.scrypt(pw, salt, 64, SCRYPT, (e, key) => (e ? reject(e) : resolve('scrypt$' + salt.toString('base64') + '$' + key.toString('base64'))));
  });
}
function verifyPassword(pw, stored) {
  return new Promise((resolve) => {
    const p = String(stored || '').split('$');
    if (p[0] !== 'scrypt' || p.length !== 3 || pw.length > 200) return resolve(false);
    const salt = Buffer.from(p[1], 'base64');
    const want = Buffer.from(p[2], 'base64');
    crypto.scrypt(pw, salt, want.length, SCRYPT, (e, key) => resolve(!e && crypto.timingSafeEqual(key, want)));
  });
}
let DUMMY_HASH = '';
hashPassword('kein-echtes-passwort').then((h) => { DUMMY_HASH = h; });

const sha = (s) => crypto.createHash('sha256').update(s).digest();
const safeEq = (a, b) => crypto.timingSafeEqual(sha(a), sha(b));
const newUserId = () => crypto.randomBytes(8).toString('hex');
const newId = () => Date.now().toString(36) + crypto.randomBytes(4).toString('hex');
const findByName = (name) => users.find((u) => u.name.toLowerCase() === String(name).trim().toLowerCase());
const adminCount = () => users.filter((u) => u.role === 'admin').length;
const publicUser = (u) => ({ id: u.id, name: u.name, role: u.role, created: u.created });

function checkName(name) {
  return typeof name === 'string' && NAME_RE.test(name.trim()) ? null : 'Der Name muss 2 bis 30 Zeichen lang sein (Buchstaben, Ziffern, Leerzeichen, Punkt, Unterstrich, Bindestrich).';
}
function checkPassword(pw) {
  return typeof pw === 'string' && pw.length >= 8 && pw.length <= 200 ? null : 'Das Passwort braucht mindestens 8 Zeichen.';
}

/* ---------- Sitzungen (signiertes Cookie) ---------- */
const COOKIE = 'trink_session';
const sign = (payload) => crypto.createHmac('sha256', SECRET).update(payload).digest('base64url');
function makeToken(u) {
  const payload = u.id + '.' + (Date.now() + SESSION_DAYS * DAY) + '.' + u.tv;
  return payload + '.' + sign(payload);
}
function readCookie(req, name) {
  for (const part of String(req.headers.cookie || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0 && part.slice(0, i).trim() === name) return part.slice(i + 1).trim();
  }
  return '';
}
function sessionOf(req) {
  const parts = readCookie(req, COOKIE).split('.');
  if (parts.length !== 4) return null;
  const [id, exp, tv, sig] = parts;
  if (!safeEq(sig, sign(id + '.' + exp + '.' + tv))) return null;
  if (!(Number(exp) > Date.now())) return null;
  const user = users.find((u) => u.id === id);
  if (!user || String(user.tv) !== tv) return null;
  return { user, exp: Number(exp) };
}
const isHttps = (req) => !!req.socket.encrypted || String(req.headers['x-forwarded-proto'] || '').split(',')[0].trim() === 'https';
function cookieFor(token, req, maxAgeSec) {
  return COOKIE + '=' + token + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=' + maxAgeSec + (isHttps(req) ? '; Secure' : '');
}

/* ---------- Bremse gegen Raten von Passwörtern ---------- */
const fails = new Map(); // "ip|name" -> { n, since }
const failKey = (ip, name) => ip + '|' + String(name).trim().toLowerCase();
function blocked(key) {
  const f = fails.get(key);
  if (!f) return false;
  if (Date.now() - f.since > 15 * 60 * 1000) { fails.delete(key); return false; }
  return f.n >= 10;
}
function noteFail(key) {
  const f = fails.get(key);
  if (!f || Date.now() - f.since > 15 * 60 * 1000) fails.set(key, { n: 1, since: Date.now() });
  else f.n++;
}

/* ---------- Sicherungen ---------- */
function prune(prefix) {
  const re = new RegExp('^' + prefix + '-\\d{4}-\\d{2}-\\d{2}\\.json$');
  const files = fs.readdirSync(BACKUP_DIR).filter((f) => re.test(f)).sort();
  while (files.length > BACKUP_KEEP) fs.unlinkSync(path.join(BACKUP_DIR, files.shift()));
}
function backup() {
  try {
    if (saveTimer) flush();
    const day = new Date().toISOString().slice(0, 10);
    if (fs.existsSync(FILE) && state.rev !== lastBackupRev) {
      fs.copyFileSync(FILE, path.join(BACKUP_DIR, 'data-' + day + '.json'));
      lastBackupRev = state.rev;
      prune('data');
    }
    if (fs.existsSync(USERS_FILE) && usersDirty) {
      const dst = path.join(BACKUP_DIR, 'users-' + day + '.json');
      fs.copyFileSync(USERS_FILE, dst);
      fs.chmodSync(dst, 0o600);
      usersDirty = false;
      prune('users');
    }
  } catch (e) {
    console.error('Sicherung fehlgeschlagen:', e.message);
  }
}
setInterval(backup, 60 * 60 * 1000).unref();

/* ---------- Prüfen eingehender Daten ---------- */
function cleanEvent(b) {
  if (!isObj(b) || !TYPES.has(b.type)) return null;
  const ts = Number(b.ts);
  if (!Number.isFinite(ts) || ts < 946684800000 || ts > 4102444800000) return null;
  const o = { type: b.type, ts: Math.round(ts) };
  for (const k of NUM_FIELDS) {
    if (b[k] === undefined || b[k] === null) continue;
    const n = Number(b[k]);
    if (!Number.isFinite(n) || n < 0 || n > 100000) return null;
    o[k] = n;
  }
  for (const k of Object.keys(STR_FIELDS)) {
    if (b[k] === undefined || b[k] === null) continue;
    if (typeof b[k] !== 'string') return null;
    o[k] = b[k].slice(0, STR_FIELDS[k]);
  }
  if (o.type === 'temp' && !(o.c >= 34 && o.c <= 43)) return null;
  if (o.type === 'medi') {
    o.name = (o.name || '').trim();
    if (!o.name) return null;
  }
  return o;
}
function cleanSettings(b) {
  if (!isObj(b)) return null;
  const o = {
    name: typeof b.name === 'string' ? b.name.slice(0, 40) : '',
    birth: typeof b.birth === 'string' && /^(\d{4}-\d{2}-\d{2})?$/.test(b.birth) ? b.birth : '',
  };
  for (const k of ['birthWeight', 'birthLength', 'birthHead']) {
    const n = Number(b[k]);
    o[k] = Number.isFinite(n) && n > 0 && n < 100000 ? n : 0;
  }
  return o;
}

/* ---------- Antworten ---------- */
// Einbetten in andere Seiten (zum Beispiel ein Home-Assistant-Dashboard) ist standardmäßig verboten.
const ALLOW_EMBED = /^(1|true|yes)$/i.test(process.env.TRINK_ALLOW_EMBED || '');
const SEC = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy':
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
    "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors " + (ALLOW_EMBED ? '*' : "'none'"),
};
if (!ALLOW_EMBED) SEC['X-Frame-Options'] = 'DENY';
function send(res, code, body, type, extra) {
  res.writeHead(code, Object.assign({ 'Content-Type': type || 'text/plain; charset=utf-8' }, SEC, extra || {}));
  res.end(body);
}
function json(res, code, obj, extra) {
  send(res, code, JSON.stringify(obj), 'application/json; charset=utf-8', Object.assign({ 'Cache-Control': 'no-store' }, extra || {}));
}
const fail = (res, code, msg) => json(res, code, { error: msg });
function jsonRev(req, res, obj) {
  const etag = '"' + state.rev + '"';
  if (req.headers['if-none-match'] === etag) { res.writeHead(304, Object.assign({ ETag: etag }, SEC)); return res.end(); }
  send(res, 200, JSON.stringify(obj), 'application/json; charset=utf-8', { ETag: etag, 'Cache-Control': 'no-cache' });
}
function readBody(req, max) {
  return new Promise((resolve, reject) => {
    if (!/^application\/json/i.test(req.headers['content-type'] || '')) return reject({ status: 415, msg: 'JSON erwartet' });
    let size = 0;
    const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > (max || MAX_BODY)) { reject({ status: 413, msg: 'Zu groß' }); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch (e) { reject({ status: 400, msg: 'Ungültiges JSON' }); }
    });
    req.on('error', () => reject({ status: 400, msg: 'Fehler beim Lesen' }));
  });
}

/* ---------- Statische Dateien ---------- */
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json',
};
const OPEN_ASSET = /^\/(manifest\.webmanifest|icon\.svg|icon-\d+\.png|apple-touch-icon\.png|login\.html|login\.js|style\.css)$/;
function serveStatic(req, res, p) {
  const name = p === '/' ? 'index.html' : p.slice(1);
  if (!/^[A-Za-z0-9._-]+$/.test(name) || name.startsWith('.')) return send(res, 404, 'Nicht gefunden');
  const file = path.join(PUBLIC_DIR, name);
  let st;
  try { st = fs.statSync(file); } catch (e) { return send(res, 404, 'Nicht gefunden'); }
  if (!st.isFile()) return send(res, 404, 'Nicht gefunden');
  const etag = 'W/"' + st.size + '-' + Math.round(st.mtimeMs) + '"';
  const headers = Object.assign({ ETag: etag, 'Cache-Control': 'no-cache' }, SEC);
  if (req.headers['if-none-match'] === etag) { res.writeHead(304, headers); return res.end(); }
  headers['Content-Type'] = MIME[path.extname(name)] || 'application/octet-stream';
  res.writeHead(200, headers);
  fs.createReadStream(file).pipe(res);
}

/* ---------- Routen ---------- */
async function handle(req, res) {
  const url = new URL(req.url, 'http://localhost');
  const p = url.pathname;
  const ip = req.socket.remoteAddress || '';
  const method = req.method;

  if (p === '/healthz') return send(res, 200, 'ok');
  if ((method === 'GET' || method === 'HEAD') && OPEN_ASSET.test(p)) return serveStatic(req, res, p);

  /* Anmelden und Abmelden brauchen noch keine Sitzung */
  if (p === '/api/login' && method === 'POST') {
    const b = await readBody(req);
    const name = isObj(b) ? String(b.name || '') : '';
    const pw = isObj(b) ? String(b.password || '') : '';
    const key = failKey(ip, name);
    if (blocked(key)) return fail(res, 429, 'Zu viele Fehlversuche. Bitte in einigen Minuten erneut versuchen.');
    const u = findByName(name);
    const good = await verifyPassword(pw, u ? u.hash : DUMMY_HASH);
    if (!u || !good) { noteFail(key); return fail(res, 401, 'Name oder Passwort stimmt nicht.'); }
    fails.delete(key);
    return json(res, 200, { name: u.name, role: u.role }, { 'Set-Cookie': cookieFor(makeToken(u), req, SESSION_DAYS * 86400) });
  }
  if (p === '/api/logout' && method === 'POST') {
    return json(res, 200, { ok: true }, { 'Set-Cookie': cookieFor('', req, 0) });
  }

  const session = sessionOf(req);
  if (!session) {
    if (p.startsWith('/api/')) return fail(res, 401, 'Bitte anmelden.');
    if (method !== 'GET' && method !== 'HEAD') return send(res, 405, 'Nicht erlaubt');
    return send(res, 302, '', 'text/plain; charset=utf-8', { Location: 'login.html', 'Cache-Control': 'no-store' });
  }
  const me = session.user;
  const canWrite = me.role !== 'viewer';
  const isAdmin = me.role === 'admin';

  if (!p.startsWith('/api/')) {
    if (method !== 'GET' && method !== 'HEAD') return send(res, 405, 'Nicht erlaubt');
    return serveStatic(req, res, p);
  }

  /* ----- eigenes Konto ----- */
  if (p === '/api/me' && method === 'GET') {
    const extra = {};
    if (session.exp - Date.now() < (SESSION_DAYS - 30) * DAY) extra['Set-Cookie'] = cookieFor(makeToken(me), req, SESSION_DAYS * 86400);
    return json(res, 200, { id: me.id, name: me.name, role: me.role }, extra);
  }
  if (p === '/api/me/password' && method === 'POST') {
    const b = await readBody(req);
    if (!isObj(b)) return fail(res, 400, 'Ungültige Anfrage.');
    if (!(await verifyPassword(String(b.current || ''), me.hash))) return fail(res, 403, 'Das aktuelle Passwort stimmt nicht.');
    const err = checkPassword(b.password);
    if (err) return fail(res, 400, err);
    me.hash = await hashPassword(b.password);
    me.tv++; // meldet alle anderen Geräte dieses Kontos ab
    saveUsers();
    return json(res, 200, { ok: true }, { 'Set-Cookie': cookieFor(makeToken(me), req, SESSION_DAYS * 86400) });
  }

  /* ----- Benutzerverwaltung (nur Admin) ----- */
  if (p === '/api/users' || p.startsWith('/api/users/')) {
    if (!isAdmin) return fail(res, 403, 'Dafür fehlt die Berechtigung.');
    if (p === '/api/users' && method === 'GET') return json(res, 200, { users: users.map(publicUser) });
    if (p === '/api/users' && method === 'POST') {
      const b = await readBody(req);
      if (!isObj(b)) return fail(res, 400, 'Ungültige Anfrage.');
      const nameErr = checkName(b.name) || checkPassword(b.password);
      if (nameErr) return fail(res, 400, nameErr);
      if (!ROLES.includes(b.role)) return fail(res, 400, 'Unbekannte Rolle.');
      if (findByName(b.name)) return fail(res, 400, 'Diesen Namen gibt es schon.');
      const u = { id: newUserId(), name: b.name.trim(), role: b.role, hash: await hashPassword(b.password), tv: 1, created: Date.now() };
      users.push(u);
      saveUsers();
      return json(res, 201, publicUser(u));
    }
    const m = p.match(/^\/api\/users\/([^/]+)$/);
    if (m && UID_RE.test(m[1])) {
      const target = users.find((u) => u.id === m[1]);
      if (!target) return fail(res, 404, 'Benutzer nicht gefunden.');
      if (method === 'DELETE') {
        if (target.id === me.id) return fail(res, 400, 'Du kannst dich nicht selbst entfernen.');
        if (target.role === 'admin' && adminCount() <= 1) return fail(res, 400, 'Es muss mindestens ein Admin übrig bleiben.');
        users = users.filter((u) => u.id !== target.id);
        saveUsers();
        return send(res, 204, '');
      }
      if (method === 'PUT') {
        const b = await readBody(req);
        if (!isObj(b)) return fail(res, 400, 'Ungültige Anfrage.');
        if (b.role !== undefined) {
          if (!ROLES.includes(b.role)) return fail(res, 400, 'Unbekannte Rolle.');
          if (target.role === 'admin' && b.role !== 'admin' && adminCount() <= 1) return fail(res, 400, 'Es muss mindestens ein Admin übrig bleiben.');
          target.role = b.role;
        }
        if (b.password !== undefined) {
          if (target.id === me.id) return fail(res, 400, 'Dein eigenes Passwort änderst du unter „Mein Passwort“.');
          const err = checkPassword(b.password);
          if (err) return fail(res, 400, err);
          target.hash = await hashPassword(b.password);
          target.tv++;
        }
        saveUsers();
        return send(res, 204, '');
      }
    }
    return fail(res, 404, 'Nicht gefunden.');
  }

  /* ----- Babys ----- */
  const publicBaby = (id) => {
    const b = state.babies[id], st = b.settings.baby || {};
    let last = 0;
    for (const k of Object.keys(b.events)) { const e = b.events[k]; if (e.type !== 'wachstum' && e.type !== 'gewicht' && e.ts > last) last = e.ts; }
    return { id, name: st.name || '', birth: st.birth || '', events: Object.keys(b.events).length, last };
  };
  if (p === '/api/babies' && method === 'GET') {
    return json(res, 200, { first: state.order[0], babies: state.order.map(publicBaby) });
  }
  if (p === '/api/babies' && method === 'POST') {
    if (!isAdmin) return fail(res, 403, 'Dafür fehlt die Berechtigung.');
    const b = await readBody(req);
    const name = isObj(b) && typeof b.name === 'string' ? b.name.trim().slice(0, 40) : '';
    if (!name) return fail(res, 400, 'Bitte einen Namen angeben.');
    if (state.order.length >= MAX_BABIES) return fail(res, 400, 'Es sind höchstens ' + MAX_BABIES + ' Babys möglich.');
    const id = 'b' + crypto.randomBytes(4).toString('hex');
    state.babies[id] = { events: {}, settings: { baby: cleanSettings({ name }) } };
    state.order.push(id);
    touch();
    return json(res, 201, publicBaby(id));
  }
  const bm = p.match(/^\/api\/babies\/([a-z0-9]{1,12})(\/import)?$/);
  if (bm) {
    if (!isAdmin) return fail(res, 403, 'Dafür fehlt die Berechtigung.');
    const id = bm[1];
    if (!state.babies[id]) return fail(res, 404, 'Dieses Baby gibt es nicht.');
    if (!bm[2] && method === 'DELETE') {
      if (id === state.order[0]) return fail(res, 400, 'Das erste Baby lässt sich nicht entfernen.');
      delete state.babies[id];
      state.order = state.order.filter((x) => x !== id);
      touch();
      return send(res, 204, '');
    }
    if (bm[2] && method === 'POST') {
      const b = await readBody(req, MAX_IMPORT);
      if (!isObj(b) || !Array.isArray(b.events)) return fail(res, 400, 'Die Datei enthält keine Einträge.');
      if (b.events.length > 20000) return fail(res, 400, 'Zu viele Einträge in einer Datei.');
      const t = state.babies[id];
      const keyOf = (e) => [e.type, e.ts, e.ml, e.min, e.g, e.len, e.head, e.diaper, e.amount, e.side, e.kind, e.c, e.name, e.dose].join('|');
      const have = new Set(Object.values(t.events).map(keyOf));
      let added = 0, duplicates = 0, invalid = 0;
      for (const r of b.events) {
        const ev = cleanEvent(r);
        if (!ev) { invalid++; continue; }
        const k = keyOf(ev);
        if (have.has(k)) { duplicates++; continue; }
        have.add(k);
        ev.by = 'Import';
        t.events[newId()] = ev;
        added++;
      }
      if (isObj(b.settings)) {
        const st = cleanSettings(Object.assign({}, t.settings.baby || {}, b.settings));
        if (st) t.settings.baby = st;
      }
      touch();
      return json(res, 200, { added, duplicates, invalid });
    }
    return fail(res, 405, 'Nicht erlaubt.');
  }

  /* ----- Einträge und Einstellungen eines Babys ----- */
  let bb = null;
  if (p === '/api/events' || p.startsWith('/api/events/') || p === '/api/settings/baby') {
    const id = url.searchParams.get('baby') || state.order[0];
    if (!BABY_RE.test(id) || !state.babies[id]) return fail(res, 404, 'Dieses Baby gibt es nicht.');
    bb = state.babies[id];
  }

  /* ----- Einträge ----- */
  if (p === '/api/events' && method === 'GET') {
    const from = Number(url.searchParams.get('from')) || 0;
    const t = url.searchParams.get('types');
    const types = t ? new Set(t.split(',')) : null;
    const docs = [];
    for (const id of Object.keys(bb.events)) {
      const e = bb.events[id];
      if (from && e.ts < from) continue;
      if (types && !types.has(e.type)) continue;
      docs.push({ id, data: e });
    }
    return jsonRev(req, res, { rev: state.rev, docs });
  }
  if (p === '/api/events' && method === 'POST') {
    if (!canWrite) return fail(res, 403, 'Dein Zugang ist nur zum Ansehen.');
    const ev = cleanEvent(await readBody(req));
    if (!ev) return fail(res, 400, 'Ungültiger Eintrag.');
    ev.by = me.name;
    const id = newId();
    bb.events[id] = ev;
    touch();
    return json(res, 201, { id });
  }
  const em = p.match(/^\/api\/events\/([^/]+)$/);
  if (em) {
    if (!ID_RE.test(em[1])) return fail(res, 400, 'Ungültige ID.');
    if (!canWrite) return fail(res, 403, 'Dein Zugang ist nur zum Ansehen.');
    if (method === 'DELETE') {
      if (bb.events[em[1]]) { delete bb.events[em[1]]; touch(); }
      return send(res, 204, '');
    }
    if (method === 'PUT') {
      const ev = cleanEvent(await readBody(req));
      if (!ev) return fail(res, 400, 'Ungültiger Eintrag.');
      const prev = bb.events[em[1]];
      ev.by = (prev && prev.by) || me.name;
      bb.events[em[1]] = ev;
      touch();
      return send(res, 204, '');
    }
    return fail(res, 405, 'Nicht erlaubt.');
  }

  /* ----- Einstellungen zum Baby ----- */
  if (p === '/api/settings/baby') {
    if (method === 'GET') {
      const d = bb.settings.baby;
      return jsonRev(req, res, { rev: state.rev, exists: !!d, data: d || null });
    }
    if (method === 'PUT') {
      if (!canWrite) return fail(res, 403, 'Dein Zugang ist nur zum Ansehen.');
      const s = cleanSettings(await readBody(req));
      if (!s) return fail(res, 400, 'Ungültige Einstellungen.');
      bb.settings.baby = s;
      touch();
      return send(res, 204, '');
    }
    return fail(res, 405, 'Nicht erlaubt.');
  }

  /* ----- Komplette Sicherung der Einträge (nur Admin) ----- */
  if (p === '/api/export.json' && method === 'GET') {
    if (!isAdmin) return fail(res, 403, 'Dafür fehlt die Berechtigung.');
    const day = new Date().toISOString().slice(0, 10);
    return send(res, 200, JSON.stringify(state, null, 1), 'application/json; charset=utf-8',
      { 'Content-Disposition': 'attachment; filename="trinkprotokoll-' + day + '.json"', 'Cache-Control': 'no-store' });
  }
  return fail(res, 404, 'Nicht gefunden.');
}

const server = http.createServer((req, res) => {
  handle(req, res).catch((e) => {
    if (e && e.status) return fail(res, e.status, e.msg);
    console.error(e);
    if (!res.headersSent) fail(res, 500, 'Interner Fehler.'); else res.end();
  });
});

/* ---------- Start ---------- */
async function bootstrap() {
  if (!fs.existsSync(FILE)) flush();
  if (users.length) return;
  let pw = ADMIN_PASSWORD;
  let generated = false;
  if (checkPassword(pw)) { pw = crypto.randomBytes(9).toString('base64url'); generated = true; }
  const name = checkName(ADMIN_USER) ? 'admin' : ADMIN_USER;
  users.push({ id: newUserId(), name, role: 'admin', hash: await hashPassword(pw), tv: 1, created: Date.now() });
  saveUsers();
  console.log('Erster Admin angelegt: ' + name);
  if (generated) {
    console.log('Es war kein gültiges Passwort angegeben (mindestens 8 Zeichen). Erzeugtes Passwort, bitte nach der Anmeldung ändern:');
    console.log('    ' + pw);
  }
}
bootstrap().then(() => {
  backup();
  server.listen(PORT, HOST, () => {
    console.log('Trinkprotokoll läuft auf http://' + (HOST === '0.0.0.0' ? 'localhost' : HOST) + ':' + PORT);
    console.log('Daten: ' + DATA_DIR + ' (' + eventCount() + ' Einträge bei ' + state.order.length + (state.order.length === 1 ? ' Baby, ' : ' Babys, ') + users.length + ' Benutzer)');
  });
});

function shutdown() {
  try { flush(); backup(); } catch (e) { console.error(e.message); }
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 2000).unref();
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
