'use strict';
const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');

const DB_PATH = process.env.GTO_DB || path.join(__dirname, 'data', 'gto.sqlite');

function open(file = DB_PATH) {
  if (file !== ':memory:') fs.mkdirSync(path.dirname(file), { recursive: true });
  const db = new DatabaseSync(file);
  db.exec(`
    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS users (
      id         INTEGER PRIMARY KEY,
      login      TEXT NOT NULL UNIQUE COLLATE NOCASE,
      name       TEXT NOT NULL DEFAULT '',
      role       TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
      pass_hash  TEXT NOT NULL,
      active     INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sessions (
      token_hash TEXT PRIMARY KEY,
      user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      expires_at INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS students (
      id          INTEGER PRIMARY KEY,
      last_name   TEXT NOT NULL,
      first_name  TEXT NOT NULL,
      middle_name TEXT NOT NULL DEFAULT '',
      sex         TEXT NOT NULL CHECK (sex IN ('M', 'F')),
      stage       INTEGER NOT NULL CHECK (stage BETWEEN 5 AND 9),
      institute   TEXT NOT NULL DEFAULT '',
      grp         TEXT NOT NULL DEFAULT '',
      created_at  TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS results (
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      test_id    TEXT NOT NULL,
      value      REAL NOT NULL,
      test_date  TEXT NOT NULL,
      entered_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
      entered_at TEXT NOT NULL DEFAULT (datetime('now')),
      PRIMARY KEY (student_id, test_id)
    );

    CREATE TABLE IF NOT EXISTS audit (
      id         INTEGER PRIMARY KEY,
      at         TEXT NOT NULL DEFAULT (datetime('now')),
      user_id    INTEGER,
      action     TEXT NOT NULL,
      details    TEXT NOT NULL
    );
  `);
  // Миграции для баз, созданных до появления полей.
  const cols = new Set(db.prepare('PRAGMA table_info(students)').all().map((c) => c.name));
  if (!cols.has('birth_date')) db.exec("ALTER TABLE students ADD COLUMN birth_date TEXT NOT NULL DEFAULT ''");
  if (!cols.has('uin')) db.exec("ALTER TABLE students ADD COLUMN uin TEXT NOT NULL DEFAULT ''");
  db.exec("CREATE UNIQUE INDEX IF NOT EXISTS students_uin ON students(uin) WHERE uin <> ''");
  return db;
}

function hashPassword(password) {
  const salt = crypto.randomBytes(16);
  const hash = crypto.scryptSync(String(password), salt, 64);
  return `scrypt$${salt.toString('hex')}$${hash.toString('hex')}`;
}

function verifyPassword(password, stored) {
  const [scheme, saltHex, hashHex] = String(stored).split('$');
  if (scheme !== 'scrypt' || !saltHex || !hashHex) return false;
  const expected = Buffer.from(hashHex, 'hex');
  const actual = crypto.scryptSync(String(password), Buffer.from(saltHex, 'hex'), expected.length);
  return crypto.timingSafeEqual(expected, actual);
}

module.exports = { open, hashPassword, verifyPassword, DB_PATH };
