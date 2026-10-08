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
  assert.match(await res.text(), /Иванов;Пётр/);

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
