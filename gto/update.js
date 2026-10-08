'use strict';
// Обновление приложения кнопкой из интерфейса администратора.
//
// Приложение само ничего не устанавливает: оно только кладёт заявку (хеш коммита) в общую папку.
// Её подхватывает отдельный сервис gto-update (systemd .path), который скачивает эту версию
// с GitHub, прогоняет тесты, подменяет код и перезапускает приложение, а при сбое возвращает
// прежнюю версию. Ставится только текущая вершина официальной ветки — подсунуть свой код нельзя.
const fs = require('node:fs');
const path = require('node:path');

function makeUpdater({
  dir = process.env.GTO_UPDATE_DIR || '',
  repo = process.env.GTO_UPDATE_REPO || 'AnVr25/Claude',
  branch = process.env.GTO_UPDATE_BRANCH || 'claude/greeting-d2g8ji',
  appDir = __dirname,
  fetchImpl = globalThis.fetch,
} = {}) {
  const readJson = (file) => {
    try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
  };

  function current() {
    return readJson(path.join(appDir, 'VERSION.json')) || { sha: '', installed_at: '' };
  }

  function enabled() {
    if (!dir) return false;
    try { fs.accessSync(dir, fs.constants.W_OK); return true; } catch { return false; }
  }

  function status() {
    return {
      enabled: enabled(),
      current: current(),
      job: enabled() ? readJson(path.join(dir, 'status.json')) : null,
      pending: enabled() && fs.existsSync(path.join(dir, 'request')),
    };
  }

  async function github(url) {
    const res = await fetchImpl(`https://api.github.com/repos/${repo}/${url}`, {
      headers: { 'User-Agent': 'fla65-gto-updater', Accept: 'application/vnd.github+json' },
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) throw new Error(`GitHub ответил ${res.status}`);
    return res.json();
  }

  const commitInfo = (c) => ({
    sha: c.sha,
    date: c.commit?.committer?.date || c.commit?.author?.date || '',
    message: String(c.commit?.message || '').split('\n')[0],
  });

  async function latest() {
    return commitInfo(await github(`commits/${encodeURIComponent(branch)}`));
  }

  // Что изменилось между установленной версией и вершиной ветки.
  async function check() {
    const head = await latest();
    const cur = current();
    let changes = [];
    if (cur.sha && cur.sha !== head.sha) {
      try {
        const cmp = await github(`compare/${cur.sha}...${head.sha}`);
        changes = (cmp.commits || []).map(commitInfo).reverse();
      } catch { changes = [head]; }
    } else if (!cur.sha) {
      changes = [head];
    }
    return { latest: head, current: cur, upToDate: cur.sha === head.sha, changes };
  }

  // Заявка на установку: только вершина ветки, проверяем по GitHub ещё раз.
  async function install(sha) {
    if (!enabled()) throw new Error('Обновление из интерфейса не настроено на сервере — запустите install.sh ещё раз');
    if (!/^[0-9a-f]{40}$/.test(String(sha))) throw new Error('Некорректная версия');
    const head = await latest();
    if (head.sha !== sha) throw new Error('Вышла более новая версия — нажмите «Проверить» ещё раз');
    const job = readJson(path.join(dir, 'status.json'));
    if (fs.existsSync(path.join(dir, 'request')) || (job && job.state === 'running')) {
      throw new Error('Обновление уже выполняется');
    }
    fs.writeFileSync(path.join(dir, 'status.json'), JSON.stringify({ state: 'queued', message: 'Заявка принята', sha, at: new Date().toISOString() }));
    fs.writeFileSync(path.join(dir, 'request'), sha + '\n');
    return { queued: true, sha };
  }

  return { status, check, install, current };
}

module.exports = { makeUpdater };
