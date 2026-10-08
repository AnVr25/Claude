'use strict';
// Управление пользователями из консоли сервера.
//   node cli.js add-user <логин> <admin|editor|viewer> ["Имя"]   — создаст пользователя и выведет пароль
//   node cli.js reset-password <логин>                            — выдаст новый пароль
//   node cli.js list-users
const crypto = require('node:crypto');
const { open, hashPassword } = require('./db');

const [cmd, ...args] = process.argv.slice(2);
const db = open();
const genPassword = () => crypto.randomBytes(9).toString('base64url');

function fail(msg) { console.error(msg); process.exit(1); }

if (cmd === 'add-user') {
  const [login, role, name = ''] = args;
  if (!login || !['admin', 'editor', 'viewer'].includes(role)) {
    fail('Использование: node cli.js add-user <логин> <admin|editor|viewer> ["Имя"]');
  }
  if (db.prepare('SELECT 1 FROM users WHERE login = ?').get(login)) fail(`Логин «${login}» уже занят`);
  const password = genPassword();
  db.prepare('INSERT INTO users (login, name, role, pass_hash) VALUES (?, ?, ?, ?)').run(login, name, role, hashPassword(password));
  console.log(`Создан пользователь ${login} (${role}). Пароль: ${password}`);
} else if (cmd === 'reset-password') {
  const [login] = args;
  const u = login && db.prepare('SELECT id FROM users WHERE login = ?').get(login);
  if (!u) fail('Пользователь не найден');
  const password = genPassword();
  db.prepare('UPDATE users SET pass_hash = ?, active = 1 WHERE id = ?').run(hashPassword(password), u.id);
  db.prepare('DELETE FROM sessions WHERE user_id = ?').run(u.id);
  console.log(`Новый пароль для ${login}: ${password}`);
} else if (cmd === 'list-users') {
  for (const u of db.prepare('SELECT login, role, name, active FROM users ORDER BY role, login').all()) {
    console.log(`${u.login}\t${u.role}\t${u.active ? '' : '(заблокирован)'}\t${u.name}`);
  }
} else {
  fail('Команды: add-user, reset-password, list-users');
}
