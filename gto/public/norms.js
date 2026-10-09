// Нормативы ВФСК ГТО, ступени I–XVIII (источник: gto.ru/normativy, октябрь 2026).
// Файл общий для сервера (require) и браузера (window.GTO).
(function (root) {
  'use strict';

  // Данные нормативов всех ступеней I–XVIII — в norms-data.js (собирается tools/build-norms.js из таблиц gto.ru).
  const DATA = typeof module !== 'undefined' && module.exports ? require('./norms-data') : root.GTO_DATA;
  const CATEGORIES = DATA.CATEGORIES;
  const TESTS = DATA.TESTS;
  const STAGE_LIST = Array.from({ length: 18 }, (_, i) => i + 1);
  const ROMAN = Object.fromEntries(STAGE_LIST.map((n) => [n, ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII'][n - 1]]));
  const STAGES = Object.fromEntries(STAGE_LIST.map((n) => {
    const a = DATA.STAGES[n].ages;
    return [n, a.endsWith('+') ? `${a.slice(0, -1)} лет и старше` : `${a.replace('-', '–')} лет`];
  }));
  const LEVELS = ['bronze', 'silver', 'gold'];
  const LEVEL_NAMES = { gold: 'Золото', silver: 'Серебро', bronze: 'Бронза' };
  const stageData = (stage, sex) => (DATA.STAGES[stage] && DATA.STAGES[stage][sex]) || null;
  // Сколько качеств (категорий) нужно на [бронзу, серебро, золото] и какие категории обязательны — у каждой ступени свои.
  const requiredFor = (stage, sex) => (stageData(stage, sex) || { required: [99, 99, 99] }).required;
  const mandatoryFor = (stage, sex) => (stageData(stage, sex) || { mandatory: [] }).mandatory;

  const TEST_BY_ID = Object.fromEntries(TESTS.map((x) => [x.id, x]));
  const CAT_BY_ID = Object.fromEntries(CATEGORIES.map((x) => [x.id, x]));

  function normsFor(stage, sex) {
    const d = stageData(stage, sex);
    return d ? d.norms : null;
  }

  function testsFor(stage, sex) {
    const n = normsFor(stage, sex);
    return n ? TESTS.filter((x) => n[x.id]) : [];
  }

  // Разбор введённого значения. Возвращает число или null.
  // Время: «12:20», «12.20», «12,20», «0:54», «1:27,5»; секунды: «13,2».
  function parseValue(testId, raw) {
    const test = TEST_BY_ID[testId];
    if (!test || raw == null) return null;
    let s = String(raw).trim().replace(/\s+/g, '').replace(/^\+/, '');
    if (!s) return null;
    if (test.kind === 'time') {
      const m = s.match(/^(\d{1,3})[:.,](\d{1,2})(?:[.,](\d{1,2}))?$/);
      if (m) {
        const sec = Number(m[2]);
        if (sec >= 60) return null;
        const frac = m[3] ? Number('0.' + m[3]) : 0;
        return Number(m[1]) * 60 + sec + frac;
      }
      if (/^\d+$/.test(s)) return Number(s); // просто секунды
      return null;
    }
    s = s.replace(',', '.');
    if (!/^-?\d+(\.\d+)?$/.test(s)) return null;
    return Number(s);
  }

  function formatValue(testId, num) {
    const test = TEST_BY_ID[testId];
    if (num == null || !test) return '';
    if (test.kind === 'time') {
      const m = Math.floor(num / 60);
      const rest = num - m * 60;
      const sec = Math.floor(rest);
      const frac = Math.round((rest - sec) * 10);
      return m + ':' + String(sec).padStart(2, '0') + (frac ? ',' + frac : '');
    }
    if (test.kind === 'sec') return num.toFixed(1).replace('.', ',');
    if (testId === 'flex' && num > 0) return '+' + String(num).replace('.', ',');
    return String(num).replace('.', ',');
  }

  // Уровень по одному испытанию: 0 — не выполнено, 1 — бронза, 2 — серебро, 3 — золото.
  function levelFor(stage, sex, testId, num) {
    const n = normsFor(stage, sex);
    const test = TEST_BY_ID[testId];
    if (!n || !n[testId] || num == null || !test) return 0;
    const thr = n[testId];
    let lvl = 0;
    for (let i = 0; i < 3; i++) {
      const ok = test.lower ? num <= thr[i] + 1e-9 : num >= thr[i] - 1e-9;
      if (ok) lvl = i + 1;
    }
    return lvl;
  }

  // Итоговый знак по набору результатов {testId: число}.
  // Знак уровня L: все обязательные категории ступени выполнены не ниже L
  // и качеств (категорий) на уровне не ниже L — сколько требует ступень.
  function badgeFor(stage, sex, values) {
    const best = {}; // категория -> лучший уровень
    const n = normsFor(stage, sex) || {};
    for (const [testId, num] of Object.entries(values || {})) {
      const test = TEST_BY_ID[testId];
      if (!test || !n[testId]) continue; // испытание не своей ступени на знак не влияет
      const lvl = levelFor(stage, sex, testId, num);
      best[test.cat] = Math.max(best[test.cat] || 0, lvl);
    }
    const mandatory = mandatoryFor(stage, sex);
    const required = requiredFor(stage, sex);
    let badge = 0;
    for (let L = 3; L >= 1; L--) {
      if (!mandatory.every((c) => (best[c] || 0) >= L)) continue;
      const count = Object.values(best).filter((v) => v >= L).length;
      if (count >= required[L - 1]) { badge = L; break; }
    }
    return { badge, byCategory: best };
  }

  // Знак и дата его выполнения: день, когда сдан последний норматив, без которого этого знака не было бы.
  // results: { testId: { value, test_date: 'ГГГГ-ММ-ДД' } }.
  function badgeWithDate(stage, sex, results) {
    const entries = Object.entries(results || {}).filter(([, r]) => r && r.value != null);
    const all = badgeFor(stage, sex, Object.fromEntries(entries.map(([k, r]) => [k, r.value])));
    if (!all.badge) return { ...all, date: '' };
    const dates = [...new Set(entries.map(([, r]) => r.test_date || ''))].sort();
    for (const d of dates) {
      const upTo = Object.fromEntries(entries.filter(([, r]) => (r.test_date || '') <= d).map(([k, r]) => [k, r.value]));
      if (badgeFor(stage, sex, upTo).badge >= all.badge) return { ...all, date: d };
    }
    return { ...all, date: dates[dates.length - 1] || '' };
  }

  // Полных лет на дату onDate (строки ГГГГ-ММ-ДД).
  function ageOn(birthDate, onDate) {
    if (!birthDate) return null;
    const [by, bm, bd] = birthDate.split('-').map(Number);
    const [y, m, d] = onDate.split('-').map(Number);
    return y - by - (m < bm || (m === bm && d < bd) ? 1 : 0);
  }

  // Ступень ГТО по возрасту: I 6–7, II 8–9, III 10–11, IV 12–13, V 14–15, VI 16–17, VII 18–19,
  // VIII 20–24, IX 25–29, дальше по пять лет до XVII 65–69 и XVIII 70 лет и старше.
  function stageForAge(age) {
    if (age == null || age < 6) return null;
    if (age < 20) return Math.floor((age - 6) / 2) + 1;
    if (age >= 70) return 18;
    return Math.floor((age - 20) / 5) + 8;
  }

  // УИН ГТО: ГГ-РР-ННННННН (например 23-65-0012345). Принимает и 11 цифр подряд.
  function normalizeUin(raw) {
    const s = String(raw || '').trim();
    if (!s) return '';
    const digits = s.replace(/\D/g, '');
    if (digits.length !== 11 || !/^[\d\s-]+$/.test(s)) return null;
    return `${digits.slice(0, 2)}-${digits.slice(2, 4)}-${digits.slice(4)}`;
  }

  // Дата из «ДД.ММ.ГГГГ», «ГГГГ-ММ-ДД» или числа Excel → «ГГГГ-ММ-ДД» (или null).
  function parseDate(raw) {
    if (raw == null || raw === '') return '';
    let y, m, d;
    const s = String(raw).trim();
    let mt;
    if ((mt = s.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/))) [, d, m, y] = mt.map(Number);
    else if ((mt = s.match(/^(\d{4})-(\d{2})-(\d{2})/))) [, y, m, d] = mt.map(Number);
    else if (/^\d{4,5}(\.\d+)?$/.test(s)) { // серийный номер даты Excel
      const dt = new Date(Date.UTC(1899, 11, 30) + Math.floor(Number(s)) * 864e5);
      [y, m, d] = [dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate()];
    } else return null;
    const dt = new Date(Date.UTC(y, m - 1, d));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
    return dt.toISOString().slice(0, 10);
  }

  const api = {
    CATEGORIES, TESTS, STAGES, STAGE_LIST, ROMAN, LEVELS, LEVEL_NAMES,
    TEST_BY_ID, CAT_BY_ID,
    normsFor, testsFor, requiredFor, mandatoryFor, parseValue, formatValue, levelFor, badgeFor, badgeWithDate,
    ageOn, stageForAge, normalizeUin, parseDate,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GTO = api;
})(typeof window !== 'undefined' ? window : globalThis);
