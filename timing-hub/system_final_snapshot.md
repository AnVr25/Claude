# system_final_snapshot — полный технический дамп SakhStart timing-hub, Мастер протоколов v3.7

- **Версия сервера (`VERSION`):** `4.5.1` (линейка v3.7: вкладки групп и отдельный лист на каждую категорию)
- **Дата сборки (`BUILD_DATE`):** `2026-10-13`
- **Ветка / коммит:** `claude/greeting-d2g8ji` / `a331a84`
- **Дамп сформирован:** 2026-10-13 10:08 скриптом `tools/make_snapshot.py` (код ниже вставлен дословно из исходников)
- **Автопроверки:** Итого: 268 из 268 проверок пройдено. · Всё работает.
- **Объём исходников:** `hub/hub.py` 6640 строк, `hub/ui.html` 3252, `hub/protocol.html` 633

> Для аудитора. Что в дампе: (1) назначение и архитектура, (2) схема SQLite, (3) весь Python Мастера, (4) весь JavaScript, (5) CSS печати, (6) API, (7) тесты, (8) известные ограничения и места, где фактическая реализация отличается от формулировок ТЗ.

## 0. Что реализовано (соответствие ТЗ)

| Требование | Где реализовано | Статус |
|---|---|---|
| Автоопределение Бег / Техника | `Hub.discipline_kind`, `Hub.result_type`, `Hub.attempt_slots` (справочник `hub/seed/disciplines.json`); в браузере `wzp` → `kindOf` | ✅ |
| Бег: вертикальный бланк, 3 поля «Сек. 1–3» | `protocol.html`: `startSheet()` → `table()` (ветка `grid=false`), `setPage(false)` | ✅ |
| Техника: сквозной «Общий список» без дорожек | `Hub.generate_scoped` (`tech → plan.append(... use_lanes=False)`), блокировка на сервере | ✅ |
| Техника: альбомный лист, 6 попыток + «Лучший результат» | `protocol.html`: `isTech`, `table()` (`N=6`), `setPage(true)`, `@page … landscape` | ✅ |
| Мастер: фильтры пол / возрастные группы (AGES) | `ui.html`: `wzp` шаг 1; сервер: `Hub.AGE_LIMITS`, `generate_scoped(scope.ages, scope.sex)` | ✅ |
| Сетка / сквозной список, генерация, сброс `reset_heats` с подтверждением | `wzp` шаг 2: `gen()`, `reset()`; `Hub.generate_scoped`, `Hub.reset_heats` | ✅ |
| Ручной ввод на финише / на секторе | `wzp` шаг 4: `step4()`, `saveRows()`; `POST /api/events/<id>/results` | ✅ |
| Корзина печати, `page-break-after: always` | `ui.html`: `cartAdd`, `renderCart`; `protocol.html`: `renderCart()` (`.cp{page-break-after:always}`) | ✅ |
| Публикация на внешний сайт | `ui.html`: обработчик `[data-cart=publish]`; `POST /api/events/<id>/publish` | ✅ (см. §8.3) |
| Обязательное «Разряд / Звание» | `Hub.check_person` (400, поле `rank`), `regs/<id>` (отказ сохранения карточки), `ui.html`: `mAdd`, `nRank` | ✅ |
| Выполненный разряд по нормам ЕВСК | `Hub.rank_for`, `hub/seed/rank_norms.json`, `tools/norms_import.py` | ✅ (сверх ТЗ) |

## 1. Архитектура

- Один процесс Python 3 (`asyncio`), один файл `hub/hub.py`, БД SQLite (`PRAGMA journal_mode=WAL`), без внешних зависимостей сервера.
- Админка: одностраничное приложение `hub/ui.html` (hash-маршруты `#reg`, `#wizard`, …), общается с сервером через `/api/…` (cookie-сессия, заголовок `X-Requested-With: timing-hub` обязателен для POST).
- Печатные формы: `hub/protocol.html` — **единая** страница для админки (`/protocol?event=ID&…`) и публичного сайта (`/r/<slug>/protocol`). **Шаблоны таблиц (`table()`) находятся здесь, а не в `ui.html`.**
- Публичный сайт: `reg.html`, `series.html`; публичный API `/r/<slug>/…` (`startlist.json`, `results.json`) отдаёт данные только при `pub_start` / `pub_results`.
- Обновление: `GET /api/system/update/github/check` → `POST …/update/github` → `…/update/install` (ветка `claude/greeting-d2g8ji`, см. `docs/github-update.md`).

Поток данных Мастера: `заявки (registrations)` → `generate_scoped` → `waves` + `entries` → `startlist()` → `protocol.html` (бланк) → судьи пишут на бумаге → секретарь вводит → `results` action (`stopwatch_main` / `parse_attempts`) → `entries.result/detail/done_rank` → `compute()` → `results` JSON → итоговый протокол.

## 2. [СХЕМА БД SQLITE]

Схема получена запуском `Store(...)` на пустой БД (создание + все миграции `_migrate`), то есть показывает **итоговое** состояние. Таблицы: `audit`, `entries`, `events`, `files`, `manual`, `raw`, `readers`, `reads`, `registrations`, `scoreboard`, `sessions`, `users`, `waves`, `wiclax_ports`.

### Таблица `events`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `name` | TEXT | да |  |  |
| 2 | `date` | TEXT |  |  |  |
| 3 | `place` | TEXT |  |  |  |
| 4 | `finish_device` | TEXT |  |  |  |
| 5 | `min_time_sec` | REAL | да | 0 |  |
| 6 | `push_wiclax` | INTEGER | да | 1 |  |
| 7 | `start_time` | TEXT |  |  |  |
| 8 | `status` | TEXT | да | 'planned' |  |
| 9 | `notes` | TEXT |  |  |  |
| 10 | `created_at` | TEXT | да |  |  |
| 11 | `check_since` | TEXT |  |  |  |
| 12 | `alert_silence_min` | REAL | да | 10 |  |
| 13 | `archived` | INTEGER | да | 0 |  |
| 14 | `finished_at` | TEXT |  |  |  |
| 15 | `organizer` | TEXT |  |  |  |
| 16 | `chief_judge` | TEXT |  |  |  |
| 17 | `chief_secretary` | TEXT |  |  |  |
| 18 | `start_clock` | TEXT |  |  |  |
| 19 | `heats_sequential` | INTEGER |  |  |  |
| 20 | `team_best` | INTEGER |  |  |  |
| 21 | `cover` | TEXT |  |  |  |
| 22 | `program` | TEXT |  |  |  |
| 23 | `contacts` | TEXT |  |  |  |
| 24 | `series` | TEXT |  |  |  |
| 25 | `reg_open` | INTEGER | да | 0 |  |
| 26 | `reg_slug` | TEXT |  |  |  |
| 27 | `reg_deadline` | TEXT |  |  |  |
| 28 | `reg_distances` | TEXT |  |  |  |
| 29 | `reg_rules` | TEXT |  |  |  |
| 30 | `reg_lanes` | INTEGER |  |  |  |
| 31 | `reg_info` | TEXT |  |  |  |
| 32 | `reg_consent` | TEXT |  |  |  |
| 33 | `kind` | TEXT |  |  |  |
| 34 | `timing` | TEXT |  |  |  |
| 35 | `pub_site` | INTEGER | да | 0 |  |
| 36 | `ours` | INTEGER | да | 1 |  |
| 37 | `level` | TEXT |  |  |  |
| 38 | `adaptive` | INTEGER | да | 0 |  |
| 39 | `date_end` | TEXT |  |  |  |
| 40 | `city` | TEXT |  |  |  |
| 41 | `note` | TEXT |  |  |  |
| 42 | `live_url` | TEXT |  |  |  |
| 43 | `photo_url` | TEXT |  |  |  |
| 44 | `links` | TEXT |  |  |  |
| 45 | `pub_start` | INTEGER | да | 0 |  |
| 46 | `pub_results` | INTEGER | да | 0 |  |

```sql
CREATE TABLE events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                date TEXT,
                place TEXT,
                finish_device TEXT,
                min_time_sec REAL NOT NULL DEFAULT 0,
                push_wiclax INTEGER NOT NULL DEFAULT 1,
                start_time TEXT,
                status TEXT NOT NULL DEFAULT 'planned',
                notes TEXT,
                created_at TEXT NOT NULL
            , check_since TEXT, alert_silence_min REAL NOT NULL DEFAULT 10, archived INTEGER NOT NULL DEFAULT 0, finished_at TEXT, organizer TEXT, chief_judge TEXT, chief_secretary TEXT, start_clock TEXT, heats_sequential INTEGER, team_best INTEGER, cover TEXT, program TEXT, contacts TEXT, series TEXT, reg_open INTEGER NOT NULL DEFAULT 0, reg_slug TEXT, reg_deadline TEXT, reg_distances TEXT, reg_rules TEXT, reg_lanes INTEGER, reg_info TEXT, reg_consent TEXT, kind TEXT, timing TEXT, pub_site INTEGER NOT NULL DEFAULT 0, ours INTEGER NOT NULL DEFAULT 1, level TEXT, adaptive INTEGER NOT NULL DEFAULT 0, date_end TEXT, city TEXT, note TEXT, live_url TEXT, photo_url TEXT, links TEXT, pub_start INTEGER NOT NULL DEFAULT 0, pub_results INTEGER NOT NULL DEFAULT 0)
```

```sql
CREATE UNIQUE INDEX idx_events_slug ON events(reg_slug);
```

### Таблица `waves`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `event_id` | INTEGER | да |  |  |
| 2 | `name` | TEXT | да |  |  |
| 3 | `start_time` | TEXT |  |  |  |
| 4 | `category` | TEXT |  |  |  |
| 5 | `distance` | TEXT |  |  |  |
| 6 | `finished_at` | TEXT |  |  |  |

```sql
CREATE TABLE waves(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                start_time TEXT, category TEXT, distance TEXT, finished_at TEXT,
                UNIQUE(event_id, name)
            )
```

### Таблица `entries`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `event_id` | INTEGER | да |  | да |
| 1 | `bib` | TEXT | да |  |  |
| 2 | `chip` | TEXT | да |  | да |
| 3 | `points` | REAL |  |  |  |
| 4 | `picked_at` | TEXT |  |  |  |
| 5 | `members` | TEXT |  |  |  |
| 6 | `rank` | TEXT |  |  |  |
| 7 | `detail` | TEXT |  |  |  |
| 8 | `done_rank` | TEXT |  |  |  |
| 9 | `result_at` | TEXT |  |  |  |
| 10 | `wave` | TEXT |  |  |  |
| 11 | `name` | TEXT |  |  |  |
| 12 | `birth_year` | TEXT |  |  |  |
| 13 | `team` | TEXT |  |  |  |
| 14 | `category` | TEXT |  |  |  |
| 15 | `lane` | INTEGER |  |  |  |
| 16 | `coach` | TEXT |  |  |  |
| 17 | `seed` | TEXT |  |  |  |
| 18 | `reg_id` | INTEGER |  |  |  |
| 19 | `sex` | TEXT |  |  |  |
| 20 | `result` | TEXT |  |  |  |
| 21 | `status` | TEXT |  |  |  |

```sql
CREATE TABLE entries(
                event_id INTEGER NOT NULL,
                bib TEXT NOT NULL,
                chip TEXT NOT NULL, points REAL, picked_at TEXT, members TEXT, rank TEXT, detail TEXT, done_rank TEXT, result_at TEXT, wave TEXT, name TEXT, birth_year TEXT, team TEXT, category TEXT, lane INTEGER, coach TEXT, seed TEXT, reg_id INTEGER, sex TEXT, result TEXT, status TEXT,
                PRIMARY KEY(event_id, chip)
            )
```

### Таблица `registrations`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `event_id` | INTEGER | да |  |  |
| 2 | `last_name` | TEXT | да |  |  |
| 3 | `first_name` | TEXT | да |  |  |
| 4 | `middle_name` | TEXT |  |  |  |
| 5 | `birth_date` | TEXT | да |  |  |
| 6 | `sex` | TEXT | да |  |  |
| 7 | `team` | TEXT |  |  |  |
| 8 | `coach` | TEXT |  |  |  |
| 9 | `distance` | TEXT | да |  |  |
| 10 | `best` | TEXT |  |  |  |
| 11 | `best_sec` | REAL |  |  |  |
| 12 | `category` | TEXT |  |  |  |
| 13 | `representative` | TEXT |  |  |  |
| 14 | `contact` | TEXT |  |  |  |
| 15 | `status` | TEXT | да | 'pending' |  |
| 16 | `note` | TEXT |  |  |  |
| 17 | `bib` | TEXT |  |  |  |
| 18 | `consent_at` | TEXT | да |  |  |
| 19 | `consent_hash` | TEXT |  |  |  |
| 20 | `created_at` | TEXT | да |  |  |
| 21 | `updated_at` | TEXT |  |  |  |
| 22 | `relay` | TEXT |  |  |  |
| 23 | `leg` | INTEGER |  |  |  |
| 24 | `rank` | TEXT |  |  |  |

```sql
CREATE TABLE registrations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                last_name TEXT NOT NULL,
                first_name TEXT NOT NULL,
                middle_name TEXT,
                birth_date TEXT NOT NULL,
                sex TEXT NOT NULL,
                team TEXT,
                coach TEXT,
                distance TEXT NOT NULL,
                best TEXT,
                best_sec REAL,
                category TEXT,
                representative TEXT,
                contact TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                note TEXT,
                bib TEXT,
                consent_at TEXT NOT NULL,
                consent_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            , relay TEXT, leg INTEGER, rank TEXT)
```

```sql
CREATE INDEX idx_reg_event ON registrations(event_id);
```

### Таблица `manual`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `event_id` | INTEGER | да |  |  |
| 2 | `device` | TEXT | да |  |  |
| 3 | `ts` | TEXT | да |  |  |
| 4 | `bib` | TEXT | да | '' |  |
| 5 | `judge` | TEXT |  |  |  |
| 6 | `client_id` | TEXT |  |  |  |
| 7 | `created_at` | TEXT | да |  |  |
| 8 | `deleted` | INTEGER | да | 0 |  |
| 9 | `wave` | TEXT |  |  |  |

```sql
CREATE TABLE manual(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                device TEXT NOT NULL,
                ts TEXT NOT NULL,
                bib TEXT NOT NULL DEFAULT '',
                judge TEXT,
                client_id TEXT UNIQUE,
                created_at TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0
            , wave TEXT)
```

```sql
CREATE INDEX idx_manual_event ON manual(event_id);
```

Замечания по схеме:

- `entries`: первичный ключ `(event_id, chip)`; уникальность номера `bib` **контролируется кодом** (`clean_bib`, `rename_bib`, `next_bib`), а не индексом. Номер без чипа хранится как чип `#<bib>`.
- Поля, добавленные в линейке 3.x: `entries.rank` (разряд из заявки), `entries.detail` (JSON `{"t":[3 секундомера],"a":[попытки]}`), `entries.picked_at` (выдача номера), `entries.members` (состав эстафеты), `entries.done_rank` (**3.5**, выполненный разряд), `registrations.rank`, `events.pub_start` / `events.pub_results` / `events.level`.
- `waves.distance` пуст у смешанного «общего списка» (глобальная сборка) — поэтому дисциплина участника берётся из `registrations.distance` через `entries.reg_id` (`Hub.entry_dists`).
- Миграции идемпотентны: `Store._migrate` через `add(table, columns)` (`ALTER TABLE … ADD COLUMN`, если столбца нет).

### `Store._migrate` — `hub/hub.py` строки 705–868

```python
    def _migrate(self) -> None:
        """Добавляет новые поля в базы, созданные старой версией."""
        def cols(t):
            return {r[1] for r in self.con.execute(f"PRAGMA table_info({t})")}

        def add(table, fields):
            have = cols(table)
            if not have:
                return      # таблицы ещё нет — её создаст схема уже с нужными полями
            for name, decl in fields:
                if name not in have:
                    self.con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

        add("events", (("check_since", "TEXT"), ("alert_silence_min", "REAL NOT NULL DEFAULT 10"),
                       ("archived", "INTEGER NOT NULL DEFAULT 0"), ("finished_at", "TEXT"),
                       ("organizer", "TEXT"), ("chief_judge", "TEXT"), ("chief_secretary", "TEXT"),
                       ("start_clock", "TEXT"), ("heats_sequential", "INTEGER")))
        add("readers", (("wiclax_port", "INTEGER"),))
        add("entries", (("points", "REAL"),))
        add("events", (("team_best", "INTEGER"),))
        add("users", (("note", "TEXT"), ("active", "INTEGER NOT NULL DEFAULT 1")))
        # 2.8: обложка, программа, контакты, серия; выдача номеров; эстафеты
        add("events", (("cover", "TEXT"), ("program", "TEXT"), ("contacts", "TEXT"), ("series", "TEXT")))
        add("entries", (("picked_at", "TEXT"), ("members", "TEXT")))
        add("entries", (("rank", "TEXT"), ("detail", "TEXT")))       # 3.2: разряд; показания секундомеров и попытки (JSON)
        add("entries", (("done_rank", "TEXT"),))                      # 3.5: выполненный разряд (вносит секретарь)
        add("entries", (("result_at", "TEXT"),))                      # 4.3: когда введён результат (для табло)
        add("entries", (("wave", "TEXT"), ("name", "TEXT"), ("birth_year", "TEXT"), ("team", "TEXT"),
                        ("category", "TEXT")))
        self.con.executescript(
            """
            CREATE TABLE IF NOT EXISTS waves(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                start_time TEXT,
                UNIQUE(event_id, name)
            );
            CREATE TABLE IF NOT EXISTS manual(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                device TEXT NOT NULL,
                ts TEXT NOT NULL,
                bib TEXT NOT NULL DEFAULT '',
                judge TEXT,
                client_id TEXT UNIQUE,
                created_at TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_manual_event ON manual(event_id);
            CREATE TABLE IF NOT EXISTS files(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                stored TEXT NOT NULL,
                size INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'protocol',
                created_at TEXT NOT NULL,
                author TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_files_event ON files(event_id);
            CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT,
                event_id INTEGER,
                action TEXT NOT NULL,
                details TEXT
            );
            """)
        add("waves", (("category", "TEXT"), ("distance", "TEXT"), ("finished_at", "TEXT")))
        add("manual", (("wave", "TEXT"),))
        # регистрация участников через публичную форму
        add("events", (("reg_open", "INTEGER NOT NULL DEFAULT 0"), ("reg_slug", "TEXT"), ("reg_deadline", "TEXT"),
                       ("reg_distances", "TEXT"), ("reg_rules", "TEXT"), ("reg_lanes", "INTEGER"),
                       ("reg_info", "TEXT"), ("reg_consent", "TEXT")))
        add("entries", (("lane", "INTEGER"), ("coach", "TEXT"), ("seed", "TEXT"), ("reg_id", "INTEGER"), ("sex", "TEXT")))
        add("files", (("folder", "TEXT"),))
        # 2.1: событие на сайте fla65.ru, тип события, введённые вручную результаты, публичные файлы
        add("events", (("kind", "TEXT"), ("timing", "TEXT"), ("pub_site", "INTEGER NOT NULL DEFAULT 0"),
                       ("ours", "INTEGER NOT NULL DEFAULT 1"), ("level", "TEXT"), ("adaptive", "INTEGER NOT NULL DEFAULT 0"),
                       ("date_end", "TEXT"), ("city", "TEXT"), ("note", "TEXT"), ("live_url", "TEXT"),
                       ("photo_url", "TEXT"), ("links", "TEXT"), ("pub_start", "INTEGER NOT NULL DEFAULT 0"),
                       ("pub_results", "INTEGER NOT NULL DEFAULT 0")))
        add("files", (("public", "INTEGER NOT NULL DEFAULT 0"),))
        add("entries", (("result", "TEXT"), ("status", "TEXT")))
        # Таблицы users/sessions могли остаться от старых сборок сервера с другим устройством —
        # тогда CREATE TABLE IF NOT EXISTS их не трогает и вход/пользователи ломаются. Откладываем старые в сторону.
        for table, need in (("users", {"login", "role", "pwd"}), ("sessions", {"token", "login", "expires_at"})):
            have = cols(table)
            if have and not need <= have:
                old = f"{table}_old_{int(time.time())}"
                self.con.execute(f"ALTER TABLE {table} RENAME TO {old}")
                log.warning("Таблица %s была старого вида (%s) — сохранена как %s, создаётся новая",
                            table, ", ".join(sorted(have)), old)
        self.con.executescript(
            """
            CREATE TABLE IF NOT EXISTS registrations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                last_name TEXT NOT NULL,
                first_name TEXT NOT NULL,
                middle_name TEXT,
                birth_date TEXT NOT NULL,
                sex TEXT NOT NULL,
                team TEXT,
                coach TEXT,
                distance TEXT NOT NULL,
                best TEXT,
                best_sec REAL,
                category TEXT,
                representative TEXT,
                contact TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                note TEXT,
                bib TEXT,
                consent_at TEXT NOT NULL,
                consent_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_reg_event ON registrations(event_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_slug ON events(reg_slug);
            CREATE TABLE IF NOT EXISTS readers(
                id TEXT PRIMARY KEY,
                name TEXT,
                box TEXT,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                device TEXT NOT NULL,
                parser TEXT NOT NULL DEFAULT 'ipico',
                enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                wiclax_port INTEGER
            );
            CREATE TABLE IF NOT EXISTS wiclax_ports(
                port INTEGER PRIMARY KEY,
                devices TEXT NOT NULL,
                name TEXT
            );
            CREATE TABLE IF NOT EXISTS users(
                login TEXT PRIMARY KEY,
                name TEXT,
                role TEXT NOT NULL DEFAULT 'judge',
                pwd TEXT NOT NULL,
                created_at TEXT,
                last_login TEXT,
                note TEXT,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS sessions(
                token TEXT PRIMARY KEY,
                login TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ip TEXT
            );
            """)
        add("registrations", (("relay", "TEXT"), ("leg", "INTEGER"), ("rank", "TEXT")))
        # 4.4: состояние стадионного табло (пульт управления) — по соревнованию
        self.con.execute("CREATE TABLE IF NOT EXISTS scoreboard(event_id INTEGER PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL)")
        # 4.5: две роли — администратор и судья; секретарь и судья на секторе становятся судьями
        self.con.execute("UPDATE users SET role = 'judge' WHERE role NOT IN ('admin', 'judge')")
```

## 3. [ВЕСЬ ИЗМЕНЁННЫЙ КОД PYTHON] — `hub/hub.py`

Примечание: функции `add_entry`, `get_next_bib`, `next_bib` приведены как есть. Отдельной функции «автоопределения официального времени» нет: правило ручного хронометража реализовано в `stopwatch_main`, а вызывается из ветки `results` (§3.6).

### 3.1 Определение типа дисциплины (Бег / Техника)

#### `Hub.discipline` — `hub/hub.py` строки 2282–2284

```python
    @classmethod
    def discipline(cls, name) -> Optional[dict]:
        return cls.disciplines()["index"].get(cls._dkey(name)) if name else None
```

#### `Hub.result_type` — `hub/hub.py` строки 2410–2414

```python
    @classmethod
    def result_type(cls, name) -> str:
        """time · distance · height · points. Неизвестная дисциплина — время, как раньше."""
        d = cls.discipline(name)
        return d["result"] if d else "time"
```

#### `Hub.discipline_kind` — `hub/hub.py` строки 2393–2401

```python
    @classmethod
    def discipline_kind(cls, name) -> str:
        """run — бег (время), tech — техника (попытки: прыжки, метания), other — очки и прочее."""
        d = cls.discipline(name)
        if not d:
            return "run"
        if d.get("attempts") or d.get("result") in ("distance", "height"):
            return "tech"
        return "run" if d.get("result") == "time" else "other"
```

#### `Hub.attempt_slots` — `hub/hub.py` строки 2202–2208

```python
    @classmethod
    def attempt_slots(cls, name) -> int:
        """Сколько ячеек попыток: 6 в прыжках и метаниях; в высоте и шесте — до 12 покорённых высот."""
        d = cls.discipline(name)
        if not d or not d.get("attempts"):
            return 0
        return 12 if d.get("result") == "height" else 6
```

#### `Hub.entry_dists` — `hub/hub.py` строки 2403–2408

```python
    def entry_dists(self, eid: int, erows: Optional[list] = None) -> dict:
        """chip → дисциплина участника: дистанция забега, а у смешанного «общего списка» — из заявки."""
        erows = erows if erows is not None else self.store.entries_rows(eid)
        wd = {w["name"]: w.get("distance") for w in self.store.waves(eid)}
        rd = {r["id"]: r.get("distance") for r in self.store.registrations(eid)}
        return {e["chip"]: (wd.get(e["wave"] or "") or rd.get(e.get("reg_id")) or None) for e in erows}
```

### 3.2 Формирование сетки: полная и выборочная (Мастер)

#### `Hub.generate_scoped` — `hub/hub.py` строки 4258–4366

```python
    def generate_scoped(self, ev: dict, lanes: int, scope: dict) -> dict:
        """Мастер протоколов: сетка одной дисциплины с фильтром по возрасту и полу.
        Бег — забеги и дорожки. Техника (попытки) — ТОЛЬКО единый «Общий список», дорожки заблокированы.
        Остальные дисциплины, их участники и введённые результаты не затрагиваются; участники другого пола
        в уже сформированном списке этой же дисциплины остаются на месте."""
        eid = ev["id"]
        dist = str(scope.get("distance") or "").strip()
        kind = self.discipline_kind(dist)
        sex = str(scope.get("sex") or "").strip().upper()[:1]
        sex = sex if sex in ("М", "Ж") else ""
        ages = [a for a in (scope.get("ages") or []) if a in self.AGE_LIMITS]
        lanes = max(1, min(int(lanes or 8), 50))
        waves = self.store.waves(eid)
        if any(w.get("start_time") for w in waves if (w.get("distance") or "") == dist):
            raise ValueError("по этой дисциплине уже был старт забега — пересобрать нельзя")
        year = int(ev["date"][:4]) if ev.get("date") else dt.date.today().year

        def in_scope(r):
            if r["distance"] != dist or r["status"] != "approved":
                return False
            if sex and str(r.get("sex") or "").upper() != sex:
                return False
            if ages:
                try:
                    age = year - int(str(r["birth_date"])[:4])
                except ValueError:
                    return False
                return any(self.AGE_LIMITS[a][0] <= age <= self.AGE_LIMITS[a][1] for a in ages)
            return True
        allregs = self.store.registrations(eid)
        regs = self.collapse_relays(ev, [r for r in allregs if in_scope(r)])
        if not regs:
            raise ValueError("нет подтверждённых заявок по выбранным условиям: проверьте дисциплину, возраст и пол")
        mine = {r["id"] for r in regs}
        entries = self.store.entries_rows(eid)
        old = {e["reg_id"]: e for e in entries if e.get("reg_id")}
        used = {e["bib"] for e in entries}
        # удаляем только свои забеги: те, где нет участников вне выбранной группы
        by_wave: dict = {}
        for e in entries:
            if e["wave"]:
                by_wave.setdefault(e["wave"], []).append(e)
        gone = []
        for w in waves:
            if (w.get("distance") or "") != dist:
                continue
            if all(e.get("reg_id") in mine for e in by_wave.get(w["name"], [])):
                gone.append(w["name"])
        for name in gone:
            self.store.delete_wave(eid, name)
        alive = {w["name"] for w in self.store.waves(eid)}
        cat_order = {r["name"]: i for i, r in enumerate(self.parse_rules(ev.get("reg_rules") or ""))}
        plan, tech = [], kind == "tech"
        if tech:
            # техника: дорожек нет; у каждой категории (пол × возраст) — свой сквозной список, своя нумерация и свои места
            bycat: dict = {}
            for r in regs:
                bycat.setdefault(r.get("category") or "", []).append(r)
            for cat in sorted(bycat, key=lambda c: (cat_order.get(c, 99), c)):
                lst = sorted(bycat[cat], key=lambda r: r["id"])
                base = "Общий список · " + dist + (" · " + cat if cat else (" · " + ("Мальчики" if sex == "М" else "Девочки") if sex else ""))
                name, i = base, 1
                while name in alive:
                    i += 1
                    name = f"{base} ({i})"
                alive.add(name)
                plan.append((name, cat, lst, False))
        else:
            n = max([int(m.group(1)) for m in (re.fullmatch(r"Забег (\d+)", x) for x in alive) if m] or [0])
            groups: dict = {}
            for r in regs:
                groups.setdefault(r.get("category") or "", []).append(r)
            for cat in sorted(groups, key=lambda c: (cat_order.get(c, 99), c)):
                lst = sorted(groups[cat], key=lambda r: (r["best_sec"] is None, r["best_sec"] or 0, r["id"]))
                k = math.ceil(len(lst) / lanes)
                b_, extra = divmod(len(lst), k)
                sizes = [b_ + (1 if i >= k - extra else 0) for i in range(k)]
                chunks, pos = [], 0
                for size in reversed(sizes):
                    chunks.append(lst[pos:pos + size])
                    pos += size
                chunks.reverse()
                for chunk in chunks:
                    n += 1
                    plan.append((f"Забег {n}", cat, chunk, True))
        heats, rows = [], []
        order = self.lane_order(lanes)
        for name, cat, chunk, use_lanes in plan:
            heats.append({"name": name, "distance": dist, "category": cat, "count": len(chunk)})
            for i, r in enumerate(chunk):
                e = old.get(r["id"])
                if e:
                    bib, chip = e["bib"], e["chip"]
                else:
                    bib = self.next_bib(ev, used, r["distance"])
                    used.add(bib)
                    chip = "#" + bib
                rows.append({"bib": bib, "chip": chip, "wave": name, "name": " ".join(x for x in (r["last_name"], r["first_name"]) if x),
                             "birth_year": r["birth_date"][:4].strip(), "team": r.get("team"), "category": r.get("category"),
                             "lane": order[i] if use_lanes else None, "coach": r.get("coach"), "seed": r.get("best"),
                             "reg_id": r["id"], "sex": r.get("sex"), "members": r.get("members"), "rank": r.get("rank"),
                             "_ids": r.get("_ids") or [r["id"]]})
        self.store.upsert_entries(eid, rows)
        for h in heats:
            self.store.update_wave(eid, h["name"], category=h["category"] or None, distance=dist)
        for r in rows:
            for rid in r["_ids"]:
                self.store.update_registration(rid, bib=r["bib"])
        return {"heats": heats, "entries": len(rows), "kind": kind, "mode": "list" if tech else "heats"}
```

#### `Hub.generate_heats` — `hub/hub.py` строки 4368–4439

```python
    def generate_heats(self, ev: dict, lanes: int, mode: str = "heats") -> dict:
        """Подтверждённые заявки → забеги по категории и дистанции, посев по лучшему результату:
        сильнейшие — в последнем забеге группы, внутри забега — на центральных дорожках."""
        eid = ev["id"]
        if any(w.get("start_time") for w in self.store.waves(eid)):
            raise ValueError("уже был старт забега — пересобрать нельзя, переносите участников вручную")
        lanes = max(1, min(int(lanes or 8), 50))
        regs = self.collapse_relays(ev, [r for r in self.store.registrations(eid) if r["status"] == "approved"])
        if not regs:
            raise ValueError("нет подтверждённых заявок")
        dist_order = {d: i for i, d in enumerate(self.reg_distances(ev))}
        cat_order = {r["name"]: i for i, r in enumerate(self.parse_rules(ev.get("reg_rules") or ""))}
        groups: dict = {}
        for r in regs:
            groups.setdefault((r["distance"], r.get("category") or ""), []).append(r)
        old = {e["reg_id"]: e for e in self.store.entries_rows(eid) if e.get("reg_id")}
        used = {e["bib"] for e in old.values()}

        def bib_for(r):
            e = old.get(r["id"])
            if e:
                return e["bib"], e["chip"]
            b = self.next_bib(ev, used, r["distance"])   # диапазон номеров дистанции, если задан
            used.add(b)
            return b, "#" + b

        heats, rows, n = [], [], 0
        plan = []        # (дистанция, категория, участники, дорожки?)
        if mode == "list":
            # «Общим списком»: никакого деления на забеги и дорожки — один сквозной список
            dists = {r["distance"] for r in regs}
            lst = sorted(regs, key=lambda r: (dist_order.get(r["distance"], 99), cat_order.get(r.get("category") or "", 99), r["id"]))
            plan.append((dists.pop() if len(dists) == 1 else "", "", lst, False))
        else:
            for key in sorted(groups, key=lambda k: (dist_order.get(k[0], 99), k[0], cat_order.get(k[1], 99), k[1])):
                sign = 1 if self.result_type(key[0]) == "time" else -1        # в прыжках и метаниях лучший — наибольший результат
                lst = sorted(groups[key], key=lambda r: (r["best_sec"] is None, sign * (r["best_sec"] or 0), r["id"]))
                k = math.ceil(len(lst) / lanes)
                base, extra = divmod(len(lst), k)
                sizes = [base + (1 if i >= k - extra else 0) for i in range(k)]   # полные забеги — последние
                chunks, pos = [], 0
                for size in reversed(sizes):            # от сильнейших
                    chunks.append(lst[pos:pos + size])
                    pos += size
                chunks.reverse()                        # слабые забеги — первыми, сильнейший — последний
                plan += [(key[0], key[1], chunk, True) for chunk in chunks]
        for dist, cat, chunk, use_lanes in plan:
            n += 1
            name = "Общий список" if mode == "list" else f"Забег {n}"
            heats.append({"name": name, "distance": dist, "category": cat, "count": len(chunk)})
            order = self.lane_order(lanes)
            for i, r in enumerate(chunk):
                bib, chip = bib_for(r)
                full = " ".join(x for x in (r["last_name"], r["first_name"]) if x)
                rows.append({"bib": bib, "chip": chip, "wave": name, "name": full, "birth_year": r["birth_date"][:4].strip(),
                             "team": r.get("team"), "category": r.get("category"), "lane": order[i] if use_lanes else None,
                             "coach": r.get("coach"), "seed": r.get("best"), "reg_id": r["id"], "sex": r.get("sex"),
                             "members": r.get("members"), "rank": r.get("rank"), "_ids": r.get("_ids") or [r["id"]]})
        self.store.con.execute("BEGIN")
        try:
            self.store.con.execute("DELETE FROM waves WHERE event_id = ?", (eid,))
            self.store.con.execute("COMMIT")
        except Exception:
            self.store.con.execute("ROLLBACK")
            raise
        self.store.set_entries(eid, rows)
        for h in heats:
            self.store.update_wave(eid, h["name"], category=h["category"] or None, distance=h["distance"] or None)
        for r in rows:
            for rid in r["_ids"]:
                self.store.update_registration(rid, bib=r["bib"])
        return {"heats": heats, "entries": len(rows)}
```

#### `Hub.lane_order` — `hub/hub.py` строки 4244–4253

```python
    @staticmethod
    def lane_order(n: int) -> list:
        """Дорожки от центра: 8 → 4,5,3,6,2,7,1,8 — сильнейшие в центре."""
        mid = (n + 1) // 2
        order = [mid]
        for k in range(1, n):
            for c in (mid + k, mid - k):
                if 1 <= c <= n and c not in order:
                    order.append(c)
        return order[:n]
```

#### `Hub.reset_heats` — `hub/hub.py` строки 4441–4458

```python
    def reset_heats(self, ev: dict, distance: Optional[str] = None) -> dict:
        """Полный сброс сетки: у участников очищаются забег и дорожка, забеги удаляются.
        Номера и чипы сохраняются; участники возвращаются в «Не распределены». distance — только эта дисциплина."""
        eid = ev["id"]
        waves = [w for w in self.store.waves(eid) if not distance or (w.get("distance") or "") == distance]
        if any(w.get("start_time") for w in waves):
            raise ValueError("уже был старт забега — сбросить сетку нельзя")
        names = [w["name"] for w in waves]
        n = 0
        for r in self.store.entries_rows(eid):
            if distance and r["wave"] not in names:
                continue
            if r["wave"] or r["lane"] is not None:
                self.store.update_entry(eid, r["bib"], wave=None, lane=None)
                n += 1
        for name in names:
            self.store.delete_wave(eid, name)
        return {"waves": len(names), "entries": n}
```

#### `Hub.AGE_LIMITS` — `hub/hub.py` строки 4256–4256

```python
    AGE_LIMITS = {"u12": (0, 12), "u14": (0, 14), "u16": (0, 16), "u18": (0, 18), "u20": (0, 20), "u23": (0, 23), "sen": (19, 200)}
```

### 3.3 Номера и участники

#### `Store.get_next_bib` — `hub/hub.py` строки 1180–1187

```python
    def get_next_bib(self, eid: int) -> str:
        """Получить следующий свободный номер участника (максимальный + 1)."""
        result = self.con.execute(
            "SELECT MAX(CAST(bib AS INTEGER)) FROM entries WHERE event_id = ? AND bib GLOB '[0-9]*'",
            (eid,)
        ).fetchone()
        max_bib = result[0] if result and result[0] is not None else 0
        return str(max_bib + 1)
```

#### `Store.add_entry` — `hub/hub.py` строки 1189–1205

```python
    def add_entry(self, eid: int, r: dict) -> None:
        # Если номер не указан, присваиваем следующий свободный
        bib = r.get("bib")
        if not bib or str(bib).strip() == "":
            bib = self.get_next_bib(eid)

        # Если чип не указан, используем номер с префиксом #
        chip = r.get("chip")
        if not chip or str(chip).strip() == "":
            chip = "#" + str(bib)

        self.con.execute(
            "INSERT INTO entries(event_id, bib, chip, wave, name, birth_year, team, category, lane, coach, seed,"
            " reg_id, sex, members, rank) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, bib, chip, r.get("wave"), r.get("name"), r.get("birth_year"), r.get("team"),
             r.get("category"), r.get("lane"), r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex"),
             r.get("members"), r.get("rank")))
```

#### `Store.set_entries` — `hub/hub.py` строки 1079–1103

```python
    def set_entries(self, eid: int, rows: list) -> None:
        keep = {r[0]: dict(zip(self._KEEP, r[1:])) for r in self.con.execute(
            "SELECT bib, picked_at, members, detail, rank, done_rank FROM entries WHERE event_id = ?", (eid,))}
        self.con.execute("BEGIN")
        try:
            self.con.execute("DELETE FROM entries WHERE event_id = ?", (eid,))

            def val(r, k):
                v = r[k] if k in r else keep.get(r["bib"], {}).get(k)
                return json.dumps(v, ensure_ascii=False) if k == "detail" and isinstance(v, dict) else v
            self.con.executemany(
                "INSERT OR REPLACE INTO entries(event_id, bib, chip, wave, name, birth_year, team, category,"
                " lane, coach, seed, reg_id, sex, result, status, points, picked_at, members, detail, rank, done_rank)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(eid, r["bib"], r["chip"], r.get("wave"), r.get("name"), r.get("birth_year"), r.get("team"),
                  r.get("category"), r.get("lane"), r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex"),
                  r.get("result"), r.get("status"), r.get("points"),
                  val(r, "picked_at"), val(r, "members"), val(r, "detail"), val(r, "rank"), val(r, "done_rank"))
                 for r in rows])
            for w in dict.fromkeys(r["wave"] for r in rows if r.get("wave")):
                self.con.execute("INSERT OR IGNORE INTO waves(event_id, name) VALUES (?,?)", (eid, w))
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
```

#### `Store.upsert_entries` — `hub/hub.py` строки 1105–1129

```python
    def upsert_entries(self, eid: int, rows: list) -> None:
        """Выборочное формирование: участники других дисциплин и уже введённые результаты не трогаются."""
        self.con.execute("BEGIN")
        try:
            for r in rows:
                have = self.con.execute("SELECT 1 FROM entries WHERE event_id = ? AND bib = ?", (eid, r["bib"])).fetchone()
                if have:
                    self.con.execute(
                        "UPDATE entries SET wave = ?, lane = ?, name = ?, birth_year = ?, team = ?, category = ?, coach = ?,"
                        " seed = ?, reg_id = ?, sex = ?, rank = ?, members = COALESCE(?, members) WHERE event_id = ? AND bib = ?",
                        (r.get("wave"), r.get("lane"), r.get("name"), r.get("birth_year"), r.get("team"), r.get("category"),
                         r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex"), r.get("rank"), r.get("members"), eid, r["bib"]))
                else:
                    self.con.execute(
                        "INSERT INTO entries(event_id, bib, chip, wave, name, birth_year, team, category, lane, coach, seed,"
                        " reg_id, sex, members, rank) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (eid, r["bib"], r["chip"], r.get("wave"), r.get("name"), r.get("birth_year"), r.get("team"),
                         r.get("category"), r.get("lane"), r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex"),
                         r.get("members"), r.get("rank")))
            for w in dict.fromkeys(r["wave"] for r in rows if r.get("wave")):
                self.con.execute("INSERT OR IGNORE INTO waves(event_id, name) VALUES (?,?)", (eid, w))
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
```

#### `Store.update_entry` — `hub/hub.py` строки 1168–1178

```python
    def update_entry(self, eid: int, bib: str, **kw) -> int:
        sets, args = [], []
        for k, v in kw.items():
            if k not in ("wave", "lane", "name", "birth_year", "team", "category", "coach", "seed", "rank", "done_rank"):
                raise ValueError(k)
            sets.append(f"{k} = ?")
            args.append(v)
        if not sets:
            return 0
        return self.con.execute(f"UPDATE entries SET {', '.join(sets)} WHERE event_id = ? AND bib = ?",
                                (*args, eid, bib)).rowcount
```

#### `Store.rename_bib` — `hub/hub.py` строки 1207–1212

```python
    def rename_bib(self, eid: int, old: str, new: str) -> None:
        """Сменить нагрудный номер участника везде: в списке, заявках и ручных отметках судей."""
        self.con.execute("UPDATE entries SET bib = ?, chip = CASE WHEN chip = ? THEN ? ELSE chip END"
                         " WHERE event_id = ? AND bib = ?", (new, "#" + old, "#" + new, eid, old))
        self.con.execute("UPDATE registrations SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
        self.con.execute("UPDATE manual SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
```

#### `Hub.next_bib` — `hub/hub.py` строки 3797–3806

```python
    def next_bib(self, ev: dict, used, distance: str) -> str:
        """Следующий свободный номер: в диапазоне дистанции («номера с 500») или после самого большого."""
        specs = self.dist_specs(ev)
        nums = {int(b) for b in used if str(b).isdigit()}
        lo = next((d["bib_from"] for d in specs if d["name"] == distance and d["bib_from"]), None)
        if lo is None:
            return str(max(nums | {0}) + 1)
        hi = min([d["bib_from"] for d in specs if d["bib_from"] and d["bib_from"] > lo] or [10 ** 9])
        inside = [n for n in nums if lo <= n < hi]
        return str(max(inside) + 1 if inside else lo)
```

### 3.4 Список для печати

#### `Hub.startlist` — `hub/hub.py` строки 4498–4517

```python
    def startlist(self, ev: dict) -> dict:
        rows = self.store.entries_rows(ev["id"])
        # у каждого участника своя дисциплина (из заявки): в смешанном «общем списке» забег без дистанции,
        # а бланк техники (6 попыток) определяется именно по ней
        rd = {r["id"]: r.get("distance") or "" for r in self.store.registrations(ev["id"])}
        for r in rows:
            d = rd.get(r.get("reg_id")) or ""
            r["distance"] = d
            r["rtype"] = self.result_type(d) if d else ""
            r["slots"] = self.attempt_slots(d) if d else 0
        heats = []
        for w in self.store.waves(ev["id"]):
            lst = sorted([r for r in rows if r["wave"] == w["name"]], key=lambda r: (r["lane"] is None, r["lane"] or 0,
                                                                                      int(r["bib"]) if r["bib"].isdigit() else 0))
            heats.append({"name": w["name"], "category": w.get("category") or "", "distance": w.get("distance") or "",
                          "rtype": self.result_type(w.get("distance")), "slots": self.attempt_slots(w.get("distance")),
                          "start_time": w.get("start_time"), "state": "finished" if w.get("finished_at") else
                          ("running" if w.get("start_time") else "planned"), "entries": lst})
        loose = [r for r in rows if not r["wave"]]
        return {"event": self._event_view(ev), "heats": heats, "no_heat": loose}
```

#### `Hub.public_startlist` — `hub/hub.py` строки 2093–2097

```python
    def public_startlist(self, ev: dict) -> dict:
        sl = self.startlist(ev)
        for h in sl["heats"]:
            h["entries"] = self._no_chips(h["entries"])
        return {"event": self._public_event(ev), "heats": sl["heats"], "no_heat": self._no_chips(sl["no_heat"])}
```

### 3.5 Хранение результата и отметок

#### `Store.set_entry_result` — `hub/hub.py` строки 1148–1159

```python
    def set_entry_result(self, eid: int, bib: str, result: Optional[str], status: Optional[str],
                         detail: Optional[dict] = None, set_detail: bool = False) -> int:
        """Итог участника. detail — показания секундомеров {"t": [...]} и попытки {"a": [...]}; None при set_detail стирает."""
        at = fmt_db(now_local()) if (result or status or detail) else None      # время ввода — табло показывает свежие сверху
        if set_detail:
            dj = json.dumps(detail, ensure_ascii=False) if detail else None
            cur = self.con.execute("UPDATE entries SET result = ?, status = ?, detail = ?, result_at = ? WHERE event_id = ? AND bib = ?",
                                   (result or None, status or None, dj, at, eid, bib))
        else:
            cur = self.con.execute("UPDATE entries SET result = ?, status = ?, result_at = ? WHERE event_id = ? AND bib = ?",
                                   (result or None, status or None, at, eid, bib))
        return cur.rowcount
```

### 3.6 Официальное время по 3 секундомерам и лучший результат из 6 попыток

#### `Hub.round_up_tenth` — `hub/hub.py` строки 2185–2187

```python
    @staticmethod
    def round_up_tenth(x: float) -> float:
        return math.ceil(round(x * 10, 6)) / 10.0
```

#### `Hub.stopwatch_main` — `hub/hub.py` строки 2189–2198

```python
    @classmethod
    def stopwatch_main(cls, secs: list) -> Optional[float]:
        """Главный результат по показаниям секундомеров (правила ручного хронометража):
        три — среднее по величине (если два совпали, это их время), два — худшее, один — он сам.
        Округление вверх до десятой доли секунды."""
        v = sorted(x for x in secs if x is not None)
        if not v:
            return None
        main = v[1] if len(v) >= 3 else v[-1]
        return cls.round_up_tenth(main)
```

#### `Hub.parse_result` — `hub/hub.py` строки 2238–2255

```python
    @classmethod
    def parse_result(cls, text) -> Optional[tuple]:
        """Результат, введённый секретарём: 12.84 · 12,8 · 1:05.32 · 2:05:31 → (секунды, текст для протокола)."""
        t = re.sub(r"\s+", "", str(text or ""))
        m = cls.RESULT_RE.fullmatch(t)
        if not m or not t:
            return None
        a, b, c, frac = m.groups()
        h, mi = (int(a), int(b)) if b is not None else (0, int(a) if a is not None else 0)
        sec = int(c)
        if (a is not None or b is not None) and sec >= 60:
            return None
        total = h * 3600 + mi * 60 + sec + (int(frac) / 10 ** len(frac) if frac else 0)
        if total <= 0:
            return None
        f = f".{frac}" if frac else ""
        txt = f"{h}:{mi:02d}:{sec:02d}{f}" if h else (f"{mi}:{sec:02d}{f}" if mi else f"{sec}{f}")
        return total, txt
```

#### `Hub.fmt_result` — `hub/hub.py` строки 2156–2167

```python
    @staticmethod
    def fmt_result(sec: float) -> str:
        """Результат для протокола: 58.3 · 4:05.2 · 1:02:05.2"""
        tenths = int(round(sec * 10))
        h, rem = divmod(tenths, 36000)
        m, rem = divmod(rem, 600)
        s, t = divmod(rem, 10)
        if h:
            return f"{h}:{m:02d}:{s:02d}.{t}"
        if m:
            return f"{m}:{s:02d}.{t}"
        return f"{s}.{t}"
```

#### `Hub.parse_typed` — `hub/hub.py` строки 2416–2435

```python
    @classmethod
    def parse_typed(cls, rtype: str, text, name=None) -> Optional[tuple]:
        """Результат по типу дисциплины → (ключ места: меньше — лучше, текст для протокола) или None.
        Время — как раньше; расстояние и высота — метры (7.85 · 7,85); очки — целое число."""
        if rtype == "time":
            return cls.parse_result(text)
        t = re.sub(r"\s+", "", str(text or ""))
        mx = (cls.discipline(name) or {}).get("max")
        if rtype == "points":
            if not re.fullmatch(r"\d{1,5}", t):
                return None
            v = int(t)
            return (-float(v), str(v)) if 0 < v <= (mx or 12000) else None
        m = re.fullmatch(r"(\d{1,3})(?:[.,](\d{1,2}))?", t)
        if not m:
            return None
        v = float(f"{m.group(1)}.{m.group(2) or 0}")
        if v <= 0 or v > (mx or (8.0 if rtype == "height" else 120.0)):
            return None
        return -v, f"{v:.2f}"
```

#### `Hub.parse_attempts` — `hub/hub.py` строки 2210–2233

```python
    @classmethod
    def parse_attempts(cls, rtype: str, cells: list, name=None) -> tuple:
        """Ячейки попыток → (чистый список, лучший результат (ключ, текст) или None, ошибки [(номер, текст)]).
        Значения — по типу дисциплины (7.85), отметки: X — неудачная, «-» — пропуск, r — отказ от попытки."""
        clean, best, errs = [], None, []
        for i, raw in enumerate(cells, 1):
            t = re.sub(r"\s+", "", str(raw or ""))
            if not t:
                clean.append("")
                continue
            if t in cls.ATTEMPT_MARKS:
                clean.append(cls.ATTEMPT_MARKS[t])
                continue
            pr = cls.parse_typed(rtype, t, name)
            if not pr:
                errs.append((i, f"попытка {i}: не понял «{t[:10]}» — пример: {cls.result_hint(rtype)}, X — неудачная, «-» — пропуск"))
                clean.append("")
                continue
            clean.append(pr[1])
            if best is None or pr[0] < best[0]:
                best = pr
        while clean and not clean[-1]:
            clean.pop()
        return clean, best, errs
```

#### `Hub.result_hint` — `hub/hub.py` строки 2437–2439

```python
    @classmethod
    def result_hint(cls, rtype: str) -> str:
        return (cls.disciplines()["data"].get("result_types", {}).get(rtype) or {}).get("hint") or "12.84 или 4:05.32"
```

### 3.7 Выполненный разряд по нормам ЕВСК

#### `Hub.norm_key` — `hub/hub.py` строки 2295–2327

```python
    @classmethod
    def norm_key(cls, name) -> str:
        """Название дисциплины → ключ для поиска норм: run:60, hurdles:110, jump:lj, throw:jt, multi:7 …
        Пустая строка — дисциплина без норм (эстафеты, неизвестные)."""
        t = re.sub(r"\s+", " ", str(name or "").lower().replace("ё", "е")).strip()
        if not t or "эстафет" in t or re.search(r"\d\s*[x×х*]\s*\d", t) or "швед" in t:
            return ""
        if "борье" in t:
            m = re.search(r"(\d+)\s*-?\s*борье", t)
            n = m.group(1) if m else next((v for k, v in cls._MULTI.items() if k in t), "")
            return f"multi:{n}" if n else ""
        for k, v in (("шест", "jump:pv"), ("тройн", "jump:tj"), ("высот", "jump:hj"), ("длин", "jump:lj"), ("ядр", "throw:sp"),
                     ("диск", "throw:dt"), ("молот", "throw:ht"), ("копь", "throw:jt"), ("гранат", "throw:gr"), ("мяч", "throw:ball")):
            if k in t:
                return v
        if "миля" in t:
            return "run:mile"
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(км|м)\b", t.replace("10 000", "10000")) or re.search(r"(\d+(?:[.,]\d+)?)", t)
        if not m:
            return ""
        meters = float(m.group(1).replace(",", ".")) * (1000 if len(m.groups()) > 1 and m.group(2) == "км" else 1)
        dist = f"{meters:g}"
        if "ходьб" in t:
            return f"walk:{dist}"
        if "кросс" in t:
            return f"cross:{dist}"
        if "шоссе" in t or "марафон" in t:
            return f"road:{dist}"
        if "с/б" in t or "м/б" in t or "барьер" in t:
            return f"hurdles:{dist}"
        if "с/п" in t or "препятств" in t or "стипль" in t:
            return f"steeple:{dist}"
        return f"run:{dist}"
```

#### `Hub.rank_norms` — `hub/hub.py` строки 2329–2342

```python
    @classmethod
    def rank_norms(cls) -> dict:
        if cls._NORMS is None:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed", "rank_norms.json")
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {"norms": []}
            idx: dict = {}
            for n in data.get("norms", []):
                idx.setdefault((n["key"], n["sex"]), []).append(n)
            cls._NORMS = {"data": data, "index": idx}
        return cls._NORMS
```

#### `Hub.age_group` — `hub/hub.py` строки 2344–2349

```python
    @staticmethod
    def age_group(age: int) -> str:
        for lim in (12, 14, 16, 18, 20, 23):
            if age < lim:
                return f"u{lim}"
        return "sen"
```

#### `Hub.rank_for` — `hub/hub.py` строки 2351–2391

```python
    def rank_for(self, ev: dict, dist, sex, birth_year, value: float, hand: bool) -> str:
        """Высший разряд, норму которого выполнил результат (value: секунды, метры или очки).
        Учитываются пол, возраст в год соревнований, ручной/автохронометраж, круг (манеж — 200 м),
        высота барьеров и масса снарядов по возрастной группе, минимальный возраст званий и статус соревнований."""
        key = self.norm_key(dist)
        sex = str(sex or "").upper()[:1]
        if not key or sex not in ("М", "Ж") or value is None:
            return ""
        rows = self.rank_norms()["index"].get((key, sex))
        if not rows:
            return ""
        try:
            age = int(str(ev.get("date") or "")[:4] or dt.date.today().year) - int(str(birth_year)[:4])
        except ValueError:
            return ""
        if age < 10:
            return ""
        grp = self.age_group(age)
        venue = self.venue_for(ev) or {}
        lap = "200" if "манеж" in (venue.get("name") or "").lower() or "(зал)" in str(dist) else "400"
        timing = "hand" if hand else "auto"
        cand = [r for r in rows if r.get("timing") in ("any", timing)] or rows
        cand = [r for r in cand if not r.get("var") or r["var"] in ("water", "track")] or cand
        laps = {r.get("lap") for r in cand}
        if lap in laps:
            cand = [r for r in cand if r.get("lap") in (lap, None)]
        elif "400" in laps:                       # нет норм для круга 200 м — берутся нормы круга 400 м
            cand = [r for r in cand if r.get("lap") in ("400", None)]
        pick = [r for r in cand if grp in (r.get("ages") or [])] or [r for r in cand if not r.get("ages")]
        if not pick:
            return ""
        norm = pick[0]
        cap = self.RANK_CAP.get(ev.get("level") or "region", "1 р.")
        allowed = self.RANK_ORDER[self.RANK_ORDER.index(cap):]
        for rk in self.RANK_ORDER:
            v = norm["v"].get(rk)
            if v is None or rk not in allowed or age < self.RANK_MIN_AGE.get(rk, 10):
                continue
            if (value <= v + 1e-9) if norm["better"] == "lower" else (value >= v - 1e-9):
                return rk
        return ""
```

#### `Hub.norm_rank` — `hub/hub.py` строки 2177–2182

```python
    @classmethod
    def norm_rank(cls, v) -> str:
        """Разряд как в протоколах: «1р», «1 разряд», «кмс» → «1 р.», «КМС». Пустое — пустая строка."""
        t = re.sub(r"\s+", " ", str(v or "")).strip()[:20]
        key = re.sub(r"[\s./]+", "", t.lower()).replace("первый", "1").replace("второй", "2").replace("третий", "3")
        return cls._RANK_ALIAS.get(key) or cls._RANK_ALIAS.get(key.rstrip("."), "") or t
```

#### `Hub.RANK_ORDER` — `hub/hub.py` строки 2288–2288

```python
    RANK_ORDER = ("МСМК", "МС", "КМС", "1 р.", "2 р.", "3 р.", "1 юн.", "2 юн.", "3 юн.")
```

#### `Hub.RANK_MIN_AGE` — `hub/hub.py` строки 2289–2289

```python
    RANK_MIN_AGE = {"МСМК": 16, "МС": 15, "КМС": 14}          # остальные разряды — с 10 лет
```

#### `Hub.RANK_CAP` — `hub/hub.py` строки 2291–2291

```python
    RANK_CAP = {"russia": "МС", "dfo": "МС", "interregion": "КМС", "region": "1 р.", "mass": "2 р."}
```

### 3.8 Ветки HTTP-API Мастера (внутри `Hub._api_event`)

#### `heats — формирование сетки (полное и выборочное)` — `hub/hub.py` строки 3530–3547

```python
        if action == "heats":
            try:
                if str(data.get("distance") or "").strip():       # мастер протоколов: одна дисциплина
                    out = self.generate_scoped(ev, data.get("lanes") or ev.get("reg_lanes") or 8, data)
                else:
                    out = self.generate_heats(ev, data.get("lanes") or ev.get("reg_lanes") or 8, "list" if data.get("mode") == "list" else "heats")
            except ValueError as e:
                return err(str(e))
            if data.get("lanes"):
                self.store.update_event(eid, {"reg_lanes": data["lanes"]})
            self.store.audit(who, eid, "Сформирован общий список" if data.get("mode") == "list" or out.get("mode") == "list" else "Сформированы забеги",
                             f"{data.get('distance') + ': ' if data.get('distance') else ''}{len(out['heats'])} забегов, {out['entries']} участников")
            try:
                self.save_file(eid, f"Стартовый список {now_local():%Y-%m-%d %H-%M}.csv",
                               self._startlist_csv(self.store.get_event(eid)).encode("utf-8"), "startlist", who, "Для судей")
            except Exception:
                log.exception("стартовый список в папку «Для судей»")
            return ok(out)
```

#### `resetheats — сброс сетки (всей или одной дисциплины)` — `hub/hub.py` строки 3523–3529

```python
        if action == "resetheats":
            try:
                out = self.reset_heats(ev, data.get("distance"))
            except ValueError as e:
                return err(str(e))
            self.store.audit(who, eid, "Сброшена сетка забегов", f"забегов удалено: {out['waves']}, участников возвращено в нераспределённые: {out['entries']}")
            return ok(out)
```

#### `publish — выгрузка в общую сеть` — `hub/hub.py` строки 3502–3522

```python
        if action == "publish":
            # «Выгрузить в общую сеть»: стартовый и/или итоговый протокол становится виден на публичной странице события
            upd = {}
            if "start" in data:
                upd["pub_start"] = bool(data["start"])
            if "results" in data:
                upd["pub_results"] = bool(data["results"])
            if not upd:
                return err("не указано, что выгружать")
            if upd.get("pub_start") and not any(w for w in self.store.waves(eid)):
                return err("стартовый протокол пуст: сначала сформируйте сетку")
            if not self.public_base():
                return err("публичный сайт не настроен на этом сервере (Система → Настройки сайта)")
            slug = self.ensure_slug(eid)
            self.store.update_event(eid, {**upd, "ours": True})
            self.store.audit(who, eid, "Протоколы выгружены в общую сеть" if any(upd.values()) else "Протоколы убраны из общей сети",
                             ", ".join(f"{k}={'да' if v else 'нет'}" for k, v in upd.items()))
            v = self._event_view(self.store.get_event(eid))
            return ok({"pub_start": v["pub_start"], "pub_results": v["pub_results"], "url": v["page_url"],
                       "start_url": f"{self.public_base()}/r/{slug}/protocol?kind=start",
                       "results_url": f"{self.public_base()}/r/{slug}/protocol?kind=results"})
```

#### `entry — перенос участника, смена номера, добавление заявки в забег (прикладной «add_entry»)` — `hub/hub.py` строки 3548–3623

```python
        if action == "entry":
            def clean_bib(v, used):
                v = str(v or "").strip()
                if not v or len(v) > 10 or not re.fullmatch(r"[0-9A-Za-zА-Яа-я\-]+", v):
                    return None, "номер — до 10 символов: цифры или буквы, без пробелов"
                if v in used or "#" + v in {e["chip"] for e in self.store.entries_rows(eid)}:
                    return None, f"номер {v} уже занят другим участником"
                return v, None
            # перенос участника в другой забег / дорожку, или добавление подтверждённой заявки в забег
            wave = str(data.get("wave") or "").strip()[:40] or None
            if wave and not self.store.get_wave(eid, wave):
                return err(f"нет забега «{wave}»")
            lane = data.get("lane")
            try:
                lane = int(lane) if lane not in (None, "") else None
            except (TypeError, ValueError):
                return err("дорожка — число")
            if data.get("reg_id"):
                r = self.store.get_registration(int(data["reg_id"]))
                if not r or r["event_id"] != eid or r["status"] != "approved":
                    return err("заявка не найдена или не подтверждена")
                if r.get("relay"):                       # эстафета — в забег всей командой
                    team = [x for x in self.store.registrations(eid) if x["status"] == "approved"
                            and x["distance"] == r["distance"] and (x.get("relay") or "").lower() == r["relay"].lower()]
                    r = self.relay_entry(team)
                rows = self.store.entries_rows(eid)
                ids = r.get("_ids") or [r["id"]]
                if any(x.get("reg_id") in ids for x in rows) or (r.get("bib") and any(e["bib"] == r["bib"] for e in rows)):
                    return err("участник уже в стартовом списке")
                if str(data.get("set_bib") or "").strip():          # номер, который секретарь вписал сам
                    bib, e_ = clean_bib(data["set_bib"], {e["bib"] for e in rows})
                    if e_:
                        return err(e_)
                else:
                    bib = self.next_bib(ev, {e["bib"] for e in rows}, r["distance"])
                if lane is None and wave:
                    taken = {e["lane"] for e in rows if e["wave"] == wave}
                    lane = next((x for x in self.lane_order(int(ev.get("reg_lanes") or 8)) if x not in taken), None)
                self.store.add_entry(eid, {"bib": bib, "chip": "#" + bib, "wave": wave,
                                           "name": " ".join(x for x in (r["last_name"], r["first_name"]) if x),
                                           "birth_year": r["birth_date"][:4].strip(),
                                           "team": r["team"], "category": r["category"], "lane": lane,
                                           "coach": r["coach"], "seed": r["best"], "reg_id": r["id"], "sex": r["sex"],
                                           "members": r.get("members"), "rank": r.get("rank")})
                for rid in ids:
                    self.store.update_registration(rid, bib=bib)
                self.store.audit(who, eid, "Участник добавлен в забег", f"№{bib} {r['last_name']} → {wave or 'без забега'}")
                return ok({"bib": bib})
            bib = str(data.get("bib") or "").strip()
            row = next((e for e in self.store.entries_rows(eid) if e["bib"] == bib), None)
            if not row:
                return err("нет участника с таким номером", 404)
            if row["wave"] and (self.store.get_wave(eid, row["wave"]) or {}).get("start_time") and "wave" in data \
                    and wave != row["wave"]:
                return err("забег участника уже стартовал")
            if "new_bib" in data:
                if str(data["new_bib"]).strip() == bib:
                    return ok({"bib": bib})
                nb, e_ = clean_bib(data["new_bib"], {e["bib"] for e in self.store.entries_rows(eid)})
                if e_:
                    return err(e_)
                self.store.rename_bib(eid, bib, nb)
                self.store.audit(who, eid, "Изменён нагрудный номер", f"{row.get('name') or ''}: №{bib} → №{nb}")
                return ok({"bib": nb})
            upd = {}
            if "wave" in data:
                upd["wave"] = wave
                if "lane" not in data and wave:
                    taken = {e["lane"] for e in self.store.entries_rows(eid) if e["wave"] == wave}
                    upd["lane"] = next((x for x in self.lane_order(int(ev.get("reg_lanes") or 8)) if x not in taken), None)
            if "lane" in data:
                upd["lane"] = lane
            self.store.update_entry(eid, bib, **upd)
            self.store.audit(who, eid, "Перенос участника", f"№{bib}: {row['wave'] or '—'} → {upd.get('wave', row['wave']) or '—'}"
                             + (f", дорожка {upd['lane']}" if upd.get("lane") else ""))
            return ok({"ok": True})
```

#### `results — ручной ввод: секундомеры, попытки, статус, выполненный разряд` — `hub/hub.py` строки 3229–3306

```python
        if action == "results" and isinstance(data.get("rows"), list):
            bad, n = [], 0
            old = {e["bib"]: e for e in self.store.entries_rows(eid)}
            ed_ = self.entry_dists(eid, list(old.values()))
            dn_of = {b_: ed_.get(e["chip"]) for b_, e in old.items()}
            for rw in data["rows"][:2000]:
                if not isinstance(rw, dict):
                    continue
                bib = str(rw.get("bib") or "").strip()
                st = str(rw.get("status") or "").strip().upper()
                txt = str(rw.get("result") or "").strip()
                if st and st not in self.STATUSES:
                    bad.append(f"{bib}: неизвестная отметка {st}")
                    continue
                if bib not in old:
                    bad.append(f"{bib}: нет такого номера")
                    continue
                dn = dn_of.get(bib)
                rt = self.result_type(dn)
                detail, set_detail, auto_txt = {}, False, None
                # показания трёх ручных секундомеров → главный результат по правилам
                if "t" in rw and isinstance(rw["t"], list):
                    set_detail = True
                    secs, tclean, terr = [], [], False
                    for i, raw in enumerate(rw["t"][:3], 1):
                        t = str(raw or "").strip()
                        if not t:
                            tclean.append("")
                            continue
                        pr = self.parse_result(t) if rt == "time" else None
                        if not pr:
                            bad.append(f"{bib}: секундомер {i}: не понял «{t[:12]}» — пример: 12.84 или 1:05.3")
                            terr = True
                            tclean.append("")
                            continue
                        secs.append(pr[0])
                        tclean.append(pr[1])
                    if terr:
                        continue
                    while tclean and not tclean[-1]:
                        tclean.pop()
                    if tclean:
                        detail["t"] = tclean
                    m = self.stopwatch_main(secs)
                    auto_txt = self.fmt_result(m) if m is not None else None
                # попытки в прыжках и метаниях → лучший результат
                if "a" in rw and isinstance(rw["a"], list):
                    set_detail = True
                    slots = self.attempt_slots(dn) or 6
                    aclean, best, aerr = self.parse_attempts(rt, rw["a"][:slots], dn)
                    if aerr:
                        bad.extend(f"{bib}: {m_}" for _, m_ in aerr)
                        continue
                    if aclean:
                        detail["a"] = aclean
                    auto_txt = best[1] if best else None
                # auto — главный результат считает система; иначе значение секретаря остаётся как есть
                if set_detail and (rw.get("auto") or not txt):
                    txt = auto_txt or ""
                pr = None
                if txt and not st:
                    pr = self.parse_typed(rt, txt, dn)
                    if not pr:
                        bad.append(f"{bib}: не понял результат «{txt[:12]}» — пример: {self.result_hint(rt)}")
                        continue
                if "done_rank" in rw:
                    # пусто — разряд считает система по ЕВСК; «—» — вручную «не выполнен»; иначе — разряд секретаря
                    dr = str(rw.get("done_rank") or "").strip()
                    dr = self.NO_RANK if dr in ("—", "-", "–", "нет") else self.norm_rank(dr)
                    self.store.update_entry(eid, bib, done_rank=dr or None)
                    if not (set(rw) - {"bib", "done_rank", "auto"}):
                        n += 1             # прислан только разряд — результат и отметку не трогаем
                        continue
                if self.store.set_entry_result(eid, bib, pr[1] if pr else None, st or None, detail or None, set_detail):
                    n += 1
            if n:
                self.store.audit(who, eid, "Введены результаты", f"строк: {n}")
            return ok({"saved": n, "errors": bad})
```

### 3.9 `Hub.compute` (итоговые результаты) — `hub/hub.py` строки 2487–2750

Дословно: включает дисциплину участника (`entry_dists`), места по дисциплине в смешанном забеге и расчёт `done_rank`.

```python
    def compute(self, ev: dict) -> dict:
        eid = ev["id"]
        erows = self.store.entries_rows(eid)
        entered, status_of, rtype_of = {}, {}, {}
        edist = self.entry_dists(eid, erows)          # дисциплина участника: у забега или, если забег смешанный, из заявки
        for r in erows:
            if r.get("status") in self.STATUSES:
                status_of[r["chip"]] = r["status"]
            elif r.get("result"):
                dn = edist.get(r["chip"])
                rt = self.result_type(dn)
                pr = self.parse_typed(rt, r["result"], dn)
                if pr:
                    entered[r["chip"]] = pr
                    rtype_of[r["chip"]] = rt
        entries = {r["chip"]: r["bib"] for r in erows}
        info = {r["chip"]: r for r in erows}
        chip_wave = {r["chip"]: r["wave"] for r in erows if r["wave"]}
        bib_chip = {r["bib"]: r["chip"] for r in erows}
        waves = self.store.waves(eid)
        wmeta = {w["name"]: w for w in waves}
        wave_order = {w["name"]: i for i, w in enumerate(waves)}
        wave_start = {w["name"]: parse_db(w["start_time"]) for w in waves if w.get("start_time")}
        wave_end = {w["name"]: parse_db(w["finished_at"]) for w in waves if w.get("finished_at")}
        ev_start = parse_db(ev["start_time"]) if ev.get("start_time") else None
        fin_dev = ev.get("finish_device") or ""
        min_time = dt.timedelta(seconds=float(ev.get("min_time_sec") or 0))
        res = {"event": self._event_view(ev), "started": bool(ev_start or wave_start or entered),
               "devices": [], "finished": [], "on_course": [], "not_seen": [], "alerts": [],
               "manual_pending": 0, "unknown": [], "groups": []}

        def wave_of_ts(ts: dt.datetime) -> Optional[str]:
            """Забег, который шёл в момент отметки (последний стартовавший до неё)."""
            best = None
            for name, st in wave_start.items():
                if st <= ts and (best is None or st > wave_start[best]):
                    best = name
            return best

        marks = []                    # (device, chip, ts, manual)
        starts = [s for s in [ev_start, *wave_start.values()] if s]
        if starts:
            lo = min(starts)
            for device, chip, ts_s in self.store.reads_window(lo, lo + dt.timedelta(hours=24)):
                marks.append((device, chip, parse_db(ts_s), False))
        for m in self.store.manual_list(eid):
            if not m["bib"]:
                res["manual_pending"] += 1
                continue
            chip = bib_chip.get(m["bib"], "#" + m["bib"])
            ts = parse_db(m["ts"])
            if chip not in chip_wave and waves:
                w = m.get("wave") or wave_of_ts(ts)
                if w:
                    chip_wave[chip] = w           # участник без заранее заданного забега: по отметке судьи
            marks.append((m["device"], chip, ts, True))
        marks.sort(key=lambda x: x[2])

        def start_of(chip: str) -> Optional[dt.datetime]:
            w = chip_wave.get(chip)
            if w and w in wave_start:
                return wave_start[w]
            if w and waves:
                return None
            return ev_start

        first: dict = {}
        manual_set = set()
        fin_all: dict = {}
        for device, chip, ts, man in marks:
            st = start_of(chip)
            if st is None or ts < st:
                continue
            w = chip_wave.get(chip)
            if w in wave_end and ts > wave_end[w] + dt.timedelta(seconds=2):
                continue                          # забег уже закрыт
            if device == fin_dev:
                if ts < st + min_time:
                    continue
                fin_all.setdefault(chip, []).append(ts)
            per = first.setdefault(chip, {})
            if device not in per:
                per[device] = ts
                if man:
                    manual_set.add((chip, device))

        dev_times: dict = {}
        for chip, per in first.items():
            st = start_of(chip)
            for d, ts in per.items():
                dev_times.setdefault(d, []).append((ts - st).total_seconds())
        order = sorted(dev_times, key=lambda d: (d == fin_dev, sorted(dev_times[d])[len(dev_times[d]) // 2]))
        res["devices"] = order

        def secs(chip, d):
            s = (first[chip][d] - start_of(chip)).total_seconds()
            if (chip, d) in manual_set:
                s = math.ceil(round(s * 10, 6)) / 10.0     # ручной хронометраж: округление вверх до 0,1 с
            return s

        def row(chip):
            per = first.get(chip, {})
            w = chip_wave.get(chip, "")
            meta = wmeta.get(w, {})
            inf = info.get(chip, {})
            return {"bib": self._bib_of(chip, entries), "chip": "" if chip.startswith("#") else chip,
                    "wave": w, "category": inf.get("category") or meta.get("category") or "",
                    "distance": edist.get(chip) or meta.get("distance") or "",
                    "rt": self.result_type(edist.get(chip) or meta.get("distance")), "sex": inf.get("sex") or "",
                    "done_rank": inf.get("done_rank") or "",
                    "name": inf.get("name") or "", "birth_year": inf.get("birth_year") or "",
                    "team": inf.get("team") or "", "coach": inf.get("coach") or "",
                    "points": inf.get("points"), "members": inf.get("members") or "", "rank": inf.get("rank") or "",
                    "sw": (inf.get("detail") or {}).get("t"), "attempts": (inf.get("detail") or {}).get("a"),
                    "splits": {d: self.fmt_elapsed(secs(chip, d)) for d in per},
                    "manual": sorted(d for d in per if (chip, d) in manual_set)}

        def fin_sec(chip):
            return entered[chip][0] if chip in entered else secs(chip, fin_dev)

        finished = [c for c in first if fin_dev in first[c] and c not in entered and c not in status_of] + list(entered)
        finished.sort(key=lambda c: (wave_order.get(chip_wave.get(c, ""), -1), fin_sec(c)))
        place_by_wave: dict = {}
        prev_by_wave: dict = {}
        for chip in finished:
            sec = fin_sec(chip)
            w = chip_wave.get(chip, "")
            if wmeta.get(w, {}).get("distance") is None or wmeta.get(w, {}).get("distance") == "":
                w = w + "\x00" + (edist.get(chip) or "")        # смешанный «общий список»: места отдельно по дисциплинам
            place_by_wave[w] = place_by_wave.get(w, 0) + 1
            r = row(chip)
            if chip in entered:
                txt = entered[chip][1]
                pv = prev_by_wave.get(w)
                place = pv[1] if pv and pv[0] == txt else place_by_wave[w]   # одинаковый результат — одно место
                ra = info.get(chip, {}).get("result_at")
                r.update(place=place, time=self.fmt_elapsed(sec), result=txt, seconds=round(sec, 3),
                         finish_at=None, finish_epoch_ms=None, entered=True,
                         entered_epoch_ms=self._epoch_ms(parse_db(ra)) if ra else None)
                if rtype_of.get(chip, "time") != "time":    # прыжки, метания, многоборья: больше — лучше
                    r.update(time=txt, seconds=None, rtype=rtype_of[chip], value=round(-sec, 2))
            else:
                txt = self.fmt_result(sec)
                pv = prev_by_wave.get(w)
                place = place_by_wave[w]
                r.update(place=place, time=self.fmt_elapsed(sec), result=txt,
                         seconds=round(sec, 3), finish_at=fmt_db(first[chip][fin_dev]),
                         finish_epoch_ms=self._epoch_ms(first[chip][fin_dev]))
            prev_by_wave[w] = (txt, place)
            # выполненный разряд: по нормам ЕВСК; вписанный секретарём — главнее
            if chip in entered:
                val = entered[chip][0] if rtype_of.get(chip, "time") == "time" else -entered[chip][0]
                hand = bool(r.get("sw")) or (ev.get("timing") or "") in ("manual", "judge")
            else:
                val, hand = sec, (chip, fin_dev) in manual_set
            auto_rk = self.rank_for(ev, r["distance"], r["sex"], r["birth_year"], val, hand) if not r.get("members") else ""
            r["done_rank_auto"] = auto_rk
            # «—» — секретарь вручную отметил «разряд не выполнен»: расчёт системы не подставляется
            r["done_rank_src"] = "manual" if r["done_rank"] else ("auto" if auto_rk else "")
            r["done_rank"] = "" if r["done_rank"] == self.NO_RANK else (r["done_rank"] or auto_rk)
            res["finished"].append(r)
        # общий рейтинг: все забеги одной категории и дистанции вместе
        groups: dict = {}
        for r in res["finished"]:
            groups.setdefault((r["category"], r["distance"]), []).append(r)
        for (cat, dist), lst in groups.items():
            lst.sort(key=lambda r: -r["value"] if r.get("rtype") else r["seconds"])
            tie: list = []      # одинаковый результат в разных забегах — делят место
            for i, r in enumerate(lst, 1):
                if tie and r["result"] == tie[0]["result"] and all(t["wave"] != r["wave"] for t in tie):
                    r["place_overall"] = tie[0]["place_overall"]
                    tie.append(r)
                else:
                    r["place_overall"] = i
                    tie = [r]
            res["groups"].append({"category": cat, "distance": dist, "count": len(lst)})
        res["groups"].sort(key=lambda g: (g["distance"], g["category"]))
        res["rank_source"] = self.rank_norms()["data"].get("source", "")
        res["rank_cap"] = self.RANK_CAP.get(ev.get("level") or "region", "1 р.")
        if ev.get("team_best"):
            res["teams"] = self.team_standings(res["finished"], int(ev["team_best"]))
        for chip, per in first.items():
            if fin_dev not in per and chip not in entered and chip not in status_of:
                last_dev = max(per, key=lambda d: per[d])
                r = row(chip)
                r.update(last_point=last_dev, last_time=self.fmt_elapsed(secs(chip, last_dev)))
                res["on_course"].append(r)
        res["on_course"].sort(key=lambda r: r["last_time"], reverse=True)
        res["not_seen"] = [{"bib": r["bib"], "chip": "" if r["chip"].startswith("#") else r["chip"],
                            "wave": r["wave"] or "", "name": r["name"] or "", "birth_year": r["birth_year"] or "",
                            "team": r["team"] or "", "coach": r.get("coach") or "", "members": r.get("members") or "",
                            "rank": r.get("rank") or "", "sw": (r.get("detail") or {}).get("t"), "attempts": (r.get("detail") or {}).get("a"),
                            "category": r["category"] or wmeta.get(r["wave"] or "", {}).get("category") or "",
                            "distance": edist.get(r["chip"]) or wmeta.get(r["wave"] or "", {}).get("distance") or "",
                            "rt": self.result_type(edist.get(r["chip"]) or wmeta.get(r["wave"] or "", {}).get("distance")),
                            "sex": r.get("sex") or "", "done_rank": r.get("done_rank") or "",
                            **({"status": status_of[r["chip"]]} if r["chip"] in status_of else {})}
                           for r in erows if (r["chip"] not in first or r["chip"] in status_of) and r["chip"] not in entered]

        # ---- предупреждения
        A = res["alerts"]
        if not fin_dev and not entered:
            A.append({"level": "warn", "text": "Не выбрана точка финиша — результаты не считаются"})
        if res["manual_pending"]:
            A.append({"level": "warn", "text": f"Отсечек судьи без номера: {res['manual_pending']} — впишите номера"})
        running = ev.get("status") == "running" and starts
        if running:
            silence = float(ev.get("alert_silence_min") or 10)
            now = now_local()
            used = set(dev_times) | {fin_dev}
            for s in self.sources.values():
                if s.cfg["mode"] == "http":
                    continue
                if not any(d == str(s.cfg["device"]) or (s.cfg["device_per_antenna"] and d.startswith(str(s.cfg["device"])))
                           for d in used):
                    continue
                if not s.connected:
                    A.append({"level": "bad", "text": f"Нет связи с точкой {s.cfg['device']}"})
                elif silence > 0 and now - min(starts) > dt.timedelta(minutes=silence):
                    last = s.last_read_at
                    if last is None or now - last > dt.timedelta(minutes=silence):
                        mins = "ни одной отметки" if last is None else f"{int((now - last).total_seconds() // 60)} мин без отметок"
                        A.append({"level": "warn", "text": f"Точка {s.cfg['device']} молчит: {mins}"})
        if entries:
            unknown = sorted(c for c in first if c not in entries and not c.startswith("#"))
            res["unknown"] = unknown
            if unknown:
                A.append({"level": "warn", "text": f"Чипы не из списка участников: {len(unknown)}"
                                                   f" ({', '.join(u[-8:] for u in unknown[:5])}{'…' if len(unknown) > 5 else ''})"})
        dup = []
        for chip, times in fin_all.items():
            clusters = 1
            for a, b in zip(times, times[1:]):
                if (b - a).total_seconds() > 30:
                    clusters += 1
            if clusters > 1:
                dup.append(self._bib_of(chip, entries) or chip[-8:])
        if dup:
            A.append({"level": "info", "text": f"Повторное прохождение финиша (круги или ошибка): {', '.join(dup[:10])}"})
        dup_bib = {}
        for m in self.store.manual_list(eid):
            if m["bib"] and m["device"] == fin_dev:
                dup_bib[(m["bib"], m.get("wave") or "")] = dup_bib.get((m["bib"], m.get("wave") or ""), 0) + 1
        twice = [b for (b, _), n in dup_bib.items() if n > 1]
        if twice:
            A.append({"level": "warn", "text": f"Номер вписан судьёй дважды: {', '.join(sorted(set(twice))[:10])}"})
        seg: dict = {}
        for chip, per in first.items():
            seq = sorted(per.items(), key=lambda x: x[1])
            for (d1, t1), (d2, t2) in zip(seq, seq[1:]):
                seg.setdefault((d1, d2), []).append((chip, (t2 - t1).total_seconds()))
        fast = []
        for (d1, d2), lst in seg.items():
            if len(lst) < 5:
                continue
            med = sorted(x for _, x in lst)[len(lst) // 2]
            if med < 60:
                continue
            for chip, x in lst:
                if x < 0.6 * med:
                    fast.append(f"{self._bib_of(chip, entries) or chip[-8:]} ({d1}→{d2})")
        if fast:
            A.append({"level": "bad", "text": f"Подозрительно быстрый отрезок (срезка?): {', '.join(fast[:10])}"})
        return res
```

## 4. [ВЕСЬ ИЗМЕНЁННЫЙ КОД JAVASCRIPT]

### 4.1 Таблица бланка: бег (3 секундомера) и техника (6 попыток) — `hub/protocol.html`

> ВАЖНО для аудитора: в ТЗ функция `table()` названа находящейся в `ui.html`. Фактически она живёт в `hub/protocol.html` (одна страница печати для админки и публичного сайта). `ui.html` печатных таблиц не строит.

#### `isTech` — `hub/protocol.html` строки 340–340

```js
const isTech=(rtype,slots,att)=>rtype==="distance"||rtype==="height"||(slots||0)>0||att===true;
```

#### `partsOf` — `hub/protocol.html` строки 343–354

```js
function partsOf(h){
  const mk=(o,es,tech)=>Object.assign({},h,o,{entries:es,tech,src:h});
  const mixD=!h.distance&&h.entries.some(e=>e.distance), mixC=!h.category&&h.entries.some(e=>e.category);
  if(!mixD&&!mixC) return [mk({},h.entries,isTech(h.rtype,h.slots,h.attempts))];
  const m=new Map();
  h.entries.forEach(e=>{ const d=mixD?(e.distance||""):h.distance, c=mixC?(e.category||""):(h.category||""), k=d+"|"+c;
    if(!m.has(k)) m.set(k,{d,c,es:[]}); m.get(k).es.push(e); });
  return [...m.values()].map(({d,c,es})=>{
    const t=mixD?(!!d&&isTech(es[0].rtype,es[0].slots)):(isTech(h.rtype,h.slots,h.attempts)||isTech(es[0].rtype,es[0].slots));
    return mk({distance:d,category:c,rtype:mixD?(es[0].rtype||h.rtype):h.rtype,slots:t?(es[0].slots||h.slots||6):0},es,t);
  });
}
```

#### `startSheet` — `hub/protocol.html` строки 356–408

```js
function startSheet(o){
  const ev=(R||SL).event, gf=o.gf||"", sf=o.sf||"", list=!!o.list, coach=!!o.coach;
  const fe=a=>sf?a.filter(e=>sexOf(e)===sf):a;                        // фильтр «Мальчики / Девочки»
  const heatsAll=SL.heats.map(h=>Object.assign({},h,{entries:fe(h.entries)}));
  const looseAll=fe(SL.no_heat||[]);
  const parts=[].concat(...heatsAll.map(partsOf));
  const gm=p=>(!DIST||p.distance===DIST||(p.src&&p.src.distance===DIST))&&(!gf||gkey(p)===gf||gkey(p.src)===gf);
  const lparts=list&&looseAll.length?partsOf({name:"",category:"",distance:"",entries:looseAll,rtype:"time",slots:0}):[];
  const shown=parts.concat(lparts).filter(p=>gm(p)&&p.entries.length);
  const tech=shown.some(p=>p.tech);
  const land=tech||(list&&!!o.landscape);
  const all=heatsAll.concat([{entries:looseAll}]);
  const anyCoach=all.some(h=>h.entries.some(e=>e.coach)), anySeed=all.some(h=>h.entries.some(e=>e.seed));
  const anyLane=all.some(h=>h.entries.some(e=>e.lane)), anyRank=all.some(h=>h.entries.some(e=>e.rank));
  // таблица: бег — три пустые графы «Сек. 1–3»; техника — ровно «Попытка 1–6» и «Лучший результат»
  const table=(entries,rtype,slots,withLane,numbered)=>{
    const grid=isTech(rtype,slots), N=6, rs=grid?2:1, W=(a,b)=>land?a:b;
    const head=`${numbered?`<th rowspan="${rs}" style="width:30px">№ п/п</th>`:""}${withLane?`<th rowspan="${rs}" style="width:42px">Дор.</th>`:""}<th rowspan="${rs}" style="width:50px">Нагр. №</th><th rowspan="${rs}">Фамилия, имя</th><th rowspan="${rs}" style="width:44px">Год рожд.</th>${anyRank?`<th rowspan="${rs}" style="width:50px">Разряд</th>`:""}<th rowspan="${rs}" style="width:${W("17%",coach&&anyCoach?"17%":"24%")}">Команда</th>`
      +(coach&&anyCoach?`<th rowspan="${rs}" style="width:${W("12%","14%")}">Тренер</th>`:"")+(anySeed?`<th rowspan="${rs}" style="width:58px">Заявл. рез.</th>`:"")
      +(grid?`<th colspan="${N}" class="sub" style="text-align:center">Попытки</th><th rowspan="2" style="width:74px">Лучший результат</th>`
            :`<th class="sub swh" style="width:62px">Сек. 1</th><th class="sub swh" style="width:62px">Сек. 2</th><th class="sub swh" style="width:62px">Сек. 3</th>`)
      +(numbered?`<th rowspan="${rs}" style="width:40px">Место</th>`:"");
    const sub=grid?`<tr>${Array.from({length:N},(_,i)=>`<th class="sub">Попытка ${i+1}</th>`).join("")}</tr>`:"";
    const cells=grid?Array.from({length:N},()=>'<td class="cell"></td>').join("")+'<td class="big"></td>':'<td class="cell sw"></td><td class="cell sw"></td><td class="cell sw"></td>';
    return `<table class="${grid?"att":"swt"}"><thead><tr>${head}</tr>${sub}</thead><tbody>
      ${entries.map((e,i)=>`<tr>${numbered?`<td class="c">${i+1}</td>`:""}${withLane?`<td class="c"><b>${e.lane??""}</b></td>`:""}<td class="c">${esc(e.bib)}</td><td>${esc(e.name||"")}${mem(e)}</td><td class="c">${esc(e.birth_year||"")}</td>${anyRank?`<td class="c">${esc(e.rank||"")}</td>`:""}<td>${esc(e.team||"")}</td>${coach&&anyCoach?`<td>${esc(e.coach||"")}</td>`:""}${anySeed?`<td class="r">${esc(e.seed||"")}</td>`:""}${cells}${numbered?"<td></td>":""}</tr>`).join("")}</tbody></table>`;
  };
  let body="";
  if(!list) parts.forEach(p=>{
    if(!gm(p)||!p.entries.length) return;
    body+=`<h2>${esc(p.name)} <small>— ${esc(gtitle(p.distance,p.category))} · ${p.entries.length} уч.</small></h2>`+table(p.entries,p.rtype,p.slots,anyLane&&!p.tech,false);
  });
  else{
    // «Общим списком»: все участники одной сквозной таблицей без забегов и дорожек
    const groups={};
    parts.concat(lparts).forEach(p=>{
      if(!gm(p)) return;
      const k=gkey(p)+"|"+(p.tech?"t":"r"), g=groups[k]||(groups[k]={dist:p.distance,cat:p.category,slots:p.slots||0,rtype:p.rtype||"time",entries:[]});
      p.entries.forEach(e=>g.entries.push(e));
    });
    Object.values(groups).forEach(g=>{
      if(!g.entries.length) return;
      g.entries.sort((a,b)=>(parseInt(a.bib)||0)-(parseInt(b.bib)||0));
      body+=`<h2>${esc(gtitle(g.dist,g.cat))} <small>— общий список${sf?" · "+(sf==="М"?"мальчики / юноши / мужчины":"девочки / девушки / женщины"):""} · ${g.entries.length} уч.</small></h2>`+table(g.entries,g.rtype,g.slots,false,true);
    });
  }
  const empty=!body;
  if(empty) body=PUB?'<div class="empty">Стартовый протокол пока пуст.</div>':'<div class="empty">Сетки пока нет — сформируйте её в «Протоколы → Мастер», шаг 2.</div>';
  const html=headHtml(ev,"СТАРТОВЫЙ ПРОТОКОЛ")+body+
    `<div class="tail"><div class="note">${list?"Участники записаны одним сквозным списком в порядке нагрудных номеров. ":"Забеги сформированы по заявленным результатам. "}${tech?"Графы «Попытка 1–6» и «Лучший результат» — для записи судьями от руки.":"Графы «Сек. 1–3» — для записи судьями показаний трёх ручных секундомеров."}</div>`+signs(ev)+
    `<div class="foot"><span>Сформировано: ${new Date().toLocaleString("ru-RU")}</span><span>${esc(ev.name)}</span></div></div>`;
  return {html,land,tech,empty};
}
```

#### `renderStart` — `hub/protocol.html` строки 490–496

```js
function renderStart(){
  if(!SL){ $("sheet").innerHTML='<div class="empty">Загрузка…</div>'; loadStart(); return; }
  const tabs=tabsFor(true); if(!tabs.some(t=>t.id===TAB)) TAB="";
  drawTabs(tabs);
  const secs=sheetsFor(currentItem(true));
  showSheets(secs);
}
```

Внутри `startSheet` — вложенная функция `table(entries, rtype, slots, withLane, numbered)`; именно она выбирает сетку: `const grid = isTech(rtype, slots), N = 6` — при `grid` рисуются 6 граф «Попытка 1…6» и «Лучший результат», иначе три графы «Сек. 1/2/3». Условие жёсткое: `rtype` `distance`/`height` или `slots>0` или `attempts` всегда ведут к сетке попыток.

### 4.2 Переключение печатных стилей landscape / portrait — `hub/protocol.html`

#### `setPage` — `hub/protocol.html` строки 331–336

```js
function setPage(land){
  let st=$("pgstyle"); if(!st){ st=document.createElement("style"); st.id="pgstyle"; document.head.appendChild(st); }
  const pg=`size:A4 ${land?"landscape":"portrait"};margin:${land?"10mm 12mm 12mm":"12mm 12mm 14mm"}`;
  st.textContent=`@page{${pg}}@media print{@page{${pg}${land?";size:landscape":""}}}`;
  $("sheet").classList.toggle("land",!!land);
}
```

#### `groupList` — `hub/protocol.html` строки 412–421

```js
function groupList(start){
  const out=new Map();
  const add=(x,dist,cat)=>{ if(DIST&&dist!==DIST) return; const k=dist+"|"+cat;
    if(!out.has(k)) out.set(k,{key:k,dist,cat,M:0,F:0,n:0}); const g=out.get(k), s=sexOf(x); g.n++; if(s==="М") g.M++; if(s==="Ж") g.F++; };
  if(start){ if(!SL) return [];
    SL.heats.forEach(h=>partsOf(h).forEach(pt=>pt.entries.forEach(e=>add(e,pt.distance||"",pt.category||""))));
    if($("smode").value==="list") partsOf({name:"",category:"",distance:"",entries:SL.no_heat||[],rtype:"time",slots:0}).forEach(pt=>pt.entries.forEach(e=>add(e,pt.distance||"",pt.category||"")));
  } else if(R) R.finished.concat(R.on_course,R.not_seen).forEach(x=>add(x,x.distance||"",x.category||""));
  return [...out.values()];
}
```

#### `tabsFor` — `hub/protocol.html` строки 422–430

```js
function tabsFor(start){
  const gs=groupList(start), n=gs.reduce((a,g)=>a+g.n,0), M=gs.reduce((a,g)=>a+g.M,0), F=gs.reduce((a,g)=>a+g.F,0);
  const tabs=[{id:"",label:"Все участники",n}];
  if(M) tabs.push({id:"М",label:"Мальчики / Мужчины",n:M});
  if(F) tabs.push({id:"Ж",label:"Девочки / Женщины",n:F});
  const multiD=new Set(gs.map(g=>g.dist)).size>1;
  if(gs.length>1) gs.forEach(g=>tabs.push({id:g.key,label:multiD?gtitle(g.dist,g.cat):(g.cat||"Без категории"),n:g.n}));
  return tabs;
}
```

#### `currentItem` — `hub/protocol.html` строки 432–435

```js
function currentItem(start){
  return {type:start?"start":"final", dist:DIST, gk:TAB.includes("|")?TAB:"", sf:TAB==="М"||TAB==="Ж"?TAB:"",
          mode:start?($("smode").value==="list"?"list":"heats"):($("mode").value==="heats"?"heats":"overall"), orient:$("orient").value};
}
```

#### `sheetsFor` — `hub/protocol.html` строки 437–445

```js
function sheetsFor(it){
  const start=it.type!=="final", coach=$("showCoach").checked;
  let keys=it.gk?[it.gk]:groupList(start).filter(g=>!it.sf||(it.sf==="М"?g.M:g.F)).map(g=>g.key);
  if(!keys.length) keys=[null];
  const out=keys.map(k=>start
    ? startSheet({gf:k??"__none__",sf:it.sf,list:it.mode==="list",coach,landscape:it.orient==="landscape"})
    : (f=>({html:f.html,land:f.land,empty:/class="empty"/.test(f.html)&&!/<table/.test(f.html)}))(buildFinal({gf:k??"__none__",sf:it.sf,mode:it.mode==="heats"?"heats":"overall"})));
  return out.filter(r=>!r.empty).length?out.filter(r=>!r.empty):out.slice(0,1);
}
```

#### `showSheets` — `hub/protocol.html` строки 447–457

```js
function showSheets(secs){
  if(secs.length===1){ setPage(secs[0].land); $("sheet").innerHTML=`<section class="cp ${secs[0].land?"land":"port"}">${secs[0].html}</section>`; fitPages(); return; }
  let st=$("pgstyle"); if(!st){ st=document.createElement("style"); st.id="pgstyle"; document.head.appendChild(st); }
  const first=secs[0].land;
  st.textContent=`@page{size:A4 ${first?"landscape":"portrait"};margin:${first?"10mm 12mm 12mm":"12mm 12mm 14mm"}}`
    +`@page cpl{size:A4 landscape;margin:10mm 12mm 12mm}@page cpp{size:A4 portrait;margin:12mm 12mm 14mm}`
    +`.cp{page-break-after:always;break-after:page}.cp:last-child{page-break-after:auto;break-after:auto}.cp.land{page:cpl}.cp.port{page:cpp}`;
  $("sheet").classList.toggle("land",secs.some(r=>r.land));
  $("sheet").innerHTML=secs.map(r=>`<section class="cp ${r.land?"land":"port"}">${r.html}</section>`).join("");
  fitPages();
}
```

#### `drawTabs` — `hub/protocol.html` строки 470–476

```js
function drawTabs(tabs){
  const box=$("ptabs");
  if(!tabs){ box.innerHTML=""; box.hidden=true; return; }
  box.hidden=false;
  box.innerHTML=`<div class="tl" role="tablist" aria-label="Группы протокола">${tabs.map(t=>`<button type="button" role="tab" aria-selected="${t.id===TAB}" class="${t.id===TAB?"on":""}" data-tab="${esc(t.id)}">${esc(t.label)}<i>${t.n}</i></button>`).join("")}</div>`
    +(PUB?"":`<button type="button" class="cartadd" id="tabCart">🛒 Добавить текущую вкладку в корзину печати</button><span class="cartmsg" id="cartMsg" role="status"></span>`);
}
```

#### `addTabToCart` — `hub/protocol.html` строки 481–489

```js
function addTabToCart(){
  const start=isStartView(), it=currentItem(start), tab=tabsFor(start).find(t=>t.id===TAB)||{label:"Все участники"};
  const label=`${start?"Старт":"Итоги"}: ${DIST||"все дисциплины"} — ${tab.label}${start?(it.mode==="list"?" · общий список":" · по забегам"):""}`;
  let a=LS.get("ss.cart."+eid,[]); a=Array.isArray(a)?a:[];
  const same=a.some(x=>["type","dist","gk","sf","mode","orient"].every(k=>(x[k]||"")===(it[k]||"")));
  if(!same){ a.push(Object.assign({id:Date.now().toString(36)+Math.random().toString(36).slice(2,6),on:true,label},it)); LS.set("ss.cart."+eid,a); }
  const n=sheetsFor(it).length;
  $("cartMsg").textContent=same?"Эта вкладка уже в корзине":`В корзине: «${tab.label}» — ${n} ${n===1?"лист":n<5?"листа":"листов"}`;
}
```

#### `buildFinal` — `hub/protocol.html` строки 525–629

```js
function buildFinal(o={}){
  const ev=R.event, mode=o.mode||$("mode").value, gf=o.gf??"", tf=$("team").hidden?"":$("team").value, sf=o.sf||"";
  const byTeam=x=>(!tf||x.team===tf)&&(!sf||sexOf(x)===sf)&&(!DIST||x.distance===DIST);
  const techX=x=>isTech(x.rt||x.rtype,0,!!(x.attempts&&x.attempts.length));
  const anyDone=R.finished.some(x=>x.done_rank);
  let anyTechShown=false;
  const renum=list=>{ let prev=null,p=0; list.forEach((x,i)=>{ if(!prev||prev.result!==x.result) p=i+1; x._pl=p; prev=x; }); };
  const anyPts=R.finished.some(x=>x.points!=null);
  const fmtPts=v=>v==null?"":String(v).replace(".",",");
  const coachOn=$("showCoach").checked&&R.finished.concat(R.not_seen).some(x=>x.coach);
  const chip=!PUB&&$("showChip").checked, spl=$("showSplits").checked, dnf=$("showDnf").checked;
  const fin=ev.finish_device, splitDevs=(R.devices||[]).filter(d=>d!==fin);
  const anyName=R.finished.concat(R.on_course,R.not_seen).some(x=>x.name), anyYear=R.finished.some(x=>x.birth_year)||R.not_seen.some(x=>x.birth_year);
  const anyTeam=!tf&&(R.finished.some(x=>x.team)||R.not_seen.some(x=>x.team)), hasHeats=ev.waves.length>0;
  const anyRank=R.finished.some(x=>x.rank)||R.not_seen.some(x=>x.rank);
  const anySw=R.finished.some(x=>x.sw&&x.sw.length), anyAtt=R.finished.some(x=>x.attempts&&x.attempts.length);
  const attTxt=x=>(x.attempts||[]).map(v=>v||"–").join(" · "), swTxt=x=>(x.sw||[]).map(v=>v||"–").join(" / ");
  const man=x=>(x.manual||[]).includes(fin);
  const allManual=R.finished.length&&R.finished.every(man), someManual=R.finished.some(man);
  const starts=ev.waves.filter(w=>w.start_time).map(w=>w.start_time.slice(11,16));
  const startTxt=ev.start_clock||(starts.length?starts[0]:(ev.start_time?ev.start_time.slice(11,16):""));

  const head=(placeLbl,withHeat)=>`<thead><tr><th style="width:42px">${placeLbl}</th><th style="width:52px">Нагр. №</th>
    ${anyName?'<th>Фамилия, имя</th>':''}${anyYear?'<th style="width:46px">Год рожд.</th>':''}${anyRank?'<th style="width:46px">Разряд</th>':''}${anyTeam?'<th>Команда</th>':''}${coachOn?'<th>Тренер</th>':''}
    ${withHeat?'<th style="width:70px">Забег</th>':''}${spl?splitDevs.map(d=>`<th style="width:70px">${esc(d)}</th>`).join(""):""}
    ${anySw?'<th>Секундомеры</th>':''}${anyAtt?'<th>Попытки</th>':''}<th style="width:78px">Результат</th>${anyDone?'<th style="width:56px">Вып. разряд</th>':''}${anyPts?'<th style="width:46px">Очки</th>':''}${chip?'<th>Чип</th>':''}<th style="width:46px">Прим.</th></tr></thead>`;
  // техника: на каждое место — все шесть попыток, чтобы был виден ход борьбы
  const techHead=withHeat=>`<thead><tr><th rowspan="2" style="width:42px">Место</th><th rowspan="2" style="width:52px">Нагр. №</th><th rowspan="2">Фамилия, имя</th><th rowspan="2" style="width:46px">Год рожд.</th>${anyRank?'<th rowspan="2" style="width:46px">Разряд</th>':''}${anyTeam?'<th rowspan="2">Команда</th>':''}${coachOn?'<th rowspan="2">Тренер</th>':''}<th colspan="6" class="sub" style="text-align:center">Попытки</th><th rowspan="2" style="width:84px">Лучший результат</th>${anyDone?'<th rowspan="2" style="width:56px">Вып. разряд</th>':''}</tr><tr>${[1,2,3,4,5,6].map(i=>`<th class="sub">Попытка ${i}</th>`).join("")}</tr></thead>`;
  const techTr=(x,place,res)=>`<tr${typeof place==="number"&&place>=1&&place<=3?` class="pl${place}"`:""}><td class="c"><b>${place}</b></td><td class="c">${esc(x.bib)}</td><td>${esc(x.name)}</td><td class="c">${esc(x.birth_year)}</td>${anyRank?`<td class="c">${esc(x.rank||"")}</td>`:''}${anyTeam?`<td>${esc(x.team)}</td>`:''}${coachOn?`<td>${esc(x.coach||"")}</td>`:''}${[0,1,2,3,4,5].map(i=>{const v=(x.attempts||[])[i]||""; return `<td class="c cellv${v&&res&&String(v).replace(",",".")===String(res).replace(",",".")?" bestv":""}">${esc(v)}</td>`;}).join("")}<td class="c"><b>${esc(res)}</b></td>${anyDone?`<td class="c">${esc(x.done_rank||"")}</td>`:''}</tr>`;
  const techOutRows=(list)=>list.map(x=>`<tr><td class="c">—</td><td class="c">${esc(x.bib)}</td><td>${esc(x.name)}</td><td class="c">${esc(x.birth_year)}</td>${anyRank?`<td class="c">${esc(x.rank||"")}</td>`:''}${anyTeam?`<td>${esc(x.team)}</td>`:''}${coachOn?`<td></td>`:''}<td class="c" colspan="6">${esc((x.attempts||[]).map(v=>v||"–").join(" · "))}</td><td class="c"><b>${esc(x.status||((x.attempts||[]).some(Boolean)?"NM":"DNS"))}</b></td>${anyDone?'<td></td>':''}</tr>`).join("");
  const tr=(x,place,withHeat,res,note)=>`<tr${typeof place==="number"&&place>=1&&place<=3?` class="pl${place}"`:""}><td class="c"><b>${place}</b></td><td class="c">${esc(x.bib)}</td>
    ${anyName?`<td>${esc(x.name)}${mem(x)}</td>`:''}${anyYear?`<td class="c">${esc(x.birth_year)}</td>`:''}${anyRank?`<td class="c">${esc(x.rank||"")}</td>`:''}${anyTeam?`<td>${esc(x.team)}</td>`:''}${coachOn?`<td>${esc(x.coach||"")}</td>`:''}
    ${withHeat?`<td class="c">${esc((x.wave||"").replace(/^Забег\s*/,""))}${x.place&&withHeat?` <small>(${x.place})</small>`:""}</td>`:''}
    ${spl?splitDevs.map(d=>`<td class="r">${esc(x.splits?.[d]||"")}</td>`).join(""):""}
    ${anySw?`<td class="c" style="font-size:11px">${esc(swTxt(x))}</td>`:''}${anyAtt?`<td class="c" style="font-size:11px">${esc(attTxt(x))}</td>`:''}<td class="r"><b>${esc(res)}</b></td>${anyDone?`<td class="c">${esc(x.done_rank||"")}</td>`:''}${anyPts?`<td class="c">${esc(fmtPts(x.points))}</td>`:''}${chip?`<td style="font-size:10px">${esc(x.chip)}</td>`:''}<td class="c">${note}</td></tr>`;
  const handNote=x=>man(x)&&!allManual?"р":"";
  // статус от секретаря (DNS/DNF/DQ/NM) важнее догадки по отметкам
  const outCode=x=>x.status||(x.last_point?"DNF":"DNS");
  const dnfRows=(list,withHeat)=>list.map(x=>tr(x,"—",withHeat,outCode(x),"")).join("");

  const teamsHtml=()=>(R.teams||[]).map(g=>{
    const cols=g.columns;
    return `<h2>Командный зачёт · ${esc(g.group)} <small>— сумма очков ${g.best} лучших участников команды в каждой категории</small></h2>
      <table><thead><tr><th style="width:52px">Место</th><th>Команда</th>${cols.map(c=>`<th style="width:90px">${esc(c)}</th>`).join("")}<th style="width:80px">Итого</th></tr></thead><tbody>
      ${g.rows.map(r=>`<tr class="${r.place<=3?"pl"+r.place:""}${tf&&r.team===tf?" mine":""}"><td class="c"><b>${r.place}</b></td><td>${esc(r.team)}</td>${cols.map(c=>`<td class="c">${esc(fmtPts(r.by[c]??""))}</td>`).join("")}<td class="c"><b>${esc(fmtPts(r.total))}</b></td></tr>`).join("")}
      </tbody></table>`;
  }).join("");
  let body="";
  if(mode==="teams"){
    body=teamsHtml();
  } else if(mode==="overall"){
    const groups={};
    R.finished.filter(byTeam).forEach(x=>(groups[gkey(x)]=groups[gkey(x)]||{f:[],d:[]}).f.push(x));
    if(dnf) R.on_course.concat(R.not_seen).filter(byTeam).forEach(x=>(groups[gkey(x)]=groups[gkey(x)]||{f:[],d:[]}).d.push(x));
    Object.keys(groups).sort().filter(k=>!gf||k===gf).forEach(k=>{
      const [d,c]=k.split("|"), g=groups[k]; g.f.sort((a,b)=>a.place_overall-b.place_overall);
      if(sf) renum(g.f);
      const pl=x=>sf?x._pl:x.place_overall;
      const th=g.f.concat(g.d).some(techX);
      if(th) anyTechShown=true;
      body+=`<h2>${esc(gtitle(d,c))} <small>— ${th?"техническая дисциплина, ":""}финишировали ${g.f.length}${g.d.length?`, без результата ${g.d.length}`:""}</small></h2>`
        +(th?`<table class="att tf">${techHead()}<tbody>${g.f.map(x=>techTr(x,pl(x),x.result)).join("")}${techOutRows(g.d)}</tbody></table>`
            :`<table>${head("Место",hasHeats)}<tbody>${g.f.map(x=>tr(x,pl(x),hasHeats,x.result,handNote(x))).join("")}${dnfRows(g.d,hasHeats)}</tbody></table>`);
    });
    if(!gf&&!tf&&!DIST) body+=teamsHtml();
  } else {
    const heats=hasHeats?ev.waves:[{name:"",category:"",distance:""}];
    heats.forEach(w=>{
      const f=R.finished.filter(x=>(x.wave||"")===w.name&&(!gf||gkey(x)===gf)&&byTeam(x)).sort((a,b)=>a.place-b.place);
      const d=dnf?R.on_course.concat(R.not_seen).filter(x=>(x.wave||"")===w.name&&(!gf||gkey(x)===gf)&&byTeam(x)):[];
      if(!f.length&&!d.length) return;
      const st=w.start_time?` · старт ${w.start_time.slice(11,19)}`:"";
      const tf_=f.filter(techX), rf=f.filter(x=>!techX(x)), td_=d.filter(techX), rd_=d.filter(x=>!techX(x));
      if(sf){ renum(tf_); renum(rf); }
      const pl=x=>sf?x._pl:x.place;
      const ttl=`<h2>${esc(w.name||"Общий старт")} <small>— ${esc(gtitle(w.distance,w.category))}${st}</small></h2>`;
      if(rf.length||rd_.length) body+=ttl+`<table>${head("Место",false)}<tbody>${rf.map(x=>tr(x,pl(x),false,x.result,handNote(x))).join("")}${dnfRows(rd_,false)}</tbody></table>`;
      if(tf_.length||td_.length){ anyTechShown=true; body+=(rf.length||rd_.length?"":ttl)+`<table class="att tf">${techHead()}<tbody>${tf_.map(x=>techTr(x,pl(x),x.result)).join("")}${techOutRows(td_)}</tbody></table>`; }
    });
  }
  if(!body) body='<div class="empty">Результатов пока нет</div>';
  const notes=[];
  if(allManual) notes.push("Хронометраж ручной, результаты округлены до 0,1 с в большую сторону.");
  else if(someManual) notes.push("«р» — результат по ручному хронометражу (округлён до 0,1 с в большую сторону).");
  if(tf&&mode!=="teams") notes.push(`Показаны только участники команды «${tf}». Места — общие по категории.`);
  if(mode==="overall"&&hasHeats) notes.push("Места определены по результатам всех забегов в категории; в скобках — место в забеге. Равный результат в разных забегах — одно место.");
  if(mode!=="teams"&&dnf&&(R.on_course.length||R.not_seen.length)){
    const codes=new Set(R.on_course.concat(R.not_seen).map(outCode));
    const more=[["DQ","дисквалифицирован"],["NM","нет результата"]].filter(([k])=>codes.has(k)).map(([k,v])=>`, ${k} — ${v}`).join("");
    notes.push(`DNS — не стартовал, DNF — не финишировал${more}.`);
  }

  if(anyDone&&mode!=="teams") notes.push(`«Вып. разряд» — по нормам ЕВСК${R.rank_source?" ("+R.rank_source.replace(/^Нормы ЕВСК[^—]*—\s*/,"")+")":""}: учтены пол, возраст в год соревнований, хронометраж, высота барьеров и масса снарядов; на соревнованиях этого статуса — не выше «${R.rank_cap||"1 р."}». Сила ветра не учитывается.`);
  if(anyTechShown) notes.push("Лучший результат определён по шести попыткам: X — неудачная попытка, «–» — пропуск.");
  if(sf&&mode!=="teams") notes.push(sf==="М"?"Показаны только мальчики, юноши, мужчины. Места пересчитаны среди показанных.":"Показаны только девочки, девушки, женщины. Места пересчитаны среди показанных.");
  return {land:anyTechShown, html:`
    ${headHtml(ev,mode==="teams"?"КОМАНДНЫЙ ЗАЧЁТ":"ПРОТОКОЛ РЕЗУЛЬТАТОВ",tf&&mode!=="teams"?"Команда: "+esc(tf):"")}
    ${stampHtml()}${body}
    <div class="tail">${notes.length?`<div class="note">${notes.map(esc).join("<br>")}</div>`:""}
    <div class="sign">
      <span>Главный судья</span><span class="u"></span><span class="nm">${esc(ev.chief_judge||"/____________________/")}</span>
      <span>Главный секретарь</span><span class="u"></span><span class="nm">${esc(ev.chief_secretary||"/____________________/")}</span>
    </div>
    <div class="foot"><span>Сформировано: ${new Date().toLocaleString("ru-RU")}</span><span>${esc(ev.name)}</span></div></div>`};
}
```

#### `render` — `hub/protocol.html` строки 514–523

```js
function render(){
  if(kind==="cart") return renderCart();
  syncStartCtl();
  if(!R){ if(PUB&&SL) renderStart(); return; }
  if($("mode").value==="start") return renderStart();
  if($("mode").value==="teams"){ drawTabs(null); const r=buildFinal(); setPage(r.land); $("sheet").innerHTML=r.html; return; }
  const tabs=tabsFor(false); if(!tabs.some(t=>t.id===TAB)) TAB="";
  drawTabs(tabs);
  showSheets(sheetsFor(currentItem(false)));
}
```

#### `renderCart` — `hub/protocol.html` строки 498–508

```js
function renderCart(){
  if(!SL){ $("sheet").innerHTML='<div class="empty">Загрузка…</div>'; loadStart(); return; }
  drawTabs(null);
  let items=LS.get("ss.cart."+eid,[]); items=Array.isArray(items)?items:[];
  if(QIDS.length) items=items.filter(it=>QIDS.includes(String(it.id)));
  const secs=[];
  items.forEach(it=>{ DIST=it.dist||""; if(it.type==="final"&&!R) return; sheetsFor(it).forEach(r=>{ if(!r.empty) secs.push(r); }); });
  DIST="";
  if(!secs.length){ $("sheet").innerHTML='<div class="empty"><b>Корзина печати пуста</b>Откройте «Протоколы → Мастер», выберите вкладку и нажмите «Добавить текущую вкладку в корзину печати».</div>'; return; }
  showSheets(secs);
}
```

#### `syncStartCtl` — `hub/protocol.html` строки 509–512

```js
function syncStartCtl(){
  const isStart=isStartView(); const list=$("smode").value==="list";
  $("smode").classList.toggle("hide",!isStart); $("orient").classList.toggle("hide",!(isStart&&list));
}
```

### 4.3 Корзина печати — `hub/ui.html`

Сборка листов галочками в массив корзины (`cartAdd` → `localStorage["ss.cart.<id события>"]`), список, печать пакета, публикация — `hub/ui.html` строки 2044–2092

```js
/* ---------- корзина печати: листы из мастера и из «Регистрации» → один документ, выгрузка в сеть ---------- */
const sexOfE = (e) => { const x = String(e.sex||"").toUpperCase(); if (x==="М"||x==="Ж") return x; const c = String(e.category||"").toLowerCase();
  if (/юнош|мальч|мужч|^муж/.test(c)) return "М"; if (/девуш|девоч|женщ|^жен/.test(c)) return "Ж"; return ""; };
const cartKey = () => "ss.cart." + curId;
function cartGet(){ try{ const v = JSON.parse(localStorage.getItem(cartKey()) || "[]"); return Array.isArray(v) ? v : []; }catch(e){ return []; } }
function cartSet(a){ try{ localStorage.setItem(cartKey(), JSON.stringify(a)); }catch(e){ toast("Браузер не сохраняет корзину — проверьте настройки приватности"); } renderCart(); }
const cartUid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
function cartAdd(items){
  const a = cartGet(); let n = 0;
  items.forEach(it => { if (a.some(x => ["type","dist","gk","sf","mode","orient"].every(k => (x[k]||"") === (it[k]||"")))) return; a.push(Object.assign({id: cartUid(), on: true}, it)); n++; });
  cartSet(a); return n;
}
function renderCart(){
  const a = cartGet(), on = a.filter(x => x.on).length;
  const html = `<h3>🛒 Корзина печати <span class="small muted">${a.length ? "— листов: " + a.length + ", к печати: " + on : ""}</span></h3>
    ${a.map(it => `<div class="ci"><label><input type="checkbox" data-cs="${esc(it.id)}" ${it.on ? "checked" : ""}> <span>${esc(it.label)}</span></label><button data-rm="${esc(it.id)}" aria-label="Убрать из корзины: ${esc(it.label)}">✕ Убрать</button></div>`).join("")
      || '<p class="small muted" style="margin:0">Корзина пуста. Над протоколом выберите вкладку (все, мальчики, девочки или категорию) и нажмите «🛒 Добавить текущую вкладку в корзину печати».</p>'}
    <div class="row"><button class="bigprint" data-cart="print" ${on ? "" : "disabled"}>🖨️ Печать пакета</button><button data-cart="publish" ${on ? "" : "disabled"}>🌐 Выгрузить в общую сеть</button><button data-cart="clear" ${a.length ? "" : "disabled"}>Очистить корзину</button></div>`;
  document.querySelectorAll(".cartmount").forEach(m => { m.innerHTML = html; });
}
document.addEventListener("click", async (e) => {
  const rm = e.target.closest("[data-rm]"); if (rm) { cartSet(cartGet().filter(x => x.id !== rm.dataset.rm)); return; }
  const b = e.target.closest("[data-cart]"); if (!b) return;
  if (b.dataset.cart === "clear") { if (confirm("Очистить корзину печати?")) cartSet([]); return; }
  if (curId == null) return;
  const sel = cartGet().filter(x => x.on);
  if (b.dataset.cart === "print") {
    if (!sel.length) return toast("Отметьте галочками листы для печати");
    window.open(`/protocol?event=${curId}&kind=cart&ids=${sel.map(x => x.id).join(",")}`, "_blank"); return;
  }
  if (b.dataset.cart === "publish") {
    if (!sel.length) return toast("Отметьте галочками листы для выгрузки");
    const start = sel.some(x => x.type === "start"), res = sel.some(x => x.type === "final");
    const what = [start && "стартовый протокол", res && "итоговый протокол"].filter(Boolean).join(" и ");
    if (!confirm(`Выгрузить в общую сеть: ${what}?\n\nНа публичной странице SakhStart станет виден протокол соревнования целиком. Убрать его оттуда можно в любой момент.`)) return;
    try{
      const r = await api(`/api/events/${curId}/publish`, Object.assign({}, start ? {start: true} : {}, res ? {results: true} : {}));
      toast("Выгружено в общую сеть"); alert("Протоколы доступны зрителям и участникам:\n" + (res ? r.results_url : r.start_url));
      loadEvents._sig = null; loadEvents();
    }catch(err){ toast("Ошибка: " + err.message); }
  }
});
document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-cs]"); if (!c) return;
  const a = cartGet(); const it = a.find(x => x.id === c.dataset.cs); if (it) { it.on = c.checked; cartSet(a); }
});
// лист, добавленный в корзину во вкладке протокола (встроенный предпросмотр), сразу виден здесь
window.addEventListener("storage", (e) => { if (curId != null && e.key === cartKey()) renderCart(); });
```

### 4.4 Мастер протоколов: переключение шагов, ветки Бег/Техника, ввод результатов — `hub/ui.html`

#### `wzp` (IIFE: состояние `W`, `go(n)`, `render()`, `step1…step5`, `gen`, `reset`, `saveRows`, обработчики) — `hub/ui.html` строки 2094–2343

```js
const wzp = (() => {
  const W = {disc: "", step: 1, ages: [], sex: "", lanes: 8, regs: [], sl: null, ev: null};
  const AGE_LIM = {u12:[0,12], u14:[0,14], u16:[0,16], u18:[0,18], u20:[0,20], u23:[0,23], sen:[19,200]};
  const STEP_T = {
    run:   ["Фильтр", "Состав по категориям", "Забеги и стартовый протокол", "Ввод на финише", "Итоговый протокол"],
    tech:  ["Фильтр", "Состав по категориям", "Общий список и стартовый протокол", "Ввод с сектора", "Итоговый протокол"]};
  // автоопределение: попытки или расстояние/высота — техника; время — бег; прочее (очки) ведём по беговой ветке
  const kindOf = (name) => { const d = discBy(name); if (!d) return "run"; if (d.attempts || d.result === "distance" || d.result === "height") return "tech"; return "run"; };
  const isPoints = (name) => { const d = discBy(name); return !!d && d.result === "points"; };
  const ev = () => curEvent();
  const kind = () => kindOf(W.disc);
  const sexWord = (x) => x === "М" ? "мальчики / юноши / мужчины" : x === "Ж" ? "девочки / девушки / женщины" : "все";
  const ageOk = (r) => { if (!W.ages.length) return true; const e = ev(), y = e && e.date ? +e.date.slice(0, 4) : new Date().getFullYear(); const age = y - (+r.birth_year || 0);
    return W.ages.some(a => AGE_LIM[a] && age >= AGE_LIM[a][0] && age <= AGE_LIM[a][1]); };
  const regsIn = () => W.regs.filter(r => r.distance === W.disc && r.status === "approved" && (!W.sex || String(r.sex||"").toUpperCase() === W.sex) && ageOk(r));
  const entriesIn = () => {            // участники дисциплины из стартового списка с учётом фильтров
    const out = []; if (!W.sl) return out;
    W.sl.heats.concat([{name: "", distance: "", entries: W.sl.no_heat || []}]).forEach(h => h.entries.forEach(e => {
      if ((e.distance || h.distance) !== W.disc) return;
      if (W.sex && sexOfE(e) !== W.sex) return;
      if (!ageOk({birth_year: e.birth_year})) return;
      out.push(Object.assign({}, e, {_heat: h.name})); }));
    return out;
  };
  const myHeats = () => W.sl ? W.sl.heats.filter(h => h.distance === W.disc || h.entries.some(e => e.distance === W.disc)) : [];
  async function load(){
    const e0 = ev(); if (!e0) return;
    // судье на секторе заявки (личные данные) не нужны и не выдаются — работает по стартовому списку
    try{ const [r, sl, rs] = await Promise.all([api(`/api/events/${e0.id}/regs`), api(`/api/events/${e0.id}/startlist`), api(`/api/events/${e0.id}/results`).catch(() => null)]);
      W.regs = r.regs; W.sl = sl; W.auto = {}; if (rs) rs.finished.forEach(x => { W.auto[x.bib] = x.done_rank_auto || ""; }); }catch(err){ console.warn(err); }
  }
  async function open(){
    const e0 = ev(); if (!e0) { $("wzpBody").innerHTML = '<p class="muted">Выберите соревнование в меню вверху.</p>'; return; }
    $("wzpEv").textContent = [e0.name, e0.date ? e0.date.split("-").reverse().join(".") : "", e0.place].filter(Boolean).join(" · ");
    await loadDisc();
    if (W.evId !== e0.id) { W.evId = e0.id; W.disc = ""; W.step = 1; W.ages = []; W.sex = ""; try{ const sv = JSON.parse(localStorage.getItem("ss.wzp." + e0.id) || "{}"); Object.assign(W, {disc: sv.disc || "", step: sv.step || 1, sex: sv.sex === "М" || sv.sex === "Ж" ? sv.sex : "", ages: Array.isArray(sv.ages) ? sv.ages : []}); }catch(x){} }
    await load();
    const names = [...new Set([...distNames(e0), ...W.regs.map(r => r.distance), ...W.sl.heats.map(h => h.distance)].filter(Boolean))];
    $("wzpDisc").innerHTML = names.map(n => `<option ${n === W.disc ? "selected" : ""}>${esc(n)}</option>`).join("") || '<option value="">нет дисциплин</option>';
    if (!names.includes(W.disc)) W.disc = names[0] || "";
    $("wzpDisc").value = W.disc; render();
  }
  function save(){ try{ localStorage.setItem("ss.wzp." + W.evId, JSON.stringify({disc: W.disc, step: W.step, sex: W.sex, ages: W.ages})); }catch(x){} }
  function go(n){ W.step = Math.max(1, Math.min(5, n)); save(); render(); }
  function render(){
    const k = kind(), t = STEP_T[k];
    $("wzpKind").className = "wzp-kind " + k;
    $("wzpKind").textContent = !W.disc ? "" : k === "tech" ? "Техника · попытки · общий список" : "Бег · забеги и дорожки" + (isPoints(W.disc) ? " (очки)" : "");
    $("wzpSteps").innerHTML = t.map((x, i) => `<button type="button" data-s="${i + 1}" class="${W.step === i + 1 ? "on" : W.step > i + 1 ? "done" : ""}" role="tab"><b>${i + 1}</b>${esc(x)}</button>`).join("");
    const body = $("wzpBody");
    if (!W.disc) { body.innerHTML = '<p class="muted">В этом соревновании пока нет дисциплин. Добавьте их на этапе «Подготовка» и примите заявки.</p>'; return; }
    ({1: step1, 2: step2, 3: step3, 4: step4, 5: step5})[W.step](body, k);
  }
  const nav = (prev, nextTxt) => `<div class="wzp-nav">${prev ? '<button type="button" data-g="-1">← Назад</button>' : ""}${nextTxt ? `<button type="button" class="primary" data-g="1">${nextTxt} →</button>` : ""}</div>`;
  function step1(body, k){
    const cnt = (x) => W.regs.filter(r => r.distance === W.disc && r.status === "approved" && (!x || String(r.sex||"").toUpperCase() === x) && ageOk(r)).length;
    const pend = W.regs.filter(r => r.distance === W.disc && r.status === "pending").length;
    const ages = (DISC.ages || []);
    body.innerHTML = `<h2>Шаг 1. Кого включаем</h2>
      <p class="small muted" style="margin:0">Выберите возрастные группы и пол. Остальные участники этой дисциплины не пропадают: можно по очереди сформировать мальчиков и девочек.</p>
      <fieldset class="pmode"><legend>Возрастная группа</legend><div class="wzp-opts">${ages.map(a => `<label><input type="checkbox" data-age="${esc(a.id)}" ${W.ages.includes(a.id) ? "checked" : ""}> ${esc(a.name)}</label>`).join("")}</div><span class="small muted">Ничего не отмечено — все возрасты.</span></fieldset>
      <fieldset class="pmode"><legend>Пол</legend><div class="wzp-opts">${[["", "Все"], ["М", "Мальчики / юноши / мужчины"], ["Ж", "Девочки / девушки / женщины"]].map(([v, t]) => `<label><input type="radio" name="wzpSex" value="${v}" ${W.sex === v ? "checked" : ""}> ${t}</label>`).join("")}</div></fieldset>
      <p><b>Подходит участников: ${cnt("")}</b> <span class="small muted">· мальчиков ${cnt("М")} · девочек ${cnt("Ж")}${pend ? ` · ещё ${pend} заявок ждут проверки во вкладке «Регистрация»` : ""}</span></p>
      ${nav(false, "К сетке")}`;
  }
  function heatsTable(){
    const hs = myHeats();
    if (!hs.length) return '<p class="muted">Сетки по этой дисциплине пока нет.</p>';
    return `<div class="tbl"><table><thead><tr><th>Забег</th><th>Категория</th><th>Участников</th><th>Мальчиков</th><th>Девочек</th></tr></thead><tbody>${hs.map(h => {
      const es = h.entries.filter(e => (e.distance || h.distance) === W.disc);
      return `<tr><td><b>${esc(h.name)}</b></td><td>${esc(h.category || "")}</td><td>${es.length}</td><td>${es.filter(e => sexOfE(e) === "М").length}</td><td>${es.filter(e => sexOfE(e) === "Ж").length}</td></tr>`; }).join("")}</tbody></table></div>`;
  }
  // шаг 2: проверка состава — как секретарь перед жеребьёвкой: кто в какой категории, сколько листов получится
  function step2(body, k){
    const tech = k === "tech", rs = regsIn(), pend = W.regs.filter(r => r.distance === W.disc && r.status === "pending").length;
    const cats = new Map(); rs.forEach(r => { const c = r.category || ""; if (!cats.has(c)) cats.set(c, {M: 0, F: 0, n: 0, inGrid: 0}); const g = cats.get(c);
      g.n++; if (String(r.sex || "").toUpperCase() === "М") g.M++; else g.F++; if (r.entry_wave) g.inGrid++; });
    const noCat = cats.has("") ? cats.get("").n : 0;
    const rows = [...cats.entries()].map(([c, g]) => `<tr><td><b>${esc(c || "без категории")}</b></td><td>${g.M}</td><td>${g.F}</td><td><b>${g.n}</b></td>
      <td>${tech ? "1 лист" : Math.ceil(g.n / (W.lanes || 8)) + " " + (Math.ceil(g.n / (W.lanes || 8)) === 1 ? "забег" : "забега")}</td><td>${g.inGrid ? g.inGrid + " уже в сетке" : "—"}</td></tr>`).join("");
    body.innerHTML = `<h2>Шаг 2. Состав по категориям</h2>
      <p class="small muted" style="margin:0">${esc(W.disc)} · возраст: ${W.ages.length ? W.ages.map(a => (DISC.ages.find(x => x.id === a) || {}).name).join(", ") : "любой"} · пол: ${esc(sexWord(W.sex))}.
        Каждая категория получает свой ${tech ? "общий список и свой судейский лист" : "забег (забеги) и свой лист"}: своя нумерация, свои места, разные категории не смешиваются.</p>
      <div class="tbl"><table><thead><tr><th>Категория</th><th>Мальчиков</th><th>Девочек</th><th>Всего</th><th>${tech ? "Список" : "Забегов при " + (W.lanes || 8) + " дор."}</th><th>Сетка</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="6" class="empty">Подтверждённых заявок по этим условиям нет.</td></tr>`}</tbody></table></div>
      ${pend ? `<div class="wzp-lock">⏳ Ещё ${pend} заявок ждут проверки во вкладке «Регистрация» — в сетку они не попадут, пока их не подтвердить.</div>` : ""}
      ${noCat ? `<div class="wzp-lock">⚠️ У ${noCat} участников не определена категория — проверьте правила категорий и год рождения в «Регистрации».</div>` : ""}
      ${nav(true, tech ? "К общему списку" : "К забегам")}`;
  }
  // шаг 3: сетка и стартовый протокол на одном экране — ровно две кнопки управления сеткой, ниже бланк с вкладками групп
  function step3(body, k){
    const tech = k === "tech", n = regsIn().length, q = `kind=start&smode=${tech ? "list" : "heats"}&orient=${tech ? "landscape" : "portrait"}`;
    body.innerHTML = `<h2>Шаг 3. ${tech ? "Общий список и стартовый протокол" : "Забеги и стартовый протокол"}</h2>
      ${tech ? '<div class="wzp-lock">🔒 Техника: дорожки заблокированы. Каждая категория — отдельный сквозной «Общий список» в порядке выполнения попыток; лист альбомный, 6 попыток и «Лучший результат».</div>'
        : `<p class="small muted" style="margin:0">Бег: посев по заявленному результату — сильнейшие в последнем забеге, на центральных дорожках. Лист книжный, графы «Сек. 1 | Сек. 2 | Сек. 3».</p>
           <label class="small">Дорожек на стадионе <input type="number" id="wzpLanes" min="1" max="50" value="${W.lanes}" style="width:80px"></label>`}
      <div class="row wzp-ctl"><button class="primary" type="button" id="wzpGen" ${n ? "" : "disabled"}>${tech ? "⚡ Сформировать общий список" : "⚡ Сформировать забеги"}</button>
        <button class="danger" type="button" id="wzpReset" ${myHeats().length ? "" : "disabled"}>❌ Сбросить сетку / Удалить забеги</button>
        <span class="small muted">${n} участников по фильтру шага 1</span></div>
      ${myHeats().length ? `<p class="small muted" style="margin:0">Над бланком — вкладки: «Все участники», «Мальчики», «Девочки» и каждая категория. Нужную вкладку можно сразу положить в корзину печати.</p>
        <iframe class="wzp-frame" src="${protoUrl(q, true)}" title="Предпросмотр стартового протокола"></iframe>
        <div class="row"><a class="btn" target="_blank" href="${protoUrl(q, false)}">Открыть для печати ↗</a></div>`
        : '<div class="card empty">Сетки по этой дисциплине пока нет — нажмите «⚡ Сформировать…».</div>'}
      ${nav(true, "К вводу результатов")}`;
  }
  async function gen(){
    const e0 = ev(), tech = kind() === "tech";
    if (tech === false) W.lanes = +($("wzpLanes") || {}).value || W.lanes;
    if (myHeats().length && !confirm("По этой дисциплине сетка уже есть. Пересобрать её для участников по фильтру шага 1? Номера сохранятся, другие дисциплины и участники вне фильтра не затрагиваются.")) return;
    try{
      const r = await api(`/api/events/${e0.id}/heats`, {distance: W.disc, ages: W.ages, sex: W.sex, lanes: W.lanes});
      toast(tech ? `Общий список сформирован, участников: ${r.entries}` : `Сформировано забегов: ${r.heats.length}, участников: ${r.entries}`);
      loadEvents._sig = null; await loadEvents(); regLoaded = null; await load(); render();
    }catch(err){ toast("Ошибка: " + err.message); }
  }
  async function reset(){
    const e0 = ev();
    if (!confirm(`Сбросить сетку дисциплины «${W.disc}» и удалить все её забеги и списки? Номера участников сохранятся. Это действие нельзя отменить.`)) return;
    try{ const r = await api(`/api/events/${e0.id}/resetheats`, {distance: W.disc}); toast(`Сетка сброшена: забегов ${r.waves}, участников ${r.entries}`); loadEvents._sig = null; await loadEvents(); regLoaded = null; await load(); render(); }
    catch(err){ toast("Ошибка: " + err.message); }
  }
  const protoUrl = (q, embed) => `/protocol?event=${ev().id}&dist=${encodeURIComponent(W.disc)}&sexf=${W.sex}&grp=${embed ? "&embed=1" : ""}&t=${Date.now()}&${q}`;
  const label = (pre) => `${pre}: ${W.disc}${W.sex ? " — " + (W.sex === "М" ? "мальчики" : "девочки") : ""}`;
  function step5(body, k){
    const tech = k === "tech", q = `kind=results&mode=overall`;
    body.innerHTML = `<h2>Шаг 5. Итоговый протокол</h2>
      <p class="small muted" style="margin:0">${tech ? "Горизонтальный лист: на каждое место видны все шесть попыток спортсмена и лучший результат." : "Вертикальный лист: места, результаты и выполненные разряды."}</p>
      <label class="small">Статус соревнований — от него зависит, какой разряд можно выполнить
        <select id="wzpLevel" style="max-width:420px">${[["mass","Муниципальные, массовые — до II разряда"],["region","Субъекта РФ (областные) — до I разряда"],["interregion","Межрегиональные — до КМС"],["dfo","Федерального округа — до МС"],["russia","Всероссийские — до МС"]].map(([v, t]) => `<option value="${v}" ${(ev().level || "region") === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <fieldset class="pmode wzp-pub"><legend>Публикация в общей сети SakhStart</legend>
        <label><input type="checkbox" id="wzpPubS" ${ev().pub_start ? "checked" : ""}> <b>Стартовый протокол на сайте</b><span class="small muted"> — зрители и участники видят составы и забеги</span></label>
        <label><input type="checkbox" id="wzpPubR" ${ev().pub_results ? "checked" : ""}> <b>Итоговый протокол на сайте</b><span class="small muted"> — места, результаты и разряды</span></label>
        <span class="small muted">${ev().page_url ? `Страница соревнования: <a id="wzpPubLink" target="_blank" href="${esc(ev().page_url)}">${esc(ev().page_url)}</a>` : "Ссылка появится после первой публикации."}</span>
      </fieldset>
      <iframe class="wzp-frame" src="${protoUrl(q, true)}" title="Предпросмотр итогового протокола"></iframe>
      <div class="row"><a class="btn" target="_blank" href="${protoUrl(q, false)}">Открыть для печати ↗</a></div>${nav(true, "")}`;
  }
  // «Вып. разряд»: пусто — считает система по нормам ЕВСК (видно в подписи); «—» — вручную «не выполнен»; иначе — разряд секретаря
  const DONE_RANKS = ["МСМК", "МС", "КМС", "1 р.", "2 р.", "3 р.", "1 юн.", "2 юн.", "3 юн."];
  const drSel = (r) => { const cur = r.done_rank || "", auto = (W.auto || {})[r.bib] || "";
    const opts = [["", auto ? `Авто: ${auto}` : "Авто: нет"], ["—", "Не выполнен"], ...[...new Set([...DONE_RANKS, ...(cur && cur !== "—" ? [cur] : [])])].map(x => [x, x])];
    return `<select class="dr${cur ? " man" : ""}" aria-label="Выполненный разряд ${esc(r.bib)}" title="Авто — по нормам ЕВСК с учётом пола, возраста, хронометража и статуса соревнований. Выберите разряд, чтобы задать его вручную — он главнее расчёта.">${opts.map(([v, t]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`; };
  /* шаг 4: экранная сетка ввода */
  function step4(body, k){
    const tech = k === "tech", es = entriesIn(), pts = isPoints(W.disc);
    const head = tech ? ["№", "Участник", "Разряд", ...[1,2,3,4,5,6].map(i => "Попытка " + i), "Лучший", "Вып. разряд", "Отметка"]
      : pts ? ["№", "Участник", "Разряд", "Очки", "Вып. разряд", "Отметка"]
      : ["Дор.", "№", "Участник", "Разряд", "Сек. 1", "Сек. 2", "Сек. 3", "Официальный", "Вып. разряд", "Отметка"];
    const row = (r) => { const d = r.detail || {};
      const inp = (c, i, v, ph) => `<td><input class="${c}" data-i="${i}" value="${esc(v || "")}" placeholder="${ph || "—"}" inputmode="decimal" aria-label="${esc(c === "sw" ? "Секундомер " + (i + 1) : "Попытка " + (i + 1))}, ${esc(r.bib)}"></td>`;
      const main = tech ? [0,1,2,3,4,5].map(i => inp("att", i, (d.a || [])[i])).join("") : pts ? `<td><input class="one" value="${esc(r.result || "")}" inputmode="numeric" aria-label="Очки ${esc(r.bib)}"></td>` : [0,1,2].map(i => inp("sw", i, (d.t || [])[i])).join("");
      return `<tr data-bib="${esc(r.bib)}">${tech || pts ? "" : `<td>${r.lane ?? ""}</td>`}<td class="bib">${esc(r.bib)}</td><td><b>${esc(r.name || "")}</b><div class="small muted">${esc(r.birth_year || "")}${r.team ? " · " + esc(r.team) : ""}</div></td><td class="small">${esc(r.rank || "")}</td>${main}
        ${pts ? "" : `<td class="out" data-out>${esc(r.result || "")}</td>`}<td>${drSel(r)}</td>
        <td><select class="stsel" aria-label="Отметка ${esc(r.bib)}"><option value="">—</option>${Object.entries(STATUS_NAMES).map(([c, t]) => `<option value="${c}" ${r.status === c ? "selected" : ""}>${t}</option>`).join("")}</select></td></tr>`; };
    const sorted = es.slice().sort((a, b) => String(a.category || "").localeCompare(String(b.category || ""), "ru") || String(a._heat).localeCompare(String(b._heat), "ru", {numeric: true})
      || (a.lane ?? 99) - (b.lane ?? 99) || (parseInt(a.bib) || 0) - (parseInt(b.bib) || 0));
    let lastCat = null;
    const rowsHtml = sorted.map(r => { const c = r.category || "без категории", hd = c !== lastCat ? `<tr class="wzp-cat"><td colspan="${head.length}">${esc(c)}</td></tr>` : ""; lastCat = c; return hd + row(r); }).join("");
    body.innerHTML = `<h2>Шаг 4. ${tech ? "Ввод с сектора" : "Ввод на финише"}</h2>
      <p class="small muted" style="margin:0">${tech ? "Запишите шесть попыток: расстояние в метрах (7.85 или 7,85), X — заступ, «-» — пропуск. Сервер сам найдёт лучшую попытку, проверит её по правилам и выставит итог." : pts ? "Введите сумму очков — целое число." : "Впишите три времени с ручных секундомеров (12.84 или 1:05.3). Сервер сам вычислит официальный результат: среднее из трёх, из двух — худшее, округление вверх до 0,1 с."}
        «Вып. разряд»: «Авто» — разряд по нормам ЕВСК (обновляется после сохранения); выберите разряд или «Не выполнен», чтобы задать его вручную — ручное значение главнее расчёта.</p>
            <div class="tbl"><table class="wzp-grid"><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody id="wzpRows">${rowsHtml || `<tr><td colspan="${head.length}" class="empty">Нет участников: сформируйте сетку на шаге 2.</td></tr>`}</tbody></table></div>
      <div class="row wzp-ctl"><button class="primary" type="button" id="wzpSave">Сохранить результаты</button>
        <span class="wzp-sync" id="wzpSync" role="status" aria-live="polite">Каждая строка сохраняется сама, как только вы переходите к следующему полю.</span>
        ${!sorted.length ? "" : '<button class="danger" type="button" id="wzpClear">❌ Удалить все результаты / Очистить протокол</button>'}</div>${nav(true, "К итоговому протоколу")}`;
  }
  const rowData = (tr) => {
    const row = {bib: tr.dataset.bib, status: tr.querySelector("select.stsel").value, auto: true, done_rank: tr.querySelector("select.dr").value};
    const sw = [...tr.querySelectorAll("input.sw")], at = [...tr.querySelectorAll("input.att")], one = tr.querySelector("input.one");
    if (sw.length) row.t = sw.map(i => i.value.trim()); if (at.length) row.a = at.map(i => i.value.trim()); if (one) row.result = one.value.trim();
    return row; };
  const sync = (t, cls) => { const s = $("wzpSync"); if (s) { s.textContent = t; s.className = "wzp-sync " + (cls || ""); } };
  let autoT = null, saving = false;
  // мгновенная отправка: строка уходит на сервер, как только судья переходит к следующему полю — табло и протокол видят её сразу
  function queueAuto(ms){ clearTimeout(autoT); autoT = setTimeout(() => saveRows(true), ms ?? 500); }
  async function saveRows(auto){
    if (saving) { if (auto) queueAuto(800); return; }
    const trs = [...document.querySelectorAll("#wzpRows tr.dirty")];
    if (!trs.length) { if (!auto) toast("Нет изменений"); return; }
    const rows = trs.map(rowData);
    saving = true; sync("Сохраняю…", "busy");
    try{
      const r = await api(`/api/events/${curId}/results`, {rows});
      const bad = new Set(r.errors.map(x => x.split(":")[0]));
      trs.forEach(tr => { if (!bad.has(tr.dataset.bib)) { if (rowData(tr) && JSON.stringify(rowData(tr)) === JSON.stringify(rows.find(x => x.bib === tr.dataset.bib))) tr.classList.remove("dirty"); }
        else tr.querySelectorAll("input").forEach(i => i.classList.add("err")); });
      if (r.errors.length) { sync("Не сохранено: " + r.errors.join("; "), "bad"); if (!auto) alert("Не сохранены:\n" + r.errors.join("\n")); }
      else sync(`Сохранено в ${new Date().toLocaleTimeString("ru-RU")} — результаты уже на сервере и на табло`, "ok");
      if (!auto) toast(`Сохранено: ${r.saved}`);
      await load();
      if (!auto && !bad.size) render(); else refreshRows();
      loadResults(); loadEvents._sig = null; loadEvents();
    }catch(err){ sync("Нет связи с сервером — изменения не потеряны, повторю через 5 секунд", "bad"); if (!auto) toast("Ошибка: " + err.message); queueAuto(5000); }
    finally{ saving = false; }
  }
  // после автосохранения обновляем только расчётные клетки (официальный результат, «Авто» разряда) — фокус и ввод не сбиваются
  function refreshRows(){
    const by = {}; entriesIn().forEach(e => { by[e.bib] = e; });
    document.querySelectorAll("#wzpRows tr[data-bib]").forEach(tr => {
      const e = by[tr.dataset.bib]; if (!e || tr.classList.contains("dirty") || tr.contains(document.activeElement)) return;
      const out = tr.querySelector("[data-out]"); if (out) out.textContent = e.result || "";
      const dr = tr.querySelector("select.dr"); if (dr && dr.options[0]) { const a = (W.auto || {})[e.bib] || ""; dr.options[0].textContent = a ? `Авто: ${a}` : "Авто: нет"; }
    });
  }
  async function clearAll(){
    const bibs = [...document.querySelectorAll("#wzpRows tr[data-bib]")].map(tr => tr.dataset.bib);
    if (!bibs.length) return;
    const lbl = `${W.disc}${W.sex ? " — " + (W.sex === "М" ? "мальчики" : "девочки") : ""}`;
    if (!confirm(`Удалить все результаты дисциплины «${lbl}» (${bibs.length} участников)?\n\nСотрутся секундомеры, попытки, отметки DNS/DNF и ручные разряды. Участники и сетка останутся. Это действие нельзя отменить.`)) return;
    try{ const r = await api(`/api/events/${curId}/clearresults`, {bibs, label: lbl}); toast(`Протокол очищен: ${r.cleared}`); await load(); render(); loadResults(); }
    catch(err){ toast("Ошибка: " + err.message); }
  }
  async function setPub(kind2, on){
    try{ const r = await api(`/api/events/${ev().id}/publish`, {[kind2]: on});
      toast(on ? "Выгружено в общую сеть SakhStart" : "Снято с публичного сайта"); loadEvents._sig = null; await loadEvents(); render();
      if (on) { const u2 = kind2 === "start" ? r.start_url : r.results_url; const a = $("wzpPubLink"); if (a) { a.href = u2; a.textContent = u2; } } }
    catch(err){ toast("Ошибка: " + err.message); render(); }
  }
  const root = $("tab-wizard");
  root.addEventListener("click", (e) => {
    const s = e.target.closest("[data-s]"); if (s) return go(+s.dataset.s);
    const g = e.target.closest("[data-g]"); if (g) return go(W.step + +g.dataset.g);
    if (e.target.id === "wzpGen") return gen();
    if (e.target.id === "wzpReset") return reset();
    if (e.target.id === "wzpSave") { clearTimeout(autoT); return saveRows(false); }
    if (e.target.id === "wzpClear") return clearAll();
  });
  root.addEventListener("change", (e) => {
    if (e.target.dataset.age) { const a = e.target.dataset.age; W.ages = e.target.checked ? [...new Set([...W.ages, a])] : W.ages.filter(x => x !== a); save(); return render(); }
    if (e.target.name === "wzpSex") { W.sex = e.target.value; save(); return render(); }
    if (e.target.id === "wzpLanes") W.lanes = +e.target.value || 8;
    if (e.target.id === "wzpLevel") { api(`/api/events/${ev().id}`, {level: e.target.value}).then(async () => { toast("Статус соревнований сохранён — разряды пересчитаны"); loadEvents._sig = null; await loadEvents(); render(); }).catch(err => toast("Ошибка: " + err.message)); return; }
    if (e.target.id === "wzpPubS") return setPub("start", e.target.checked);
    if (e.target.id === "wzpPubR") return setPub("results", e.target.checked);
    const tr = e.target.closest("#wzpRows tr"); if (tr) { tr.classList.add("dirty"); queueAuto(); }
  });
  root.addEventListener("input", (e) => {
    const tr = e.target.closest("#wzpRows tr"); if (!tr) return; tr.classList.add("dirty"); e.target.classList.remove("err");
    const out = tr.querySelector("[data-out]"); if (!out) return;
    const sw = [...tr.querySelectorAll("input.sw")], at = [...tr.querySelectorAll("input.att")];
    out.textContent = sw.length ? swMain(sw.map(i => i.value)) : at.length ? attBest(at.map(i => i.value)) : out.textContent;
  });
  root.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !e.target.matches("#wzpRows input")) return; e.preventDefault();
    const all = [...document.querySelectorAll("#wzpRows input")], i = all.indexOf(e.target);
    if (all[i + 1]) { all[i + 1].focus(); all[i + 1].select(); } else $("wzpSave").click();
  });
  $("wzpDisc").onchange = (e) => { W.disc = e.target.value; W.step = 1; W.ages = []; W.sex = ""; save(); render(); };
  return {open};
})();
```

### 4.5 Расчёт официального результата на клиенте (зеркало серверного) — `hub/ui.html`

#### `parseT` — `hub/ui.html` строки 3059–3064

```js
function parseT(t){
  t = String(t || "").replace(/\s+/g, ""); const m = T_RE.exec(t); if (!m || !t) return null;
  const [, a, b, c, f] = m, h = b != null ? +a : 0, mi = b != null ? +b : (a != null ? +a : 0), sec = +c;
  if ((a != null || b != null) && sec >= 60) return null;
  const tot = h * 3600 + mi * 60 + sec + (f ? +f / Math.pow(10, f.length) : 0); return tot > 0 ? tot : null;
}
```

#### `fmtT` — `hub/ui.html` строки 3065–3068

```js
function fmtT(sec){
  const tn = Math.round(sec * 10), h = Math.floor(tn / 36000), m = Math.floor(tn % 36000 / 600), s = Math.floor(tn % 600 / 10), t = tn % 10;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${t}` : m ? `${m}:${String(s).padStart(2, "0")}.${t}` : `${s}.${t}`;
}
```

#### `swMain` — `hub/ui.html` строки 3069–3073

```js
function swMain(vals){
  const v = vals.map(parseT).filter(x => x != null).sort((a, b) => a - b); if (!v.length) return "";
  const main = v.length >= 3 ? v[1] : v[v.length - 1];
  return fmtT(Math.ceil(+(main * 10).toFixed(6)) / 10);
}
```

#### `attBest` — `hub/ui.html` строки 3074–3077

```js
function attBest(vals, hi){
  let best = null; vals.forEach(x => { const m = /^(\d{1,3})(?:[.,](\d{1,2}))?$/.exec(String(x || "").replace(/\s+/g, "")); if (m) { const v = +(m[1] + "." + (m[2] || "0")); if (v > 0 && (best == null || v > best)) best = v; } });
  return best == null ? "" : best.toFixed(2);
}
```

Клиентский расчёт — только подсказка при вводе; **официальный результат всегда считает сервер** (`stopwatch_main`, `parse_attempts`), клиент его не подменяет (`auto: true`).

### 4.6 Обязательное поле «Разряд / Звание» — `hub/ui.html`

#### `rankOpts` — `hub/ui.html` строки 1856–1856

```js
const rankOpts = (cur, ph) => `<option value="">${ph || "—"}</option>` + [...new Set([...RANKS, ...(cur ? [cur] : [])])].map(r => `<option${r === cur ? " selected" : ""}>${esc(r)}</option>`).join("");
```

```js
$("mAdd").onclick = async () => {
  if (!$("mRank").value) { $("mRank").focus(); return toast("Укажите разряд или звание; если разряда нет — «Б/р»"); }
  const body = {last_name:$("mLast").value, first_name:$("mFirst").value, birth_date:$("mBirth").value, sex:$("mSex").value, rank:$("mRank").value,
    team:$("mTeam").value, coach:$("mCoach").value, representative:$("mRep").value, distances:[{distance:$("mDist").value, best:$("mBest").value}]};
```

На сервере то же правило (не обходится запросом в обход UI):

```python
    @classmethod
    def norm_rank(cls, v) -> str:
        """Разряд как в протоколах: «1р», «1 разряд», «кмс» → «1 р.», «КМС». Пустое — пустая строка."""
        t = re.sub(r"\s+", " ", str(v or "")).strip()[:20]
        key = re.sub(r"[\s./]+", "", t.lower()).replace("первый", "1").replace("второй", "2").replace("третий", "3")
        return cls._RANK_ALIAS.get(key) or cls._RANK_ALIAS.get(key.rstrip("."), "") or t
```

```python
rank = self.norm_rank(d.get("rank"))
        if not rank:
            errs["rank"] = "укажите разряд или звание; если разряда нет — «Б/р»"
```

```python
# карточка участника не сохраняется без разряда (смена одного статуса заявки — не правка карточки)
            if set(data) - {"status", "note"} and not (upd["rank"] if "rank" in upd else r.get("rank")):
                return err("Укажите разряд или звание участника; если разряда нет — «Б/р»")
```

## 5. [CSS ДЛЯ ПРИНТЕРА] — `hub/protocol.html`

Ориентация листа не задаётся статически: функция `setPage(land)` (§4.2) перезаписывает `<style id="pgstyle">` с правилом `@page{size:A4 landscape|portrait;margin:…}` и дублем в `@media print{@page{…;size:landscape}}`. Для корзины (смешанные ориентации в одном документе) используются **именованные страницы** `@page cpl` / `@page cpp` и свойство `page:` (Chromium ≥ 85, проверено выводом в PDF: страницы 1 — альбомная, 2–3 — книжные).

Генерируемый CSS (из `setPage` и `renderCart`):

```css
/* setPage(land): одиночный протокол */
@page{size:A4 landscape;margin:10mm 12mm 12mm}
@media print{@page{size:A4 landscape;margin:10mm 12mm 12mm;size:landscape}}
/* (портрет) @page{size:A4 portrait;margin:12mm 12mm 14mm} */

/* renderCart(): пакет листов, каждый — с новой страницы */
@page{size:A4 landscape|portrait;margin:…}          /* по ориентации первого листа */
@page cpl{size:A4 landscape;margin:10mm 12mm 12mm}
@page cpp{size:A4 portrait;margin:12mm 12mm 14mm}
.cp{page-break-after:always;break-after:page}
.cp:last-child{page-break-after:auto;break-after:auto}  /* без пустой страницы в конце */
.cp.land{page:cpl}.cp.port{page:cpp}
```

Статические правила страницы:

#### `hub/protocol.html` строки 135–135

```css
@media print{.cp+.cp{margin-top:0;border-top:0;padding-top:0}}
```

#### `hub/protocol.html` строки 145–160

```css
@media print{
  html,body{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .cp.fit{zoom:var(--z,1)}
  .sign,.tail,table{page-break-inside:auto}
  .sign,.tail{break-inside:avoid;page-break-inside:avoid}
  h2{margin-top:3mm}
  :root{--pr-ink:#000;--pr-muted:#3B4452;--pr-line:#B9C3D0;--pr-line-2:#9AA7B8}
  html,body{background:#fff;color:#000}
  .bar{display:none}
  .stamp .so{display:none}.stamp .po{display:inline}.stamp::before{display:none}
  .sheet{width:auto;min-height:0;margin:0;padding:0;box-shadow:none}
  .sheet,.meta b,.ev,td,.sign{color:#000}
  .brandrow,.org,h1,.ev,.meta{break-inside:avoid;page-break-inside:avoid}
  .brandrow+*{break-before:avoid}
  a{color:inherit;text-decoration:none}
}
```

Правила сетки бланка и корзины:

```css
.sheet.land{width:297mm;min-height:210mm}
.hide{display:none!important}
.cartmode .bar select,.cartmode .bar label,.cartmode #csv{display:none}
.embed .bar{display:none}.embed .sheet{margin:0 auto;box-shadow:none}
.att.tf td.cellv{min-width:12mm;height:8mm;font-size:12px;border-left:1px solid var(--pr-line-2)}.att.tf td.bestv{font-weight:700;background:rgba(0,0,0,.05)}
.cp{margin:0}.cp+.cp{margin-top:18mm;border-top:2px dashed var(--pr-line-2);padding-top:10mm}
.att th,.att td,.swt th.swh{padding:3px 2px}
.swt td.sw{height:8mm;border-left:1px solid var(--pr-line-2)}
.att th.sub{white-space:normal;line-height:1.1}
table.att,table.swt{table-layout:auto}
.att td.cell{height:8mm;min-width:10mm;border-left:1px solid var(--pr-line-2)}
.att th.sub{font-weight:600;font-size:10px;padding:2px 0;text-align:center}
.att td.big{height:8mm}
.cp.land .sign,.sheet.land .sign{grid-template-columns:auto 1fr auto auto 1fr auto;max-width:none;column-gap:10px}
```

## 6. API Мастера

| Метод и адрес | Тело | Ответ / поведение |
|---|---|---|
| `POST /api/events/<id>/heats` | `{lanes, mode}` — полная сборка; `{distance, ages[], sex, lanes}` — **выборочная** (Мастер) | `{heats[], entries, kind, mode}`; техника → всегда `mode:list`, `lane=null`; 400 «нет подтверждённых заявок…» |
| `POST /api/events/<id>/resetheats` | `{distance?}` | `{waves, entries}`; 400, если был старт забега |
| `GET /api/events/<id>/startlist` | — | `heats[]` (`rtype`, `slots`) и участники с `distance`, `rtype`, `slots`, `done_rank` |
| `POST /api/events/<id>/results` | `{rows:[{bib, t[3] \| a[≤6/12] \| result, status, auto, done_rank}]}` | `{saved, errors[]}`; сервер считает результат |
| `GET /api/events/<id>/results` | — | `finished[]` с `place`, `place_overall`, `result`, `sw`, `attempts`, `rt`, `sex`, `done_rank`, `done_rank_auto`, `done_rank_src` |
| `POST /api/events/<id>/publish` | `{start?, results?}` | `{pub_start, pub_results, url, start_url, results_url}` |
| `POST /api/events/<id>/entry` | `{bib, wave, lane, new_bib}` / `{reg_id, wave, set_bib}` | перенос, смена номера, добавление подтверждённой заявки |
| `GET /protocol?event=ID&kind=start\|results\|cart` | параметры: `smode`, `orient`, `sexf`, `dist`, `grp`, `mode`, `embed`, `ids` | HTML бланка; `X-Frame-Options: SAMEORIGIN` только для этого пути |

## 7. Тесты (`tools/selftest.py`)

Результат прогона при формировании дампа: **Итого: 268 из 268 проверок пройдено. · Всё работает.** (код возврата 0).

Проверки, относящиеся к Мастеру (имена из вывода):

- ✅ 3.4: у участника в списке своя дисциплина, тип результата и число попыток (для бланка техники)
- ✅ 3.5: техника — только «Общий список», дорожки заблокированы, участницы не потеряны
- ✅ 3.5: после списка мальчиков девочки на месте: 2 списка, 4 прыгуна, у всех slots=6, дорожек нет
- ✅ 3.5: бег — забеги с дорожками, выборочная сетка не тронула технику
- ✅ 3.5: фильтр по возрасту без подходящих участников — понятная ошибка
- ✅ 3.5: техника — лучшая попытка 7.85 найдена сервером, шесть попыток и выполненный разряд в итогах
- ✅ 3.5: бег — официальный результат по трём секундомерам (среднее 8.33 → 8.4 вверх), разряд сохранён
- ✅ 3.6: разряд считается сам — 60 м девочка 15 лет 9.2 (ручной) → 1 юн.; длина юноша 16 лет 6.10 → 2 р.
- ✅ 3.6: на региональных соревнованиях потолок — I разряд (5.75 у девушки — норма КМС, засчитан 1 р.)
- ✅ 3.6: вписанный секретарём разряд главнее расчётного
- ✅ 3.6: на межрегиональных соревнованиях та же попытка 5.75 даёт КМС
- ✅ 3.6: «Метание мяча/снаряда» есть в справочнике как техническая дисциплина (попытки, расстояние)
- ✅ 3.5: в смешанном общем списке прыжок читается как расстояние (5.45), а не как время
- ✅ 3.5: «Выгрузить в общую сеть» открывает стартовый и итоговый протоколы на публичной странице
- ✅ 3.5: выгрузка без указания, что выгружать, отклоняется
- ✅ 3.5: сброс одной дисциплины убирает только её списки, забеги бега остаются

Браузерные проверки (headless Chromium, playwright-core; сценарии не входят в репозиторий): пять шагов обеих веток, предпросмотр в `iframe`, корзина из 3 листов → печать пакета → PDF с чередованием ориентации, диалог выгрузки, ввод 6 попыток и 3 секундомеров, смена статуса соревнований и пересчёт разрядов; ошибок JS в консоли нет.

## 8. Известные ограничения и честные оговорки

1. **Нет функции `add_entry` как метода Hub.** Есть `Store.add_entry` (низкоуровневая вставка) и ветка API `entry` (§3.8), которая и является прикладным «добавлением участника в забег».
2. **`table()` не в `ui.html`**, а в `protocol.html` (см. §4.1).
3. **Выгрузка в сеть** (`publish`) открывает на публичной странице протокол соревнования **целиком** (`pub_start`/`pub_results`), а не отдельные листы корзины; требует настроенного `public.url` и `ours=true`.
4. **Версия.** `3.7.0`. Механизм обновления сравнивает строки (`latest != VERSION`), поэтому версия только растёт.
5. **Push без force.** Изменения отправляются обычным `git push`; принудительная отправка не нужна (ветка не расходилась с удалённой) и могла бы стереть чужие коммиты.
6. **Корзина хранится в `localStorage` браузера секретаря** (по событию), не на сервере: на другом компьютере она пуста.
7. **Разряды по нормам:** источник — Нормы ЕВСК по виду спорта «лёгкая атлетика» — приложение № 16 к приказу Минспорта России от 10.03.2026; 264 норм; пропущены 2 ячейки-опечатки таблицы (`skipped` в `rank_norms.json`). Не учитываются ветер, эстафеты, «бег 24 часа»; МСМК не присваивается автоматически. Для 500 м, 2000 м, 80 м с/б, ходьбы 1500 м норм в таблице нет.
8. **Попыток в высоте/шесте на бланке 6** (ТЗ), хотя `attempt_slots` для ввода допускает 12 высот.
9. **Ключ сопоставления дисциплины с нормами** строится по названию (`norm_key`); нестандартные названия («Метание снаряда» без слова «мяч») нормы не находят — разряд вносится вручную.
10. **Персональные данные** в дамп и репозиторий не попадают (152-ФЗ): только код, схема и обезличенные тестовые данные.

## 9. Состав проекта (файлы, затронутые линейкой 3.4–3.6)

| Файл | Назначение |
|---|---|
| `hub/hub.py` | сервер: БД, API, генерация сетки, расчёт результатов и разрядов |
| `hub/ui.html` | админка: Мастер протоколов, корзина печати, форма регистрации |
| `hub/protocol.html` | печатные формы: стартовые и итоговые протоколы, корзина-пакет |
| `hub/seed/disciplines.json` | справочник дисциплин (тип результата, attempts, aliases) |
| `hub/seed/rank_norms.json` | нормы ЕВСК по лёгкой атлетике (генерируется) |
| `tools/norms_import.py` | импорт норм из xls Минспорта |
| `tools/selftest.py` | автопроверки |
| `tools/make_snapshot.py` | генератор этого файла |
| `docs/cart-3.4.md, wizard-3.5.md, ranks-3.6.md` | описания |

### Журнал коммитов линейки

```text
a331a84 2026-10-13 major: упорядочена система ролей (Админ/Судья) и ликвидировано забавление кнопок обновлений v4.5.0
43ccb4d 2026-10-13 major: зафиксирован единый монолитный интерфейс навигации и внедрен пульт управления табло v4.4.0
c3e08b9 2026-10-13 major: запущен выделенный мобильный роут /sector для планшетов судей со сквозной трансляцией результатов на Табло v4.3.0
b452b31 2026-10-13 fix: проведен тотальный аудит системы, ликвидирован откат Мастера соревнований и хаос в шестерёнке v4.2.0
935b9f6 2026-10-13 major: ликвидирован хаос в настройках системы, внедрено разделение по вкладкам оборудования и VPN v4.1.0
01ffe18 2026-10-13 major: запущен АРМ мобильного Судьи на секторе и оптимизирована компактная шапка бланков печати v4.0.0
723d34d 2026-10-13 major: ликвидировано задвоение шагов навигации, оптимизировано АРМ секретаря под чистый Мастер протоколов v3.9.0
98d2695 2026-10-13 major: оптимизирована компактность печати на один лист и добавлен ручной ввод выполненных разрядов v3.8.0
66fb854 2026-10-13 major: упорядочен интерфейс Мастера, внедрено автоматическое разделение протоколов по вкладкам пола и категорий v3.7.0
1a87b16 2026-10-13 release: глобальный дамп архитектуры Мастера протоколов v3.6
72977c5 2026-10-13 chore: версия 3.6.1 (справочник: метание мяча/снаряда) для установки через кнопку обновления
076cf3c 2026-10-13 feat: в справочник дисциплин добавлено «Метание мяча/снаряда» (техника, 6 попыток)
ccc81bc 2026-10-13 feat: выполненные разряды по нормам ЕВСК в итоговом протоколе v3.6.0
5ce3b56 2026-10-13 feat: запущен полный Мастер стартовых и итоговых протоколов бега и техники v3.5.0
```

