'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const GTO = require('../public/norms');
const { open, hashPassword } = require('../db');
const { createApp } = require('../server');

test('разбор и форматирование значений', () => {
  assert.equal(GTO.parseValue('run3000', '12:20'), 740);
  assert.equal(GTO.parseValue('run3000', '12.20'), 740);
  assert.equal(GTO.parseValue('swim50', '0:54'), 54);
  assert.equal(GTO.parseValue('run60', '8,4'), 8.4);
  assert.equal(GTO.parseValue('flex', '+11'), 11);
  assert.equal(GTO.parseValue('flex', '-3'), -3);
  assert.equal(GTO.parseValue('run3000', '12:75'), null);
  assert.equal(GTO.parseValue('pushup', 'abc'), null);
  assert.equal(GTO.formatValue('run3000', 740), '12:20');
  assert.equal(GTO.formatValue('run60', 8), '8,0');
});

test('уровень по испытанию: меньше — лучше и больше — лучше', () => {
  assert.equal(GTO.levelFor(7, 'M', 'run60', 7.9), 3);
  assert.equal(GTO.levelFor(7, 'M', 'run60', 8.4), 2);
  assert.equal(GTO.levelFor(7, 'M', 'run60', 8.9), 1);
  assert.equal(GTO.levelFor(7, 'M', 'run60', 9.0), 0);
  assert.equal(GTO.levelFor(7, 'M', 'pullHigh', 15), 3);
  assert.equal(GTO.levelFor(7, 'M', 'pullHigh', 7), 0);
  assert.equal(GTO.levelFor(7, 'F', 'pullHigh', 20), 0, 'испытания нет у девушек');
});

test('подсчёт знака', () => {
  const gold = { run60: 7.8, run3000: 700, flex: 15, pullHigh: 16, jump: 240, swim50: 45 };
  assert.equal(GTO.badgeFor(7, 'M', gold).badge, 3);
  // одно обязательное провалено — знака нет, сколько бы ни было остальных
  assert.equal(GTO.badgeFor(7, 'M', { ...gold, flex: 0 }).badge, 0);
  // 4 обязательных на золото + 1 по выбору = 5 качеств: только серебро (для золота нужно 6)
  const five = { run60: 7.8, run3000: 700, flex: 15, pullHigh: 16, jump: 240 };
  assert.equal(GTO.badgeFor(7, 'M', five).badge, 2);
  // два испытания одной категории считаются за одно качество
  assert.equal(GTO.badgeFor(7, 'M', { run60: 7.8, run3000: 700, flex: 15, pullHigh: 16, jump: 240, situps: 60 }).badge, 2);
  // только обязательные — знака нет
  assert.equal(GTO.badgeFor(7, 'M', { run60: 7.8, run3000: 700, flex: 15, pullHigh: 16 }).badge, 0);
});

test('нормативы заданы для всех ступеней и монотонны', () => {
  for (const stage of [5, 6, 7, 8, 9]) {
    for (const sex of ['M', 'F']) {
      const n = GTO.normsFor(stage, sex);
      assert.ok(n, `${stage}${sex}`);
      for (const [id, [b, s, g]] of Object.entries(n)) {
        const t = GTO.TEST_BY_ID[id];
        assert.ok(t, id);
        if (t.lower) assert.ok(b >= s && s >= g, `${stage}${sex} ${id}`);
        else assert.ok(b <= s && s <= g, `${stage}${sex} ${id}`);
      }
      for (const c of GTO.CATEGORIES.filter((x) => x.mandatory)) {
        assert.ok(GTO.testsFor(stage, sex).some((t) => t.cat === c.id), `${stage}${sex} нет ${c.id}`);
      }
    }
  }
});

// ---------- API ----------
async function startServer() {
  const db = open(':memory:');
  for (const [login, role] of [['admin', 'admin'], ['ed', 'editor'], ['teacher', 'viewer']]) {
    db.prepare('INSERT INTO users (login, name, role, pass_hash) VALUES (?, ?, ?, ?)').run(login, login, role, hashPassword('password123'));
  }
  const server = http.createServer(createApp({ db }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  return { server, base };
}

async function login(base, user) {
  const res = await fetch(base + '/api/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login: user, password: 'password123' }),
  });
  assert.equal(res.status, 200);
  const cookie = res.headers.get('set-cookie').split(';')[0];
  return (method, path, body) => fetch(base + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'gto', Cookie: cookie },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

test('API: роли и ввод результатов', async (t) => {
  const { server, base } = await startServer();
  t.after(() => server.close());

  assert.equal((await fetch(base + '/api/data')).status, 401, 'без входа данных нет');
  const bad = await fetch(base + '/api/login', { method: 'POST', body: JSON.stringify({ login: 'ed', password: 'nope' }) });
  assert.equal(bad.status, 401);

  const ed = await login(base, 'ed');
  const viewer = await login(base, 'teacher');

  let res = await ed('POST', '/api/students', { last_name: 'Иванов', first_name: 'Пётр', sex: 'M', stage: 7, institute: 'ИЕН', grp: 'Б-21' });
  assert.equal(res.status, 201);
  const st = await res.json();

  res = await ed('PUT', '/api/results', { student_id: st.id, test_id: 'run60', value: '8,1', test_date: '2026-09-15' });
  assert.equal(res.status, 200);
  assert.equal((await res.json()).value, 8.1);

  res = await ed('PUT', '/api/results', { student_id: st.id, test_id: 'pullLow', value: '20' });
  assert.equal(res.status, 400, 'испытания нет в ступени юношей');
  res = await ed('PUT', '/api/results', { student_id: st.id, test_id: 'run60', value: '8,1', test_date: '2999-01-01' });
  assert.equal(res.status, 400, 'дата из будущего');

  // учитель видит, но не может менять
  res = await viewer('GET', '/api/data');
  const data = await res.json();
  assert.equal(data.students.length, 1);
  assert.equal(data.results[0].test_date, '2026-09-15');
  assert.equal((await viewer('PUT', '/api/results', { student_id: st.id, test_id: 'run60', value: '7' })).status, 403);
  assert.equal((await viewer('POST', '/api/students', { last_name: 'Х', first_name: 'У', sex: 'M', stage: 7 })).status, 403);
  assert.equal((await viewer('DELETE', `/api/students/${st.id}`)).status, 403);
  assert.equal((await viewer('GET', '/api/users')).status, 403);
  assert.equal((await ed('GET', '/api/users')).status, 403, 'управлять пользователями может только админ');

  // экспорт доступен всем вошедшим
  res = await viewer('GET', '/api/export.csv');
  assert.equal(res.status, 200);
  assert.match(await res.text(), /Иванов;П\.;/, "учитель видит фамилию и первую букву имени");

  // импорт
  res = await ed('POST', '/api/students/import', { rows: [
    { last_name: 'Петрова', first_name: 'Анна', sex: 'Ж', stage: 6, institute: 'ИЕН', grp: 'Б-22' },
    { last_name: 'Сидоров', first_name: 'Олег', sex: 'М', stage: 8 },
  ] });
  assert.equal((await res.json()).imported, 2);
  res = await ed('POST', '/api/students/import', { rows: [{ last_name: 'Без', first_name: 'Пола', stage: 6 }] });
  assert.equal(res.status, 400);

  // без заголовка X-Requested-With изменения отклоняются (CSRF)
  const cookieOnly = await fetch(base + '/api/login', { method: 'POST', body: JSON.stringify({ login: 'ed', password: 'password123' }) });
  const c = cookieOnly.headers.get('set-cookie').split(';')[0];
  res = await fetch(base + `/api/students/${st.id}`, { method: 'DELETE', headers: { Cookie: c } });
  assert.equal(res.status, 403);

  // смена ступени удаляет неподходящие результаты
  await ed('PUT', '/api/results', { student_id: st.id, test_id: 'pullHigh', value: '12' });
  res = await ed('PUT', `/api/students/${st.id}`, { last_name: 'Иванова', first_name: 'Петра', sex: 'F', stage: 7 });
  assert.equal(res.status, 200);
  const after = await (await ed('GET', '/api/data')).json();
  assert.deepEqual(after.results.filter((r) => r.student_id === st.id).map((r) => r.test_id), ['run60']);
});

test('API: администратор управляет пользователями', async (t) => {
  const { server, base } = await startServer();
  t.after(() => server.close());
  const admin = await login(base, 'admin');
  let res = await admin('POST', '/api/users', { login: 'fizruk', name: 'Учитель', role: 'viewer', password: 'secret-pass' });
  assert.equal(res.status, 201);
  const { id } = await res.json();
  res = await fetch(base + '/api/login', { method: 'POST', body: JSON.stringify({ login: 'fizruk', password: 'secret-pass' }) });
  assert.equal(res.status, 200);
  await admin('PUT', `/api/users/${id}`, { active: false });
  res = await fetch(base + '/api/login', { method: 'POST', body: JSON.stringify({ login: 'fizruk', password: 'secret-pass' }) });
  assert.equal(res.status, 401, 'заблокированный не входит');
  const me = await (await admin('GET', '/api/me')).json();
  assert.equal((await admin('PUT', `/api/users/${me.id}`, { role: 'viewer' })).status, 400, 'нельзя разжаловать себя');
});

test('УИН, даты, ступень по возрасту', () => {
  assert.equal(GTO.normalizeUin('23-65-0012345'), '23-65-0012345');
  assert.equal(GTO.normalizeUin('23650012345'), '23-65-0012345');
  assert.equal(GTO.normalizeUin(''), '');
  assert.equal(GTO.normalizeUin('23-65-12'), null);
  assert.equal(GTO.parseDate('05.03.2006'), '2006-03-05');
  assert.equal(GTO.parseDate('2006-03-05'), '2006-03-05');
  assert.equal(GTO.parseDate('38781'), '2006-03-05', 'серийная дата Excel');
  assert.equal(GTO.parseDate('31.02.2006'), null);
  assert.equal(GTO.ageOn('2006-10-09', '2026-10-08'), 19);
  assert.equal(GTO.ageOn('2006-10-08', '2026-10-08'), 20);
  assert.equal(GTO.stageForAge(19), 7);
  assert.equal(GTO.stageForAge(20), 8);
  assert.equal(GTO.stageForAge(30), null);
});

test('шаблон .xlsx читается обратно', () => {
  const { buildTemplate, readFirstSheet, zip } = require('../xlsx');
  const rows = readFirstSheet(buildTemplate());
  assert.equal(rows.length, 1);
  assert.match(rows[0][0], /Фамилия/);
  assert.match(rows[0][5], /УИН/);
  // заполненный файл с sharedStrings и числовой датой, как сохраняет Excel
  const book = zip({
    'xl/workbook.xml': '<workbook xmlns:r="r"><sheets><sheet name="A" sheetId="1" r:id="rId1"/></sheets></workbook>',
    'xl/_rels/workbook.xml.rels': '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
    'xl/sharedStrings.xml': '<sst><si><t>Фамилия</t></si><si><t>Ёлкина</t></si><si><r><t>Ан</t></r><r><t>на</t></r></si></sst>',
    'xl/worksheets/sheet1.xml': '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row>' +
      '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c><c r="D2"><v>38781</v></c></row></sheetData></worksheet>',
  });
  assert.deepEqual(readFirstSheet(book), [['Фамилия'], ['Ёлкина', 'Анна', '', '38781']]);
});

test('API: УИН, дата рождения, маскировка для просмотра, загрузка списка', async (t) => {
  const { server, base } = await startServer();
  t.after(() => server.close());
  const ed = await login(base, 'ed');
  const viewer = await login(base, 'teacher');
  const admin = await login(base, 'admin');

  // ступень по дате рождения
  let res = await ed('POST', '/api/students', { last_name: 'Ёлкина', first_name: 'Анна', middle_name: 'Сергеевна', sex: 'Ж',
    birth_date: '05.03.2006', uin: '23650012345', institute: 'ИЕН', grp: 'Б-21' });
  assert.equal(res.status, 201);
  const st = await res.json();
  assert.equal(st.uin, '23-65-0012345');
  assert.equal(st.birth_date, '2006-03-05');
  assert.equal(st.stage, GTO.stageForAge(GTO.ageOn('2006-03-05', new Date().toISOString().slice(0, 10))));

  res = await ed('POST', '/api/students', { last_name: 'Дубль', first_name: 'УИН', sex: 'М', stage: 7, uin: '23-65-0012345' });
  assert.equal(res.status, 409, 'УИН уникален');
  res = await ed('POST', '/api/students', { last_name: 'Х', first_name: 'У', sex: 'М', uin: '123' });
  assert.equal(res.status, 400);

  // просмотр: фамилия и первая буква имени, без УИН и даты рождения
  const v = (await (await viewer('GET', '/api/data')).json()).students[0];
  assert.equal(v.last_name, 'Ёлкина');
  assert.equal(v.first_name, 'А.');
  assert.equal(v.middle_name, '');
  assert.equal(v.uin, '');
  assert.equal(v.birth_date, '');
  const a = (await (await admin('GET', '/api/data')).json()).students[0];
  assert.equal(a.first_name, 'Анна');
  assert.equal(a.uin, '23-65-0012345');
  const csv = await (await viewer('GET', '/api/export.csv')).text();
  assert.ok(!csv.includes('Анна') && !csv.includes('0012345') && !csv.includes('Сергеевна'), 'в выгрузке для просмотра нет полных данных');
  assert.match(await (await admin('GET', '/api/export.csv')).text(), /23-65-0012345;Ёлкина;Анна;Сергеевна;05\.03\.2006/);

  // шаблон доступен и учителю
  res = await viewer('GET', '/api/template.xlsx');
  assert.equal(res.status, 200);
  assert.equal(Buffer.from(await res.arrayBuffer()).readUInt32LE(0), 0x04034b50);
  assert.equal((await viewer('POST', '/api/import/parse', { text: 'x' })).status, 403);

  // разбор списка по заголовкам: существующий (по УИН) → обновление, ошибки построчно
  const text = 'Группа;Фамилия;Имя;Пол;Дата рождения;УИН;Институт\n' +
    'Б-22;Ёлкина;Анна;Ж;05.03.2006;23-65-0012345;ИЕН\n' +
    'Б-22;Новиков;Олег;М;01.09.2007;;ИЕН\n' +
    'Б-22;Старый;Дед;М;01.01.1980;;ИЕН\n';
  const parsed = (await (await ed('POST', '/api/import/parse', { text })).json()).rows;
  assert.equal(parsed[0].action, 'update');
  assert.equal(parsed[1].action, 'create');
  assert.match(parsed[2].error, /Возраст/);
  res = await ed('POST', '/api/students/import', { rows: parsed.filter((r) => !r.error) });
  assert.deepEqual(await res.json(), { imported: 2, created: 1, updated: 1 });
  const all = (await (await admin('GET', '/api/data')).json()).students;
  assert.equal(all.length, 2);
  assert.equal(all.find((s) => s.last_name === 'Ёлкина').grp, 'Б-22', 'группа обновилась');

  // повторная загрузка того же списка ничего не задваивает (совпадение по ФИО + дате рождения)
  res = await ed('POST', '/api/students/import', { rows: parsed.filter((r) => !r.error) });
  assert.deepEqual(await res.json(), { imported: 2, created: 0, updated: 2 });
});

test('за nginx блокировка подбора пароля — по настоящему IP, а не для всех', async (t) => {
  const db = open(':memory:');
  db.prepare('INSERT INTO users (login, name, role, pass_hash) VALUES (?, ?, ?, ?)').run('ed', 'ed', 'editor', hashPassword('password123'));
  const server = http.createServer(createApp({ db, trustProxy: true }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${server.address().port}`;
  const tryLogin = (ip, password) => fetch(base + '/api/login', {
    method: 'POST', headers: { 'X-Real-IP': ip }, body: JSON.stringify({ login: 'ed', password }),
  });
  for (let i = 0; i < 10; i++) await tryLogin('10.0.0.1', 'wrong');
  assert.equal((await tryLogin('10.0.0.1', 'password123')).status, 429, 'злоумышленник заблокирован');
  assert.equal((await tryLogin('10.0.0.2', 'password123')).status, 200, 'остальные входят');
});

test('за nginx: cookie Secure только по https, при обязательном https вход по http отклоняется', async (t) => {
  const mk = async (secureCookie) => {
    const db = open(':memory:');
    db.prepare('INSERT INTO users (login, name, role, pass_hash) VALUES (?, ?, ?, ?)').run('ed', 'ed', 'editor', hashPassword('password123'));
    const server = http.createServer(createApp({ db, trustProxy: true, secureCookie }));
    await new Promise((r) => server.listen(0, '127.0.0.1', r));
    t.after(() => server.close());
    const base = `http://127.0.0.1:${server.address().port}`;
    return (proto) => fetch(base + '/api/login', {
      method: 'POST', headers: { 'X-Forwarded-Proto': proto }, body: JSON.stringify({ login: 'ed', password: 'password123' }),
    });
  };
  const relaxed = await mk(false);
  let res = await relaxed('http');
  assert.equal(res.status, 200);
  assert.ok(!/Secure/.test(res.headers.get('set-cookie')), 'по http без Secure');
  res = await relaxed('https');
  assert.match(res.headers.get('set-cookie'), /Secure/);
  const strict = await mk(true);
  res = await strict('http');
  assert.equal(res.status, 400);
  assert.match((await res.json()).error, /https:\/\//);
  assert.equal((await strict('https')).status, 200);
});

test('подбор пароля к одной учётке не блокирует другие, даже если все адреса одинаковые', async (t) => {
  const db = open(':memory:');
  for (const l of ['ed', 'admin']) db.prepare('INSERT INTO users (login, name, role, pass_hash) VALUES (?, ?, ?, ?)').run(l, l, 'editor', hashPassword('password123'));
  const server = http.createServer(createApp({ db }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${server.address().port}`;
  const tryLogin = (login, password) => fetch(base + '/api/login', { method: 'POST', body: JSON.stringify({ login, password }) });
  for (let i = 0; i < 10; i++) await tryLogin('admin', 'wrong');
  assert.equal((await tryLogin('admin', 'password123')).status, 429);
  assert.equal((await tryLogin('ed', 'password123')).status, 200);
});

test('API обновления: только админ, ставится только вершина ветки, заявка кладётся в папку', async (t) => {
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const { makeUpdater } = require('../update');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gto-upd-'));
  const appDir = fs.mkdtempSync(path.join(os.tmpdir(), 'gto-app-'));
  t.after(() => { fs.rmSync(dir, { recursive: true, force: true }); fs.rmSync(appDir, { recursive: true, force: true }); });
  const OLD = 'a'.repeat(40);
  const HEAD = 'b'.repeat(40);
  fs.writeFileSync(path.join(appDir, 'VERSION.json'), JSON.stringify({ sha: OLD, installed_at: '2026-10-01T10:00:00Z' }));
  const commit = (sha, msg) => ({ sha, commit: { message: msg + '\n\nподробности', committer: { date: '2026-10-09T01:00:00Z' } } });
  const fakeFetch = async (url) => ({
    ok: true,
    json: async () => (url.includes('/compare/')
      ? { commits: [commit('c'.repeat(40), 'Первое изменение'), commit(HEAD, 'Второе изменение')],
          files: [{ filename: 'gto/server.js' }, { filename: 'timing-hub/hub/hub.py' }] }
      : url.includes('commits?')
        ? [commit(HEAD, 'Второе изменение'), commit('c'.repeat(40), 'Первое изменение'), commit('d'.repeat(40), 'Старое')]
        : commit(HEAD, 'Второе изменение')),
  });
  const updater = makeUpdater({ dir, appDir, fetchImpl: fakeFetch });

  const db = open(':memory:');
  for (const [l, r] of [['admin', 'admin'], ['ed', 'editor']]) db.prepare('INSERT INTO users (login, name, role, pass_hash) VALUES (?, ?, ?, ?)').run(l, l, r, hashPassword('password123'));
  const server = http.createServer(createApp({ db, updater }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${server.address().port}`;
  const admin = await login(base, 'admin');
  const ed = await login(base, 'ed');

  assert.equal((await ed('GET', '/api/update/check')).status, 403, 'редактор не обновляет');
  assert.equal((await ed('POST', '/api/update/install', { sha: HEAD })).status, 403);

  const st = await (await admin('GET', '/api/update/status')).json();
  assert.equal(st.enabled, true);
  assert.equal(st.current.sha, OLD);

  const chk = await (await admin('GET', '/api/update/check')).json();
  assert.equal(chk.upToDate, false);
  assert.equal(chk.latest.sha, HEAD);
  assert.deepEqual(chk.changes.map((c) => c.message), ['Второе изменение', 'Первое изменение'], 'новые сверху, только первая строка');

  let res = await admin('POST', '/api/update/install', { sha: 'c'.repeat(40) });
  assert.equal(res.status, 409, 'не вершина ветки — отказ');
  assert.ok(!fs.existsSync(path.join(dir, 'request')));

  res = await admin('POST', '/api/update/install', { sha: HEAD });
  assert.equal(res.status, 202);
  assert.equal(fs.readFileSync(path.join(dir, 'request'), 'utf8').trim(), HEAD);
  assert.equal((await admin('POST', '/api/update/install', { sha: HEAD })).status, 409, 'повторная заявка, пока идёт обновление');

  // на вершине ветки менялся только сервер хронометража (timing-hub/) — ГТО обновлять нечего
  const OTHER = 'e'.repeat(40);
  const onlyHub = async (url) => ({
    ok: true,
    json: async () => (url.includes('/compare/')
      ? { commits: [commit(OTHER, 'SakhStart 2.1')], files: [{ filename: 'timing-hub/hub/hub.py' }] }
      : url.includes('commits?') ? [commit(OLD, 'ГТО: прежняя версия')] : commit(OTHER, 'SakhStart 2.1')),
  });
  const appDir2 = fs.mkdtempSync(path.join(os.tmpdir(), 'gto-app-'));
  t.after(() => fs.rmSync(appDir2, { recursive: true, force: true }));
  fs.writeFileSync(path.join(appDir2, 'VERSION.json'), JSON.stringify({ sha: OLD, installed_at: '2026-10-01T10:00:00Z' }));
  const chk2 = await makeUpdater({ dir, appDir: appDir2, fetchImpl: onlyHub }).check();
  assert.equal(chk2.upToDate, true, 'изменения SakhStart не считаются обновлением ГТО');
  assert.deepEqual(chk2.changes, []);

  // без папки заявок (сервер не настроен) — кнопка честно говорит об этом
  const off = makeUpdater({ dir: '', appDir, fetchImpl: fakeFetch });
  assert.equal(off.status().enabled, false);
  await assert.rejects(off.install(HEAD), /не настроено/);
});
