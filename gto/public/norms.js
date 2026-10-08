// Нормативы ВФСК ГТО, ступени V–IX (источник: gto.ru/normativy, октябрь 2026).
// Файл общий для сервера (require) и браузера (window.GTO).
(function (root) {
  'use strict';

  // Категории (физические качества / навыки). mandatory — обязательные испытания.
  const CATEGORIES = [
    { id: 'speed', name: 'Скоростные возможности', mandatory: true },
    { id: 'endurance', name: 'Выносливость', mandatory: true },
    { id: 'flex', name: 'Гибкость', mandatory: true },
    { id: 'strength', name: 'Сила', mandatory: true },
    { id: 'coord', name: 'Координационные способности', mandatory: false },
    { id: 'power', name: 'Скоростно-силовые возможности', mandatory: false },
    { id: 'applied', name: 'Прикладные навыки', mandatory: false },
  ];

  // kind: 'sec' — секунды с десятыми; 'time' — мин:сек; 'num' — число.
  // lower: true — чем меньше, тем лучше.
  const TESTS = [
    { id: 'run30', cat: 'speed', short: '30 м', name: 'Бег на 30 м', unit: 'с', kind: 'sec', lower: true },
    { id: 'run60', cat: 'speed', short: '60 м', name: 'Бег на 60 м', unit: 'с', kind: 'sec', lower: true },
    { id: 'run100', cat: 'speed', short: '100 м', name: 'Бег на 100 м', unit: 'с', kind: 'sec', lower: true },
    { id: 'run1000', cat: 'endurance', short: '1000 м', name: 'Бег на 1000 м', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'run2000', cat: 'endurance', short: '2000 м', name: 'Бег на 2000 м', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'run3000', cat: 'endurance', short: '3000 м', name: 'Бег на 3000 м', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'cross3', cat: 'endurance', short: 'Кросс 3 км', name: 'Кросс на 3 км (пересечённая местность)', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'cross5', cat: 'endurance', short: 'Кросс 5 км', name: 'Кросс на 5 км (пересечённая местность)', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'ski3', cat: 'endurance', short: 'Лыжи 3 км', name: 'Бег на лыжах 3 км', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'ski5', cat: 'endurance', short: 'Лыжи 5 км', name: 'Бег на лыжах 5 км', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'flex', cat: 'flex', short: 'Наклон', name: 'Наклон вперёд стоя на гимнастической скамье', unit: 'см', kind: 'num', lower: false },
    { id: 'pullHigh', cat: 'strength', short: 'Подтяг. высок.', name: 'Подтягивание из виса на высокой перекладине', unit: 'раз', kind: 'num', lower: false },
    { id: 'pullLow', cat: 'strength', short: 'Подтяг. низк.', name: 'Подтягивание из виса лёжа на низкой перекладине 90 см', unit: 'раз', kind: 'num', lower: false },
    { id: 'pushup', cat: 'strength', short: 'Отжимания', name: 'Сгибание и разгибание рук в упоре лёжа на полу', unit: 'раз', kind: 'num', lower: false },
    { id: 'kettle', cat: 'strength', short: 'Гиря 16 кг', name: 'Рывок гири 16 кг', unit: 'раз', kind: 'num', lower: false },
    { id: 'shuttle', cat: 'coord', short: 'Челнок 3×10', name: 'Челночный бег 3×10 м', unit: 'с', kind: 'sec', lower: true },
    { id: 'jump', cat: 'power', short: 'Прыжок', name: 'Прыжок в длину с места толчком двумя ногами', unit: 'см', kind: 'num', lower: false },
    { id: 'situps', cat: 'power', short: 'Пресс', name: 'Поднимание туловища из положения лёжа на спине за 1 мин', unit: 'раз', kind: 'num', lower: false },
    { id: 'swim50', cat: 'applied', short: 'Плавание 50 м', name: 'Плавание на 50 м', unit: 'мин:с', kind: 'time', lower: true },
    { id: 'shootOpen', cat: 'applied', short: 'Стрельба откр.', name: 'Стрельба 10 м, пневм. винтовка с открытым прицелом', unit: 'очки', kind: 'num', lower: false },
    { id: 'shootDiop', cat: 'applied', short: 'Стрельба диопт.', name: 'Стрельба 10 м, винтовка с диоптрическим прицелом / «электронное оружие»', unit: 'очки', kind: 'num', lower: false },
    { id: 'selfdef', cat: 'applied', short: 'Самозащита', name: 'Самозащита без оружия', unit: 'очки', kind: 'num', lower: false },
    { id: 'hike', cat: 'applied', short: 'Поход', name: 'Туристский поход с проверкой туристских навыков', unit: 'навыков', kind: 'num', lower: false },
    { id: 'throw150', cat: 'applied', short: 'Метание 150 г', name: 'Метание мяча весом 150 г', unit: 'м', kind: 'num', lower: false },
    { id: 'throw500', cat: 'applied', short: 'Метание 500 г', name: 'Метание спортивного снаряда 500 г', unit: 'м', kind: 'num', lower: false },
    { id: 'throw700', cat: 'applied', short: 'Метание 700 г', name: 'Метание спортивного снаряда 700 г', unit: 'м', kind: 'num', lower: false },
  ];

  const STAGES = {
    5: '14–15 лет', 6: '16–17 лет', 7: '18–19 лет', 8: '20–24 лет', 9: '25–29 лет',
  };

  // Для получения знака: [бронза, серебро, золото] испытаний (качеств).
  const REQUIRED = [5, 5, 6];
  const LEVELS = ['bronze', 'silver', 'gold'];
  const LEVEL_NAMES = { gold: 'Золото', silver: 'Серебро', bronze: 'Бронза' };

  const t = (m, s) => m * 60 + s;
  const COMMON = { shootOpen: [15, 20, 25], shootDiop: [18, 25, 30], selfdef: [15, 21, 26], hike: [3, 5, 7] };

  // NORMS[ступень][пол] = { тест: [бронза, серебро, золото] }; время — в секундах.
  const NORMS = {
    5: {
      M: {
        run30: [5.4, 5.0, 4.6], run60: [9.7, 9.1, 8.1],
        run2000: [t(10, 10), t(9, 27), t(8, 0)], cross3: [t(16, 55), t(15, 45), t(14, 10)], ski3: [t(19, 15), t(17, 15), t(16, 5)],
        flex: [4, 6, 11],
        pullHigh: [5, 9, 13], pushup: [19, 25, 37], pullLow: [12, 18, 25],
        shuttle: [8.2, 7.7, 7.1],
        jump: [167, 193, 218], situps: [34, 40, 50],
        swim50: [t(1, 27), t(1, 13), t(0, 54)], throw150: [30, 35, 41], ...COMMON,
      },
      F: {
        run30: [5.7, 5.3, 4.9], run60: [10.8, 10.2, 9.5],
        run2000: [t(12, 40), t(11, 27), t(9, 55)], cross3: [t(19, 55), t(18, 5), t(16, 40)], ski3: [t(22, 55), t(20, 25), t(19, 5)],
        flex: [5, 8, 15],
        pushup: [7, 11, 16], pullLow: [9, 13, 19],
        shuttle: [9.1, 8.7, 7.9],
        jump: [148, 162, 183], situps: [31, 35, 44],
        swim50: [t(1, 32), t(1, 18), t(1, 1)], throw150: [19, 21, 27], ...COMMON,
      },
    },
    6: {
      M: {
        run60: [9.0, 8.4, 7.9], run100: [14.8, 14.1, 13.2],
        run3000: [t(15, 20), t(14, 10), t(12, 20)], cross5: [t(27, 0), t(25, 0), t(23, 0)], ski5: [t(27, 55), t(25, 45), t(23, 40)],
        flex: [6, 8, 13],
        pullHigh: [8, 12, 15], pushup: [25, 32, 43], kettle: [14, 19, 34],
        jump: [192, 213, 235], situps: [35, 41, 51],
        swim50: [t(1, 20), t(1, 5), t(0, 49)], throw700: [27, 30, 36], ...COMMON,
      },
      F: {
        run60: [10.7, 9.9, 9.2], run100: [17.9, 16.9, 15.8],
        run2000: [t(12, 25), t(11, 10), t(9, 45)], cross3: [t(19, 25), t(17, 35), t(16, 5)], ski3: [t(20, 30), t(18, 35), t(16, 40)],
        flex: [7, 9, 16],
        pushup: [8, 12, 17], pullLow: [10, 14, 20],
        jump: [157, 173, 188], situps: [32, 37, 45],
        swim50: [t(1, 45), t(1, 18), t(1, 0)], throw500: [12, 17, 22], ...COMMON,
      },
    },
    7: {
      M: {
        run60: [8.9, 8.4, 7.9], run100: [14.8, 14.1, 13.2],
        run3000: [t(15, 20), t(14, 10), t(12, 20)], cross5: [t(27, 0), t(25, 0), t(23, 0)], ski5: [t(28, 0), t(25, 40), t(23, 30)],
        flex: [6, 8, 13],
        pullHigh: [8, 12, 15], pushup: [25, 32, 43], kettle: [14, 19, 35],
        jump: [192, 213, 233], situps: [34, 41, 51],
        swim50: [t(1, 17), t(1, 3), t(0, 49)], throw700: [27, 29, 36], ...COMMON,
      },
      F: {
        run60: [10.7, 9.9, 9.2], run100: [17.9, 16.9, 15.8],
        run2000: [t(12, 20), t(11, 5), t(9, 40)], cross3: [t(19, 20), t(17, 40), t(16, 10)], ski3: [t(19, 20), t(17, 40), t(16, 40)],
        flex: [7, 9, 16],
        pushup: [8, 12, 17], pullLow: [10, 14, 20],
        jump: [157, 173, 188], situps: [31, 37, 45],
        swim50: [t(1, 30), t(1, 16), t(1, 0)], throw500: [13, 16, 20], ...COMMON,
      },
    },
    8: {
      M: {
        run60: [9.1, 8.5, 8.0], run100: [15.8, 14.4, 13.9],
        run3000: [t(14, 50), t(13, 20), t(12, 0)], cross5: [t(26, 30), t(24, 30), t(21, 30)], ski5: [t(27, 30), t(25, 0), t(21, 35)],
        flex: [6, 8, 13],
        pullHigh: [9, 13, 16], pushup: [27, 33, 45], kettle: [20, 26, 44],
        jump: [207, 228, 244], situps: [32, 38, 50],
        swim50: [t(1, 15), t(0, 58), t(0, 48)], throw700: [32, 36, 38], ...COMMON,
      },
      F: {
        run60: [11.1, 10.3, 9.5], run100: [18.1, 17.1, 16.2],
        run1000: [t(4, 35), t(4, 15), t(4, 0)], run2000: [t(13, 25), t(12, 15), t(10, 40)],
        cross3: [t(19, 35), t(18, 10), t(17, 10)], ski3: [t(21, 30), t(19, 20), t(17, 50)],
        flex: [8, 11, 16],
        pushup: [9, 13, 18], pullLow: [9, 13, 19],
        jump: [167, 183, 198], situps: [31, 36, 45],
        swim50: [t(1, 28), t(1, 13), t(0, 58)], throw500: [13, 18, 22], ...COMMON,
      },
    },
    9: {
      M: {
        run60: [9.6, 9.0, 8.1], run100: [15.3, 14.6, 13.6],
        run3000: [t(15, 20), t(14, 20), t(12, 30)], cross5: [t(27, 0), t(25, 30), t(22, 0)], ski5: [t(28, 0), t(26, 0), t(22, 0)],
        flex: [5, 7, 12],
        pullHigh: [6, 10, 14], pushup: [21, 25, 40], kettle: [18, 24, 41],
        jump: [202, 223, 239], situps: [29, 36, 47],
        swim50: [t(1, 17), t(1, 3), t(0, 53)], throw700: [32, 36, 38], ...COMMON,
      },
      F: {
        run60: [11.4, 10.5, 9.8], run100: [19.1, 17.9, 16.7],
        run1000: [t(5, 10), t(4, 40), t(4, 20)], run2000: [t(14, 20), t(12, 50), t(11, 15)],
        cross3: [t(22, 30), t(19, 50), t(17, 40)], ski3: [t(23, 0), t(20, 20), t(18, 10)],
        flex: [7, 9, 14],
        pushup: [8, 12, 17], pullLow: [8, 12, 18],
        jump: [163, 178, 193], situps: [23, 30, 38],
        swim50: [t(1, 30), t(1, 15), t(0, 59)], throw500: [12, 16, 19], ...COMMON,
      },
    },
  };

  const TEST_BY_ID = Object.fromEntries(TESTS.map((x) => [x.id, x]));
  const CAT_BY_ID = Object.fromEntries(CATEGORIES.map((x) => [x.id, x]));

  function normsFor(stage, sex) {
    return (NORMS[stage] && NORMS[stage][sex]) || null;
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
  // Знак уровня L: все 4 обязательные категории выполнены не ниже L
  // и общее число категорий не ниже L >= REQUIRED[L].
  function badgeFor(stage, sex, values) {
    const best = {}; // категория -> лучший уровень
    for (const [testId, num] of Object.entries(values || {})) {
      const test = TEST_BY_ID[testId];
      if (!test) continue;
      const lvl = levelFor(stage, sex, testId, num);
      best[test.cat] = Math.max(best[test.cat] || 0, lvl);
    }
    const mandatory = CATEGORIES.filter((c) => c.mandatory).map((c) => c.id);
    let badge = 0;
    for (let L = 3; L >= 1; L--) {
      if (!mandatory.every((c) => (best[c] || 0) >= L)) continue;
      const count = Object.values(best).filter((v) => v >= L).length;
      if (count >= REQUIRED[L - 1]) { badge = L; break; }
    }
    return { badge, byCategory: best };
  }

  const api = {
    CATEGORIES, TESTS, STAGES, NORMS, REQUIRED, LEVELS, LEVEL_NAMES,
    TEST_BY_ID, CAT_BY_ID,
    normsFor, testsFor, parseValue, formatValue, levelFor, badgeFor,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.GTO = api;
})(typeof window !== 'undefined' ? window : globalThis);
