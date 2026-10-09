'use strict';
// Собирает public/norms-data.js из таблиц norms-src/<M|F><ступень>.txt (переписаны с gto.ru/normativy).
// Формат таблицы: «@mandatory» / «@choice» — раздел, «#Категория», строки «Название (ед.)|золото|серебро|бронза»,
// «=cat|з|с|б» — сколько качеств нужно на знак. Запуск: node tools/build-norms.js
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const SRC = path.join(ROOT, 'norms-src');
const OUT = path.join(ROOT, 'public', 'norms-data.js');

const CATEGORIES = [
  ['speed', 'Скоростные возможности'],
  ['endurance', 'Выносливость'],
  ['flex', 'Гибкость'],
  ['strength', 'Сила'],
  ['power', 'Скоростно-силовые возможности'],
  ['coord', 'Координационные способности'],
  ['applied', 'Прикладные навыки'],
];
const CAT_BY_NAME = Object.fromEntries(CATEGORIES.map(([id, name]) => [name, id]));

// Справочник испытаний: id, категория, краткое и полное название, единица, вид значения, «меньше — лучше»,
// и как узнать испытание в названии с gto.ru (названия на сайте пишутся по-разному: «на лыжах 2 км» и «на лыжах на 2 км»).
// kind: sec — секунды с десятыми; time — мин:сек; num — число.
const T = (id, cat, short, name, unit, kind, lower, re) => ({ id, cat, short, name, unit, kind, lower, re });
const TESTS = [
  T('run10', 'speed', '10 м', 'Бег на 10 м', 'с', 'sec', true, /^Бег 10 м/),
  T('run30', 'speed', '30 м', 'Бег на 30 м', 'с', 'sec', true, /^Бег (на )?30 м/),
  T('run60', 'speed', '60 м', 'Бег на 60 м', 'с', 'sec', true, /^Бег на 60 м/),
  T('run100', 'speed', '100 м', 'Бег на 100 м', 'с', 'sec', true, /^Бег на 100 м/),
  T('run6min', 'endurance', '6-мин. бег', 'Шестиминутный бег', 'м', 'num', false, /^Шестиминутный бег/),
  T('mixedCrossM', 'endurance', 'Смеш. перел.', 'Смешанное передвижение по пересечённой местности (дистанция за время)', 'м', 'num', false, /^Смешанное передвижение по пересеченной местности \(м\)/),
  T('skiM', 'endurance', 'Ходьба на лыжах', 'Ходьба на лыжах (дистанция за время)', 'м', 'num', false, /^Ходьба на лыжах \(м\)/),
  T('mixed1000', 'endurance', 'Смеш. 1000 м', 'Смешанное передвижение на 1000 м', 'мин:с', 'time', true, /^Смешанное передвижение на 1000/),
  T('mixed2000', 'endurance', 'Смеш. 2000 м', 'Смешанное передвижение на 2000 м', 'мин:с', 'time', true, /^Смешанное передвижение на 2000/),
  T('mixedCross1', 'endurance', 'Пересеч. 1 км', 'Смешанное передвижение по пересечённой местности на 1 км', 'мин:с', 'time', true, /^Смешанное передвижение по пересеченной местности на 1 км/),
  T('run1000', 'endurance', '1000 м', 'Бег на 1000 м', 'мин:с', 'time', true, /^Бег на 1000 м/),
  T('run1500', 'endurance', '1500 м', 'Бег на 1500 м', 'мин:с', 'time', true, /^Бег (н[аa]|a) 1500/),
  T('run2000', 'endurance', '2000 м', 'Бег на 2000 м', 'мин:с', 'time', true, /^Бег н[аa] 2000 м/),
  T('run3000', 'endurance', '3000 м', 'Бег на 3000 м', 'мин:с', 'time', true, /^Бег на 3000 м/),
  T('cross2', 'endurance', 'Кросс 2 км', 'Кросс на 2 км (пересечённая местность)', 'мин:с', 'time', true, /^Кросс на 2 км/),
  T('cross3', 'endurance', 'Кросс 3 км', 'Кросс на 3 км (пересечённая местность)', 'мин:с', 'time', true, /^Кросс на 3 км/),
  T('cross5', 'endurance', 'Кросс 5 км', 'Кросс на 5 км (пересечённая местность)', 'мин:с', 'time', true, /^Кросс на 5 км/),
  T('ski1', 'endurance', 'Лыжи 1 км', 'Бег на лыжах 1 км', 'мин:с', 'time', true, /^Бег на лыжах (на )?1 км/),
  T('ski2', 'endurance', 'Лыжи 2 км', 'Бег (передвижение) на лыжах 2 км', 'мин:с', 'time', true, /^(Бег|Передвижение) на лыжах (на )?2 км/),
  T('ski3', 'endurance', 'Лыжи 3 км', 'Бег (передвижение) на лыжах 3 км', 'мин:с', 'time', true, /^(Бег|Передвижение) на лыжах (на )?3 км/),
  T('ski5', 'endurance', 'Лыжи 5 км', 'Бег на лыжах 5 км', 'мин:с', 'time', true, /^Бег на лыжах (на )?5 км/),
  T('walk3', 'endurance', 'Сканд. ходьба', 'Скандинавская ходьба на 3 км', 'мин:с', 'time', true, /^Скандинавская ходьба на 3 км/),
  T('flex', 'flex', 'Наклон', 'Наклон вперёд стоя на гимнастической скамье', 'см', 'num', false, /^Наклон вперед/),
  T('pullHigh', 'strength', 'Подтяг. высок.', 'Подтягивание из виса на высокой перекладине', 'раз', 'num', false, /^Подтягивание из виса на высокой/),
  T('pullLow', 'strength', 'Подтяг. низк.', 'Подтягивание из виса лёжа на низкой перекладине 90 см', 'раз', 'num', false, /^Подтягивание из виса лежа на низкой/),
  T('pushup', 'strength', 'Отжимания', 'Сгибание и разгибание рук в упоре лёжа на полу', 'раз', 'num', false, /^Сгибание и разгибание рук в упоре лёжа на полу/),
  T('pushBench', 'strength', 'Отжим. скамья', 'Сгибание и разгибание рук в упоре о гимнастическую скамью', 'раз', 'num', false, /^Сгибание и разгибание рук в упоре о гимнастическую скамью/),
  T('pushChair', 'strength', 'Отжим. стул', 'Сгибание и разгибание рук в упоре о сиденье стула', 'раз', 'num', false, /^Сгибание и разгибание рук в упоре о сиденье стула/),
  T('kettle', 'strength', 'Гиря 16 кг', 'Рывок гири 16 кг', 'раз', 'num', false, /^Рывок гири 16 кг/),
  T('ballThrow', 'power', 'Набивной мяч', 'Бросок набивного мяча 1 кг из-за головы', 'см', 'num', false, /^Бросок набивного мяча/),
  T('jump', 'power', 'Прыжок', 'Прыжок в длину с места толчком двумя ногами', 'см', 'num', false, /^Прыжок в длину с места/),
  T('situps30', 'power', 'Пресс 30 с', 'Поднимание туловища из положения лёжа на спине за 30 с', 'раз', 'num', false, /^Поднимание туловища.*30 с/),
  T('situps', 'power', 'Пресс', 'Поднимание туловища из положения лёжа на спине за 1 мин', 'раз', 'num', false, /^Поднимание туловища.*1 мин/),
  T('target5', 'coord', 'Мяч в цель 5 м', 'Метание теннисного мяча в цель, 5 м (попаданий из 5)', 'попад.', 'num', false, /^Метание теннисного мяча в цель, дистанция 5 м/),
  T('target6', 'coord', 'Мяч в цель 6 м', 'Метание теннисного мяча в цель, 6 м', 'попад.', 'num', false, /^Метание теннисного мяча в цель, дистанция 6 м/),
  T('shuttle', 'coord', 'Челнок 3×10', 'Челночный бег 3×10 м', 'с', 'sec', true, /^Челночный бег 3x10/),
  T('swimM', 'applied', 'Плавание', 'Плавание (дистанция без учёта времени)', 'м', 'num', false, /^Плавание \(м\)/),
  T('swim25', 'applied', 'Плавание 25 м', 'Плавание на 25 м', 'мин:с', 'time', true, /^Плавание на 25 м/),
  T('swim50', 'applied', 'Плавание 50 м', 'Плавание на 50 м', 'мин:с', 'time', true, /^Плавание на 50 м/),
  T('mixedCross2', 'applied', 'Пересеч. 2 км', 'Смешанное передвижение по пересечённой местности на 2 км', 'мин:с', 'time', true, /^Смешанное передвижение по пересеченной местности на 2 км/),
  T('mixedCross3', 'applied', 'Пересеч. 3 км', 'Смешанное передвижение по пересечённой местности на 3 км', 'мин:с', 'time', true, /^Смешанное передвижение по пересеченной местности на 3 км/),
  T('throw150', 'applied', 'Метание 150 г', 'Метание мяча весом 150 г', 'м', 'num', false, /^Метание мяча весом 150 г/),
  T('throw500', 'applied', 'Метание 500 г', 'Метание спортивного снаряда 500 г', 'м', 'num', false, /^Метание спортивного снаряда:? весом 500 г/),
  T('throw700', 'applied', 'Метание 700 г', 'Метание спортивного снаряда 700 г', 'м', 'num', false, /^Метание спортивного снаряда:? весом 700 г/),
  T('shootOpen', 'applied', 'Стрельба откр.', 'Стрельба 10 м, пневм. винтовка с открытым прицелом', 'очки', 'num', false, /^Стрельба/),
  T('shootDiop', 'applied', 'Стрельба диопт.', 'Стрельба 10 м, винтовка с диоптрическим прицелом / «электронное оружие»', 'очки', 'num', false, /^или из пневматической винтовки с диоптрическим/),
  T('selfdef', 'applied', 'Самозащита', 'Самозащита без оружия', 'очки', 'num', false, /^Самозащита без оружия/),
  T('hike', 'applied', 'Поход', 'Туристский поход с проверкой туристских навыков', 'навыков', 'num', false, /^Туристский поход/),
];

function parseNum(test, raw) {
  let s = String(raw).trim().replace(/\s+/g, '');
  if (/^\d+-\d+$/.test(s)) s = s.split('-')[0];            // «26-30» очков — нижняя граница
  if (test.kind === 'time') {
    const m = s.match(/^(\d{1,3})[:.,](\d{2})$/);             // «9:11», на сайте бывает и «9,11»
    if (!m) throw new Error(`время «${raw}»`);
    return Number(m[1]) * 60 + Number(m[2]);
  }
  s = s.replace(',', '.').replace(/^\+/, '');
  if (!/^-?\d+(\.\d+)?$/.test(s)) throw new Error(`число «${raw}»`);
  return Number(s);
}

const STAGES = {};
const problems = [];
for (const file of fs.readdirSync(SRC).filter((f) => /^[MF]\d+\.txt$/.test(f)).sort()) {
  const sex = file[0];
  const lines = fs.readFileSync(path.join(SRC, file), 'utf8').split('\n');
  let stage, ages, section, cat;
  const norms = {};
  const mand = new Set();
  const cats = new Set();
  let req;
  for (const raw of lines) {
    const l = raw.trim();
    if (!l) continue;
    if (l.startsWith('stage ')) stage = Number(l.slice(6));
    else if (l.startsWith('ages ')) ages = l.slice(5);
    else if (l.startsWith('@')) section = l.slice(1);
    else if (l.startsWith('#')) {
      cat = CAT_BY_NAME[l.slice(1)];
      if (!cat) problems.push(`${file}: неизвестная категория «${l}»`);
      cats.add(cat);
      if (section === 'mandatory') mand.add(cat);
    } else if (l.startsWith('=cat|')) {
      const [g, s, b] = l.split('|').slice(1).map(Number);
      req = [b, s, g];
    } else if (l.includes('|') && !l.startsWith('=')) {
      const [name, g, s, b] = l.split('|');
      const test = TESTS.find((t) => t.re.test(name));
      if (!test) { problems.push(`${file}: не узнал испытание «${name}»`); continue; }
      if (test.cat !== cat) problems.push(`${file}: «${name}» в категории ${cat}, в справочнике ${test.cat}`);
      if (norms[test.id]) problems.push(`${file}: испытание ${test.id} дважды`);
      try {
        const v = [b, s, g].map((x) => parseNum(test, x));
        const ok = test.lower ? v[0] >= v[1] && v[1] >= v[2] : v[0] <= v[1] && v[1] <= v[2];
        if (!ok) problems.push(`${file}: ${test.id} — уровни не по порядку: ${v}`);
        norms[test.id] = v;
      } catch (e) { problems.push(`${file}: ${test.id}: ${e.message}`); }
    }
  }
  if (!stage || !req) problems.push(`${file}: нет ступени или числа качеств`);
  STAGES[stage] = STAGES[stage] || { ages };
  STAGES[stage][sex] = { mandatory: CATEGORIES.map(([id]) => id).filter((id) => mand.has(id)), required: req, norms };
}
for (let s = 1; s <= 18; s++) for (const sex of ['M', 'F']) if (!STAGES[s] || !STAGES[s][sex]) problems.push(`нет ступени ${s}${sex}`);
if (problems.length) {
  console.error('Ошибки в таблицах нормативов:\n' + problems.join('\n'));
  process.exit(1);
}

const used = new Set(Object.values(STAGES).flatMap((st) => ['M', 'F'].flatMap((x) => Object.keys(st[x].norms))));
const data = {
  CATEGORIES: CATEGORIES.map(([id, name]) => ({ id, name })),
  TESTS: TESTS.filter((t) => used.has(t.id)).map(({ re, ...t }) => t),
  STAGES,
};
const out = `// Сгенерировано tools/build-norms.js из norms-src/*.txt (gto.ru/normativy). Не править вручную.
(function (root) {
  'use strict';
  const data = ${JSON.stringify(data)};
  if (typeof module !== 'undefined' && module.exports) module.exports = data;
  else root.GTO_DATA = data;
})(typeof window !== 'undefined' ? window : globalThis);
`;
fs.writeFileSync(OUT, out);
console.log(`norms-data.js: ступеней ${Object.keys(STAGES).length}, испытаний ${data.TESTS.length}`);
