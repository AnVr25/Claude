'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { open, hashPassword, verifyPassword } = require('./db');
const GTO = require('./public/norms');
const { buildTemplate, readFirstSheet } = require('./xlsx');
const { makeUpdater } = require('./update');

const PUBLIC_DIR = path.join(__dirname, 'public');
const SESSION_DAYS = 30;
const COOKIE = 'gto_session';
const MAX_BODY = 12 * 1024 * 1024; // xlsx приходит в base64
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

function createApp({
  db = open(),
  secureCookie = process.env.GTO_SECURE_COOKIE === '1',
  trustProxy = process.env.GTO_TRUST_PROXY === '1',
  updater = makeUpdater(),
} = {}) {
  const loginAttempts = new Map(); // «ip|логин» -> {count, until}

  // За nginx все запросы приходят с 127.0.0.1 — настоящий адрес в X-Real-IP (ставит наш nginx).
  function clientIp(req) {
    if (trustProxy && req.headers['x-real-ip']) return String(req.headers['x-real-ip']);
    return req.socket.remoteAddress || '';
  }

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

  // Пришёл ли запрос по HTTPS. За nginx это видно по X-Forwarded-Proto.
  function isHttps(req) {
    if (trustProxy) return String(req.headers['x-forwarded-proto'] || '').split(',')[0].trim() === 'https';
    return secureCookie;
  }

  // Флаг Secure ставим только для HTTPS: по http браузер такой cookie выбросил бы и вход «не держался».
  function sessionCookie(req, token, maxAge) {
    return `${COOKIE}=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${isHttps(req) ? '; Secure' : ''}`;
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

  function parseSex(v) {
    const x = String(v ?? '').trim().toLowerCase();
    if (/^(f|ж|жен\S*|д|дев\S*)$/.test(x)) return 'F';
    if (/^(m|м|муж\S*|ю|юн\S*)$/.test(x)) return 'M';
    return '';
  }
  const ROMAN_STAGE = { v: 5, vi: 6, vii: 7, viii: 8, ix: 9 };

  function cleanStudent(b) {
    const s = {
      last_name: str(b.last_name, 80),
      first_name: str(b.first_name, 80),
      middle_name: str(b.middle_name, 80),
      sex: parseSex(b.sex),
      birth_date: GTO.parseDate(str(b.birth_date, 20)),
      uin: GTO.normalizeUin(str(b.uin, 30)),
      stage: ROMAN_STAGE[str(b.stage, 5).toLowerCase()] || Number(str(b.stage, 5) || 0),
      institute: str(b.institute, 160),
      grp: str(b.grp, 60),
    };
    if (!s.last_name || !s.first_name) throw new HttpError(400, 'Укажите фамилию и имя');
    if (!s.sex) throw new HttpError(400, 'Укажите пол (М или Ж)');
    if (s.birth_date === null) throw new HttpError(400, 'Дата рождения — в формате ДД.ММ.ГГГГ');
    if (s.birth_date && (s.birth_date > today() || s.birth_date < '1940-01-01')) throw new HttpError(400, 'Некорректная дата рождения');
    if (s.uin === null) throw new HttpError(400, 'УИН — 11 цифр в формате ГГ-РР-ННННННН, например 23-65-0012345');
    if (!s.stage && s.birth_date) {
      const age = GTO.ageOn(s.birth_date, today());
      s.stage = GTO.stageForAge(age);
      if (!s.stage) throw new HttpError(400, `Возраст ${age} лет не подходит для ступеней V–IX (14–29 лет)`);
    }
    if (!(s.stage >= 5 && s.stage <= 9)) throw new HttpError(400, 'Укажите ступень (5–9) или дату рождения');
    return s;
  }

  function checkUinFree(uin, exceptId = 0) {
    if (uin && db.prepare('SELECT 1 FROM students WHERE uin = ? AND id <> ?').get(uin, exceptId)) {
      throw new HttpError(409, `УИН ${uin} уже есть у другого студента`);
    }
  }

  // Студент для ответа: роль «Просмотр» видит только фамилию и первую букву имени.
  function present(user, s) {
    if (user.role !== 'viewer') return s;
    return {
      id: s.id, last_name: s.last_name, first_name: s.first_name ? s.first_name[0] + '.' : '', middle_name: '',
      sex: s.sex, stage: s.stage, institute: s.institute, grp: s.grp, birth_date: '', uin: '',
    };
  }

  // Таблица (массив строк) → объекты студентов. Колонки ищем по заголовкам, иначе — порядок шаблона.
  const HEADER_MAP = [
    [/^фио|ф\.и\.о/, 'fio'], [/фамил/, 'last_name'], [/^имя/, 'first_name'], [/отчеств/, 'middle_name'],
    [/рожд|^дата/, 'birth_date'], [/^пол/, 'sex'], [/уин|uin/, 'uin'], [/инстит|факульт|вуз|учебн/, 'institute'],
    [/групп/, 'grp'], [/ступен/, 'stage'],
  ];
  const DEFAULT_ORDER = ['last_name', 'first_name', 'middle_name', 'birth_date', 'sex', 'uin', 'institute', 'grp', 'stage'];

  function tableToRows(table) {
    table = table.filter((r) => r.some((c) => String(c).trim()));
    if (!table.length) return [];
    let fields = table[0].map((h) => {
      const x = String(h).trim().toLowerCase();
      const hit = HEADER_MAP.find(([re]) => re.test(x));
      return hit ? hit[1] : null;
    });
    if (fields.filter(Boolean).length >= 2) table = table.slice(1);
    else fields = DEFAULT_ORDER;
    return table.map((r) => {
      const o = {};
      fields.forEach((f, i) => { if (f && r[i] != null && o[f] === undefined) o[f] = String(r[i]).trim(); });
      if (o.fio) {
        const p = o.fio.split(/\s+/);
        o.last_name = o.last_name || p[0] || '';
        o.first_name = o.first_name || p[1] || '';
        o.middle_name = o.middle_name || p.slice(2).join(' ');
        delete o.fio;
      }
      return o;
    });
  }

  function parseCsvText(text) {
    const lines = String(text).replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim());
    if (!lines.length) return [];
    const sep = lines[0].includes('\t') ? '\t' : lines[0].includes(';') ? ';' : ',';
    return lines.map((l) => l.split(sep).map((c) => c.trim().replace(/^"(.*)"$/, '$1').replace(/""/g, '"')));
  }

  // Найти существующего студента: по УИН, иначе по ФИО + дате рождения.
  function findExisting(s) {
    if (s.uin) {
      const byUin = db.prepare('SELECT id FROM students WHERE uin = ?').get(s.uin);
      if (byUin) return byUin.id;
    }
    if (s.birth_date) {
      // SQLite lower() не понимает кириллицу — сравниваем в JS.
      const key = (x) => [x.last_name, x.first_name, x.middle_name].join(' ').toLowerCase().replace(/ё/g, 'е');
      const r = db.prepare('SELECT id, last_name, first_name, middle_name FROM students WHERE birth_date = ?')
        .all(s.birth_date).find((x) => key(x) === key(s));
      if (r) return r.id;
    }
    return null;
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
      if (secureCookie && !isHttps(req)) {
        throw new HttpError(400, `Вход только по защищённому адресу: https://${str(req.headers.host, 100)}`);
      }
      const b = await readBody(req);
      // Ключ — адрес + логин: если прокси (например, OpenVPN port-share) скрывает адреса,
      // подбор пароля к одной учётке не блокирует вход остальным.
      const key = clientIp(req) + '|' + str(b.login, 80).toLowerCase();
      const att = loginAttempts.get(key);
      if (att && att.count >= 10 && att.until > Date.now()) {
        throw new HttpError(429, 'Слишком много попыток. Подождите 15 минут.');
      }
      const u = db.prepare('SELECT * FROM users WHERE login = ? AND active = 1').get(str(b.login, 80));
      if (!u || !verifyPassword(String(b.password || ''), u.pass_hash)) {
        const a = att && att.until > Date.now() ? att : { count: 0, until: Date.now() + 15 * 60e3 };
        a.count++;
        loginAttempts.set(key, a);
        throw new HttpError(401, 'Неверный логин или пароль');
      }
      loginAttempts.delete(key);
      db.prepare("UPDATE users SET last_login = datetime('now') WHERE id = ?").run(u.id);
      const token = crypto.randomBytes(32).toString('hex');
      db.prepare('DELETE FROM sessions WHERE expires_at < ?').run(Date.now());
      db.prepare('INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)')
        .run(sha256(token), u.id, Date.now() + SESSION_DAYS * 864e5);
      return send(res, 200, { id: u.id, login: u.login, name: u.name, role: u.role },
        { 'Set-Cookie': sessionCookie(req, token, SESSION_DAYS * 86400) });
    }

    if (method === 'POST' && p === '/api/logout') {
      const token = parseCookies(req)[COOKIE];
      if (token) db.prepare('DELETE FROM sessions WHERE token_hash = ?').run(sha256(token));
      return send(res, 200, { ok: true }, { 'Set-Cookie': sessionCookie(req, '', 0) });
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
      const students = db.prepare('SELECT * FROM students ORDER BY last_name, first_name, middle_name').all()
        .map((s) => present(user, s));
      const results = db.prepare(`
        SELECT r.student_id, r.test_id, r.value, r.test_date, r.entered_at, u.name AS entered_by_name, u.login AS entered_by_login
        FROM results r LEFT JOIN users u ON u.id = r.entered_by
      `).all();
      return send(res, 200, { students, results });
    }

    if (method === 'GET' && p === '/api/export.csv') {
      return sendCsv(res, user);
    }

    if (method === 'GET' && p === '/api/template.xlsx') {
      res.writeHead(200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': `attachment; filename="gto-shablon-spiska.xlsx"; filename*=UTF-8''${encodeURIComponent('ГТО — шаблон списка студентов.xlsx')}`,
        'Cache-Control': 'no-store',
      });
      return res.end(buildTemplate());
    }

    // --- студенты (admin, editor) ---
    if (method === 'POST' && p === '/api/students') {
      requireRole(user, 'admin', 'editor');
      const s = cleanStudent(await readBody(req));
      checkUinFree(s.uin);
      const r = db.prepare(`INSERT INTO students (last_name, first_name, middle_name, sex, birth_date, uin, stage, institute, grp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`)
        .run(s.last_name, s.first_name, s.middle_name, s.sex, s.birth_date, s.uin, s.stage, s.institute, s.grp);
      audit(user, 'student.create', { id: Number(r.lastInsertRowid), ...s });
      return send(res, 201, getStudent(r.lastInsertRowid));
    }

    // Разбор файла/текста списка: возвращает строки и ошибки по каждой, ничего не сохраняет.
    if (method === 'POST' && p === '/api/import/parse') {
      requireRole(user, 'admin', 'editor');
      const b = await readBody(req);
      let table;
      try {
        table = b.xlsx ? readFirstSheet(Buffer.from(String(b.xlsx), 'base64')) : parseCsvText(b.text || '');
      } catch (e) { throw new HttpError(400, e.message || 'Не удалось прочитать файл'); }
      const rows = tableToRows(table);
      if (rows.length > 5000) throw new HttpError(400, 'Не больше 5000 строк за раз');
      const seenUin = new Set();
      const out = rows.map((row) => {
        try {
          const s = cleanStudent(row);
          if (s.uin && seenUin.has(s.uin)) throw new HttpError(400, `УИН ${s.uin} повторяется в списке`);
          if (s.uin) seenUin.add(s.uin);
          const existing = findExisting(s);
          if (s.uin) checkUinFree(s.uin, existing || 0);
          return { ...s, action: existing ? 'update' : 'create' };
        } catch (e) { return { ...row, error: e.message }; }
      });
      return send(res, 200, { rows: out });
    }

    // Загрузка: новые добавляются, существующие (по УИН или ФИО + дате рождения) обновляются.
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
      const seen = new Map();
      clean.forEach((s, i) => {
        if (!s.uin) return;
        if (seen.has(s.uin)) errors.push({ row: i + 1, error: `УИН ${s.uin} повторяется (строка ${seen.get(s.uin)})` });
        else seen.set(s.uin, i + 1);
      });
      if (errors.length) return send(res, 400, { error: 'Есть ошибки в строках', errors });
      const ins = db.prepare(`INSERT INTO students (last_name, first_name, middle_name, sex, birth_date, uin, stage, institute, grp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`);
      const upd = db.prepare(`UPDATE students SET last_name=?, first_name=?, middle_name=?, sex=?, birth_date=?,
        uin=CASE WHEN ? <> '' THEN ? ELSE uin END, stage=?, institute=?, grp=?, updated_at=datetime('now') WHERE id=?`);
      let created = 0;
      let updated = 0;
      db.exec('BEGIN');
      try {
        clean.forEach((s, i) => {
          try {
            const id = findExisting(s);
            if (s.uin) checkUinFree(s.uin, id || 0);
            if (id) {
              upd.run(s.last_name, s.first_name, s.middle_name, s.sex, s.birth_date, s.uin, s.uin, s.stage, s.institute, s.grp, id);
              updated++;
            } else {
              ins.run(s.last_name, s.first_name, s.middle_name, s.sex, s.birth_date, s.uin, s.stage, s.institute, s.grp);
              created++;
            }
          } catch (e) { e.row = i + 1; throw e; }
        });
        db.exec('COMMIT');
      } catch (e) {
        db.exec('ROLLBACK');
        if (e instanceof HttpError) return send(res, e.status, { error: e.message, errors: [{ row: e.row, error: e.message }] });
        throw e;
      }
      audit(user, 'student.import', { created, updated });
      return send(res, 200, { imported: created + updated, created, updated });
    }

    // Массовое удаление (только администратор): выбранные или все найденные по фильтру.
    if (method === 'POST' && p === '/api/students/delete') {
      requireRole(user, 'admin');
      const b = await readBody(req);
      const ids = [...new Set((Array.isArray(b.ids) ? b.ids : []).map(Number).filter((x) => Number.isInteger(x) && x > 0))];
      if (!ids.length) throw new HttpError(400, 'Никто не выбран');
      if (ids.length > 20000) throw new HttpError(400, 'Слишком много за раз');
      const get = db.prepare('SELECT id, last_name, first_name, middle_name, birth_date, uin FROM students WHERE id = ?');
      const del = db.prepare('DELETE FROM students WHERE id = ?');
      const gone = [];
      db.exec('BEGIN');
      try {
        for (const id of ids) {
          const st = get.get(id);
          if (!st) continue;
          del.run(id);
          gone.push(st);
        }
        db.exec('COMMIT');
      } catch (e) { db.exec('ROLLBACK'); throw e; }
      audit(user, 'student.delete_bulk', { count: gone.length, students: gone });
      return send(res, 200, { deleted: gone.length });
    }

    if ((m = p.match(/^\/api\/students\/(\d+)$/))) {
      requireRole(user, 'admin', 'editor');
      const old = getStudent(m[1]);
      if (method === 'PUT') {
        const s = cleanStudent(await readBody(req));
        checkUinFree(s.uin, old.id);
        db.prepare(`UPDATE students SET last_name=?, first_name=?, middle_name=?, sex=?, birth_date=?, uin=?, stage=?, institute=?, grp=?,
          updated_at=datetime('now') WHERE id=?`)
          .run(s.last_name, s.first_name, s.middle_name, s.sex, s.birth_date, s.uin, s.stage, s.institute, s.grp, old.id);
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

    // --- обновление приложения (admin) ---
    if (p === '/api/update/status' && method === 'GET') {
      requireRole(user, 'admin');
      return send(res, 200, updater.status());
    }
    if (p === '/api/update/check' && method === 'GET') {
      requireRole(user, 'admin');
      try { return send(res, 200, await updater.check()); } catch (e) { throw new HttpError(502, `Не удалось проверить обновления: ${e.message}`); }
    }
    if (p === '/api/update/install' && method === 'POST') {
      requireRole(user, 'admin');
      const b = await readBody(req);
      try {
        const r = await updater.install(str(b.sha, 40));
        audit(user, 'app.update', { sha: r.sha });
        return send(res, 202, r);
      } catch (e) { throw new HttpError(409, e.message); }
    }

    // --- пользователи (admin) ---
    if (p === '/api/users' && method === 'GET') {
      requireRole(user, 'admin');
      return send(res, 200, db.prepare('SELECT id, login, name, role, note, active, created_at, last_login FROM users ORDER BY active DESC, role, login').all());
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
      const r = db.prepare('INSERT INTO users (login, name, role, note, pass_hash) VALUES (?, ?, ?, ?, ?)')
        .run(login, str(b.name, 120), role, str(b.note, 200), hashPassword(b.password));
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
        if (b.note !== undefined) db.prepare('UPDATE users SET note = ? WHERE id = ?').run(str(b.note, 200), target.id);
        if (b.active !== undefined) {
          db.prepare('UPDATE users SET active = ? WHERE id = ?').run(b.active ? 1 : 0, target.id);
          if (!b.active) db.prepare('DELETE FROM sessions WHERE user_id = ?').run(target.id);
        }
        if (b.password) {
          if (String(b.password).length < 8) throw new HttpError(400, 'Пароль — минимум 8 символов');
          db.prepare('UPDATE users SET pass_hash = ? WHERE id = ?').run(hashPassword(b.password), target.id);
          db.prepare('DELETE FROM sessions WHERE user_id = ?').run(target.id);
        }
        audit(user, 'user.update', { id: target.id, role: b.role, active: b.active, note: b.note, password: !!b.password });
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

  function sendCsv(res, user) {
    const full = user.role !== 'viewer';
    const students = db.prepare('SELECT * FROM students ORDER BY institute, grp, last_name, first_name').all()
      .map((s) => present(user, s));
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
    const head = [...(full ? ['УИН', 'Фамилия', 'Имя', 'Отчество', 'Дата рождения'] : ['Фамилия', 'Имя']), 'Пол', 'Ступень', 'Институт', 'Группа',
      ...GTO.TESTS.flatMap((x) => [x.short, x.short + ' (дата)']), 'Знак'];
    const lines = [head.map(esc).join(';')];
    for (const s of students) {
      const rs = byStudent.get(s.id) || {};
      const values = Object.fromEntries(Object.entries(rs).map(([k, r]) => [k, r.value]));
      const badge = GTO.badgeFor(s.stage, s.sex, values).badge;
      lines.push([
        ...(full ? [s.uin, s.last_name, s.first_name, s.middle_name, s.birth_date ? s.birth_date.split('-').reverse().join('.') : '']
          : [s.last_name, s.first_name]),
        s.sex === 'M' ? 'М' : 'Ж', s.stage, s.institute, s.grp,
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
