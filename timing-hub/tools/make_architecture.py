#!/usr/bin/env python3
"""Собирает system_architecture_snapshot.md — полную спецификацию архитектуры SakhStart для стороннего ИИ-аудитора.

Код попадает в файл ДОСЛОВНО из исходников (ast и срезы по строкам), схема БД снимается с реальной свежей базы,
поэтому документ не расходится с репозиторием. Запуск из корня проекта:  python3 tools/make_architecture.py
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

rd = lambda n: open(os.path.join(HUB, n), encoding="utf-8").read()  # noqa: E731
PY, UI, REG, BOARD = rd("hub.py"), rd("ui.html"), rd("reg.html"), rd("board.html")
TREE = ast.parse(PY)
LINES = PY.splitlines()
OUT = []


def w(s=""):
    OUT.append(s)


def code(lang, text):
    w(f"```{lang}\n{text.rstrip()}\n```\n")


def py_func(cls, name):
    """Метод класса или функция верхнего уровня целиком (с декораторами): (строка с, строка по, текст)."""
    nodes = []
    for c in TREE.body:
        if cls is None and isinstance(c, ast.FunctionDef) and c.name == name:
            nodes.append(c)
        if isinstance(c, ast.ClassDef) and c.name == cls:
            nodes += [f for f in c.body if isinstance(f, ast.FunctionDef) and f.name == name]
    if not nodes:
        raise KeyError(f"{cls}.{name}")
    f = nodes[0]
    a = min([f.lineno] + [d.lineno for d in f.decorator_list])
    return a, f.end_lineno, "\n".join(LINES[a - 1:f.end_lineno])


def py_func_or_none(cls, name):
    try:
        return py_func(cls, name)
    except KeyError:
        return None


def show_func(cls, name, title=None):
    a, b, t = py_func(cls, name)
    w(f"### `{(cls + '.') if cls else ''}{name}` — `hub/hub.py` строки {a}–{b}" + (f" ({title})" if title else ""))
    w()
    code("python", t)


def js_slice(src, start_marker, end_marker):
    a = src.index(start_marker)
    b = src.index(end_marker, a)
    return src[:a].count("\n") + 1, src[:b].count("\n"), src[a:b]


def js_func(src, name):
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


git = lambda *a: subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True).stdout.strip()  # noqa: E731
st = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "selftest.py")], capture_output=True, text=True)
st_tail = [ln for ln in st.stdout.splitlines() if ln.startswith(("Итого", "Всё", "ЕСТЬ"))]

# ============================================================== шапка
w("# system_architecture_snapshot — полная спецификация архитектуры SakhStart timing-hub")
w()
w(f"- **Версия сервера (`VERSION`):** `{H.VERSION}`")
w(f"- **Дата сборки (`BUILD_DATE`):** `{H.BUILD_DATE}`")
w(f"- **Ветка / коммит:** `{git('rev-parse', '--abbrev-ref', 'HEAD')}` / `{git('rev-parse', '--short', 'HEAD')}`")
w(f"- **Сформирован:** {dt.datetime.now():%Y-%m-%d %H:%M} скриптом `tools/make_architecture.py` (код — дословно из исходников)")
w(f"- **Автопроверки (`tools/selftest.py`):** {' · '.join(st_tail)}")
w(f"- **Объём:** `hub/hub.py` {len(LINES)} строк, `hub/ui.html` {UI.count(chr(10))}, `hub/reg.html` {REG.count(chr(10))}, `hub/board.html` {BOARD.count(chr(10))}")
w()
w("> Для ИИ-аудитора. Разделы: 1 — назначение; 2 — что исправлено в 7.4.5 и где; 3 — схема SQLite (снята с живой базы); "
  "4 — Python (ключевые функции дословно); 5 — HTML/JS/CSS (дословно); 6 — маршруты и права; 7 — допущения и известные ограничения.")
w("> В документе нет персональных данных и секретов: только код и структура.")
w()

# ============================================================== 1
w("## 1. Назначение и концепция")
w()
w("**SakhStart timing-hub** — стадионно-манежный монолит РСОО «ФЛАСО» для лёгкой атлетики (Южно-Сахалинск). Один процесс Python "
  "(`hub/hub.py`, asyncio, собственный HTTP-сервер без фреймворков) + SQLite (один файл) + статические HTML-страницы без сборки.")
w()
w("| Часть | Что делает | Файл |")
w("|---|---|---|")
w("| Секретариат (АРМ секретаря) | события, заявки, нагрудные номера (вручную), Мастер протоколов (шаги 1–5), забеги/общий список, Excel, печать, итоговый протокол | `hub/ui.html` |")
w("| АРМ судьи на секторе | планшет: ввод попыток/секундомеров, очередь с повтором при обрыве связи | `hub/sector.html`, маршрут `/sector` |")
w("| Табло | `auto` / `fixed` / `rotate`, автопрокрутка длинных таблиц, 6 ячеек попыток с подсветкой заступа и лучшей попытки | `hub/board.html`, пульт `hub/scoreboard.html` |")
w("| Публичная страница соревнования | регистрация по ссылке, блок документов, кнопка «Участники соревнований», окно `/r/<slug>/participants` (модуль в духе MyRace) | `hub/reg.html` |")
w("| Личный кабинет тренера | регистрация по e-mail с подтверждением, вход, закрытые стартовые и итоговые протоколы | `hub/reg.html` (`trainerPage`), `Hub.trainer_api` |")
w("| Протоколы / печать | стартовые, итоговые, корзина печати, альбомные бланки техники на 6 попыток | `hub/protocol.html` |")
w()
w("**Принципы.** (1) Официальный результат считается только на сервере (`official_from_raw`, `POST /api/calc`). "
  "(2) Нагрудные номера только вручную, один человек (ФИО + год) — один номер на все его дисциплины. "
  "(3) Чипового хронометража нет с 7.0.0 (удалены ридеры, IPICO, Wiclax; миграция `_migrate_v7`). "
  "(4) ФЗ-152: согласие отдельно от Политики, архив редакций (`consent_texts`), обезличивание ПДн через 180 дней после соревнования, "
  "открытый список участников — только по включённому тумблеру и с учётом текста согласия (`PUBLIC_LIST_MARK`), "
  "протоколы закрыты без входа. (5) Общее состояние Мастера и корзины печати хранится на сервере (`ui_state`), а не в браузере.")
w()

# ============================================================== 2
w("## 2. Исправления и функции версии 7.4.x — что и где")
w()
w("| Требование | Реализация | Статус |")
w("|---|---|---|")
w("| Восстановление года рождения / тренера: жёсткая связь `entries.reg_id` ↔ `registrations.id`, затем ключ ФИО (`_name_key`: без регистра, пробелов, NBSP, «ё»=«е»); принудительно при каждом старте | `Store._migrate_v74`, `_name_key` (раздел 4.6) | ✅ |")
w("| Публичный `/participants`: год, номер (Bib) и тренер у каждого, без пустых клеток | `Hub.participants_list` (резервное чтение из `entries`), `reg.html` выводит «—» вместо пустого | ✅ с оговоркой ↓ |")
w("| Смена номера на шаге 2 мгновенно видна на сайте | номер берётся из БД при каждом запросе (`_reg_bib`), ответ `Cache-Control: no-cache`, страница сама обновляется раз в 20 с (`plRefresh`) | ✅ |")
w("| Яндекс.Карты: манеж Горького, 39 не уходит в Хабаровск | `Hub.venue_for`: центр карты `ll=142.760570,46.928092`, метка `pt=`, масштаб 17, текст «Южно-Сахалинск, улица Горького, 39, Легкоатлетический манеж» | ✅ |")
w("| Адаптивная кнопка «Участники соревнований» | `reg.html`: `a.btn.pbtn` (по центру, на всю ширину формы; на узком экране тот же центр) | ✅ |")
w("| Пакетная генерация «⚡ Сформировать ВСЕ» | `Hub.generate_all`, `POST /api/events/<id>/heats-all`, `wzp.genAll` | ✅ |")
w()
w("**Оговорка.** Год рождения и тренер в открытом списке скрыты для заявок, поданных по тексту согласия без пункта о публикации "
  "(это требование 152-ФЗ, а не пустые данные в БД). Секретарь снимает скрытие тумблером «Показывать год рождения и тренера у всех» "
  "(`events.pub_regs_full`) после подтверждения, что согласия получены. Без тумблера для таких заявок на сайте «—».")
w()

# ============================================================== 3 схема
w("## 3. Схема SQLite (снята с реальной свежей базы через `sqlite_master`)")
w()
tmp = os.path.join(tempfile.mkdtemp(), "arch.db")
H.Store(tmp)
con = sqlite3.connect(tmp)
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
w(f"Таблицы ({len(tables)}): " + ", ".join(f"`{t}`" for t in tables))
w()
for t in tables:
    w(f"### `{t}`")
    w()
    w("| # | поле | тип | NOT NULL | по умолчанию | PK |")
    w("|---|---|---|---|---|---|")
    for cid, name, typ, nn, dflt, pk in con.execute(f"PRAGMA table_info({t})"):
        w(f"| {cid} | `{name}` | {typ or ''} | {'да' if nn else ''} | {'' if dflt is None else '`' + str(dflt) + '`'} | {'да' if pk else ''} |")
    w()
w("### Индексы и триггеры (`sqlite_master`)")
w()
rows = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type, tbl_name, name").fetchall()
if rows:
    code("sql", "\n".join(f"-- {t} {n} ({tb})\n{s};" for t, n, tb, s in rows))
else:
    w("_нет_")
tr = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0]
w(f"Триггеров в схеме: **{tr}**" + (" (бизнес-логика целиком в Python; целостность — индексами и транзакциями)." if not tr else "."))
w()
w("### Полный DDL (для воспроизведения)")
w()
code("sql", "\n\n".join(f"{s};" for (s,) in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name")))
con.close()
w("Примечание: таблица `waves` — забеги/группы соревнования (имя, категория, дистанция, время старта); участник привязан к забегу полем `entries.wave` (по имени). "
  "Связь «один человек — одна строка на дисциплину»: `entries.id` (строка) ≠ нагрудный номер (`entries.bib`, может повторяться у одного человека).")
w()

# ============================================================== 4 python
w("## 4. Python: ключевые функции дословно (`hub/hub.py`)")
w()
w("### 4.1 Генерация и сброс сетки")
w()
if py_func_or_none("Hub", "generate_heats"):
    show_func("Hub", "generate_heats")
else:
    w("`generate_heats` удалён в 6.0.0 — единственный генератор `generate_scoped` (одна дисциплина) вызывается из `generate_all`.")
    w()
show_func("Hub", "generate_scoped", "сетка одной дисциплины: бег — забеги и дорожки, техника — общий список")
show_func("Hub", "reset_heats", "принудительный сброс, обнуляет время старта")
w("### 4.2 Пакетная генерация «heats-all»")
w()
show_func("Hub", "generate_all", "все дисциплины с одобренными заявками одним проходом")
ha = next(i for i, l in enumerate(LINES) if l.strip() == 'if action == "heats-all":')
hb_ = next(i for i in range(ha + 1, len(LINES)) if LINES[i].startswith("        if action =="))
w(f"Ветка `POST /api/events/<id>/heats-all` (`Hub._api…`, `hub/hub.py` строки {ha + 1}–{hb_}):")
w()
code("python", "\n".join(LINES[ha:hb_]))
w("### 4.3 Нагрудные номера: сохранение, очистка, единая картина")
w()
for n in ("_bib_state", "_own_bib", "_reg_bib", "_need_bibs", "save_bibs", "clear_bibs"):
    show_func("Hub", n)
w("### 4.4 Публичный список участников")
w()
show_func("Hub", "participants_list")
w("Маршрут отдачи (фрагмент `_public_route`):")
w()
a, b, t = py_func("Hub", "_public_route")
pj = t.index('if method == "GET" and sub == "/participants.json":')
code("python", t[pj:t.index('if method == "GET" and sub in ("/results.json"', pj)])
w("### 4.5 Карты (Яндекс.Карты)")
w()
show_func("Hub", "venue_for")
w("Площадки и координаты:")
w()
ys = next(i for i, l in enumerate(LINES) if l.strip().startswith("YS_CENTER ="))
code("python", LINES[ys])
a = next(i for i, l in enumerate(LINES) if l.strip().startswith("VENUES = ("))
b = next(i for i in range(a, a + 20) if LINES[i].strip() == ")")
code("python", "\n".join(LINES[a:b + 1]))
w("### 4.6 Миграции: восстановление пустых полей тренеров и годов")
w()
show_func(None, "_name_key")
show_func("Store", "_migrate_v74", "запускается из `_migrate()` при каждом старте")
show_func("Store", "_migrate_v7", "7.0: удаление чипового хронометража, пересборка entries с собственным id")
w("### 4.7 Тренеры: регистрация и подтверждение e-mail, вход, сессии")
w()
show_func("Hub", "trainer_api", "consent / register / verify / resend / login / logout")
for n in ("send_mail", "protocol_viewer", "role_allows"):
    show_func("Hub", n)
w()

# ============================================================== 5 front
w("## 5. HTML / JavaScript / CSS дословно")
w()
w("### 5.1 `hub/reg.html` — публичный модуль «Участники» (окно `/r/<slug>/participants`)")
w()
a = REG.index(".pl h2{") if ".pl h2{" in REG else 0
css_a = REG.index("a.btn.pbtn{")
css_b = REG.index("\n", REG.index(".pl-h3{"))
w("**CSS модуля и адаптивной кнопки:**")
w()
code("css", REG[css_a:REG.index("\n", REG.index("@media(max-width:480px){a.btn.pbtn"))] + "\n" + REG[REG.index(".pl h2{"):css_b])
w("**Кнопка на главной странице (фрагмент `layout()`) и страница модуля:**")
w()
la, lb, lt = js_func(REG, "layout")
code("javascript", lt)
for n in ("participantsPage",):
    s, e, t = js_func(REG, n)
    w(f"`{n}` — `hub/reg.html` строки {s}–{e}")
    code("javascript", t)
pa = REG.index("// 7.2: открытый модуль")
pb = REG.index("function paint(html)")
w(f"Весь JS модуля участников (`PL`, `PS`, `loadParticipants`, `plRefresh`, `plRows`, `drawPl`, обработчики) — `hub/reg.html` строки {REG[:pa].count(chr(10)) + 1}–{REG[:pb].count(chr(10))}:")
w()
code("javascript", REG[pa:pb])
w("### 5.2 `hub/board.html` — табло: автопрокрутка, 6 попыток, заступы (целиком)")
w()
code("html", BOARD)
w("### 5.3 `hub/ui.html` — Мастер протоколов (`wzp`, шаги 1–5), целиком")
w()
wa = UI.index("const wzp = (() => {")
wb = UI.index("\n})();", wa) + len("\n})();")
w(f"`hub/ui.html` строки {UI[:wa].count(chr(10)) + 1}–{UI[:wb].count(chr(10)) + 1}. Шаги: 1 «Участники» (фильтры), 2 «Нагрудные номера» (ввод вручную, живая проверка, сохранение одним запросом), "
  "3 «Стартовые протоколы» (сетка, Excel, «⚡ Сформировать ВСЕ»), 4 «Ввод результатов», 5 «Итоговый протокол».")
w()
code("javascript", UI[wa:wb])
w("### 5.4 Тумблеры публикации на этапе «1. Подготовка» (`hub/ui.html`)")
w()
ta = UI.index('<label class="switch"><input type="checkbox" id="sPubRegs">')
code("html", UI[ta:UI.index("</div>", UI.index('id="sPubFull"'))])
w()

# ============================================================== 6 routes
w("## 6. Маршруты API и права доступа")
w()
w("### 6.1 Роли и правила (код дословно)")
w()
code("python", "\n".join(LINES[next(i for i, l in enumerate(LINES) if l.strip().startswith("ROLES")):][:1]))
a = next(i for i, l in enumerate(LINES) if l.strip().startswith("ADMIN_ONLY = re.compile"))
code("python", "\n".join(LINES[a - 1:a + 3]))
show_func("Hub", "role_allows")
w("Сводная таблица прав (следует из `role_allows`, `ADMIN_ONLY`, `JUDGE_OPEN`, `JUDGE_DENY_POST`, `TRAINER_PANEL`, `protocol_viewer`):")
w()
w("| Область | admin | judge | trainer | без входа |")
w("|---|---|---|---|---|")
w("| `/api/events/*` (кроме удаления), ввод результатов, номера, сетка | ✅ | ✅ | ✖ | ✖ |")
w("| `POST /api/events/<id>/delete` | ✅ | ✖ | ✖ | ✖ |")
w("| `/api/system/*` (обновление, резервные копии, VPN), `/api/users*`, `/api/trainers*`, `/api/consents*`, `/simple` | ✅ | ✖ | ✖ | ✖ |")
w("| `POST /api/system/scoreboard/control` (пульт табло) | ✅ | ✅ | ✖ | ✖ |")
w("| `/api/me`, `/api/logout`, `/protocol` | ✅ | ✅ | ✅ | ✖ |")
w("| `/r/<slug>` страница, `/info`, `POST` заявка, `/participants`, `/participants.json` (если включена публикация) | ✅ | ✅ | ✅ | ✅ |")
w("| `/r/<slug>/protocol`, `/startlist.json`, `/results.json` | ✅ | ✅ | ✅ (подтверждённая почта) | ✖ (401) |")
w("| `/r/trainer/api/*` (consent, register, verify, resend, login, logout, me, events) | — | — | ✅ | ✅ (первые пять) |")
w("| `/board`, `/api/clock` | экран табло открыт для показа на стадионе | | | см. `_public_route` |")
w()
w("### 6.2 Перечень роутов (автоизвлечение из исходника: строка, шаблон, метод по условию рядом)")
w()
w("Таблица собрана скриптом по литералам `/api/…`, `/r/…` и сравнениям `path ==` / `sub ==` в `hub/hub.py`; "
  "метод указан, если он есть в той же строке условия, иначе `GET|POST` (определяется в теле ветки).")
w()
seen = set()
rt = []
pat_re = re.compile(r'r?"(/(?:api|r|sector|board|scoreboard|login|logout|protocol|simple|privacy|series)[^"\s]*)"')
for i, ln in enumerate(LINES, 1):
    s = ln.strip()
    if s.startswith("#") or "re.fullmatch" not in s and "path ==" not in s and "sub ==" not in s and "path in" not in s and "startswith" not in s:
        continue
    for pth in pat_re.findall(s):
        mth = "POST" if 'method == "POST"' in s else "GET" if 'method == "GET"' in s else "GET|POST"
        key = (pth, mth)
        if key not in seen:
            seen.add(key)
            rt.append((pth, mth, i))
w("| Шаблон | Метод | `hub/hub.py` |")
w("|---|---|---|")
for pth, mth, i in sorted(rt):
    w(f"| `{pth}` | {mth} | {i} |")
w()
w("Внутренние ветки `_api` с разбором `action` (`/api/events/<id>/<action>`, допустимые символы `[a-z.-]+`):")
w()
acts = sorted(set(re.findall(r'action == "([a-z.-]+)"', PY)))
w(", ".join(f"`{x}`" for x in acts))
w()
w("### 6.3 Сессии")
w()
w("Администратор/судья — вход через браузер (`/login`), cookie сессии (SQLite `sessions`), пароли хранятся хэшем (`hash_password`/`verify_password`). "
  "Тренер — отдельная таблица `trainers`: e-mail + пароль-хэш + одноразовый код подтверждения (`verification_token`, срок `token_expires`, счётчик попыток `token_attempts`), "
  "согласие и Политика отдельными отметками (`consent_*`, `policy_hash`). Тренер без подтверждённой почты протоколы не видит. "
  "Ограничение частоты: `Hub._rate_ok` (по IP и по соревнованию).")
w()

# ============================================================== 7
w("## 7. Допущения и известные ограничения")
w()
w("- Скрытие года и тренера для старых заявок — осознанное (152-ФЗ); снимается тумблером `pub_regs_full` ответственностью организатора.")
w("- Координаты манежа взяты с карточки дома на Яндекс.Картах (46.928092, 142.760570); для «Спартака» и «Триумфа» точных координат нет — карта центрируется на Южно-Сахалинске.")
w("- Список роутов в 6.2 извлечён автоматически и может содержать лишние служебные строки; источник истины — `Hub._api`, `Hub._public_route`, `Hub.trainer_api`.")
w("- Перечень маршрутов `/r/trainer/api/*`, вход, SMTP-параметры и секреты живут в конфиге сервера (`cfg`), в репозиторий не попадают.")
w("- Запуск и проверка: `python3 tools/selftest.py` (поднимает временный сервер, ~320+ проверок), `python3 tools/make_architecture.py` — пересборка этого файла.")
w()

open(os.path.join(ROOT, "system_architecture_snapshot.md"), "w", encoding="utf-8").write("\n".join(OUT))
print("system_architecture_snapshot.md:", sum(len(x) for x in OUT) // 1024, "КБ")
