'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { open, hashPassword, verifyPassword } = require('./db');
const GTO = require('./public/norms');

const PUBLIC_DIR = path.join(__dirname, 'public');
const SESSION_DAYS = 30;
const COOKIE = 'gto_session';
const MAX_BODY = 2 * 1024 * 1024;
const ROLES = ['admin', 'editor', 'viewer'];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const sha256 = (s) => crypto.createHash('sha256').update(s).digest('hex');
const today = () => new Date().toISOString().slice(0, 10);
const str = (v, max = 200) => String(v ?? '').trim().slice(0, max);

function createApp({ db = open(), secureCookie = process.env.GTO_SECURE_COOKIE === '1' } = {}) {
  const loginAttempts = new Map(); // ip -> {count, until}

  // ---------- helpers ----------
  function send(res, status, body, headers = {}) {
    const isJson = typeof body !== 'string' && !Buffer.isBuffer(body);
    res.writeHead(status, {
      'Content-Type': isJson ? 'application/json; charset=utf-8' : 'text/plain; charset=utf-8',
      'Cache-Control': 'no-store',
      ...headers,
    });
    res.end(isJson ? JSON.stringify(body) : body);
  }

  function readBody(req) {
    return new Promise((resolve, reject) => {
      let size = 0;
      const chunks = [];
      req.on('data', (c) => {
        size += c.length;
        if (size > MAX_BODY) { reject(new HttpError(413, 'Слишком большой запрос')); req.destroy(); return; }
        chunks.push(c);
      });
      req.on('end', () => {
        if (!chunks.length) return resolve({});
        try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
        catch { reject(new HttpError(400, 'Некорректный JSON')); }
      });
      req.on('error', reject);
    });
  }

  function parseCookies(req) {
    const out = {};
    for (const part of String(req.headers.cookie || '').split(';')) {
      const i = part.indexOf('=');
      if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
    }
    return out;
  }

  function sessionCookie(token, maxAge) {
    return `${COOKIE}=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${secureCookie ? '; Secure' : ''}`;
  }

  function currentUser(req) {
    const token = parseCookies(req)[COOKIE];
    if (!token) return null;
    const row = db.prepare(`
      SELECT u.id, u.login, u.name, u.role FROM sessions s
      JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1
    `).get(sha256(token), Date.now());
    return row || null;
  }

  function requireRole(user, ...roles) {
    if (!user) throw new HttpError(401, 'Нужно войти');
    if (!roles.includes(user.role)) throw new HttpError(403, 'Недостаточно прав');
  }

  function audit(user, action, details) {
    db.prepare('INSERT INTO audit (user_id, action, details) VALUES (?, ?, ?)')
      .run(user ? user.id : null, action, JSON.stringify(details));
  }

  function validDate(d) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(d))) return false;
    const dt = new Date(d + 'T00:00:00Z');
    return !Number.isNaN(dt.getTime()) && dt.toISOString().slice(0, 10) === d;
  }

  function cleanStudent(b) {
    const s = {
      last_name: str(b.last_name, 80),
      first_name: str(b.first_name, 80),
      middle_name: str(b.middle_name, 80),
      sex: b.sex === 'F' || b.sex === 'Ж' || b.sex === 'ж' ? 'F' : (b.sex === 'M' || b.sex === 'М' || b.sex === 'м' ? 'M' : ''),
      stage: Number(b.stage),
      institute: str(b.institute, 160),
      grp: str(b.grp, 60),
    };
    if (!s.last_name || !s.first_name) throw new HttpError(400, 'Укажите фамилию и имя');
    if (!s.sex) throw new HttpError(400, 'Укажите пол (М или Ж)');
    if (!(s.stage >= 5 && s.stage <= 9)) throw new HttpError(400, 'Ступень должна быть от 5 до 9');
    return s;
  }

  function getStudent(id) {
    const s = db.prepare('SELECT * FROM students WHERE id = ?').get(Number(id));
    if (!s) throw new HttpError(404, 'Студент не найден');
    return s;
  }

  // ---------- routes ----------
  async function api(req, res, url) {
    const method = req.method;
    const p = url.pathname;
    let m;

    if (method === 'POST' && p === '/api/login') {
      const ip = req.socket.remoteAddress || '';
      const att = loginAttempts.get(ip);
      if (att && att.count >= 10 && att.until > Date.now()) {
        throw new HttpError(429, 'Слишком много попыток. Подождите 15 минут.');
      }
      const b = await readBody(req);
      const u = db.prepare('SELECT * FROM users WHERE login = ? AND active = 1').get(str(b.login, 80));
      if (!u || !verifyPassword(String(b.password || ''), u.pass_hash)) {
        const a = att && att.until > Date.now() ? att : { count: 0, until: Date.now() + 15 * 60e3 };
        a.count++;
        loginAttempts.set(ip, a);
        throw new HttpError(401, 'Неверный логин или пароль');
      }
      loginAttempts.delete(ip);
      const token = crypto.randomBytes(32).toString('hex');
      db.prepare('DELETE FROM sessions WHERE expires_at < ?').run(Date.now());
      db.prepare('INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)')
        .run(sha256(token), u.id, Date.now() + SESSION_DAYS * 864e5);
      return send(res, 200, { id: u.id, login: u.login, name: u.name, role: u.role },
        { 'Set-Cookie': sessionCookie(token, SESSION_DAYS * 86400) });
    }

    if (method === 'POST' && p === '/api/logout') {
      const token = parseCookies(req)[COOKIE];
      if (token) db.prepare('DELETE FROM sessions WHERE token_hash = ?').run(sha256(token));
      return send(res, 200, { ok: true }, { 'Set-Cookie': sessionCookie('', 0) });
    }

    const user = currentUser(req);
    if (!user) throw new HttpError(401, 'Нужно войти');

    // Защита от CSRF: все изменяющие запросы — только из нашего JS.
    if (method !== 'GET' && req.headers['x-requested-with'] !== 'gto') {
      throw new HttpError(403, 'Запрос отклонён');
    }

    if (method === 'GET' && p === '/api/me') return send(res, 200, user);

    if (method === 'POST' && p === '/api/me/password') {
      const b = await readBody(req);
      const u = db.prepare('SELECT pass_hash FROM users WHERE id = ?').get(user.id);
      if (!verifyPassword(String(b.old || ''), u.pass_hash)) throw new HttpError(400, 'Текущий пароль неверный');
      if (String(b.new || '').length < 8) throw new HttpError(400, 'Новый пароль — минимум 8 символов');
      db.prepare('UPDATE users SET pass_hash = ? WHERE id = ?').run(hashPassword(b.new), user.id);
      audit(user, 'password.change', { user_id: user.id });
      return send(res, 200, { ok: true });
    }

    if (method === 'GET' && p === '/api/data') {
      const students = db.prepare('SELECT * FROM students ORDER BY last_name, first_name, middle_name').all();
      const results = db.prepare(`
        SELECT r.student_id, r.test_id, r.value, r.test_date, r.entered_at, u.name AS entered_by_name, u.login AS entered_by_login
        FROM results r LEFT JOIN users u ON u.id = r.entered_by
      `).all();
      return send(res, 200, { students, results });
    }

    if (method === 'GET' && p === '/api/export.csv') {
      return sendCsv(res);
    }

    // --- студенты (admin, editor) ---
    if (method === 'POST' && p === '/api/students') {
      requireRole(user, 'admin', 'editor');
      const s = cleanStudent(await readBody(req));
      const r = db.prepare(`INSERT INTO students (last_name, first_name, middle_name, sex, stage, institute, grp)
        VALUES (?, ?, ?, ?, ?, ?, ?)`).run(s.last_name, s.first_name, s.middle_name, s.sex, s.stage, s.institute, s.grp);
      audit(user, 'student.create', { id: Number(r.lastInsertRowid), ...s });
      return send(res, 201, getStudent(r.lastInsertRowid));
    }

    if (method === 'POST' && p === '/api/students/import') {
      requireRole(user, 'admin', 'editor');
      const b = await readBody(req);
      const rows = Array.isArray(b.rows) ? b.rows : [];
      if (!rows.length) throw new HttpError(400, 'Нет строк для импорта');
      if (rows.length > 5000) throw new HttpError(400, 'Не больше 5000 строк за раз');
      const errors = [];
      const clean = [];
      rows.forEach((row, i) => {
        try { clean.push(cleanStudent(row)); } catch (e) { errors.push({ row: i + 1, error: e.message }); }
      });
      if (errors.length) return send(res, 400, { error: 'Есть ошибки в строках', errors });
      const ins = db.prepare(`INSERT INTO students (last_name, first_name, middle_name, sex, stage, institute, grp)
        VALUES (?, ?, ?, ?, ?, ?, ?)`);
      db.exec('BEGIN');
      try {
        for (const s of clean) ins.run(s.last_name, s.first_name, s.middle_name, s.sex, s.stage, s.institute, s.grp);
        db.exec('COMMIT');
      } catch (e) { db.exec('ROLLBACK'); throw e; }
      audit(user, 'student.import', { count: clean.length });
      return send(res, 200, { imported: clean.length });
    }

    if ((m = p.match(/^\/api\/students\/(\d+)$/))) {
      requireRole(user, 'admin', 'editor');
      const old = getStudent(m[1]);
      if (method === 'PUT') {
        const s = cleanStudent(await readBody(req));
        db.prepare(`UPDATE students SET last_name=?, first_name=?, middle_name=?, sex=?, stage=?, institute=?, grp=?,
          updated_at=datetime('now') WHERE id=?`)
          .run(s.last_name, s.first_name, s.middle_name, s.sex, s.stage, s.institute, s.grp, old.id);
        // Результаты испытаний, которых нет в новой ступени/поле, удаляем.
        const allowed = new Set(GTO.testsFor(s.stage, s.sex).map((x) => x.id));
        for (const r of db.prepare('SELECT test_id FROM results WHERE student_id = ?').all(old.id)) {
          if (!allowed.has(r.test_id)) db.prepare('DELETE FROM results WHERE student_id = ? AND test_id = ?').run(old.id, r.test_id);
        }
        audit(user, 'student.update', { id: old.id, before: old, after: s });
        return send(res, 200, getStudent(old.id));
      }
      if (method === 'DELETE') {
        db.prepare('DELETE FROM students WHERE id = ?').run(old.id);
        audit(user, 'student.delete', old);
        return send(res, 200, { ok: true });
      }
    }

    // --- результаты (admin, editor) ---
    if (method === 'PUT' && p === '/api/results') {
      requireRole(user, 'admin', 'editor');
      const b = await readBody(req);
      const st = getStudent(b.student_id);
      const testId = str(b.test_id, 40);
      if (!GTO.normsFor(st.stage, st.sex)?.[testId]) throw new HttpError(400, 'Это испытание не входит в ступень студента');
      const value = GTO.parseValue(testId, b.value);
      if (value == null) throw new HttpError(400, `Не понял результат «${str(b.value, 20)}». Формат: ${GTO.TEST_BY_ID[testId].unit}`);
      const date = str(b.test_date || today(), 10);
      if (!validDate(date)) throw new HttpError(400, 'Некорректная дата испытания');
      if (date > today()) throw new HttpError(400, 'Дата испытания не может быть в будущем');
      db.prepare(`INSERT INTO results (student_id, test_id, value, test_date, entered_by, entered_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT (student_id, test_id) DO UPDATE SET value=excluded.value, test_date=excluded.test_date,
          entered_by=excluded.entered_by, entered_at=excluded.entered_at`)
        .run(st.id, testId, value, date, user.id);
      audit(user, 'result.set', { student_id: st.id, test_id: testId, value, date });
      const row = db.prepare(`SELECT r.student_id, r.test_id, r.value, r.test_date, r.entered_at, u.name AS entered_by_name, u.login AS entered_by_login
        FROM results r LEFT JOIN users u ON u.id = r.entered_by WHERE r.student_id = ? AND r.test_id = ?`).get(st.id, testId);
      return send(res, 200, row);
    }

    if (method === 'DELETE' && (m = p.match(/^\/api\/results\/(\d+)\/([A-Za-z0-9]+)$/))) {
      requireRole(user, 'admin', 'editor');
      db.prepare('DELETE FROM results WHERE student_id = ? AND test_id = ?').run(Number(m[1]), m[2]);
      audit(user, 'result.delete', { student_id: Number(m[1]), test_id: m[2] });
      return send(res, 200, { ok: true });
    }

    // --- пользователи (admin) ---
    if (p === '/api/users' && method === 'GET') {
      requireRole(user, 'admin');
      return send(res, 200, db.prepare('SELECT id, login, name, role, active, created_at FROM users ORDER BY role, login').all());
    }

    if (p === '/api/users' && method === 'POST') {
      requireRole(user, 'admin');
      const b = await readBody(req);
      const login = str(b.login, 80);
      const role = ROLES.includes(b.role) ? b.role : null;
      if (!/^[A-Za-z0-9._@-]{3,80}$/.test(login)) throw new HttpError(400, 'Логин: 3+ символа, латиница, цифры, . _ - @');
      if (!role) throw new HttpError(400, 'Неизвестная роль');
      if (String(b.password || '').length < 8) throw new HttpError(400, 'Пароль — минимум 8 символов');
      if (db.prepare('SELECT 1 FROM users WHERE login = ?').get(login)) throw new HttpError(409, 'Такой логин уже есть');
      const r = db.prepare('INSERT INTO users (login, name, role, pass_hash) VALUES (?, ?, ?, ?)')
        .run(login, str(b.name, 120), role, hashPassword(b.password));
      audit(user, 'user.create', { id: Number(r.lastInsertRowid), login, role });
      return send(res, 201, { id: Number(r.lastInsertRowid) });
    }

    if ((m = p.match(/^\/api\/users\/(\d+)$/))) {
      requireRole(user, 'admin');
      const target = db.prepare('SELECT * FROM users WHERE id = ?').get(Number(m[1]));
      if (!target) throw new HttpError(404, 'Пользователь не найден');
      if (method === 'PUT') {
        const b = await readBody(req);
        if (target.id === user.id && (b.role && b.role !== 'admin' || b.active === false)) {
          throw new HttpError(400, 'Нельзя снять права администратора или заблокировать самого себя');
        }
        if (b.role !== undefined) {
          if (!ROLES.includes(b.role)) throw new HttpError(400, 'Неизвестная роль');
          db.prepare('UPDATE users SET role = ? WHERE id = ?').run(b.role, target.id);
        }
        if (b.name !== undefined) db.prepare('UPDATE users SET name = ? WHERE id = ?').run(str(b.name, 120), target.id);
        if (b.active !== undefined) {
          db.prepare('UPDATE users SET active = ? WHERE id = ?').run(b.active ? 1 : 0, target.id);
          if (!b.active) db.prepare('DELETE FROM sessions WHERE user_id = ?').run(target.id);
        }
        if (b.password) {
          if (String(b.password).length < 8) throw new HttpError(400, 'Пароль — минимум 8 символов');
          db.prepare('UPDATE users SET pass_hash = ? WHERE id = ?').run(hashPassword(b.password), target.id);
          db.prepare('DELETE FROM sessions WHERE user_id = ?').run(target.id);
        }
        audit(user, 'user.update', { id: target.id, role: b.role, active: b.active, password: !!b.password });
        return send(res, 200, { ok: true });
      }
      if (method === 'DELETE') {
        if (target.id === user.id) throw new HttpError(400, 'Нельзя удалить самого себя');
        db.prepare('DELETE FROM users WHERE id = ?').run(target.id);
        audit(user, 'user.delete', { id: target.id, login: target.login });
        return send(res, 200, { ok: true });
      }
    }

    throw new HttpError(404, 'Не найдено');
  }

  function sendCsv(res) {
    const students = db.prepare('SELECT * FROM students ORDER BY institute, grp, last_name, first_name').all();
    const results = db.prepare('SELECT * FROM results').all();
    const byStudent = new Map();
    for (const r of results) {
      if (!byStudent.has(r.student_id)) byStudent.set(r.student_id, {});
      byStudent.get(r.student_id)[r.test_id] = r;
    }
    const esc = (v) => {
      const s = String(v ?? '');
      return /[";\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const head = ['Фамилия', 'Имя', 'Отчество', 'Пол', 'Ступень', 'Институт', 'Группа',
      ...GTO.TESTS.flatMap((x) => [x.short, x.short + ' (дата)']), 'Знак'];
    const lines = [head.map(esc).join(';')];
    for (const s of students) {
      const rs = byStudent.get(s.id) || {};
      const values = Object.fromEntries(Object.entries(rs).map(([k, r]) => [k, r.value]));
      const badge = GTO.badgeFor(s.stage, s.sex, values).badge;
      lines.push([
        s.last_name, s.first_name, s.middle_name, s.sex === 'M' ? 'М' : 'Ж', s.stage, s.institute, s.grp,
        ...GTO.TESTS.flatMap((x) => rs[x.id] ? [GTO.formatValue(x.id, rs[x.id].value), rs[x.id].test_date] : ['', '']),
        badge ? GTO.LEVEL_NAMES[GTO.LEVELS[badge - 1]] : '',
      ].map(esc).join(';'));
    }
    // BOM, чтобы Excel открыл кириллицу корректно
    res.writeHead(200, {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="gto-${today()}.csv"`,
      'Cache-Control': 'no-store',
    });
    res.end('﻿' + lines.join('\r\n'));
  }

  function serveStatic(req, res, url) {
    let rel = decodeURIComponent(url.pathname);
    if (rel === '/' || !path.extname(rel)) rel = '/index.html';
    const file = path.normalize(path.join(PUBLIC_DIR, rel));
    if (!file.startsWith(PUBLIC_DIR + path.sep)) return send(res, 403, 'Forbidden');
    fs.readFile(file, (err, buf) => {
      if (err) return send(res, 404, 'Not found');
      res.writeHead(200, {
        'Content-Type': MIME[path.extname(file)] || 'application/octet-stream',
        'Cache-Control': 'no-cache',
      });
      res.end(buf);
    });
  }

  return async function handler(req, res) {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'same-origin');
    res.setHeader('Content-Security-Policy',
      "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'none'");
    const url = new URL(req.url, 'http://localhost');
    try {
      if (url.pathname.startsWith('/api/')) await api(req, res, url);
      else if (req.method === 'GET') serveStatic(req, res, url);
      else send(res, 405, 'Method not allowed');
    } catch (e) {
      if (e instanceof HttpError) send(res, e.status, { error: e.message });
      else { console.error(e); send(res, 500, { error: 'Внутренняя ошибка сервера' }); }
    }
  };
}

if (require.main === module) {
  const port = Number(process.env.PORT || 3000);
  const host = process.env.HOST || '127.0.0.1';
  const db = open();
  const count = db.prepare('SELECT COUNT(*) AS n FROM users').get().n;
  if (!count) {
    console.log('Пользователей пока нет. Создайте администратора:');
    console.log('  node cli.js add-user admin admin "Имя Фамилия"');
  }
  http.createServer(createApp({ db })).listen(port, host, () => {
    console.log(`ГТО: http://${host}:${port}`);
  });
}

module.exports = { createApp };
