/* global GTO */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  user: null,
  students: [],
  results: new Map(), // studentId -> { testId: row }
  computed: new Map(), // studentId -> { badge, byCategory }
  filters: { q: '', inst: '', grp: '', stage: '', sex: '', badge: '' },
  selected: new Set(), // выбранные для массового удаления (только администратор)
};

const ROMAN = GTO.ROMAN;
const ROLE_NAMES = { admin: 'Администратор', editor: 'Ввод результатов', viewer: 'Просмотр' };
const BADGE_TEXT = { 3: 'Золото', 2: 'Серебро', 1: 'Бронза' };

// ---------- utils ----------
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const norm = (s) => String(s || '').toLowerCase().replace(/ё/g, 'е').trim();
const fullName = (s) => [s.last_name, s.first_name, s.middle_name].filter(Boolean).join(' ');
const fmtDate = (d) => (d ? d.slice(0, 10).split('-').reverse().join('.') : '');
const fmtDateTime = (d) => {
  if (!d) return '';
  const dt = new Date(d.replace(' ', 'T') + 'Z');
  return dt.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};
const todayISO = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const canEdit = () => state.user && (state.user.role === 'admin' || state.user.role === 'editor');
const isAdmin = () => state.user && state.user.role === 'admin';
// Роль «Просмотр» получает с сервера только фамилию и первую букву имени — без УИН и даты рождения.
const fullAccess = () => state.user && state.user.role !== 'viewer';
const ageText = (bd) => {
  const a = GTO.ageOn(bd, todayISO());
  return a == null ? '' : `${a} ${a % 10 === 1 && a % 100 !== 11 ? 'год' : a % 10 >= 2 && a % 10 <= 4 && (a % 100 < 10 || a % 100 >= 20) ? 'года' : 'лет'}`;
};

function genPassword() {
  const abc = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const a = new Uint32Array(12);
  crypto.getRandomValues(a);
  return [...a].map((x) => abc[x % abc.length]).join('');
}

function toast(msg, ok = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (ok ? ' ok' : '');
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, ok ? 2500 : 5000);
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'gto' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  let data = null;
  try { data = await res.json(); } catch { /* пусто */ }
  if (res.status === 401 && url !== '/api/login') { showLogin(); throw new Error('Сессия истекла, войдите снова'); }
  if (!res.ok) {
    const err = new Error((data && data.error) || `Ошибка ${res.status}`);
    err.data = data;
    throw err;
  }
  return data;
}

// ---------- данные ----------
function recompute(studentId) {
  const s = state.students.find((x) => x.id === studentId);
  if (!s) { state.computed.delete(studentId); return; }
  const rs = state.results.get(studentId) || {};
  state.computed.set(studentId, GTO.badgeWithDate(s.stage, s.sex, rs));
}

async function loadData() {
  const data = await api('GET', '/api/data');
  const coll = new Intl.Collator('ru');
  state.students = data.students.sort((x, y) => coll.compare(fullName(x), fullName(y)));
  state.results = new Map();
  for (const r of data.results) {
    if (!state.results.has(r.student_id)) state.results.set(r.student_id, {});
    state.results.get(r.student_id)[r.test_id] = r;
  }
  state.computed = new Map();
  for (const s of state.students) recompute(s.id);
  fillFilterOptions();
  render();
}

// ---------- фильтры ----------
const FILTER_KEY = 'gto.filters';
function saveFilters() { try { localStorage.setItem(FILTER_KEY, JSON.stringify(state.filters)); } catch { /* нет доступа */ } }
function loadFilters() {
  try { Object.assign(state.filters, JSON.parse(localStorage.getItem(FILTER_KEY) || '{}')); } catch { /* нет доступа */ }
}

function uniqSorted(arr) {
  return [...new Set(arr.filter(Boolean))].sort((a, b) => a.localeCompare(b, 'ru', { numeric: true }));
}

function fillFilterOptions() {
  const f = state.filters;
  const insts = uniqSorted(state.students.map((s) => s.institute));
  if (f.inst && !insts.includes(f.inst)) f.inst = '';
  $('#f-inst').innerHTML = '<option value="">Все институты</option>' +
    insts.map((i) => `<option${i === f.inst ? ' selected' : ''}>${esc(i)}</option>`).join('');
  const grps = uniqSorted(state.students.filter((s) => !f.inst || s.institute === f.inst).map((s) => s.grp));
  if (f.grp && !grps.includes(f.grp)) f.grp = '';
  $('#f-grp').innerHTML = '<option value="">Все группы</option>' +
    grps.map((g) => `<option${g === f.grp ? ' selected' : ''}>${esc(g)}</option>`).join('');
  $('#f-q').value = f.q;
  if ($('#f-stage').options.length < 2) {
    $('#f-stage').insertAdjacentHTML('beforeend', GTO.STAGE_LIST.map((n) => `<option value="${n}">${ROMAN[n]} ступень · ${GTO.STAGES[n].replace(' лет', '')}</option>`).join(''));
  }
  $('#f-stage').value = f.stage;
  $('#f-sex').value = f.sex;
  $('#f-badge').value = f.badge;
}

function filtered() {
  const f = state.filters;
  const words = norm(f.q).split(/\s+/).filter(Boolean);
  return state.students.filter((s) => {
    if (f.inst && s.institute !== f.inst) return false;
    if (f.grp && s.grp !== f.grp) return false;
    if (f.stage && String(s.stage) !== f.stage) return false;
    if (f.sex && s.sex !== f.sex) return false;
    if (f.badge !== '' && String(state.computed.get(s.id)?.badge ?? 0) !== f.badge) return false;
    if (words.length) {
      const hay = norm(fullName(s) + ' ' + s.grp + ' ' + (s.uin || ''));
      if (!words.every((w) => hay.includes(w))) return false;
    }
    return true;
  });
}

// ---------- таблица ----------
function badgeHtml(level, date) {
  return level
    ? `<span class="badge lvl-${level}">${BADGE_TEXT[level]}</span>${date ? `<span class="badge-date" title="Дата выполнения последнего норматива на этот знак">${fmtDate(date)}</span>` : ''}`
    : '<span class="badge none">—</span>';
}

function render() {
  const rows = filtered();
  const total = state.students.length;
  $('#count').innerHTML = total
    ? `Найдено: <strong>${rows.length}</strong> из ${total}`
    : 'Студентов пока нет';

  // колонки — только испытания, которые есть хотя бы у одного найденного студента
  const used = new Set();
  const combos = [...new Set(rows.map((s) => s.stage + s.sex))].map((c) => [Number(c.slice(0, -1)), c.slice(-1)]);
  for (const [st, sx] of combos) for (const t of GTO.testsFor(st, sx)) used.add(t.id);
  // испытания не своей ступени, которые кому-то всё же внесли, тоже показываем
  for (const s of rows) for (const id of Object.keys(state.results.get(s.id) || {})) used.add(id);
  // категория обязательна, если обязательна во всех ступенях на экране
  const mandAll = (cat) => combos.length > 0 && combos.every(([st, sx]) => GTO.mandatoryFor(st, sx).includes(cat));
  const tests = GTO.TESTS.filter((t) => used.has(t.id));

  const empty = $('#empty');
  if (!rows.length) {
    $('#grid').innerHTML = '';
    empty.hidden = false;
    empty.innerHTML = total
      ? 'Никого не нашли. Измените условия поиска.'
      : (canEdit() ? 'Добавьте студентов кнопкой «+ Студент» или через «Загрузить список».' : 'Данные ещё не внесены.');
    return;
  }
  empty.hidden = true;

  // строка категорий
  const groups = [];
  for (const t of tests) {
    const last = groups[groups.length - 1];
    if (last && last.cat === t.cat) last.span++;
    else groups.push({ cat: t.cat, span: 1 });
  }
  const full = fullAccess();
  const sel = isAdmin();
  const allSel = sel && rows.length > 0 && rows.every((s) => state.selected.has(s.id));
  let head = '<thead><tr class="cat-row"><th class="sticky left" rowspan="2">' +
    (sel ? `<span class="name-cell"><input type="checkbox" class="sel-box" id="sel-head" title="Выбрать всех найденных"${allSel ? ' checked' : ''}>ФИО</span>` : 'ФИО') + '</th>' +
    (full ? '<th class="info" rowspan="2">УИН</th><th class="info" rowspan="2">Дата рожд.</th>' : '') +
    '<th class="info left" rowspan="2">Институт</th><th rowspan="2">Группа</th><th rowspan="2">Ступ.</th><th rowspan="2">Знак</th>';
  for (const g of groups) {
    const c = GTO.CAT_BY_ID[g.cat];
    const mand = mandAll(c.id);
    head += `<th colspan="${g.span}" class="${mand ? 'cat-mand' : ''}" title="${esc(c.name)}${mand ? ' — обязательное' : ''}">${esc(shortCat(c))}</th>`;
  }
  head += '</tr><tr class="test-row">';
  for (const t of tests) head += `<th title="${esc(t.name)}, ${esc(t.unit)}">${esc(t.short)}</th>`;
  head += '</tr></thead>';

  const parts = [];
  rows.forEach((s, i) => {
    const rs = state.results.get(s.id) || {};
    const n = GTO.normsFor(s.stage, s.sex);
    const comp = state.computed.get(s.id);
    const on = sel && state.selected.has(s.id);
    let tr = `<tr data-id="${s.id}"${on ? ' class="selected"' : ''}><td class="sticky left">` +
      (sel ? `<span class="name-cell"><input type="checkbox" class="sel-box" data-sel="${s.id}" aria-label="Выбрать"${on ? ' checked' : ''}>` : '') +
      `<button class="name-btn" data-open="${s.id}">` +
      `<span class="name-sub nm-num">${i + 1}.</span> ${esc(s.last_name)} <span class="name-sub nm-full">${esc(s.first_name)} ${esc(s.middle_name)}</span>` +
      `<span class="name-sub nm-short">${esc(initials(s))}</span></button>${sel ? '</span>' : ''}</td>` +
      (full ? `<td class="info mono">${esc(s.uin) || '<span class="name-sub">—</span>'}</td><td class="info" title="${esc(ageText(s.birth_date))}">${fmtDate(s.birth_date)}</td>` : '') +
      `<td class="info" title="${esc(s.institute)}">${esc(s.institute)}</td><td>${esc(s.grp)}</td>` +
      `<td title="${s.sex === 'M' ? 'юноша' : 'девушка'}">${ROMAN[s.stage]} <span class="name-sub">${s.sex === 'M' ? 'м' : 'ж'}</span></td><td class="badge-cell">${badgeHtml(comp?.badge, comp?.date)}</td>`;
    for (const t of tests) {
      const r = rs[t.id];
      if (!n[t.id]) {
        const tip = `${t.name}: не входит в ${ROMAN[s.stage]} ступень — результат можно внести, на знак он не влияет` +
          (r ? `\n${GTO.formatValue(t.id, r.value)} ${t.unit}, ${fmtDate(r.test_date)}` : '');
        tr += `<td class="res na${r ? ' extra' : ''}" data-t="${t.id}" title="${esc(tip)}"${canEdit() ? ' tabindex="0"' : ''}>${r ? esc(GTO.formatValue(t.id, r.value)) : ''}</td>`;
        continue;
      }
      if (!r) { tr += `<td class="res empty" data-t="${t.id}"${canEdit() ? ' tabindex="0"' : ''}></td>`; continue; }
      const lvl = GTO.levelFor(s.stage, s.sex, t.id, r.value);
      const title = `${t.name}: ${GTO.formatValue(t.id, r.value)} ${t.unit} — ${lvl ? BADGE_TEXT[lvl].toLowerCase() : 'норматив не выполнен'}\nДата испытания: ${fmtDate(r.test_date)}`;
      tr += `<td class="res lvl-${lvl}" data-t="${t.id}" title="${esc(title)}"${canEdit() ? ' tabindex="0"' : ''}>${esc(GTO.formatValue(t.id, r.value))}</td>`;
    }
    tr += '</tr>';
    parts.push(tr);
  });

  $('#grid').innerHTML = head + '<tbody>' + parts.join('') + '</tbody>';
  renderSelbar(rows);
}

// ---------- массовое удаление ----------
function renderSelbar(rows = filtered()) {
  const bar = $('#selbar');
  for (const id of [...state.selected]) if (!state.students.some((s) => s.id === id)) state.selected.delete(id);
  if (!isAdmin() || !state.selected.size) { bar.hidden = true; return; }
  bar.hidden = false;
  const n = state.selected.size;
  $('#sel-count').textContent = `Выбрано: ${n}`;
  const rest = rows.filter((s) => !state.selected.has(s.id)).length;
  $('#sel-all').hidden = !rest;
  $('#sel-all').textContent = `Выбрать всех найденных (${rows.length})`;
}

function deleteSelected() {
  const ids = [...state.selected];
  if (!ids.length) return;
  const names = state.students.filter((s) => state.selected.has(s.id)).slice(0, 8).map(fullName);
  const word = 'УДАЛИТЬ';
  const p = openModal(`
    <h2>Удалить ${ids.length} ${plural(ids.length, 'участника', 'участников', 'участников')}?</h2>
    <p class="sub">Вместе с ними удалятся все их результаты. Отменить это нельзя — перед удалением можно сделать «Экспорт CSV».</p>
    <p>${names.map(esc).join(', ')}${ids.length > names.length ? ` и ещё ${ids.length - names.length}` : ''}</p>
    <label>Для подтверждения введите слово ${word}<input id="del-word" autocomplete="off"></label>
    <p class="form-error" id="del-error"></p>
    <div class="modal-actions">
      <button class="btn btn-outline" data-close-modal>Отмена</button>
      <button class="btn btn-danger" id="del-go" disabled>Удалить</button>
    </div>`);
  const inp = p.querySelector('#del-word');
  inp.addEventListener('input', () => { p.querySelector('#del-go').disabled = inp.value.trim().toUpperCase() !== word; });
  inp.focus();
  p.querySelector('#del-go').addEventListener('click', async () => {
    try {
      const r = await api('POST', '/api/students/delete', { ids });
      state.selected.clear();
      closeModal();
      await loadData();
      toast(`Удалено: ${r.deleted}`, true);
    } catch (e) { p.querySelector('#del-error').textContent = e.message; }
  });
}

function plural(n, one, few, many) {
  const a = n % 10, b = n % 100;
  return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many;
}

function initials(s) {
  return [s.first_name, s.middle_name].filter(Boolean).map((x) => x[0] + '.').join(' ');
}

function shortCat(c) {
  return { speed: 'Скорость', endurance: 'Выносливость', flex: 'Гибкость', strength: 'Сила', coord: 'Координация', power: 'Скор.-силовые', applied: 'Прикладные навыки' }[c.id];
}

// ---------- карточка студента ----------
let drawerStudentId = null;

function openDrawer(id) {
  drawerStudentId = id;
  renderDrawer();
  $('#drawer').hidden = false;
  $('.drawer-close').focus();
}
function closeDrawer() { $('#drawer').hidden = true; drawerStudentId = null; }

function renderDrawer() {
  const s = state.students.find((x) => x.id === drawerStudentId);
  if (!s) { closeDrawer(); return; }
  const rs = state.results.get(s.id) || {};
  const comp = state.computed.get(s.id) || { badge: 0, byCategory: {} };
  const tests = GTO.testsFor(s.stage, s.sex);
  const n = GTO.normsFor(s.stage, s.sex);
  const mandatory = GTO.mandatoryFor(s.stage, s.sex);

  const done = tests.filter((t) => rs[t.id]).length;
  let badgeNote;
  if (comp.badge) {
    badgeNote = { 3: 'Выполнены требования на золотой знак отличия.', 2: 'Выполнены требования на серебряный знак отличия.', 1: 'Выполнены требования на бронзовый знак отличия.' }[comp.badge];
  } else {
    const missing = GTO.CATEGORIES.filter((c) => mandatory.includes(c.id) && !(comp.byCategory[c.id] >= 1)).map((c) => c.name.toLowerCase());
    badgeNote = missing.length
      ? `Для бронзы не хватает обязательных: ${missing.join(', ')}.`
      : 'Обязательные выполнены — для бронзы нужно ещё одно испытание по выбору.';
  }
  const cats = GTO.CATEGORIES.filter((c) => tests.some((t) => t.cat === c.id)).map((c) => {
    const lvl = comp.byCategory[c.id];
    const cls = lvl === undefined ? 'na-chip' : `lvl-${lvl}`;
    return `<span class="chip ${cls}" title="${esc(c.name)}">${esc(shortCat(c))}${mandatory.includes(c.id) ? ' *' : ''}</span>`;
  }).join('');

  let html = `<h2>${esc(fullName(s))}</h2>
    <div class="meta">${esc(s.institute || 'Институт не указан')} · группа ${esc(s.grp || '—')} · ${ROMAN[s.stage]} ступень (${GTO.STAGES[s.stage]}) · ${s.sex === 'M' ? 'юноша' : 'девушка'}${fullAccess()
      ? `<br>УИН: <strong>${esc(s.uin) || 'не указан'}</strong> · дата рождения: <strong>${s.birth_date ? fmtDate(s.birth_date) + '</strong> (' + ageText(s.birth_date) + ')' : 'не указана</strong>'}`
      : ''}</div>
    <div class="badge-box${comp.badge ? ' lvl-' + comp.badge : ''}">
      <div class="badge-title">${comp.badge ? 'Знак: ' + BADGE_TEXT[comp.badge] + (comp.date ? ` · выполнен ${fmtDate(comp.date)}` : '') : 'Знак пока не выполнен'}</div>
      <div class="badge-note">${esc(badgeNote)} Сдано испытаний: ${done} из ${tests.length}.</div>
      <div class="cats">${cats}</div>
    </div>`;

  for (const c of GTO.CATEGORIES) {
    const ts = tests.filter((t) => t.cat === c.id);
    if (!ts.length) continue;
    html += `<h3>${esc(c.name)}${mandatory.includes(c.id) ? '<span class="req">обязательное</span>' : ''}</h3><table class="tests"><tbody>`;
    for (const t of ts) {
      const r = rs[t.id];
      const thr = n[t.id];
      const thrText = `бронза ${GTO.formatValue(t.id, thr[0])} · серебро ${GTO.formatValue(t.id, thr[1])} · золото ${GTO.formatValue(t.id, thr[2])}`;
      let val = '<span class="muted">—</span>';
      let when = '';
      if (r) {
        const lvl = GTO.levelFor(s.stage, s.sex, t.id, r.value);
        val = `${esc(GTO.formatValue(t.id, r.value))} <span class="chip lvl-${lvl}">${lvl ? BADGE_TEXT[lvl] : 'не выполнено'}</span>`;
        when = `<strong>${fmtDate(r.test_date)}</strong><span class="thr" title="Когда и кем внесено">внесено ${fmtDateTime(r.entered_at)}${r.entered_by_name || r.entered_by_login ? ' · ' + esc(r.entered_by_name || r.entered_by_login) : ''}</span>`;
      }
      html += `<tr><td class="t-name">${esc(t.name)}, ${esc(t.unit)}<span class="thr">${esc(thrText)}</span></td>
        <td class="t-val">${val}</td><td class="t-date">${when}</td>
        <td class="t-act">${canEdit() ? `<button class="btn btn-outline btn-sm" data-edit-result="${t.id}">${r ? 'Изменить' : 'Внести'}</button>` : ''}</td></tr>`;
    }
    html += '</tbody></table>';
  }

  // испытания не своей ступени: можно внести, в протокол попадают, на знак не влияют
  const extra = GTO.TESTS.filter((t) => !n[t.id]);
  const extraDone = extra.filter((t) => rs[t.id]);
  if (extraDone.length || canEdit()) {
    html += '<h3>Другие испытания<span class="req muted-req">не входят в ступень — на знак не влияют</span></h3>';
    if (extraDone.length) {
      html += '<table class="tests"><tbody>' + extraDone.map((t) => {
        const r = rs[t.id];
        return `<tr><td class="t-name">${esc(t.name)}, ${esc(t.unit)}</td><td class="t-val">${esc(GTO.formatValue(t.id, r.value))}</td>
          <td class="t-date"><strong>${fmtDate(r.test_date)}</strong></td>
          <td class="t-act">${canEdit() ? `<button class="btn btn-outline btn-sm" data-edit-result="${t.id}">Изменить</button>` : ''}</td></tr>`;
      }).join('') + '</tbody></table>';
    }
    const free = extra.filter((t) => !rs[t.id]);
    if (canEdit() && free.length) {
      html += `<div class="extra-add"><select id="extra-test" aria-label="Испытание">${free.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select>
        <button class="btn btn-outline btn-sm" data-extra-add>Внести</button></div>`;
    }
  }

  if (canEdit()) {
    html += `<div class="drawer-actions">
      <button class="btn btn-secondary" data-edit-student>Изменить данные</button>
      <button class="btn btn-danger" data-delete-student>Удалить студента</button>
    </div>`;
  }
  $('#drawer-body').innerHTML = html;
}

// ---------- модальные окна ----------
let modalOnClose = null;
function openModal(html, { wide = false, onClose = null } = {}) {
  const p = $('#modal-panel');
  p.className = 'modal-panel' + (wide ? ' wide' : '');
  p.innerHTML = '<button class="modal-close" data-close-modal aria-label="Закрыть">×</button>' + html;
  $('#modal').hidden = false;
  modalOnClose = onClose;
  const first = p.querySelector('[autofocus], input, select, textarea, button:not(.modal-close)');
  if (first) first.focus();
  return p;
}
function closeModal() {
  $('#modal').hidden = true;
  $('#modal-panel').innerHTML = '';
  if (modalOnClose) { const f = modalOnClose; modalOnClose = null; f(); }
}

// Ввод результата
function editResult(studentId, testId) {
  if (!canEdit()) return;
  const s = state.students.find((x) => x.id === studentId);
  const t = GTO.TEST_BY_ID[testId];
  const thr = (GTO.normsFor(s.stage, s.sex) || {})[testId];
  const r = (state.results.get(studentId) || {})[testId];
  const placeholder = t.kind === 'time' ? 'например 12:20' : t.kind === 'sec' ? 'например 8,4' : 'например 25';
  const p = openModal(`
    <h2>${esc(t.name)}</h2>
    <p class="sub">${esc(fullName(s))} · ${ROMAN[s.stage]} ступень · ${s.sex === 'M' ? 'юноша' : 'девушка'}</p>
    <form id="result-form" class="form-grid">
      <label>Результат, ${esc(t.unit)}
        <input name="value" inputmode="decimal" placeholder="${placeholder}" value="${r ? esc(GTO.formatValue(testId, r.value)) : ''}" autofocus required>
      </label>
      <label>Дата испытания
        <input name="date" type="date" max="${todayISO()}" value="${r ? r.test_date : todayISO()}" required>
      </label>
      <div class="full preview-level" id="preview"></div>
      ${thr ? `<table class="thr-table full"><tr>
        <td class="lvl-1">бронза ${esc(GTO.formatValue(testId, thr[0]))}</td>
        <td class="lvl-2">серебро ${esc(GTO.formatValue(testId, thr[1]))}</td>
        <td class="lvl-3">золото ${esc(GTO.formatValue(testId, thr[2]))}</td>
      </tr></table>` : `<p class="full hint">Это испытание не входит в ${ROMAN[s.stage]} ступень: результат сохранится и попадёт в выгрузку, но на знак не повлияет.</p>`}
      <p class="form-error full" id="result-error"></p>
      <div class="modal-actions full">
        ${r ? '<button type="button" class="btn btn-danger left" id="result-del">Удалить результат</button>' : ''}
        <button type="button" class="btn btn-outline" data-close-modal>Отмена</button>
        <button type="submit" class="btn btn-primary">Сохранить</button>
      </div>
    </form>`);
  const input = p.querySelector('[name=value]');
  input.select();
  const preview = () => {
    const v = GTO.parseValue(testId, input.value);
    const box = $('#preview');
    if (!input.value.trim()) { box.innerHTML = ''; return; }
    if (v == null) { box.innerHTML = `<span class="chip lvl-0">Не понял значение — формат ${t.kind === 'time' ? 'мин:сек' : t.unit}</span>`; return; }
    if (!thr) { box.innerHTML = `Будет записано: <strong>${GTO.formatValue(testId, v)} ${esc(t.unit)}</strong> — вне ступени, на знак не влияет`; return; }
    const lvl = GTO.levelFor(s.stage, s.sex, testId, v);
    box.innerHTML = `Будет засчитано как <span class="chip lvl-${lvl}">${GTO.formatValue(testId, v)} — ${lvl ? BADGE_TEXT[lvl] : 'норматив не выполнен'}</span>`;
  };
  input.addEventListener('input', preview);
  preview();

  p.querySelector('#result-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const row = await api('PUT', '/api/results', { student_id: studentId, test_id: testId, value: fd.get('value'), test_date: fd.get('date') });
      if (!state.results.has(studentId)) state.results.set(studentId, {});
      state.results.get(studentId)[testId] = row;
      recompute(studentId);
      closeModal();
      render();
      if (drawerStudentId === studentId) renderDrawer();
      toast('Сохранено', true);
    } catch (err) { $('#result-error').textContent = err.message; }
  });
  const del = p.querySelector('#result-del');
  if (del) del.addEventListener('click', async () => {
    if (!confirm('Удалить этот результат?')) return;
    try {
      await api('DELETE', `/api/results/${studentId}/${testId}`);
      delete state.results.get(studentId)[testId];
      recompute(studentId);
      closeModal();
      render();
      if (drawerStudentId === studentId) renderDrawer();
      toast('Результат удалён', true);
    } catch (err) { $('#result-error').textContent = err.message; }
  });
}

// Добавление / редактирование студента
function editStudent(id) {
  const s = id ? state.students.find((x) => x.id === id) : { sex: 'M', stage: 7, institute: state.filters.inst, grp: state.filters.grp };
  const insts = uniqSorted(state.students.map((x) => x.institute));
  const grps = uniqSorted(state.students.map((x) => x.grp));
  const p = openModal(`
    <h2>${id ? 'Изменить данные' : 'Новый студент'}</h2>
    <p class="sub">${id ? 'Если сменить ступень или пол, результаты испытаний, которых нет в новой ступени, удалятся.' : 'Результаты можно будет внести сразу после сохранения.'}</p>
    <form id="student-form" class="form-grid">
      <label>Фамилия<input name="last_name" value="${esc(s.last_name)}" required autofocus></label>
      <label>Имя<input name="first_name" value="${esc(s.first_name)}" required></label>
      <label>Отчество<input name="middle_name" value="${esc(s.middle_name)}"></label>
      <label>Дата рождения<input name="birth_date" type="date" max="${todayISO()}" value="${esc(s.birth_date)}"></label>
      <label>УИН ГТО<input name="uin" value="${esc(s.uin)}" placeholder="23-65-0012345" pattern="\\d{2}-?\\d{2}-?\\d{7}" title="11 цифр: ГГ-РР-ННННННН"></label>
      <div class="hint" id="age-hint"></div>
      <label>Институт<input name="institute" list="dl-inst" value="${esc(s.institute)}"></label>
      <label>Группа<input name="grp" list="dl-grp" value="${esc(s.grp)}"></label>
      <label>Ступень
        <select name="stage">${GTO.STAGE_LIST.map((n) => `<option value="${n}"${n === s.stage ? ' selected' : ''}>${ROMAN[n]} ступень · ${GTO.STAGES[n]}</option>`).join('')}</select>
      </label>
      <div><label>Пол</label>
        <div class="radio-row">
          <label><input type="radio" name="sex" value="M"${s.sex === 'M' ? ' checked' : ''}> юноша</label>
          <label><input type="radio" name="sex" value="F"${s.sex === 'F' ? ' checked' : ''}> девушка</label>
        </div>
      </div>
      <datalist id="dl-inst">${insts.map((i) => `<option value="${esc(i)}">`).join('')}</datalist>
      <datalist id="dl-grp">${grps.map((g) => `<option value="${esc(g)}">`).join('')}</datalist>
      <p class="form-error full" id="student-error"></p>
      <div class="modal-actions full">
        <button type="button" class="btn btn-outline" data-close-modal>Отмена</button>
        <button type="submit" class="btn btn-primary">Сохранить</button>
      </div>
    </form>`);
  // По дате рождения подставляем ступень.
  const bd = p.querySelector('[name=birth_date]');
  const stageSel = p.querySelector('[name=stage]');
  const syncStage = () => {
    const hint = $('#age-hint');
    if (!bd.value) { hint.textContent = ''; return; }
    const age = GTO.ageOn(bd.value, todayISO());
    const st = GTO.stageForAge(age);
    if (st) { stageSel.value = String(st); hint.textContent = `Возраст ${ageText(bd.value)} → ${ROMAN[st]} ступень`; }
    else hint.textContent = `Возраст ${ageText(bd.value)} — комплекс ГТО с 6 лет`;
  };
  bd.addEventListener('change', syncStage);
  if (bd.value) syncStage();
  p.querySelector('#student-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    try {
      const saved = await api(id ? 'PUT' : 'POST', id ? `/api/students/${id}` : '/api/students', body);
      closeModal();
      await loadData();
      toast(id ? 'Данные обновлены' : 'Студент добавлен', true);
      openDrawer(saved.id);
    } catch (err) { $('#student-error').textContent = err.message; }
  });
}

async function deleteStudent(id) {
  const s = state.students.find((x) => x.id === id);
  if (!confirm(`Удалить ${fullName(s)} вместе со всеми результатами?`)) return;
  try {
    await api('DELETE', `/api/students/${id}`);
    closeDrawer();
    await loadData();
    toast('Студент удалён', true);
  } catch (err) { toast(err.message); }
}

// Загрузка списка студентов (Excel или CSV / вставка из Excel)
function openImport() {
  const p = openModal(`
    <h2>Загрузить список студентов</h2>
    <p class="sub">Физрук скачивает <a href="/api/template.xlsx" download="GTO-shablon-spiska.xlsx">шаблон списка</a>, заполняет и передаёт файл сюда.
      Студенты, которые уже есть в базе (совпал УИН или ФИО + дата рождения), обновятся, остальные добавятся.
      Прошлые результаты с листа «Результаты» загружает только администратор — после проверки и подтверждения.</p>
    <p class="sub">Можно и <strong>одним CSV</strong>: участник и результат в одной строке (<a href="/api/template.csv" download>шаблон CSV</a>:
      колонки «Испытание», «Результат», «Дата выполнения»; несколько результатов — несколько строк), или файл из «Экспорт CSV» после правки.</p>
    <label class="drop-zone" id="imp-drop">
      <strong>Выберите файл .xlsx или .csv</strong>
      <span>или перетащите его сюда</span>
      <input type="file" id="imp-file" accept=".xlsx,.csv,.txt" hidden>
    </label>
    <details class="mt"><summary class="hint">…или вставьте строки из Excel</summary>
      <textarea id="imp-text" placeholder="Фамилия&#9;Имя&#9;Отчество&#9;Дата рождения&#9;Пол&#9;УИН&#9;Институт&#9;Группа&#9;Ступень"></textarea>
      <button class="btn btn-outline btn-sm mt" id="imp-parse-text">Проверить</button>
    </details>
    <div class="preview-level" id="imp-summary"></div>
    <div id="imp-preview"></div>
    <div id="imp-results"></div>
    <ul class="import-errors" id="imp-errors"></ul>
    <div class="modal-actions">
      <button class="btn btn-outline" data-close-modal>Отмена</button>
      <button class="btn btn-primary" id="imp-go" disabled>Загрузить</button>
    </div>`, { wide: true });

  let good = [];
  let goodResults = [];
  let canResults = false;
  const resultsOn = () => canResults && goodResults.length && $('#imp-res-ok') && $('#imp-res-ok').checked;
  function updateGo() {
    const n = good.length;
    const m = resultsOn() ? goodResults.length : 0;
    $('#imp-go').disabled = !n && !m;
    $('#imp-go').textContent = n || m ? `Загрузить (${[n ? n + ' уч.' : '', m ? m + ' рез.' : ''].filter(Boolean).join(', ')})` : 'Загрузить';
  }
  function renderResults(results) {
    const box = $('#imp-results');
    if (!results.length) { box.innerHTML = ''; return; }
    goodResults = results.filter((r) => !r.error && r.action !== 'skip');
    const bad = results.filter((r) => r.error).length;
    const skip = results.filter((r) => r.action === 'skip').length;
    const extra = goodResults.filter((r) => !r.in_stage).length;
    box.innerHTML = `<h3 class="mt">Прошлые результаты</h3>
      <div class="preview-level">Строк: <strong>${results.length}</strong> · будет записано: <strong>${goodResults.length}</strong>` +
      (extra ? ` · из них вне ступени (на знак не влияют): ${extra}` : '') +
      (skip ? ` · пропуск — в базе свежее: ${skip}` : '') +
      (bad ? ` · <span class="chip lvl-0">с ошибками: ${bad} — будут пропущены</span>` : '') + `</div>
      <div class="import-scroll"><table class="import-table"><thead><tr><th>#</th><th>Участник</th><th>Ступ.</th><th>Испытание</th><th>Результат</th><th>Дата</th><th></th></tr></thead><tbody>
      ${results.map((r, i) => {
        const t = r.test_id ? GTO.TEST_BY_ID[r.test_id] : null;
        const status = r.error ? esc(r.error)
          : r.action === 'skip' ? esc(r.note)
          : !r.in_stage ? 'вне ступени — на знак не влияет'
          : `<span class="chip lvl-${r.level}">${r.level ? BADGE_TEXT[r.level] : 'не выполнено'}</span>${r.note ? ' · ' + esc(r.note) : ''}`;
        return `<tr class="${r.error ? 'bad' : ''}"><td>${i + 1}</td><td>${esc([r.last_name, r.first_name, r.middle_name].filter(Boolean).join(' '))}</td>
          <td>${r.stage ? ROMAN[r.stage] : ''}</td><td>${t ? esc(t.name) : esc(r.test_raw)}</td>
          <td>${t && r.value != null ? esc(GTO.formatValue(r.test_id, r.value)) : esc(r.value_raw)}</td>
          <td>${r.test_date ? fmtDate(r.test_date) : esc(r.date_raw)}</td><td class="${r.error ? 'err' : ''}">${status}</td></tr>`;
      }).join('')}</tbody></table></div>` +
      (!goodResults.length ? '' : canResults
        ? `<label class="check mt"><input type="checkbox" id="imp-res-ok"> Результаты проверены — загрузить их в базу (${goodResults.length}). Более поздние результаты в базе не заменяются.</label>`
        : '<p class="hint mt">Результаты в файле есть, но загрузить их может только администратор — передайте файл ему.</p>');
    const ok = $('#imp-res-ok');
    if (ok) ok.addEventListener('change', updateGo);
  }
  async function parse(body) {
    $('#imp-errors').innerHTML = '';
    $('#imp-summary').textContent = 'Проверяю…';
    try {
      const { rows, results = [], can_import_results: cir } = await api('POST', '/api/import/parse', body);
      canResults = !!cir;
      goodResults = [];
      good = rows.filter((r) => !r.error);
      const bad = rows.length - good.length;
      const upd = good.filter((r) => r.action === 'update').length;
      $('#imp-summary').innerHTML = rows.length
        ? `Строк: <strong>${rows.length}</strong> · новых: <strong>${good.length - upd}</strong> · обновятся: <strong>${upd}</strong>` +
          (bad ? ` · <span class="chip lvl-0">с ошибками: ${bad} — будут пропущены</span>` : '')
        : 'В файле не нашлось строк со студентами.';
      $('#imp-preview').innerHTML = rows.length ? `<div class="import-scroll"><table class="import-table"><thead><tr>
          <th>#</th><th>ФИО</th><th>Дата рожд.</th><th>Пол</th><th>УИН</th><th>Институт</th><th>Группа</th><th>Ступ.</th><th></th></tr></thead><tbody>
          ${rows.map((r, i) => `<tr class="${r.error ? 'bad' : ''}"><td>${i + 1}</td>
            <td>${esc([r.last_name, r.first_name, r.middle_name].filter(Boolean).join(' '))}</td>
            <td>${r.error ? esc(r.birth_date) : fmtDate(r.birth_date)}</td><td>${r.error ? esc(r.sex) : r.sex === 'M' ? 'М' : 'Ж'}</td>
            <td>${esc(r.uin)}</td><td>${esc(r.institute)}</td><td>${esc(r.grp)}</td><td>${r.error ? esc(r.stage) : ROMAN[r.stage]}</td>
            <td class="${r.error ? 'err' : ''}">${r.error ? esc(r.error) : r.action === 'update' ? 'обновить' : 'новый'}</td></tr>`).join('')}
          </tbody></table></div>` : '';
      renderResults(results);
      updateGo();
    } catch (err) {
      $('#imp-summary').textContent = '';
      $('#imp-errors').innerHTML = `<li>${esc(err.message)}</li>`;
      $('#imp-go').disabled = true;
    }
  }

  async function handleFile(f) {
    if (!f) return;
    const buf = await f.arrayBuffer();
    if (/\.xlsx$/i.test(f.name)) {
      let bin = '';
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      parse({ xlsx: btoa(bin) });
    } else {
      let text = new TextDecoder('utf-8').decode(buf);
      if (text.includes('�')) text = new TextDecoder('windows-1251').decode(buf); // CSV из Excel
      parse({ text });
    }
  }

  const drop = p.querySelector('#imp-drop');
  p.querySelector('#imp-file').addEventListener('change', (e) => handleFile(e.target.files[0]));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); handleFile(e.dataTransfer.files[0]); });
  p.querySelector('#imp-parse-text').addEventListener('click', () => parse({ text: $('#imp-text').value }));

  p.querySelector('#imp-go').addEventListener('click', async () => {
    try {
      const r = await api('POST', '/api/students/import', { rows: good, results: resultsOn() ? goodResults : [] });
      closeModal();
      await loadData();
      toast(`Готово: добавлено ${r.created}, обновлено ${r.updated}` +
        (r.results != null ? `, результатов записано ${r.results}${r.results_skipped ? ` (пропущено ${r.results_skipped} — в базе свежее)` : ''}` : ''), true);
    } catch (err) {
      const errs = err.data && err.data.errors;
      $('#imp-errors').innerHTML = errs
        ? errs.slice(0, 50).map((x) => `<li>Строка ${x.row}: ${esc(x.error)}</li>`).join('')
        : `<li>${esc(err.message)}</li>`;
    }
  });
}

// Смена своего пароля
function openPassword() {
  const p = openModal(`
    <h2>Смена пароля</h2>
    <form id="pw-form" class="form-grid">
      <label class="full">Текущий пароль<input name="old" type="password" autocomplete="current-password" required autofocus></label>
      <label class="full">Новый пароль (от 8 символов)<input name="new" type="password" autocomplete="new-password" minlength="8" required></label>
      <p class="form-error full" id="pw-error"></p>
      <div class="modal-actions full">
        <button type="button" class="btn btn-outline" data-close-modal>Отмена</button>
        <button type="submit" class="btn btn-primary">Сменить</button>
      </div>
    </form>`);
  p.querySelector('#pw-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api('POST', '/api/me/password', Object.fromEntries(new FormData(e.target)));
      closeModal();
      toast('Пароль изменён', true);
    } catch (err) { $('#pw-error').textContent = err.message; }
  });
}

// Пользователи (только администратор)
// SQLite datetime('now') — UTC без зоны: показываем в местном времени
const fmtUtc = (s) => new Date(s.replace(' ', 'T') + 'Z').toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
async function openUsers(notice = '') {
  let users;
  try { users = await api('GET', '/api/users'); } catch (err) { toast(err.message); return; }
  const roleOpts = (r) => Object.entries(ROLE_NAMES).map(([k, v]) => `<option value="${k}"${k === r ? ' selected' : ''}>${v}</option>`).join('');
  const p = openModal(`
    <h2>Пользователи</h2>
    <p class="sub"><strong>Ввод результатов</strong> — добавляет студентов и вносит результаты. <strong>Просмотр</strong> — учителя физкультуры: только поиск и просмотр. Имя, роль и примечание сохраняются сразу.</p>
    ${notice}
    <table class="users-table"><thead><tr><th>Логин</th><th>Имя</th><th>Роль</th><th>Примечание</th><th>Последний вход</th><th></th></tr></thead><tbody>
    ${users.map((u) => `<tr data-uid="${u.id}" data-login="${esc(u.login)}" class="${u.active ? '' : 'inactive'}">
      <td>${esc(u.login)}${u.active ? '' : ' <span class="muted">заблокирован</span>'}</td>
      <td><input data-f="name" value="${esc(u.name)}" maxlength="120" aria-label="Имя"></td>
      <td><select data-role${u.id === state.user.id ? ' disabled' : ''}>${roleOpts(u.role)}</select></td>
      <td><input data-f="note" value="${esc(u.note || '')}" maxlength="200" placeholder="—" aria-label="Примечание"></td>
      <td class="u-last">${u.last_login ? fmtUtc(u.last_login) : 'не входил'}</td>
      <td class="u-act">
        ${u.id === state.user.id ? '<span class="muted">свой пароль — кнопка «Пароль» вверху</span>' : `<button class="btn btn-outline btn-sm" data-reset>Новый пароль</button>
        <button class="btn btn-outline btn-sm" data-active="${u.active ? 0 : 1}">${u.active ? 'Заблокировать' : 'Разблокировать'}</button>
        <button class="btn btn-danger btn-sm" data-del>Удалить</button>`}
      </td></tr>`).join('')}
    </tbody></table>
    <form id="add-user" class="add-user">
      <label>Логин<input name="login" required pattern="[A-Za-z0-9._@\\-]{3,80}" placeholder="ivanova"></label>
      <label>Имя<input name="name" placeholder="Иванова Мария Петровна"></label>
      <label>Роль<select name="role"><option value="viewer">Просмотр</option><option value="editor">Ввод результатов</option><option value="admin">Администратор</option></select></label>
      <label>Примечание<input name="note" maxlength="200" placeholder="школа № 5, физрук"></label>
      <button class="btn btn-primary" type="submit">Добавить</button>
    </form>
    <p class="form-error" id="users-error"></p>`, { wide: true });
  p.classList.add('users');

  const err = (e) => { $('#users-error').textContent = e.message; };
  p.querySelectorAll('[data-role]').forEach((sel) => sel.addEventListener('change', async () => {
    const id = Number(sel.closest('tr').dataset.uid);
    try { await api('PUT', `/api/users/${id}`, { role: sel.value }); toast('Роль изменена', true); } catch (e) { err(e); }
  }));
  p.querySelectorAll('input[data-f]').forEach((inp) => {
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });
    inp.addEventListener('change', async () => {
      try {
        await api('PUT', `/api/users/${inp.closest('tr').dataset.uid}`, { [inp.dataset.f]: inp.value });
        inp.classList.add('saved'); setTimeout(() => inp.classList.remove('saved'), 900);
      } catch (e) { err(e); }
    });
  });
  p.querySelectorAll('[data-reset]').forEach((b) => b.addEventListener('click', async () => {
    const tr = b.closest('tr');
    const pw = genPassword();
    try {
      await api('PUT', `/api/users/${tr.dataset.uid}`, { password: pw });
      openUsers(`<p class="sub">Новый пароль для <strong>${esc(tr.dataset.login)}</strong>: <span class="secret">${pw}</span> — передайте его пользователю, повторно он показан не будет.</p>`);
    } catch (e) { err(e); }
  }));
  p.querySelectorAll('[data-active]').forEach((b) => b.addEventListener('click', async () => {
    try { await api('PUT', `/api/users/${b.closest('tr').dataset.uid}`, { active: b.dataset.active === '1' }); openUsers(); } catch (e) { err(e); }
  }));
  p.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
    const tr = b.closest('tr');
    if (!confirm(`Удалить пользователя ${tr.dataset.login}?`)) return;
    try { await api('DELETE', `/api/users/${tr.dataset.uid}`); openUsers(); } catch (e) { err(e); }
  }));
  p.querySelector('#add-user').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    body.password = genPassword();
    try {
      await api('POST', '/api/users', body);
      openUsers(`<p class="sub">Создан <strong>${esc(body.login)}</strong>, пароль: <span class="secret">${body.password}</span> — передайте его пользователю, повторно он показан не будет.</p>`);
    } catch (e2) { err(e2); }
  });
}

// Обновление приложения (только администратор)
const shortSha = (sha) => (sha ? sha.slice(0, 7) : '—');
const fmtIso = (d) => {
  const dt = new Date(d);
  return Number.isNaN(dt.getTime()) ? '' : dt.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};
const JOB_TEXT = { queued: 'В очереди', running: 'Идёт обновление', ok: 'Готово', error: 'Ошибка' };

async function openUpdate() {
  let st;
  try { st = await api('GET', '/api/update/status'); } catch (err) { toast(err.message); return; }
  const cur = st.current || {};
  const p = openModal(`
    <h2>Обновление</h2>
    <p class="sub">Установленная версия: <strong>${esc(shortSha(cur.sha))}</strong>${cur.installed_at ? ` от ${esc(fmtIso(cur.installed_at))}` : ''}</p>
    ${st.enabled ? '' : '<p class="form-error">Обновление кнопкой ещё не настроено на сервере. Один раз запустите на сервере команду установки (install.sh) — после этого кнопка заработает.</p>'}
    <div id="upd-job"></div>
    <div id="upd-body" class="hint">Нажмите «Проверить», чтобы узнать, есть ли новая версия.</div>
    <p class="form-error" id="upd-error"></p>
    <div class="modal-actions">
      <button class="btn btn-outline" data-close-modal>Закрыть</button>
      <button class="btn btn-secondary" id="upd-check">Проверить</button>
      <button class="btn btn-primary" id="upd-install" hidden>Установить</button>
    </div>`, { wide: true, onClose: () => clearInterval(openUpdate.timer) });

  let latestSha = '';
  const showJob = (job) => {
    const box = $('#upd-job');
    if (!box) return;
    if (!job) { box.innerHTML = ''; return; }
    const cls = job.state === 'ok' ? 'lvl-3' : job.state === 'error' ? 'lvl-0' : 'lvl-2';
    box.innerHTML = `<p class="preview-level"><span class="chip ${cls}">${esc(JOB_TEXT[job.state] || job.state)}</span> ${esc(job.message || '')}` +
      `${job.at ? ` <span class="hint">· ${esc(fmtIso(job.at))}</span>` : ''}</p>`;
  };
  showJob(st.job);

  const poll = () => {
    clearInterval(openUpdate.timer);
    openUpdate.timer = setInterval(async () => {
      let s;
      try { s = await api('GET', '/api/update/status'); } catch { return; } // во время перезапуска сервер недолго недоступен
      showJob(s.job);
      if (s.job && (s.job.state === 'ok' || s.job.state === 'error') && !s.pending) {
        clearInterval(openUpdate.timer);
        if (s.job.state === 'ok') { toast('Обновлено — страница перезагрузится', true); setTimeout(() => location.reload(), 1500); }
      }
    }, 2000);
  };
  if (st.pending || (st.job && (st.job.state === 'running' || st.job.state === 'queued'))) poll();

  p.querySelector('#upd-check').addEventListener('click', async () => {
    $('#upd-error').textContent = '';
    $('#upd-body').textContent = 'Проверяю…';
    try {
      const r = await api('GET', '/api/update/check');
      latestSha = r.latest.sha;
      if (r.upToDate) {
        $('#upd-body').innerHTML = `<p>Установлена последняя версия ГТО (<strong>${esc(shortSha(r.latest.label || r.latest.sha))}</strong>). Изменения сервера хронометража SakhStart сюда не относятся — он обновляется своей кнопкой.</p>`;
        $('#upd-install').hidden = true;
        return;
      }
      $('#upd-body').innerHTML = `<p>Доступна новая версия ГТО <strong>${esc(shortSha(r.latest.label || r.latest.sha))}</strong> от ${esc(fmtIso(r.latest.date))}. Что изменилось:</p>
        <ul class="changes">${r.changes.map((c) => `<li>${esc(c.message)} <span class="hint">· ${esc(shortSha(c.sha))}</span></li>`).join('')}</ul>
        <p class="hint">Сервер скачает версию, прогонит автотесты и только потом установит. Если что-то пойдёт не так — вернёт прежнюю. Сайт будет недоступен несколько секунд.</p>`;
      $('#upd-install').hidden = !st.enabled;
    } catch (err) { $('#upd-body').textContent = ''; $('#upd-error').textContent = err.message; }
  });

  p.querySelector('#upd-install').addEventListener('click', async () => {
    if (!confirm('Установить новую версию?')) return;
    $('#upd-error').textContent = '';
    try {
      await api('POST', '/api/update/install', { sha: latestSha });
      $('#upd-install').hidden = true;
      $('#upd-check').disabled = true;
      showJob({ state: 'queued', message: 'Заявка принята' });
      poll();
    } catch (err) { $('#upd-error').textContent = err.message; }
  });
}

// ---------- вход / выход ----------
function showLogin() {
  state.user = null;
  closeModal();
  closeDrawer();
  $('#app-view').hidden = true;
  $('#login-view').hidden = false;
  $('#login-form [name=login]').focus();
}

async function showApp(user) {
  state.user = user;
  document.body.classList.toggle('can-edit', canEdit());
  $('#me-name').textContent = user.name || user.login;
  const rc = $('#me-role');
  rc.textContent = ROLE_NAMES[user.role];
  rc.className = 'role-chip ' + user.role;
  $('#btn-users').hidden = user.role !== 'admin';
  $('#btn-update').hidden = user.role !== 'admin';
  $('#login-view').hidden = true;
  $('#app-view').hidden = false;
  await loadData();
}

// ---------- события ----------
function bind() {
  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    $('#login-error').textContent = '';
    try {
      const u = await api('POST', '/api/login', { login: fd.get('login'), password: fd.get('password') });
      e.target.reset();
      // Пароль верный, но браузер не сохранил сессию (например, http вместо https)
      const check = await fetch('/api/me', { credentials: 'same-origin' });
      if (!check.ok) {
        $('#login-error').textContent = location.protocol === 'http:'
          ? `Пароль верный, но браузер не сохранил вход. Откройте https://${location.host}`
          : 'Пароль верный, но браузер не сохранил вход. Разрешите cookie для этого сайта.';
        return;
      }
      await showApp(u);
    } catch (err) { $('#login-error').textContent = err.message; }
  });

  $('#btn-logout').addEventListener('click', async () => {
    try { await api('POST', '/api/logout'); } catch { /* всё равно выходим */ }
    showLogin();
  });
  $('#btn-password').addEventListener('click', openPassword);
  $('#btn-users').addEventListener('click', () => openUsers());
  $('#btn-update').addEventListener('click', openUpdate);
  $('#btn-add').addEventListener('click', () => editStudent(null));
  $('#btn-import').addEventListener('click', openImport);

  const f = state.filters;
  let qTimer;
  $('#f-q').addEventListener('input', (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { f.q = e.target.value; saveFilters(); render(); }, 120);
  });
  $('#f-inst').addEventListener('change', (e) => { f.inst = e.target.value; f.grp = ''; fillFilterOptions(); saveFilters(); render(); });
  $('#f-grp').addEventListener('change', (e) => { f.grp = e.target.value; saveFilters(); render(); });
  $('#f-stage').addEventListener('change', (e) => { f.stage = e.target.value; saveFilters(); render(); });
  $('#f-sex').addEventListener('change', (e) => { f.sex = e.target.value; saveFilters(); render(); });
  $('#f-badge').addEventListener('change', (e) => { f.badge = e.target.value; saveFilters(); render(); });
  $('#btn-reset').addEventListener('click', () => {
    Object.assign(f, { q: '', inst: '', grp: '', stage: '', sex: '', badge: '' });
    fillFilterOptions(); saveFilters(); render();
  });

  $('#grid').addEventListener('change', (e) => {
    const box = e.target.closest('.sel-box');
    if (!box) return;
    if (box.id === 'sel-head') {
      for (const st of filtered()) { if (box.checked) state.selected.add(st.id); else state.selected.delete(st.id); }
    } else {
      const id = Number(box.dataset.sel);
      if (box.checked) state.selected.add(id); else state.selected.delete(id);
    }
    render();
  });
  $('#sel-all').addEventListener('click', () => { for (const st of filtered()) state.selected.add(st.id); render(); });
  $('#sel-none').addEventListener('click', () => { state.selected.clear(); render(); });
  $('#sel-delete').addEventListener('click', deleteSelected);

  $('#grid').addEventListener('click', (e) => {
    const open = e.target.closest('[data-open]');
    if (open) { openDrawer(Number(open.dataset.open)); return; }
    const cell = e.target.closest('td.res[data-t]');
    if (cell && canEdit()) editResult(Number(cell.closest('tr').dataset.id), cell.dataset.t);
  });
  $('#grid').addEventListener('keydown', (e) => {
    const cell = e.target.closest('td.res[data-t]');
    if (cell && (e.key === 'Enter' || e.key === ' ') && canEdit()) {
      e.preventDefault();
      editResult(Number(cell.closest('tr').dataset.id), cell.dataset.t);
    }
  });

  $('#drawer').addEventListener('click', (e) => {
    if (e.target.id === 'drawer' || e.target.closest('[data-close]')) { closeDrawer(); return; }
    const er = e.target.closest('[data-edit-result]');
    if (er) { editResult(drawerStudentId, er.dataset.editResult); return; }
    if (e.target.closest('[data-extra-add]')) { editResult(drawerStudentId, $('#extra-test').value); return; }
    if (e.target.closest('[data-edit-student]')) { editStudent(drawerStudentId); return; }
    if (e.target.closest('[data-delete-student]')) deleteStudent(drawerStudentId);
  });

  $('#modal').addEventListener('click', (e) => {
    if (e.target.id === 'modal' || e.target.closest('[data-close-modal]')) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!$('#modal').hidden) closeModal();
    else if (!$('#drawer').hidden) closeDrawer();
  });
}

(async function init() {
  loadFilters();
  bind();
  try {
    const me = await fetch('/api/me', { credentials: 'same-origin' });
    if (me.ok) await showApp(await me.json());
    else showLogin();
  } catch { showLogin(); }
})();
