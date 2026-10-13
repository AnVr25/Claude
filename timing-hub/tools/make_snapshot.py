#!/usr/bin/env python3
"""Собирает system_final_snapshot.md — полный технический дамп Мастера протоколов для внешнего аудита.

Код в дамп попадает ДОСЛОВНО из исходников (ast и срезы по строкам), поэтому дамп не расходится с репозиторием.
Запуск из корня проекта:  python3 tools/make_snapshot.py
"""
import ast
import datetime as dt
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HUB = os.path.join(ROOT, "hub")
sys.path.insert(0, HUB)
import hub as H  # noqa: E402

PY = open(os.path.join(HUB, "hub.py"), encoding="utf-8").read()
UI = open(os.path.join(HUB, "ui.html"), encoding="utf-8").read()
PR = open(os.path.join(HUB, "protocol.html"), encoding="utf-8").read()
TREE = ast.parse(PY)
OUT = []


def w(s=""):
    OUT.append(s)


def code(lang, text):
    w(f"```{lang}\n{text.rstrip()}\n```\n")


def py_func(cls, name):
    """Метод класса целиком (с декораторами) и номера строк в hub/hub.py."""
    for c in TREE.body:
        if isinstance(c, ast.ClassDef) and c.name == cls:
            for f in c.body:
                if isinstance(f, ast.FunctionDef) and f.name == name:
                    start = min([f.lineno] + [d.lineno for d in f.decorator_list])
                    lines = PY.splitlines()[start - 1:f.end_lineno]
                    return start, f.end_lineno, "\n".join(lines)
    raise KeyError(f"{cls}.{name}")


def py_const(cls, name):
    for c in TREE.body:
        if isinstance(c, ast.ClassDef) and c.name == cls:
            for n in c.body:
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == name for t in n.targets):
                    return n.lineno, n.end_lineno, "\n".join(PY.splitlines()[n.lineno - 1:n.end_lineno])
    raise KeyError(name)


def py_block(pattern, indent=8):
    """Ветка `if action == "...":` из Hub._api_*: от строки-условия до следующего `if` того же отступа."""
    lines = PY.splitlines()
    pad = " " * indent
    for i, ln in enumerate(lines):
        if re.match(rf"^{pad}{pattern}", ln):
            j = i + 1
            while j < len(lines) and not (re.match(rf"^{pad}(if|return|m = |# )", lines[j]) and not lines[j].startswith(pad + " ")):
                j += 1
            return i + 1, j, "\n".join(lines[i:j])
    raise KeyError(pattern)


def js_decl(src, name, kind="function"):
    """Верхнеуровневая декларация JS по имени: от строки до следующей декларации с нулевым отступом."""
    lines = src.splitlines()
    pat = re.compile(rf"^(async\s+)?function\s+{re.escape(name)}\b|^(const|let|var)\s+{re.escape(name)}\b")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            j = i + 1
            while j < len(lines):
                s = lines[j]
                if s and not s[0].isspace() and not s.startswith(("}", ")", "]")):
                    break
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            return i + 1, j, "\n".join(lines[i:j])
    raise KeyError(name)


def js_block(src, start_marker, end_marker):
    a = src.index(start_marker)
    b = src.index(end_marker, a)
    return src[:a].count("\n") + 1, src[:b].count("\n"), src[a:b]


def css_media(src, head):
    """@media-блок с нулевым отступом: от строки head до закрывающей скобки на нулевом отступе."""
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        if (ln.startswith(head) and head != "@media print{") or ln.rstrip() == head:
            if ln.rstrip().endswith("}") and ln.count("{") == ln.count("}"):
                return i + 1, i + 1, ln
            j = i + 1
            while not lines[j].startswith("}"):
                j += 1
            return i + 1, j + 1, "\n".join(lines[i:j + 1])
    raise KeyError(head)


def ref(path, a, b):
    return f"`{path}` строки {a}–{b}"


# ------------------------------------------------------------------ данные для шапки
git = lambda *a: subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
branch, commit = git("rev-parse", "--abbrev-ref", "HEAD"), git("rev-parse", "--short", "HEAD")
selftest = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "selftest.py")], capture_output=True, text=True)
st_tail = [ln for ln in selftest.stdout.splitlines() if ln.startswith("Итого") or ln.startswith("Всё") or ln.startswith("ЕСТЬ")]
st_checks = [ln for ln in selftest.stdout.splitlines() if re.match(r"\[OK  \] (3\.[4-6]|3\.5|3\.6)", ln)]
norms = H.Hub.rank_norms()["data"]

w(f"# system_final_snapshot — полный технический дамп SakhStart timing-hub, Мастер протоколов v3.7")
w()
w(f"- **Версия сервера (`VERSION`):** `{H.VERSION}` (линейка v3.7: вкладки групп и отдельный лист на каждую категорию)")
w(f"- **Дата сборки (`BUILD_DATE`):** `{H.BUILD_DATE}`")
w(f"- **Ветка / коммит:** `{branch}` / `{commit}`")
w(f"- **Дамп сформирован:** {dt.datetime.now():%Y-%m-%d %H:%M} скриптом `tools/make_snapshot.py` (код ниже вставлен дословно из исходников)")
w(f"- **Автопроверки:** {' · '.join(st_tail)}")
w(f"- **Объём исходников:** `hub/hub.py` {PY.count(chr(10))} строк, `hub/ui.html` {UI.count(chr(10))}, `hub/protocol.html` {PR.count(chr(10))}")
w()
w("> Для аудитора. Что в дампе: (1) назначение и архитектура, (2) схема SQLite, (3) весь Python Мастера, (4) весь JavaScript, "
  "(5) CSS печати, (6) API, (7) тесты, (8) известные ограничения и места, где фактическая реализация отличается от формулировок ТЗ.")
w()

# ------------------------------------------------------------------ 0. что реализовано
w("## 0. Что реализовано (соответствие ТЗ)")
w()
w("| Требование | Где реализовано | Статус |")
w("|---|---|---|")
w("| Автоопределение Бег / Техника | `Hub.discipline_kind`, `Hub.result_type`, `Hub.attempt_slots` (справочник `hub/seed/disciplines.json`); в браузере `wzp` → `kindOf` | ✅ |")
w("| Бег: вертикальный бланк, 3 поля «Сек. 1–3» | `protocol.html`: `startSheet()` → `table()` (ветка `grid=false`), `setPage(false)` | ✅ |")
w("| Техника: сквозной «Общий список» без дорожек | `Hub.generate_scoped` (`tech → plan.append(... use_lanes=False)`), блокировка на сервере | ✅ |")
w("| Техника: альбомный лист, 6 попыток + «Лучший результат» | `protocol.html`: `isTech`, `table()` (`N=6`), `setPage(true)`, `@page … landscape` | ✅ |")
w("| Мастер: фильтры пол / возрастные группы (AGES) | `ui.html`: `wzp` шаг 1; сервер: `Hub.AGE_LIMITS`, `generate_scoped(scope.ages, scope.sex)` | ✅ |")
w("| Сетка / сквозной список, генерация, сброс `reset_heats` с подтверждением | `wzp` шаг 2: `gen()`, `reset()`; `Hub.generate_scoped`, `Hub.reset_heats` | ✅ |")
w("| Ручной ввод на финише / на секторе | `wzp` шаг 4: `step4()`, `saveRows()`; `POST /api/events/<id>/results` | ✅ |")
w("| Корзина печати, `page-break-after: always` | `ui.html`: `cartAdd`, `renderCart`; `protocol.html`: `renderCart()` (`.cp{page-break-after:always}`) | ✅ |")
w("| Публикация на внешний сайт | `ui.html`: обработчик `[data-cart=publish]`; `POST /api/events/<id>/publish` | ✅ (см. §8.3) |")
w("| Обязательное «Разряд / Звание» | `Hub.check_person` (400, поле `rank`), `regs/<id>` (отказ сохранения карточки), `ui.html`: `mAdd`, `nRank` | ✅ |")
w("| Выполненный разряд по нормам ЕВСК | `Hub.rank_for`, `hub/seed/rank_norms.json`, `tools/norms_import.py` | ✅ (сверх ТЗ) |")
w()

# ------------------------------------------------------------------ 1. архитектура
w("## 1. Архитектура")
w()
w("- Один процесс Python 3 (`asyncio`), один файл `hub/hub.py`, БД SQLite (`PRAGMA journal_mode=WAL`), без внешних зависимостей сервера.")
w("- Админка: одностраничное приложение `hub/ui.html` (hash-маршруты `#reg`, `#wizard`, …), общается с сервером через `/api/…` (cookie-сессия, заголовок `X-Requested-With: timing-hub` обязателен для POST).")
w("- Печатные формы: `hub/protocol.html` — **единая** страница для админки (`/protocol?event=ID&…`) и публичного сайта (`/r/<slug>/protocol`). **Шаблоны таблиц (`table()`) находятся здесь, а не в `ui.html`.**")
w("- Публичный сайт: `reg.html`, `series.html`; публичный API `/r/<slug>/…` (`startlist.json`, `results.json`) отдаёт данные только при `pub_start` / `pub_results`.")
w("- Обновление: `GET /api/system/update/github/check` → `POST …/update/github` → `…/update/install` (ветка `claude/greeting-d2g8ji`, см. `docs/github-update.md`).")
w()
w("Поток данных Мастера: `заявки (registrations)` → `generate_scoped` → `waves` + `entries` → `startlist()` → `protocol.html` (бланк) → судьи пишут на бумаге → секретарь вводит → `results` action (`stopwatch_main` / `parse_attempts`) → `entries.result/detail/done_rank` → `compute()` → `results` JSON → итоговый протокол.")
w()

# ------------------------------------------------------------------ 2. схема БД
w("## 2. [СХЕМА БД SQLITE]")
w()
tmp = tempfile.mkdtemp(prefix="snap-")
H.Store(os.path.join(tmp, "snap.db"))
con = sqlite3.connect(os.path.join(tmp, "snap.db"))
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
w("Схема получена запуском `Store(...)` на пустой БД (создание + все миграции `_migrate`), то есть показывает **итоговое** состояние. "
  f"Таблицы: {', '.join(f'`{t}`' for t in tables)}.")
w()
for t in ("events", "waves", "entries", "registrations", "manual"):
    cols = con.execute(f"PRAGMA table_info({t})").fetchall()
    w(f"### Таблица `{t}`")
    w()
    w("| # | поле | тип | NOT NULL | по умолчанию | PK |")
    w("|---|---|---|---|---|---|")
    for cid, name, typ, nn, dflt, pk in cols:
        w(f"| {cid} | `{name}` | {typ or ''} | {'да' if nn else ''} | {dflt if dflt is not None else ''} | {'да' if pk else ''} |")
    w()
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0]
    code("sql", sql)
    idx = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (t,))]
    if idx:
        code("sql", ";\n".join(idx) + ";")
w("Замечания по схеме:")
w()
w("- `entries`: первичный ключ `(event_id, chip)`; уникальность номера `bib` **контролируется кодом** (`clean_bib`, `rename_bib`, `next_bib`), а не индексом. "
  "Номер без чипа хранится как чип `#<bib>`.")
w("- Поля, добавленные в линейке 3.x: `entries.rank` (разряд из заявки), `entries.detail` (JSON `{\"t\":[3 секундомера],\"a\":[попытки]}`), "
  "`entries.picked_at` (выдача номера), `entries.members` (состав эстафеты), `entries.done_rank` (**3.5**, выполненный разряд), `registrations.rank`, `events.pub_start` / `events.pub_results` / `events.level`.")
w("- `waves.distance` пуст у смешанного «общего списка» (глобальная сборка) — поэтому дисциплина участника берётся из `registrations.distance` через `entries.reg_id` (`Hub.entry_dists`).")
w("- Миграции идемпотентны: `Store._migrate` через `add(table, columns)` (`ALTER TABLE … ADD COLUMN`, если столбца нет).")
w()
for fn in ("_migrate",):
    a, b, src = py_func("Store", fn)
    w(f"### `Store.{fn}` — {ref('hub/hub.py', a, b)}")
    w()
    code("python", src)

# ------------------------------------------------------------------ 3. Python
w("## 3. [ВЕСЬ ИЗМЕНЁННЫЙ КОД PYTHON] — `hub/hub.py`")
w()
w("Примечание: функции `add_entry`, `get_next_bib`, `next_bib` приведены как есть. Отдельной функции «автоопределения официального времени» нет: "
  "правило ручного хронометража реализовано в `stopwatch_main`, а вызывается из ветки `results` (§3.6).")
w()
sections = [
    ("3.1 Определение типа дисциплины (Бег / Техника)", [
        ("Hub", "discipline"), ("Hub", "result_type"), ("Hub", "discipline_kind"), ("Hub", "attempt_slots"), ("Hub", "entry_dists")]),
    ("3.2 Формирование сетки: полная и выборочная (Мастер)", [
        ("Hub", "generate_scoped"), ("Hub", "generate_heats"), ("Hub", "lane_order"), ("Hub", "reset_heats")]),
    ("3.3 Номера и участники", [
        ("Store", "get_next_bib"), ("Store", "add_entry"), ("Store", "set_entries"), ("Store", "upsert_entries"),
        ("Store", "update_entry"), ("Store", "rename_bib"), ("Hub", "next_bib")]),
    ("3.4 Список для печати", [("Hub", "startlist"), ("Hub", "public_startlist")]),
    ("3.5 Хранение результата и отметок", [("Store", "set_entry_result")]),
    ("3.6 Официальное время по 3 секундомерам и лучший результат из 6 попыток", [
        ("Hub", "round_up_tenth"), ("Hub", "stopwatch_main"), ("Hub", "parse_result"), ("Hub", "fmt_result"),
        ("Hub", "parse_typed"), ("Hub", "parse_attempts"), ("Hub", "result_hint")]),
    ("3.7 Выполненный разряд по нормам ЕВСК", [
        ("Hub", "norm_key"), ("Hub", "rank_norms"), ("Hub", "age_group"), ("Hub", "rank_for"), ("Hub", "norm_rank")]),
]
for title, items in sections:
    w(f"### {title}")
    w()
    for cls, name in items:
        try:
            a, b, src = py_func(cls, name)
        except KeyError:
            continue
        w(f"#### `{cls}.{name}` — {ref('hub/hub.py', a, b)}")
        w()
        code("python", src)
    if title.startswith("3.2"):
        a, b, src = py_const("Hub", "AGE_LIMITS")
        w(f"#### `Hub.AGE_LIMITS` — {ref('hub/hub.py', a, b)}")
        w()
        code("python", src)
    if title.startswith("3.7"):
        for nm in ("RANK_ORDER", "RANK_MIN_AGE", "RANK_CAP"):
            a, b, src = py_const("Hub", nm)
            w(f"#### `Hub.{nm}` — {ref('hub/hub.py', a, b)}")
            w()
            code("python", src)

w("### 3.8 Ветки HTTP-API Мастера (внутри `Hub._api_event`)")
w()
for pat, label in ((r'if action == "heats":', "heats — формирование сетки (полное и выборочное)"),
                   (r'if action == "resetheats":', "resetheats — сброс сетки (всей или одной дисциплины)"),
                   (r'if action == "publish":', "publish — выгрузка в общую сеть"),
                   (r'if action == "entry":', "entry — перенос участника, смена номера, добавление заявки в забег (прикладной «add_entry»)"),
                   (r'if action == "results" and isinstance', "results — ручной ввод: секундомеры, попытки, статус, выполненный разряд")):
    a, b, src = py_block(pat)
    w(f"#### `{label}` — {ref('hub/hub.py', a, b)}")
    w()
    code("python", src)

a, b, src = py_func("Hub", "compute")
seg = src.split("\n")
w(f"### 3.9 `Hub.compute` (итоговые результаты) — {ref('hub/hub.py', a, b)}")
w()
w("Дословно: включает дисциплину участника (`entry_dists`), места по дисциплине в смешанном забеге и расчёт `done_rank`.")
w()
code("python", src)

# ------------------------------------------------------------------ 4. JavaScript
w("## 4. [ВЕСЬ ИЗМЕНЁННЫЙ КОД JAVASCRIPT]")
w()
w("### 4.1 Таблица бланка: бег (3 секундомера) и техника (6 попыток) — `hub/protocol.html`")
w()
w("> ВАЖНО для аудитора: в ТЗ функция `table()` названа находящейся в `ui.html`. Фактически она живёт в `hub/protocol.html` "
  "(одна страница печати для админки и публичного сайта). `ui.html` печатных таблиц не строит.")
w()
a, b, src = js_decl(PR, "isTech")
w(f"#### `isTech` — {ref('hub/protocol.html', a, b)}\n")
code("js", src)
for nm in ("partsOf", "startSheet", "renderStart"):
    a, b, src = js_decl(PR, nm)
    w(f"#### `{nm}` — {ref('hub/protocol.html', a, b)}\n")
    code("js", src)
w("Внутри `startSheet` — вложенная функция `table(entries, rtype, slots, withLane, numbered)`; "
  "именно она выбирает сетку: `const grid = isTech(rtype, slots), N = 6` — при `grid` рисуются 6 граф «Попытка 1…6» и «Лучший результат», "
  "иначе три графы «Сек. 1/2/3». Условие жёсткое: `rtype` `distance`/`height` или `slots>0` или `attempts` всегда ведут к сетке попыток.")
w()
w("### 4.2 Переключение печатных стилей landscape / portrait — `hub/protocol.html`")
w()
a, b, src = js_decl(PR, "setPage")
w(f"#### `setPage` — {ref('hub/protocol.html', a, b)}\n")
code("js", src)
for nm in ("groupList", "tabsFor", "currentItem", "sheetsFor", "showSheets", "drawTabs", "addTabToCart", "buildFinal", "render", "renderCart", "syncStartCtl"):
    a, b, src = js_decl(PR, nm)
    w(f"#### `{nm}` — {ref('hub/protocol.html', a, b)}\n")
    code("js", src)

w("### 4.3 Корзина печати — `hub/ui.html`")
w()
a, b, src = js_block(UI, "/* ---------- корзина печати", "/* ---------- Мастер протоколов")
w(f"Сборка листов галочками в массив корзины (`cartAdd` → `localStorage[\"ss.cart.<id события>\"]`), список, печать пакета, публикация — {ref('hub/ui.html', a, b)}\n")
code("js", src)

w("### 4.4 Мастер протоколов: переключение шагов, ветки Бег/Техника, ввод результатов — `hub/ui.html`")
w()
a, b, src = js_block(UI, "/* ---------- Мастер протоколов", "async function moveEntry") if "async function moveEntry" in UI[UI.index("/* ---------- Мастер протоколов"):] else (0, 0, "")
a, b, src = js_decl(UI, "wzp")
w(f"#### `wzp` (IIFE: состояние `W`, `go(n)`, `render()`, `step1…step5`, `gen`, `reset`, `saveRows`, обработчики) — {ref('hub/ui.html', a, b)}\n")
code("js", src)

w("### 4.5 Расчёт официального результата на клиенте (зеркало серверного) — `hub/ui.html`")
w()
for nm in ("parseT", "fmtT", "swMain", "attBest"):
    a, b, src = js_decl(UI, nm)
    w(f"#### `{nm}` — {ref('hub/ui.html', a, b)}\n")
    code("js", src)
w("Клиентский расчёт — только подсказка при вводе; **официальный результат всегда считает сервер** (`stopwatch_main`, `parse_attempts`), клиент его не подменяет (`auto: true`).")
w()
w("### 4.6 Обязательное поле «Разряд / Звание» — `hub/ui.html`")
w()
a, b, src = js_decl(UI, "rankOpts")
w(f"#### `rankOpts` — {ref('hub/ui.html', a, b)}\n")
code("js", src)
i = UI.index('$("mAdd").onclick')
j = UI.index("};", i) + 2
code("js", UI[i:j])
w("На сервере то же правило (не обходится запросом в обход UI):")
w()
a, b, src = py_func("Hub", "norm_rank")
code("python", src)
i = PY.index('rank = self.norm_rank(d.get("rank"))')
code("python", PY[i:PY.index("\n", PY.index('errs["rank"]', i))])
i = PY.index("# карточка участника не сохраняется без разряда")
code("python", PY[i:PY.index("\n", PY.index("return err(", i))])

# ------------------------------------------------------------------ 5. CSS
w("## 5. [CSS ДЛЯ ПРИНТЕРА] — `hub/protocol.html`")
w()
w("Ориентация листа не задаётся статически: функция `setPage(land)` (§4.2) перезаписывает `<style id=\"pgstyle\">` с правилом "
  "`@page{size:A4 landscape|portrait;margin:…}` и дублем в `@media print{@page{…;size:landscape}}`. "
  "Для корзины (смешанные ориентации в одном документе) используются **именованные страницы** `@page cpl` / `@page cpp` и свойство `page:` (Chromium ≥ 85, проверено выводом в PDF: страницы 1 — альбомная, 2–3 — книжные).")
w()
w("Генерируемый CSS (из `setPage` и `renderCart`):")
w()
code("css", """/* setPage(land): одиночный протокол */
@page{size:A4 landscape;margin:10mm 12mm 12mm}
@media print{@page{size:A4 landscape;margin:10mm 12mm 12mm;size:landscape}}
/* (портрет) @page{size:A4 portrait;margin:12mm 12mm 14mm} */

/* renderCart(): пакет листов, каждый — с новой страницы */
@page{size:A4 landscape|portrait;margin:…}          /* по ориентации первого листа */
@page cpl{size:A4 landscape;margin:10mm 12mm 12mm}
@page cpp{size:A4 portrait;margin:12mm 12mm 14mm}
.cp{page-break-after:always;break-after:page}
.cp:last-child{page-break-after:auto;break-after:auto}  /* без пустой страницы в конце */
.cp.land{page:cpl}.cp.port{page:cpp}""")
w("Статические правила страницы:")
w()
for head in ("@media print{.cp+.cp", "@media print{"):
    try:
        a, b, src = css_media(PR, head)
        w(f"#### {ref('hub/protocol.html', a, b)}\n")
        code("css", src)
    except (KeyError, IndexError):
        pass
lines = PR.splitlines()
cssl = [ln for ln in lines if re.match(r"^(\.sheet\.land|\.hide|\.att|\.swt|table\.att|\.cartmode|\.embed|\.cp|\.swt td|\.att td|\.att th)", ln)]
w("Правила сетки бланка и корзины:")
w()
code("css", "\n".join(cssl))

# ------------------------------------------------------------------ 6. API
w("## 6. API Мастера")
w()
w("| Метод и адрес | Тело | Ответ / поведение |")
w("|---|---|---|")
w("| `POST /api/events/<id>/heats` | `{lanes, mode}` — полная сборка; `{distance, ages[], sex, lanes}` — **выборочная** (Мастер) | `{heats[], entries, kind, mode}`; техника → всегда `mode:list`, `lane=null`; 400 «нет подтверждённых заявок…» |")
w("| `POST /api/events/<id>/resetheats` | `{distance?}` | `{waves, entries}`; 400, если был старт забега |")
w("| `GET /api/events/<id>/startlist` | — | `heats[]` (`rtype`, `slots`) и участники с `distance`, `rtype`, `slots`, `done_rank` |")
w("| `POST /api/events/<id>/results` | `{rows:[{bib, t[3] \\| a[≤6/12] \\| result, status, auto, done_rank}]}` | `{saved, errors[]}`; сервер считает результат |")
w("| `GET /api/events/<id>/results` | — | `finished[]` с `place`, `place_overall`, `result`, `sw`, `attempts`, `rt`, `sex`, `done_rank`, `done_rank_auto`, `done_rank_src` |")
w("| `POST /api/events/<id>/publish` | `{start?, results?}` | `{pub_start, pub_results, url, start_url, results_url}` |")
w("| `POST /api/events/<id>/entry` | `{bib, wave, lane, new_bib}` / `{reg_id, wave, set_bib}` | перенос, смена номера, добавление подтверждённой заявки |")
w("| `GET /protocol?event=ID&kind=start\\|results\\|cart` | параметры: `smode`, `orient`, `sexf`, `dist`, `grp`, `mode`, `embed`, `ids` | HTML бланка; `X-Frame-Options: SAMEORIGIN` только для этого пути |")
w()

# ------------------------------------------------------------------ 7. тесты
w("## 7. Тесты (`tools/selftest.py`)")
w()
w(f"Результат прогона при формировании дампа: **{' · '.join(st_tail)}** (код возврата {selftest.returncode}).")
w()
w("Проверки, относящиеся к Мастеру (имена из вывода):")
w()
for ln in st_checks:
    w(f"- {ln.replace('[OK  ] ', '✅ ')}")
w()
w("Браузерные проверки (headless Chromium, playwright-core; сценарии не входят в репозиторий): пять шагов обеих веток, предпросмотр в `iframe`, корзина из 3 листов → печать пакета → PDF с чередованием ориентации, "
  "диалог выгрузки, ввод 6 попыток и 3 секундомеров, смена статуса соревнований и пересчёт разрядов; ошибок JS в консоли нет.")
w()

# ------------------------------------------------------------------ 8. ограничения
w("## 8. Известные ограничения и честные оговорки")
w()
w("1. **Нет функции `add_entry` как метода Hub.** Есть `Store.add_entry` (низкоуровневая вставка) и ветка API `entry` (§3.8), которая и является прикладным «добавлением участника в забег».")
w("2. **`table()` не в `ui.html`**, а в `protocol.html` (см. §4.1).")
w(f"3. **Выгрузка в сеть** (`publish`) открывает на публичной странице протокол соревнования **целиком** (`pub_start`/`pub_results`), а не отдельные листы корзины; требует настроенного `public.url` и `ours=true`.")
w("4. **Версия.** `3.7.0`. Механизм обновления сравнивает строки (`latest != VERSION`), поэтому версия только растёт.")
w("5. **Push без force.** Изменения отправляются обычным `git push`; принудительная отправка не нужна (ветка не расходилась с удалённой) и могла бы стереть чужие коммиты.")
w("6. **Корзина хранится в `localStorage` браузера секретаря** (по событию), не на сервере: на другом компьютере она пуста.")
w(f"7. **Разряды по нормам:** источник — {norms.get('source')}; {norms.get('count')} норм; пропущены 2 ячейки-опечатки таблицы (`skipped` в `rank_norms.json`). Не учитываются ветер, эстафеты, «бег 24 часа»; МСМК не присваивается автоматически. Для 500 м, 2000 м, 80 м с/б, ходьбы 1500 м норм в таблице нет.")
w("8. **Попыток в высоте/шесте на бланке 6** (ТЗ), хотя `attempt_slots` для ввода допускает 12 высот.")
w("9. **Ключ сопоставления дисциплины с нормами** строится по названию (`norm_key`); нестандартные названия («Метание снаряда» без слова «мяч») нормы не находят — разряд вносится вручную.")
w("10. **Персональные данные** в дамп и репозиторий не попадают (152-ФЗ): только код, схема и обезличенные тестовые данные.")
w()

# ------------------------------------------------------------------ 9. файлы
w("## 9. Состав проекта (файлы, затронутые линейкой 3.4–3.6)")
w()
files = [
    ("hub/hub.py", "сервер: БД, API, генерация сетки, расчёт результатов и разрядов"),
    ("hub/ui.html", "админка: Мастер протоколов, корзина печати, форма регистрации"),
    ("hub/protocol.html", "печатные формы: стартовые и итоговые протоколы, корзина-пакет"),
    ("hub/seed/disciplines.json", "справочник дисциплин (тип результата, attempts, aliases)"),
    ("hub/seed/rank_norms.json", "нормы ЕВСК по лёгкой атлетике (генерируется)"),
    ("tools/norms_import.py", "импорт норм из xls Минспорта"),
    ("tools/selftest.py", "автопроверки"),
    ("tools/make_snapshot.py", "генератор этого файла"),
    ("docs/cart-3.4.md, wizard-3.5.md, ranks-3.6.md", "описания"),
]
w("| Файл | Назначение |")
w("|---|---|")
for f, d in files:
    w(f"| `{f}` | {d} |")
w()
w("### Журнал коммитов линейки")
w()
code("text", git("log", "--format=%h %ad %s", "--date=short", "-14"))

open(os.path.join(ROOT, "system_final_snapshot.md"), "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("OK", sum(len(x) for x in OUT), "символов")
