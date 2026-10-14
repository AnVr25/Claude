# system_final_snapshot — полный технический дамп SakhStart timing-hub, Мастер протоколов v3.7

- **Версия сервера (`VERSION`):** `7.4.5` (линейка v3.7: вкладки групп и отдельный лист на каждую категорию)
- **Дата сборки (`BUILD_DATE`):** `2026-10-14`
- **Ветка / коммит:** `claude/greeting-d2g8ji` / `a623134`
- **Дамп сформирован:** 2026-10-14 11:11 скриптом `tools/make_snapshot.py` (код ниже вставлен дословно из исходников)
- **Автопроверки:** Итого: 324 из 324 проверок пройдено. · Всё работает.
- **Объём исходников:** `hub/hub.py` 5790 строк, `hub/ui.html` 2770, `hub/protocol.html` 637

> Для аудитора. Что в дампе: (1) назначение и архитектура, (2) схема SQLite, (3) весь Python Мастера, (4) весь JavaScript, (5) CSS печати, (6) API, (7) тесты, (8) известные ограничения и места, где фактическая реализация отличается от формулировок ТЗ.

## 0. Что реализовано (соответствие ТЗ)

| Требование | Где реализовано | Статус |
|---|---|---|
| Автоопределение Бег / Техника | `Hub.discipline_kind`, `Hub.result_type`, `Hub.attempt_slots` (справочник `hub/seed/disciplines.json`); в браузере `wzp` → `kindOf` | ✅ |
| Бег: вертикальный бланк, 3 поля «Сек. 1–3» | `protocol.html`: `startSheet()` → `table()` (ветка `grid=false`), `setPage(false)` | ✅ |
| Техника: сквозной «Общий список» без дорожек | `Hub.generate_scoped` (`tech → plan.append(... use_lanes=False)`), блокировка на сервере | ✅ |
| Техника: альбомный лист, 6 попыток + «Лучший результат» | `protocol.html`: `isTech`, `table()` (`N=6`), `setPage(true)`, `@page … landscape` | ✅ |
| Мастер: фильтры пол / возрастные группы (AGES) | `ui.html`: `wzp` шаг 1; сервер: `Hub.age_limits` (из `seed/disciplines.json`), `generate_scoped(scope.ages, scope.sex)` | ✅ |
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

Схема получена запуском `Store(...)` на пустой БД (создание + все миграции `_migrate`), то есть показывает **итоговое** состояние. Таблицы: `audit`, `consent_texts`, `entries`, `events`, `files`, `manual`, `registrations`, `scoreboard`, `sessions`, `trainers`, `ui_state`, `users`, `waves`.

### Таблица `events`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `name` | TEXT | да |  |  |
| 2 | `date` | TEXT |  |  |  |
| 3 | `place` | TEXT |  |  |  |
| 4 | `finish_device` | TEXT |  |  |  |
| 5 | `start_time` | TEXT |  |  |  |
| 6 | `status` | TEXT | да | 'planned' |  |
| 7 | `notes` | TEXT |  |  |  |
| 8 | `created_at` | TEXT | да |  |  |
| 9 | `archived` | INTEGER | да | 0 |  |
| 10 | `finished_at` | TEXT |  |  |  |
| 11 | `organizer` | TEXT |  |  |  |
| 12 | `chief_judge` | TEXT |  |  |  |
| 13 | `chief_secretary` | TEXT |  |  |  |
| 14 | `start_clock` | TEXT |  |  |  |
| 15 | `heats_sequential` | INTEGER |  |  |  |
| 16 | `team_best` | INTEGER |  |  |  |
| 17 | `cover` | TEXT |  |  |  |
| 18 | `program` | TEXT |  |  |  |
| 19 | `contacts` | TEXT |  |  |  |
| 20 | `series` | TEXT |  |  |  |
| 21 | `reg_open` | INTEGER | да | 0 |  |
| 22 | `reg_slug` | TEXT |  |  |  |
| 23 | `reg_deadline` | TEXT |  |  |  |
| 24 | `reg_distances` | TEXT |  |  |  |
| 25 | `reg_rules` | TEXT |  |  |  |
| 26 | `reg_lanes` | INTEGER |  |  |  |
| 27 | `reg_info` | TEXT |  |  |  |
| 28 | `reg_consent` | TEXT |  |  |  |
| 29 | `kind` | TEXT |  |  |  |
| 30 | `timing` | TEXT |  |  |  |
| 31 | `pub_site` | INTEGER | да | 0 |  |
| 32 | `ours` | INTEGER | да | 1 |  |
| 33 | `level` | TEXT |  |  |  |
| 34 | `adaptive` | INTEGER | да | 0 |  |
| 35 | `date_end` | TEXT |  |  |  |
| 36 | `city` | TEXT |  |  |  |
| 37 | `note` | TEXT |  |  |  |
| 38 | `live_url` | TEXT |  |  |  |
| 39 | `photo_url` | TEXT |  |  |  |
| 40 | `links` | TEXT |  |  |  |
| 41 | `pub_start` | INTEGER | да | 0 |  |
| 42 | `pub_results` | INTEGER | да | 0 |  |
| 43 | `pub_regs` | INTEGER | да | 0 |  |
| 44 | `pub_regs_full` | INTEGER | да | 0 |  |

```sql
CREATE TABLE events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                date TEXT,
                place TEXT,
                finish_device TEXT,
                start_time TEXT,
                status TEXT NOT NULL DEFAULT 'planned',
                notes TEXT,
                created_at TEXT NOT NULL
            , archived INTEGER NOT NULL DEFAULT 0, finished_at TEXT, organizer TEXT, chief_judge TEXT, chief_secretary TEXT, start_clock TEXT, heats_sequential INTEGER, team_best INTEGER, cover TEXT, program TEXT, contacts TEXT, series TEXT, reg_open INTEGER NOT NULL DEFAULT 0, reg_slug TEXT, reg_deadline TEXT, reg_distances TEXT, reg_rules TEXT, reg_lanes INTEGER, reg_info TEXT, reg_consent TEXT, kind TEXT, timing TEXT, pub_site INTEGER NOT NULL DEFAULT 0, ours INTEGER NOT NULL DEFAULT 1, level TEXT, adaptive INTEGER NOT NULL DEFAULT 0, date_end TEXT, city TEXT, note TEXT, live_url TEXT, photo_url TEXT, links TEXT, pub_start INTEGER NOT NULL DEFAULT 0, pub_results INTEGER NOT NULL DEFAULT 0, pub_regs INTEGER NOT NULL DEFAULT 0, pub_regs_full INTEGER NOT NULL DEFAULT 0)
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
| 0 | `id` | INTEGER |  |  | да |
| 1 | `event_id` | INTEGER | да |  |  |
| 2 | `bib` | TEXT | да |  |  |
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                bib TEXT NOT NULL
            , points REAL, picked_at TEXT, members TEXT, rank TEXT, detail TEXT, done_rank TEXT, result_at TEXT, wave TEXT, name TEXT, birth_year TEXT, team TEXT, category TEXT, lane INTEGER, coach TEXT, seed TEXT, reg_id INTEGER, sex TEXT, result TEXT, status TEXT)
```

```sql
CREATE INDEX idx_entries_event ON entries(event_id, bib);
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
| 25 | `policy_hash` | TEXT |  |  |  |
| 26 | `anonymized_at` | TEXT |  |  |  |

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
            , relay TEXT, leg INTEGER, rank TEXT, policy_hash TEXT, anonymized_at TEXT)
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

### `Store._migrate` — `hub/hub.py` строки 391–565

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

        add("events", (("archived", "INTEGER NOT NULL DEFAULT 0"), ("finished_at", "TEXT"),
                       ("organizer", "TEXT"), ("chief_judge", "TEXT"), ("chief_secretary", "TEXT"),
                       ("start_clock", "TEXT"), ("heats_sequential", "INTEGER")))
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
        add("events", (("pub_regs", "INTEGER NOT NULL DEFAULT 0"),))      # 7.1: открытый список «прошли регистрацию» для тренеров
        add("events", (("pub_regs_full", "INTEGER NOT NULL DEFAULT 0"),))  # 7.4: секретарь подтвердил согласия на распространение по старым заявкам
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
        # 6.0: общее состояние экранов секретарей — активная дисциплина и фильтры Мастера, корзина печати.
        # Раньше жили в localStorage браузера (у двух секретарей — две разные картины). rev растёт на каждую запись
        self.con.execute("""CREATE TABLE IF NOT EXISTS ui_state(
            event_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 1,
            who TEXT, cid TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(event_id, key))""")
        # 5.0: личный кабинет тренера — учётки с подтверждённой почтой, вход к закрытым протоколам.
        # verification_token — sha256 от кода из письма (сам код в базе не хранится)
        self.con.execute("""CREATE TABLE IF NOT EXISTS trainers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 0,
            verification_token TEXT,
            created_at TEXT NOT NULL)""")
        add("trainers", (("token_expires", "TEXT"), ("token_attempts", "INTEGER NOT NULL DEFAULT 0"),
                         ("token_sent_at", "TEXT"), ("active", "INTEGER NOT NULL DEFAULT 1"), ("last_login", "TEXT"),
                         ("verified_at", "TEXT"), ("verified_by", "TEXT"),
                         # 5.0.1: согласие на обработку ПДн — флаг, когда дано и с какой редакцией политики
                         ("consent_accepted", "INTEGER NOT NULL DEFAULT 0"), ("consent_at", "TEXT"), ("consent_hash", "TEXT"),
                         # 5.1: согласие и ознакомление с Политикой — отдельно (ст. 9 152-ФЗ в ред. с 01.09.2025)
                         ("policy_hash", "TEXT")))
        add("registrations", (("policy_hash", "TEXT"), ("anonymized_at", "TEXT")))
        # архив редакций текстов согласий: по отпечатку из заявки/учётной записи можно показать точный текст
        self.con.execute("""CREATE TABLE IF NOT EXISTS consent_texts(
            hash TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL)""")
        # 4.5: две роли — администратор и судья; секретарь и судья на секторе становятся судьями
        self.con.execute("UPDATE users SET role = 'judge' WHERE role NOT IN ('admin', 'judge')")
        self._migrate_v7()
        self._migrate_v74()
```

## 3. [ВЕСЬ ИЗМЕНЁННЫЙ КОД PYTHON] — `hub/hub.py`

Примечание: функции `add_entry`, `get_next_bib`, `next_bib` приведены как есть. Отдельной функции «автоопределения официального времени» нет: правило ручного хронометража реализовано в `stopwatch_main`, а вызывается из ветки `results` (§3.6).

### 3.1 Определение типа дисциплины (Бег / Техника)

#### `Hub.discipline` — `hub/hub.py` строки 1785–1787

```python
    @classmethod
    def discipline(cls, name) -> Optional[dict]:
        return cls.disciplines()["index"].get(cls._dkey(name)) if name else None
```

#### `Hub.result_type` — `hub/hub.py` строки 1913–1917

```python
    @classmethod
    def result_type(cls, name) -> str:
        """time · distance · height · points. Неизвестная дисциплина — время, как раньше."""
        d = cls.discipline(name)
        return d["result"] if d else "time"
```

#### `Hub.discipline_kind` — `hub/hub.py` строки 1896–1904

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

#### `Hub.attempt_slots` — `hub/hub.py` строки 1586–1592

```python
    @classmethod
    def attempt_slots(cls, name) -> int:
        """Сколько ячеек попыток: 6 в прыжках и метаниях; в высоте и шесте — до 12 покорённых высот."""
        d = cls.discipline(name)
        if not d or not d.get("attempts"):
            return 0
        return 12 if d.get("result") == "height" else 6
```

#### `Hub.entry_dists` — `hub/hub.py` строки 1906–1911

```python
    def entry_dists(self, eid: int, erows: Optional[list] = None) -> dict:
        """id строки участника → её дисциплина: дистанция забега, а у смешанного «общего списка» — из заявки."""
        erows = erows if erows is not None else self.store.entries_rows(eid)
        wd = {w["name"]: w.get("distance") for w in self.store.waves(eid)}
        rd = {r["id"]: r.get("distance") for r in self.store.registrations(eid)}
        return {e["id"]: (wd.get(e["wave"] or "") or rd.get(e.get("reg_id")) or None) for e in erows}
```

### 3.2 Формирование сетки: полная и выборочная (Мастер)

#### `Hub.generate_scoped` — `hub/hub.py` строки 3803–3904

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
        ages = [a for a in (scope.get("ages") or []) if a in self.age_limits()]
        lanes = max(1, min(int(lanes or 8), 50))
        waves = self.store.waves(eid)
        if any(w.get("start_time") for w in waves if (w.get("distance") or "") == dist):
            raise ValueError("по этой дисциплине стоит время старта — нажмите «Сбросить сетку», затем сформируйте список заново")
        year = int(ev["date"][:4]) if ev.get("date") else dt.date.today().year

        def in_scope(r):
            if r["distance"] != dist or r["status"] != "approved":
                return False
            if sex and str(r.get("sex") or "").upper() != sex:
                return False
            return self.age_ok(year, r["birth_date"], ages)
        allregs = self.store.registrations(eid)
        regs = self.collapse_relays(ev, [r for r in allregs if in_scope(r)])
        if not regs:
            raise ValueError("нет подтверждённых заявок по выбранным условиям: проверьте дисциплину, возраст и пол")
        mine = {r["id"] for r in regs}
        st = self._bib_state(eid)
        entries = st["entries"]
        self._need_bibs(regs, st)                       # без ручных номеров сетку не строим
        my_keys = {st["key_of"].get(i) for i in mine}
        theirs = {e["bib"] for e in entries if e.get("reg_id") not in mine and st["key_of"].get(e.get("reg_id")) not in my_keys}
        clash = [self._reg_bib(r, st) for r in regs if self._reg_bib(r, st) in theirs]
        if clash:
            raise ValueError(f"номер {clash[0]} уже у другого участника — исправьте на шаге 2")
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
                bib = self._reg_bib(r, st)
                rows.append({"bib": bib, "wave": name, "name": " ".join(x for x in (r["last_name"], r["first_name"]) if x),
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

#### `Hub.lane_order` — `hub/hub.py` строки 3773–3782

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

#### `Hub.reset_heats` — `hub/hub.py` строки 3925–3965

```python
    def reset_heats(self, ev: dict, distance: Optional[str] = None) -> dict:
        """Принудительный сброс сетки (кнопка «Сбросить сетку / Удалить забеги»). Никогда не блокируется тем, что у забега
        стоит время старта — в том числе поставленное по ошибке: часы забегов останавливаются, start_time обнуляется
        (NULL), забеги и дорожки удаляются, участники возвращаются в «Не распределены». Номера, заявки и введённые
        результаты сохраняются; после сброса список формируется заново и подтягивает ВСЕХ подтверждённых участников."""
        eid = ev["id"]
        rows = self.store.entries_rows(eid)
        ed = self.entry_dists(eid, rows)
        dkey = self._dkey(distance) if distance else None

        def mine(w):
            if not distance:
                return True
            if w.get("distance"):
                return self._dkey(w["distance"]) == dkey
            inside = [r for r in rows if r["wave"] == w["name"]]          # забег без дисциплины: по составу
            return bool(inside) and all(self._dkey(ed.get(r["id"]) or "") == dkey for r in inside)
        gone = [w for w in self.store.waves(eid) if mine(w)]
        names = {w["name"] for w in gone}
        stopped = [w["name"] for w in gone if w.get("start_time")]
        con = self.store.con
        con.execute("BEGIN")
        try:
            for w in gone:
                con.execute("UPDATE waves SET start_time = NULL, finished_at = NULL WHERE event_id = ? AND name = ?", (eid, w["name"]))
            n = 0
            for r in rows:
                inside = r["wave"] in names or (distance and self._dkey(ed.get(r["id"]) or "") == dkey
                                                and (r["wave"] or r["lane"] is not None))
                if inside:
                    con.execute("UPDATE entries SET wave = NULL, lane = NULL WHERE id = ?", (r["id"],))
                    n += 1
            for name in names:
                self.store.delete_wave(eid, name)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        if not any(w.get("start_time") for w in self.store.waves(eid)):      # часы соревнования тоже остановлены
            self.store.set_event_field(eid, start_time=None, status="finished" if ev.get("status") == "finished" else "planned")
        return {"waves": len(names), "entries": n, "stopped": stopped}
```

#### `Hub.age_limits` — `hub/hub.py` строки 3785–3789

```python
    @classmethod
    def age_limits(cls) -> dict:
        """Возрастные группы шага 1 Мастера: границы берутся ТОЛЬКО из seed/disciplines.json (ages[].min/max)."""
        return {a["id"]: (int(a.get("min", 0)), int(a.get("max", 200)))
                for a in (cls.disciplines()["data"].get("ages") or []) if a.get("id")}
```

#### `Hub.age_ok` — `hub/hub.py` строки 3791–3801

```python
    @classmethod
    def age_ok(cls, year: int, birth, ages: list) -> bool:
        """Год рождения подходит хотя бы под одну из выбранных групп; пустой выбор — подходят все."""
        if not ages:
            return True
        try:
            age = year - int(str(birth)[:4])
        except ValueError:
            return False
        lim = cls.age_limits()
        return any(lim[a][0] <= age <= lim[a][1] for a in ages if a in lim)
```

### 3.3 Номера и участники

#### `Store.add_entry` — `hub/hub.py` строки 927–938

```python
    def add_entry(self, eid: int, r: dict) -> int:
        # нагрудный номер вписывает только судья/секретарь — автоматической выдачи номеров нет
        bib = str(r.get("bib") or "").strip()
        if not bib:
            raise ValueError("нет нагрудного номера — впишите его на шаге 2 «Нагрудные номера»")
        cur = self.con.execute(
            "INSERT INTO entries(event_id, bib, wave, name, birth_year, team, category, lane, coach, seed,"
            " reg_id, sex, members, rank) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, bib, r.get("wave"), r.get("name"), r.get("birth_year"), r.get("team"),
             r.get("category"), r.get("lane"), r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex"),
             r.get("members"), r.get("rank")))
        return int(cur.lastrowid)
```

#### `Store.upsert_entries` — `hub/hub.py` строки 854–880

```python
    def upsert_entries(self, eid: int, rows: list) -> None:
        """Формирование сетки одной дисциплины: строки ищутся по заявке (reg_id); введённые результаты не трогаются,
        участники других дисциплин остаются на месте."""
        self.con.execute("BEGIN")
        try:
            for r in rows:
                have = self.con.execute("SELECT id FROM entries WHERE event_id = ? AND reg_id = ?", (eid, r["reg_id"])).fetchone() \
                    if r.get("reg_id") else None
                if have:
                    self.con.execute(
                        "UPDATE entries SET bib = ?, wave = ?, lane = ?, name = ?, birth_year = ?, team = ?, category = ?, coach = ?,"
                        " seed = ?, sex = ?, rank = ?, members = COALESCE(?, members) WHERE id = ?",
                        (r["bib"], r.get("wave"), r.get("lane"), r.get("name"), r.get("birth_year"), r.get("team"), r.get("category"),
                         r.get("coach"), r.get("seed"), r.get("sex"), r.get("rank"), r.get("members"), have[0]))
                else:
                    self.con.execute(
                        "INSERT INTO entries(event_id, bib, wave, name, birth_year, team, category, lane, coach, seed,"
                        " reg_id, sex, members, rank) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (eid, r["bib"], r.get("wave"), r.get("name"), r.get("birth_year"), r.get("team"),
                         r.get("category"), r.get("lane"), r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex"),
                         r.get("members"), r.get("rank")))
            for w in dict.fromkeys(r["wave"] for r in rows if r.get("wave")):
                self.con.execute("INSERT OR IGNORE INTO waves(event_id, name) VALUES (?,?)", (eid, w))
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
```

#### `Store.update_entry` — `hub/hub.py` строки 915–925

```python
    def update_entry(self, eid: int, entry_id: int, **kw) -> int:
        sets, args = [], []
        for k, v in kw.items():
            if k not in ("wave", "lane", "name", "birth_year", "team", "category", "coach", "seed", "rank", "done_rank"):
                raise ValueError(k)
            sets.append(f"{k} = ?")
            args.append(v)
        if not sets:
            return 0
        return self.con.execute(f"UPDATE entries SET {', '.join(sets)} WHERE event_id = ? AND id = ?",
                                (*args, eid, entry_id)).rowcount
```

#### `Store.rename_bib` — `hub/hub.py` строки 940–944

```python
    def rename_bib(self, eid: int, old: str, new: str) -> None:
        """Сменить нагрудный номер везде: во всех строках участника (дисциплинах), заявках и ручных отметках судей."""
        self.con.execute("UPDATE entries SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
        self.con.execute("UPDATE registrations SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
        self.con.execute("UPDATE manual SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
```

### 3.4 Список для печати

#### `Hub.startlist` — `hub/hub.py` строки 4005–4024

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

#### `Hub.public_startlist` — `hub/hub.py` строки 1486–1490

```python
    def public_startlist(self, ev: dict) -> dict:
        sl = self.startlist(ev)
        for h in sl["heats"]:
            h["entries"] = self._public_rows(h["entries"])
        return {"event": self._public_event(ev), "heats": sl["heats"], "no_heat": self._public_rows(sl["no_heat"])}
```

### 3.5 Хранение результата и отметок

#### `Store.set_entry_result` — `hub/hub.py` строки 894–905

```python
    def set_entry_result(self, eid: int, entry_id: int, result: Optional[str], status: Optional[str],
                         detail: Optional[dict] = None, set_detail: bool = False) -> int:
        """Итог строки участника. detail — показания секундомеров {"t": [...]} и попытки {"a": [...]}; None при set_detail стирает."""
        at = fmt_db(now_local()) if (result or status or detail) else None      # время ввода — табло показывает свежие сверху
        if set_detail:
            dj = json.dumps(detail, ensure_ascii=False) if detail else None
            cur = self.con.execute("UPDATE entries SET result = ?, status = ?, detail = ?, result_at = ? WHERE event_id = ? AND id = ?",
                                   (result or None, status or None, dj, at, eid, entry_id))
        else:
            cur = self.con.execute("UPDATE entries SET result = ?, status = ?, result_at = ? WHERE event_id = ? AND id = ?",
                                   (result or None, status or None, at, eid, entry_id))
        return cur.rowcount
```

### 3.6 Официальное время по 3 секундомерам и лучший результат из 6 попыток

#### `Hub.round_up_tenth` — `hub/hub.py` строки 1569–1571

```python
    @staticmethod
    def round_up_tenth(x: float) -> float:
        return math.ceil(round(x * 10, 6)) / 10.0
```

#### `Hub.stopwatch_main` — `hub/hub.py` строки 1573–1582

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

#### `Hub.parse_result` — `hub/hub.py` строки 1741–1758

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

#### `Hub.fmt_result` — `hub/hub.py` строки 1540–1551

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

#### `Hub.parse_typed` — `hub/hub.py` строки 1919–1938

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

#### `Hub.parse_attempts` — `hub/hub.py` строки 1713–1736

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

#### `Hub.result_hint` — `hub/hub.py` строки 1940–1942

```python
    @classmethod
    def result_hint(cls, rtype: str) -> str:
        return (cls.disciplines()["data"].get("result_types", {}).get(rtype) or {}).get("hint") or "12.84 или 4:05.32"
```

### 3.7 Выполненный разряд по нормам ЕВСК

#### `Hub.norm_key` — `hub/hub.py` строки 1798–1830

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

#### `Hub.rank_norms` — `hub/hub.py` строки 1832–1845

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

#### `Hub.age_group` — `hub/hub.py` строки 1847–1852

```python
    @staticmethod
    def age_group(age: int) -> str:
        for lim in (12, 14, 16, 18, 20, 23):
            if age < lim:
                return f"u{lim}"
        return "sen"
```

#### `Hub.rank_for` — `hub/hub.py` строки 1854–1894

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

#### `Hub.norm_rank` — `hub/hub.py` строки 1561–1566

```python
    @classmethod
    def norm_rank(cls, v) -> str:
        """Разряд как в протоколах: «1р», «1 разряд», «кмс» → «1 р.», «КМС». Пустое — пустая строка."""
        t = re.sub(r"\s+", " ", str(v or "")).strip()[:20]
        key = re.sub(r"[\s./]+", "", t.lower()).replace("первый", "1").replace("второй", "2").replace("третий", "3")
        return cls._RANK_ALIAS.get(key) or cls._RANK_ALIAS.get(key.rstrip("."), "") or t
```

#### `Hub.RANK_ORDER` — `hub/hub.py` строки 1791–1791

```python
    RANK_ORDER = ("МСМК", "МС", "КМС", "1 р.", "2 р.", "3 р.", "1 юн.", "2 юн.", "3 юн.")
```

#### `Hub.RANK_MIN_AGE` — `hub/hub.py` строки 1792–1792

```python
    RANK_MIN_AGE = {"МСМК": 16, "МС": 15, "КМС": 14}          # остальные разряды — с 10 лет
```

#### `Hub.RANK_CAP` — `hub/hub.py` строки 1794–1794

```python
    RANK_CAP = {"russia": "МС", "dfo": "МС", "interregion": "КМС", "region": "1 р.", "mass": "2 р."}
```

### 3.8 Ветки HTTP-API Мастера (внутри `Hub._api_event`)

#### `heats — формирование сетки (полное и выборочное)` — `hub/hub.py` строки 2785–2801

```python
        if action == "heats":
            try:
                if not str(data.get("distance") or "").strip():
                    return err("выберите дисциплину")
                out = self.generate_scoped(ev, data.get("lanes") or ev.get("reg_lanes") or 8, data)
            except ValueError as e:
                return err(str(e))
            if data.get("lanes"):
                self.store.update_event(eid, {"reg_lanes": data["lanes"]})
            self.store.audit(who, eid, "Сформирован общий список" if out.get("mode") == "list" else "Сформированы забеги",
                             f"{data.get('distance') + ': ' if data.get('distance') else ''}{len(out['heats'])} забегов, {out['entries']} участников")
            try:
                self.save_file(eid, f"Стартовый список {now_local():%Y-%m-%d %H-%M}.csv",
                               self._startlist_csv(self.store.get_event(eid)).encode("utf-8"), "startlist", who, "Для судей")
            except Exception:
                log.exception("стартовый список в папку «Для судей»")
            return ok(out)
```

#### `resetheats — сброс сетки (всей или одной дисциплины)` — `hub/hub.py` строки 2766–2773

```python
        if action == "resetheats":
            try:
                out = self.reset_heats(ev, data.get("distance"))
            except ValueError as e:
                return err(str(e))
            self.store.audit(who, eid, "Сброшена сетка забегов", f"забегов удалено: {out['waves']}, участников возвращено в нераспределённые: {out['entries']}"
                             + (f"; сброшено время старта: {', '.join(out['stopped'])}" if out["stopped"] else ""))
            return ok(out)
```

#### `publish — выгрузка в общую сеть` — `hub/hub.py` строки 2742–2765

```python
        if action == "publish":
            # публикация: открытый список «прошли регистрацию» (pub_regs, минимум данных) и протоколы для тренеров в кабинете (pub_start / pub_results — закрыты, нужен вход)
            upd = {}
            if "regs" in data:                      # 7.1: открытый список «прошли регистрацию» (минимум данных, без входа)
                upd["pub_regs"] = bool(data["regs"])
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
            self.store.audit(who, eid, "Публикация включена (тренерам / открытый список)" if any(upd.values()) else "Публикация снята",
                             ", ".join(f"{k}={'да' if v else 'нет'}" for k, v in upd.items()))
            v = self._event_view(self.store.get_event(eid))
            return ok({"pub_start": v["pub_start"], "pub_results": v["pub_results"], "pub_regs": v["pub_regs"], "url": v["page_url"],
                       "registered_url": f"{self.public_base()}/r/{slug}/participants",
                       "start_url": f"{self.public_base()}/r/{slug}/protocol?kind=start",
                       "results_url": f"{self.public_base()}/r/{slug}/protocol?kind=results"})
```

#### `entry — перенос участника, смена номера, добавление заявки в забег (прикладной «add_entry»)` — `hub/hub.py` строки 2817–2894

```python
        if action == "entry":
            # добавление подтверждённой заявки в сетку (поздний участник), перенос участника в другой забег / на другую дорожку
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
                ids = r.get("_ids") or [r["id"]]
                rows = self.store.entries_rows(eid)
                if any(x.get("reg_id") in ids for x in rows):
                    return err("участник уже в стартовом списке")
                typed = str(data.get("set_bib") or "").strip()
                if typed:                                # вписанный номер ложится на все дисциплины человека, с проверкой повторов
                    code_, out_ = self.save_bibs(ev, [{"ids": ids, "bib": typed}], who)
                    if code_ != 200:
                        return err((out_.get("errors") or [{}])[0].get("error") or out_.get("error") or "номер не сохранён")
                st = self._bib_state(eid)
                bib = self._reg_bib(st["regs"][ids[0]], st)
                if not bib:
                    return err("впишите нагрудный номер участника (шаг 2 Мастера «Нагрудные номера»)")
                if lane is None and wave:
                    taken = {e["lane"] for e in rows if e["wave"] == wave}
                    lane = next((x for x in self.lane_order(int(ev.get("reg_lanes") or 8)) if x not in taken), None)
                self.store.add_entry(eid, {"bib": bib, "wave": wave,
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
            all_rows = self.store.entries_rows(eid)
            row, why = self._entry_of(bib, [e for e in all_rows if e["bib"] == bib], data.get("distance"), self.entry_dists(eid, all_rows))
            if not row:
                return err(why if any(e["bib"] == bib for e in all_rows) else "нет участника с таким номером", 404)
            if row["wave"] and (self.store.get_wave(eid, row["wave"]) or {}).get("start_time") and "wave" in data \
                    and wave != row["wave"]:
                return err("забег участника уже стартовал")
            if "new_bib" in data:
                nb = str(data["new_bib"] or "").strip()
                if nb == bib:
                    return ok({"bib": bib})
                if row.get("reg_id"):                    # номер меняется у человека во всех его дисциплинах
                    code_, out_ = self.save_bibs(ev, [{"ids": [row["reg_id"]], "bib": nb}], who)
                    if code_ != 200:
                        return err((out_.get("errors") or [{}])[0].get("error") or out_.get("error") or "номер не сохранён")
                else:
                    if not self.BIB_RE.fullmatch(nb) or any(e["bib"] == nb for e in all_rows):
                        return err(f"номер {nb or '—'} не подходит или уже занят другим участником")
                    self.store.rename_bib(eid, bib, nb)
                self.store.audit(who, eid, "Изменён нагрудный номер", f"{row.get('name') or ''}: №{bib} → №{nb}")
                return ok({"bib": nb})
            upd = {}
            if "wave" in data:
                upd["wave"] = wave
                if "lane" not in data and wave:
                    taken = {e["lane"] for e in all_rows if e["wave"] == wave}
                    upd["lane"] = next((x for x in self.lane_order(int(ev.get("reg_lanes") or 8)) if x not in taken), None)
            if "lane" in data:
                upd["lane"] = lane
            self.store.update_entry(eid, row["id"], **upd)
            self.store.audit(who, eid, "Перенос участника", f"№{bib}: {row['wave'] or '—'} → {upd.get('wave', row['wave']) or '—'}"
                             + (f", дорожка {upd['lane']}" if upd.get("lane") else ""))
            return ok({"ok": True})
```

#### `results — ручной ввод: секундомеры, попытки, статус, выполненный разряд` — `hub/hub.py` строки 2508–2555

```python
        if action == "results" and isinstance(data.get("rows"), list):
            bad, n = [], 0
            all_rows = self.store.entries_rows(eid)
            ed_ = self.entry_dists(eid, all_rows)
            old: dict = {}                      # номер → строки этого номера (по одной на дисциплину)
            for e_ in all_rows:
                old.setdefault(e_["bib"], []).append(e_)
            for rw in data["rows"][:2000]:
                if not isinstance(rw, dict):
                    continue
                bib = str(rw.get("bib") or "").strip()
                st = str(rw.get("status") or "").strip().upper()
                txt = str(rw.get("result") or "").strip()
                if st and st not in self.STATUSES:
                    bad.append(f"{bib}: неизвестная отметка {st}")
                    continue
                row_, why = self._entry_of(bib, old.get(bib) or [], rw.get("distance"), ed_)
                if row_ is None:
                    bad.append(f"{bib}: {why}")
                    continue
                dn = ed_.get(row_["id"])
                rt = self.result_type(dn)
                detail, set_detail, auto_txt, errs = self.official_from_raw(dn, rt, rw)
                if errs:
                    bad.extend(f"{bib}: {m_}" for m_ in errs)
                    continue
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
                    self.store.update_entry(eid, row_["id"], done_rank=dr or None)
                    if not (set(rw) - {"bib", "distance", "done_rank", "auto"}):
                        n += 1             # прислан только разряд — результат и отметку не трогаем
                        continue
                if self.store.set_entry_result(eid, row_["id"], pr[1] if pr else None, st or None, detail or None, set_detail):
                    n += 1
            if n:
                self.store.audit(who, eid, "Введены результаты", f"строк: {n}")
            return ok({"saved": n, "errors": bad})
```

### 3.9 `Hub.compute` (итоговые результаты) — `hub/hub.py` строки 1990–2181

Дословно: включает дисциплину участника (`entry_dists`), места по дисциплине в смешанном забеге и расчёт `done_rank`.

```python
    def compute(self, ev: dict) -> dict:
        """Результаты соревнования: введённые вручную итоги (секундомеры, попытки, очки) и отсечки судьи JUDGE.
        Строка участника = спортсмен в одной дисциплине (ключ — id), поэтому у многоборца места считаются по каждому виду отдельно."""
        eid = ev["id"]
        erows = self.store.entries_rows(eid)
        entered, status_of, rtype_of = {}, {}, {}
        edist = self.entry_dists(eid, erows)          # дисциплина строки: у забега или, если забег смешанный, из заявки
        for r in erows:
            k = r["id"]
            if r.get("status") in self.STATUSES:
                status_of[k] = r["status"]
            elif r.get("result"):
                dn = edist.get(k)
                rt = self.result_type(dn)
                pr = self.parse_typed(rt, r["result"], dn)
                if pr:
                    entered[k] = pr
                    rtype_of[k] = rt
        info = {r["id"]: r for r in erows}
        ent_wave = {r["id"]: r["wave"] for r in erows if r["wave"]}
        by_bib: dict = {}
        for r in erows:
            by_bib.setdefault(r["bib"], []).append(r)
        waves = self.store.waves(eid)
        wmeta = {w["name"]: w for w in waves}
        wave_order = {w["name"]: i for i, w in enumerate(waves)}
        wave_start = {w["name"]: parse_db(w["start_time"]) for w in waves if w.get("start_time")}
        wave_end = {w["name"]: parse_db(w["finished_at"]) for w in waves if w.get("finished_at")}
        ev_start = parse_db(ev["start_time"]) if ev.get("start_time") else None
        fin_dev = ev.get("finish_device") or ""
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

        marks = []                    # (точка, id строки, время)
        lost = []
        for m in self.store.manual_list(eid):
            if not m["bib"]:
                res["manual_pending"] += 1
                continue
            cands = by_bib.get(m["bib"]) or []
            if not cands:
                lost.append(m["bib"])
                continue
            ts = parse_db(m["ts"])
            w = m.get("wave") or None
            row_ = next((c for c in cands if c["wave"] and c["wave"] == w), None) or cands[0]
            k = row_["id"]
            if k not in ent_wave and waves:
                w2 = w or wave_of_ts(ts)
                if w2:
                    ent_wave[k] = w2           # участник без заранее заданного забега: по отметке судьи
            marks.append((m["device"], k, ts))
        marks.sort(key=lambda x: x[2])

        def start_of(k: int) -> Optional[dt.datetime]:
            w = ent_wave.get(k)
            if w and w in wave_start:
                return wave_start[w]
            if w and waves:
                return None
            return ev_start

        first: dict = {}
        for device, k, ts in marks:
            st = start_of(k)
            if st is None or ts < st:
                continue
            w = ent_wave.get(k)
            if w in wave_end and ts > wave_end[w] + dt.timedelta(seconds=2):
                continue                          # забег уже закрыт
            first.setdefault(k, {}).setdefault(device, ts)
        res["devices"] = sorted({d for per in first.values() for d in per})

        def secs(k, d):
            s = (first[k][d] - start_of(k)).total_seconds()
            return math.ceil(round(s * 10, 6)) / 10.0     # ручной хронометраж: округление вверх до 0,1 с

        def row(k):
            per = first.get(k, {})
            w = ent_wave.get(k, "")
            meta = wmeta.get(w, {})
            inf = info.get(k, {})
            return {"id": k, "bib": inf.get("bib") or "",
                    "wave": w, "category": inf.get("category") or meta.get("category") or "",
                    "distance": edist.get(k) or meta.get("distance") or "",
                    "rt": self.result_type(edist.get(k) or meta.get("distance")), "sex": inf.get("sex") or "",
                    "done_rank": inf.get("done_rank") or "",
                    "name": inf.get("name") or "", "birth_year": inf.get("birth_year") or "",
                    "team": inf.get("team") or "", "coach": inf.get("coach") or "",
                    "points": inf.get("points"), "members": inf.get("members") or "", "rank": inf.get("rank") or "",
                    "sw": (inf.get("detail") or {}).get("t"), "attempts": (inf.get("detail") or {}).get("a"),
                    "splits": {d: self.fmt_elapsed(secs(k, d)) for d in per}}

        def fin_sec(k):
            return entered[k][0] if k in entered else secs(k, fin_dev)

        finished = [k for k in first if fin_dev in first[k] and k not in entered and k not in status_of] + list(entered)
        finished.sort(key=lambda k: (wave_order.get(ent_wave.get(k, ""), -1), fin_sec(k)))
        place_by_wave: dict = {}
        prev_by_wave: dict = {}
        for k in finished:
            sec = fin_sec(k)
            w = ent_wave.get(k, "")
            if wmeta.get(w, {}).get("distance") is None or wmeta.get(w, {}).get("distance") == "":
                w = w + "\x00" + (edist.get(k) or "")        # смешанный «общий список»: места отдельно по дисциплинам
            place_by_wave[w] = place_by_wave.get(w, 0) + 1
            r = row(k)
            if k in entered:
                txt = entered[k][1]
                pv = prev_by_wave.get(w)
                place = pv[1] if pv and pv[0] == txt else place_by_wave[w]   # одинаковый результат — одно место
                ra = info.get(k, {}).get("result_at")
                r.update(place=place, time=self.fmt_elapsed(sec), result=txt, seconds=round(sec, 3),
                         finish_at=None, finish_epoch_ms=None, entered=True,
                         entered_epoch_ms=self._epoch_ms(parse_db(ra)) if ra else None)
                if rtype_of.get(k, "time") != "time":    # прыжки, метания, многоборья: больше — лучше
                    r.update(time=txt, seconds=None, rtype=rtype_of[k], value=round(-sec, 2))
            else:
                txt = self.fmt_result(sec)
                place = place_by_wave[w]
                r.update(place=place, time=self.fmt_elapsed(sec), result=txt,
                         seconds=round(sec, 3), finish_at=fmt_db(first[k][fin_dev]),
                         finish_epoch_ms=self._epoch_ms(first[k][fin_dev]))
            prev_by_wave[w] = (txt, place)
            # выполненный разряд: по нормам ЕВСК; вписанный секретарём — главнее
            if k in entered:
                val = entered[k][0] if rtype_of.get(k, "time") == "time" else -entered[k][0]
                hand = bool(r.get("sw")) or (ev.get("timing") or "") in ("manual", "judge")
            else:
                val, hand = sec, True
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
        res["not_seen"] = [{"id": r["id"], "bib": r["bib"],
                            "wave": r["wave"] or "", "name": r["name"] or "", "birth_year": r["birth_year"] or "",
                            "team": r["team"] or "", "coach": r.get("coach") or "", "members": r.get("members") or "",
                            "rank": r.get("rank") or "", "sw": (r.get("detail") or {}).get("t"), "attempts": (r.get("detail") or {}).get("a"),
                            "category": r["category"] or wmeta.get(r["wave"] or "", {}).get("category") or "",
                            "distance": edist.get(r["id"]) or wmeta.get(r["wave"] or "", {}).get("distance") or "",
                            "rt": self.result_type(edist.get(r["id"]) or wmeta.get(r["wave"] or "", {}).get("distance")),
                            "sex": r.get("sex") or "", "done_rank": r.get("done_rank") or "",
                            **({"status": status_of[r["id"]]} if r["id"] in status_of else {})}
                           for r in erows if (r["id"] not in first or r["id"] in status_of) and r["id"] not in entered]

        # ---- предупреждения
        A = res["alerts"]
        if not fin_dev and not entered:
            A.append({"level": "warn", "text": "Не выбрана точка финиша — результаты не считаются"})
        if res["manual_pending"]:
            A.append({"level": "warn", "text": f"Отсечек судьи без номера: {res['manual_pending']} — впишите номера"})
        if lost:
            A.append({"level": "warn", "text": f"Номера из отсечек судьи нет в списке участников: {', '.join(sorted(set(lost))[:10])}"})
        dup_bib = {}
        for m in self.store.manual_list(eid):
            if m["bib"] and m["device"] == fin_dev:
                dup_bib[(m["bib"], m.get("wave") or "")] = dup_bib.get((m["bib"], m.get("wave") or ""), 0) + 1
        twice = [b for (b, _), n in dup_bib.items() if n > 1]
        if twice:
            A.append({"level": "warn", "text": f"Номер вписан судьёй дважды: {', '.join(sorted(set(twice))[:10])}"})
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

#### `renderStart` — `hub/protocol.html` строки 494–500

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

#### `addTabToCart` — `hub/protocol.html` строки 481–493

```js
async function addTabToCart(){
  const start=isStartView(), it=currentItem(start), tab=tabsFor(start).find(t=>t.id===TAB)||{label:"Все участники"};
  const label=`${start?"Старт":"Итоги"}: ${DIST||"все дисциплины"} — ${tab.label}${start?(it.mode==="list"?" · общий список":" · по забегам"):""}`;
  const n=sheetsFor(it).length;
  // 6.0: корзина общая для всех секретарей — лежит на сервере (ui_state); дубли отсекает сервер
  try{
    const r=await fetch(`/api/events/${encodeURIComponent(eid)}/ui`,{method:"POST",headers:{"X-Requested-With":"timing-hub","Content-Type":"application/json"},
      body:JSON.stringify({key:"cart",op:"add",item:Object.assign({label},it)})});
    const d=await r.json(); if(!r.ok) throw new Error(d.error||r.status);
    try{ parent.postMessage({ss:"cart"},location.origin); }catch(e){}
    $("cartMsg").textContent=d.added?`В корзине: «${tab.label}» — ${n} ${n===1?"лист":n<5?"листа":"листов"}`:"Эта вкладка уже в корзине";
  }catch(e){ $("cartMsg").textContent="Не удалось добавить в корзину: "+e.message; }
}
```

#### `buildFinal` — `hub/protocol.html` строки 530–633

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
  const dnf=$("showDnf").checked, fin=ev.finish_device||"JUDGE";
  const anyName=R.finished.concat(R.on_course,R.not_seen).some(x=>x.name), anyYear=R.finished.some(x=>x.birth_year)||R.not_seen.some(x=>x.birth_year);
  const anyTeam=!tf&&(R.finished.some(x=>x.team)||R.not_seen.some(x=>x.team)), hasHeats=ev.waves.length>0;
  const anyRank=R.finished.some(x=>x.rank)||R.not_seen.some(x=>x.rank);
  // 5.2: в итоговом протоколе — только официальный результат; показания секундомеров остаются в базе и на шаге 4
  const anySw=false, anyAtt=R.finished.some(x=>x.attempts&&x.attempts.length);
  const attTxt=x=>(x.attempts||[]).map(v=>v||"–").join(" · "), swTxt=x=>(x.sw||[]).map(v=>v||"–").join(" / ");
  const man=x=>(x.manual||[]).includes(fin);
  const allManual=R.finished.length&&R.finished.every(man), someManual=R.finished.some(man);
  const starts=ev.waves.filter(w=>w.start_time).map(w=>w.start_time.slice(11,16));
  const startTxt=ev.start_clock||(starts.length?starts[0]:(ev.start_time?ev.start_time.slice(11,16):""));

  const head=(placeLbl,withHeat)=>`<thead><tr><th style="width:42px">${placeLbl}</th><th style="width:52px">Нагр. №</th>
    ${anyName?'<th>Фамилия, имя</th>':''}${anyYear?'<th style="width:46px">Год рожд.</th>':''}${anyRank?'<th style="width:46px">Разряд</th>':''}${anyTeam?'<th>Команда</th>':''}${coachOn?'<th>Тренер</th>':''}
    ${withHeat?'<th style="width:70px">Забег</th>':''}
    ${anySw?'<th>Секундомеры</th>':''}${anyAtt?'<th>Попытки</th>':''}<th style="width:78px">Результат</th>${anyDone?'<th style="width:56px">Вып. разряд</th>':''}${anyPts?'<th style="width:46px">Очки</th>':''}<th style="width:46px">Прим.</th></tr></thead>`;
  // техника: на каждое место — все шесть попыток, чтобы был виден ход борьбы
  const techHead=withHeat=>`<thead><tr><th rowspan="2" style="width:42px">Место</th><th rowspan="2" style="width:52px">Нагр. №</th><th rowspan="2">Фамилия, имя</th><th rowspan="2" style="width:46px">Год рожд.</th>${anyRank?'<th rowspan="2" style="width:46px">Разряд</th>':''}${anyTeam?'<th rowspan="2">Команда</th>':''}${coachOn?'<th rowspan="2">Тренер</th>':''}<th colspan="6" class="sub" style="text-align:center">Попытки</th><th rowspan="2" style="width:84px">Лучший результат</th>${anyDone?'<th rowspan="2" style="width:56px">Вып. разряд</th>':''}</tr><tr>${[1,2,3,4,5,6].map(i=>`<th class="sub">Попытка ${i}</th>`).join("")}</tr></thead>`;
  const techTr=(x,place,res)=>`<tr${typeof place==="number"&&place>=1&&place<=3?` class="pl${place}"`:""}><td class="c"><b>${place}</b></td><td class="c">${esc(x.bib)}</td><td>${esc(x.name)}</td><td class="c">${esc(x.birth_year)}</td>${anyRank?`<td class="c">${esc(x.rank||"")}</td>`:''}${anyTeam?`<td>${esc(x.team)}</td>`:''}${coachOn?`<td>${esc(x.coach||"")}</td>`:''}${[0,1,2,3,4,5].map(i=>{const v=(x.attempts||[])[i]||""; return `<td class="c cellv${v&&res&&String(v).replace(",",".")===String(res).replace(",",".")?" bestv":""}">${esc(v)}</td>`;}).join("")}<td class="c"><b>${esc(res)}</b></td>${anyDone?`<td class="c">${esc(x.done_rank||"")}</td>`:''}</tr>`;
  const techOutRows=(list)=>list.map(x=>`<tr><td class="c">—</td><td class="c">${esc(x.bib)}</td><td>${esc(x.name)}</td><td class="c">${esc(x.birth_year)}</td>${anyRank?`<td class="c">${esc(x.rank||"")}</td>`:''}${anyTeam?`<td>${esc(x.team)}</td>`:''}${coachOn?`<td></td>`:''}<td class="c" colspan="6">${esc((x.attempts||[]).map(v=>v||"–").join(" · "))}</td><td class="c"><b>${esc(x.status||((x.attempts||[]).some(Boolean)?"NM":"DNS"))}</b></td>${anyDone?'<td></td>':''}</tr>`).join("");
  const tr=(x,place,withHeat,res,note)=>`<tr${typeof place==="number"&&place>=1&&place<=3?` class="pl${place}"`:""}><td class="c"><b>${place}</b></td><td class="c">${esc(x.bib)}</td>
    ${anyName?`<td>${esc(x.name)}${mem(x)}</td>`:''}${anyYear?`<td class="c">${esc(x.birth_year)}</td>`:''}${anyRank?`<td class="c">${esc(x.rank||"")}</td>`:''}${anyTeam?`<td>${esc(x.team)}</td>`:''}${coachOn?`<td>${esc(x.coach||"")}</td>`:''}
    ${withHeat?`<td class="c">${esc((x.wave||"").replace(/^Забег\s*/,""))}${x.place&&withHeat?` <small>(${x.place})</small>`:""}</td>`:''}
    ${anySw?`<td class="c" style="font-size:11px">${esc(swTxt(x))}</td>`:''}${anyAtt?`<td class="c" style="font-size:11px">${esc(attTxt(x))}</td>`:''}<td class="r"><b>${esc(res)}</b></td>${anyDone?`<td class="c">${esc(x.done_rank||"")}</td>`:''}${anyPts?`<td class="c">${esc(fmtPts(x.points))}</td>`:''}<td class="c">${note}</td></tr>`;
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

#### `render` — `hub/protocol.html` строки 519–528

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

#### `renderCart` — `hub/protocol.html` строки 502–513

```js
async function renderCart(){
  if(!SL){ $("sheet").innerHTML='<div class="empty">Загрузка…</div>'; loadStart(); return; }
  drawTabs(null);
  let items=[];
  try{ const r=await fetch(`/api/events/${encodeURIComponent(eid)}/ui`,{headers:{"X-Requested-With":"timing-hub"}}); const d=await r.json(); items=Array.isArray(d.state&&d.state.cart.value)?d.state.cart.value:[]; }catch(e){}
  if(QIDS.length) items=items.filter(it=>QIDS.includes(String(it.id)));
  const secs=[];
  items.forEach(it=>{ DIST=it.dist||""; if(it.type==="final"&&!R) return; sheetsFor(it).forEach(r=>{ if(!r.empty) secs.push(r); }); });
  DIST="";
  if(!secs.length){ $("sheet").innerHTML='<div class="empty"><b>Корзина печати пуста</b>Откройте «Протоколы → Мастер», выберите вкладку и нажмите «Добавить текущую вкладку в корзину печати».</div>'; return; }
  showSheets(secs);
}
```

#### `syncStartCtl` — `hub/protocol.html` строки 514–517

```js
function syncStartCtl(){
  const isStart=isStartView(); const list=$("smode").value==="list";
  $("smode").classList.toggle("hide",!isStart); $("orient").classList.toggle("hide",!(isStart&&list));
}
```

### 4.3 Корзина печати — `hub/ui.html`

Сборка листов галочками в массив корзины (`cartAdd` → `localStorage["ss.cart.<id события>"]`), список, печать пакета, публикация — `hub/ui.html` строки 1651–1708

```js
/* ---------- корзина печати: листы из мастера и из «Регистрации» → один документ, выгрузка в сеть ---------- */
const sexOfE = (e) => { const x = String(e.sex||"").toUpperCase(); if (x==="М"||x==="Ж") return x; const c = String(e.category||"").toLowerCase();
  if (/юнош|мальч|мужч|^муж/.test(c)) return "М"; if (/девуш|девоч|женщ|^жен/.test(c)) return "Ж"; return ""; };
// 6.0: корзина печати и состояние Мастера общие для всех секретарей — лежат в базе (ui_state), в браузере не хранятся.
// Добавление/удаление/отметка — операции на сервере: два секретаря, работающие одновременно, не затирают друг друга.
const UI = {ev: null, cart: [], cartRev: -1};
const cartGet = () => UI.ev === curId ? UI.cart : [];
async function cartOp(body){
  if (curId == null) return null;
  try{ const r = await api(`/api/events/${curId}/ui`, Object.assign({key: "cart"}, body));
    UI.ev = curId; UI.cart = r.value; UI.cartRev = r.rev; renderCart(); return r; }
  catch(err){ toast("Корзина не сохранилась: " + err.message); return null; }
}
async function cartAdd(items){ let n = 0; for (const it of items) { const r = await cartOp({op: "add", item: it}); if (r && r.added) n++; } return n; }
// опрос общего состояния раз в 3 с и сразу по сигналу из встроенного протокола; first — первое открытие Мастера
async function uiSync(first){
  if (curId == null) return;
  const id = curId, r = await api(`/api/events/${id}/ui`); if (id !== curId) return;
  if (UI.ev !== id) { UI.ev = id; UI.cart = []; UI.cartRev = -1; }
  const c = r.state.cart; if (c.rev !== UI.cartRev) { UI.cart = Array.isArray(c.value) ? c.value : []; UI.cartRev = c.rev; renderCart(); }
  wzp.remote(r.state.wizard, first, id);
}
window.addEventListener("message", (e) => { if (e.origin === location.origin && e.data && e.data.ss === "cart") uiSync().catch(() => {}); });
function renderCart(){
  const a = cartGet(), on = a.filter(x => x.on).length;
  const html = `<h3>🛒 Корзина печати <span class="small muted">${a.length ? "— листов: " + a.length + ", к печати: " + on : ""}</span></h3>
    ${a.map(it => `<div class="ci"><label><input type="checkbox" data-cs="${esc(it.id)}" ${it.on ? "checked" : ""}> <span>${esc(it.label)}</span></label><button data-rm="${esc(it.id)}" aria-label="Убрать из корзины: ${esc(it.label)}">✕ Убрать</button></div>`).join("")
      || '<p class="small muted" style="margin:0">Корзина пуста. Над протоколом выберите вкладку (все, мальчики, девочки или категорию) и нажмите «🛒 Добавить текущую вкладку в корзину печати».</p>'}
    <div class="row"><button class="bigprint" data-cart="print" ${on ? "" : "disabled"}>🖨️ Печать пакета</button><button data-cart="publish" ${on ? "" : "disabled"}>🔐 Открыть тренерам в кабинете</button><button data-cart="clear" ${a.length ? "" : "disabled"}>Очистить корзину</button></div>`;
  document.querySelectorAll(".cartmount").forEach(m => { m.innerHTML = html; });
}
document.addEventListener("click", async (e) => {
  const rm = e.target.closest("[data-rm]"); if (rm) { cartOp({op: "remove", id: rm.dataset.rm}); return; }
  const b = e.target.closest("[data-cart]"); if (!b) return;
  if (b.dataset.cart === "clear") { if (confirm("Очистить корзину печати?")) cartOp({op: "clear"}); return; }
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
    if (!confirm(`Открыть тренерам в личном кабинете: ${what}?\n\nПротокол увидят только вошедшие тренеры, судьи и организаторы — в открытый доступ он не попадает. Закрыть его можно в любой момент.`)) return;
    try{
      const r = await api(`/api/events/${curId}/publish`, Object.assign({}, start ? {start: true} : {}, res ? {results: true} : {}));
      toast("Открыто тренерам в личном кабинете"); alert("Протокол доступен после входа в личный кабинет тренера:\n" + (res ? r.results_url : r.start_url));
      loadEvents._sig = null; loadEvents();
    }catch(err){ toast("Ошибка: " + err.message); }
  }
});
document.addEventListener("change", (e) => {
  const c = e.target.closest("[data-cs]"); if (!c) return;
  cartOp({op: "toggle", id: c.dataset.cs, on: c.checked});
});
```

### 4.4 Мастер протоколов: переключение шагов, ветки Бег/Техника, ввод результатов — `hub/ui.html`

#### `wzp` (IIFE: состояние `W`, `go(n)`, `render()`, `step1…step5`, `gen`, `reset`, `saveRows`, обработчики) — `hub/ui.html` строки 1710–2153

```js
const wzp = (() => {
  const W = {disc: "", step: 1, ages: [], sex: "", lanes: 8, regs: [], sl: null, ev: null};
  // границы возрастных групп — только из справочника seed/disciplines.json (ages[].min/max), в коде их нет
  const ageBy = (id) => (DISC.ages || []).find(a => a.id === id);
  // названия шагов одинаковы для бега и техники; различия — в уточнениях (подписях) шагов 3 и 4
  const STEP_T = ["Дисциплина и фильтр", "Нагрудные номера", "Стартовый протокол", "Ввод результатов", "Итоговый протокол"];
  const STEP_NOTE = {
    run:  {3: "забеги, 3 секундомера, лист книжный", 4: "на финише"},
    tech: {3: "общий список, 6 попыток, лист альбомный", 4: "с сектора"}};
  const stepHead = (n, k) => `<h2>Шаг ${n}. ${STEP_T[n - 1]}${STEP_NOTE[k][n] ? ` <small class="muted" style="font:400 15px var(--body)">— ${STEP_NOTE[k][n]}</small>` : ""}</h2>`;
  // автоопределение: попытки или расстояние/высота — техника; время — бег; прочее (очки) ведём по беговой ветке
  const kindOf = (name) => { const d = discBy(name); if (!d) return "run"; if (d.attempts || d.result === "distance" || d.result === "height") return "tech"; return "run"; };
  const isPoints = (name) => { const d = discBy(name); return !!d && d.result === "points"; };
  const ev = () => curEvent();
  const kind = () => kindOf(W.disc);
  const sexWord = (x) => x === "М" ? "мальчики / юноши / мужчины" : x === "Ж" ? "девочки / девушки / женщины" : "все";
  const ageOk = (r) => { if (!W.ages.length) return true; const e = ev(), y = e && e.date ? +e.date.slice(0, 4) : new Date().getFullYear(); const age = y - (+r.birth_year || 0);
    return W.ages.some(id => { const a = ageBy(id); return a && age >= a.min && age <= a.max; }); };
  const regsIn = () => W.regs.filter(r => r.distance === W.disc && r.status === "approved" && (!W.sex || String(r.sex||"").toUpperCase() === W.sex) && ageOk(r));
  const entriesIn = () => {            // участники дисциплины из стартового списка с учётом фильтров
    const out = []; if (!W.sl) return out;
    W.sl.heats.concat([{name: "", distance: "", entries: W.sl.no_heat || []}]).forEach(h => h.entries.forEach(e => {
      if ((e.distance || h.distance) !== W.disc) return;
      if (W.sex && sexOfE(e) !== W.sex) return;
      if (!ageOk({birth_year: e.birth_year})) return;
      out.push(Object.assign({}, e, {_heat: h.name, distance: e.distance || h.distance})); }));
    return out;
  };
  const myHeats = () => W.sl ? W.sl.heats.filter(h => h.distance === W.disc || h.entries.some(e => e.distance === W.disc)) : [];
  async function load(){
    const e0 = ev(); if (!e0) return;
    // судье на секторе заявки (личные данные) не нужны и не выдаются — работает по стартовому списку
    try{ const [r, sl, rs] = await Promise.all([api(`/api/events/${e0.id}/regs`), api(`/api/events/${e0.id}/startlist`), api(`/api/events/${e0.id}/results`).catch(() => null)]);
      W.regs = r.regs; W.sl = sl; W.auto = {}; if (rs) rs.finished.forEach(x => { W.auto[x.bib + "|" + (x.distance || "")] = x.done_rank_auto || ""; }); }catch(err){ console.warn(err); }
  }
  async function open(){
    const e0 = ev(); if (!e0) { $("wzpBody").innerHTML = '<p class="muted">Выберите соревнование в меню вверху.</p>'; return; }
    $("wzpEv").textContent = [e0.name, e0.date ? e0.date.split("-").reverse().join(".") : "", e0.place].filter(Boolean).join(" · ");
    await loadDisc();
    if (W.evId !== e0.id) {
      // 6.0: активная дисциплина, шаг и фильтры — общие для всех секретарей, лежат в базе (таблица ui_state), а не в браузере
      W.evId = e0.id; W.disc = ""; W.step = 1; W.ages = []; W.sex = ""; W.uiRev = -1; W.lanes = e0.reg_lanes || 8;
      try{ await uiSync(true); }catch(x){ console.warn(x); }
      if (W.forceStep) { W.step = W.forceStep; W.forceStep = 0; save(); }
    }
    await load();
    const names = [...new Set([...distNames(e0), ...W.regs.map(r => r.distance), ...W.sl.heats.map(h => h.distance)].filter(Boolean))];
    $("wzpDisc").innerHTML = names.map(n => `<option ${n === W.disc ? "selected" : ""}>${esc(n)}</option>`).join("") || '<option value="">нет дисциплин</option>';
    if (!names.includes(W.disc)) W.disc = names[0] || "";
    $("wzpDisc").value = W.disc; render(); renderCart();
  }
  // запись общего состояния на сервер; ответ с номером версии запоминаем, чтобы собственное эхо не принимать за чужое
  function save(){
    if (W.evId == null) return;
    api(`/api/events/${W.evId}/ui`, {key: "wizard", cid: CID, value: {disc: W.disc, step: W.step, sex: W.sex, ages: W.ages}})
      .then(r => { W.uiRev = Math.max(W.uiRev ?? -1, r.rev); }).catch(err => console.warn("состояние Мастера не записано", err)); }
  const CID = Math.random().toString(36).slice(2, 12);
  const busyEditing = () => { const a = document.activeElement;
    return W.bibDirty || !!document.querySelector("#wzpRows tr.dirty") || (a && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName) && $("tab-wizard").contains(a)); };
  // чужое изменение (другой секретарь переключил дисциплину, шаг или фильтр): принимаем, но не выбиваем у человека ввод из-под рук
  function remote(w, first, evId){
    if (evId !== W.evId) return;          // ответ про другое соревнование
    if (first && w && w.rev > 0) { const v = w.value || {};     // первое открытие: берём то, на чём остановились другие, без уведомлений
      Object.assign(W, {disc: v.disc || "", step: v.step || 1, sex: v.sex === "М" || v.sex === "Ж" ? v.sex : "", ages: Array.isArray(v.ages) ? v.ages : []}); W.uiRev = w.rev; return; }
    if (first) { W.uiRev = w ? w.rev : 0; return; }
    if (!w || W.evId == null || w.rev <= (W.uiRev ?? -1)) { if (W.deferred && !busyEditing()) { W.deferred = false; applyDraw(); } return; }
    W.uiRev = w.rev;
    const v = w.value || {}; if (w.cid === CID || !v.disc) return;
    const same = v.disc === W.disc && v.step === W.step && (v.sex || "") === W.sex && JSON.stringify(v.ages || []) === JSON.stringify(W.ages);
    if (same) return;
    Object.assign(W, {disc: v.disc, step: v.step || 1, sex: v.sex || "", ages: v.ages || []});
    toast(`${w.who || "Другой секретарь"}: ${W.disc} · шаг ${W.step}`);
    if (document.body.dataset.view !== "wizard") return;
    if (busyEditing()) { W.deferred = true; return; }
    applyDraw();
  }
  function applyDraw(){ const sel = $("wzpDisc"); if (sel && [...sel.options].some(o => o.value === W.disc)) sel.value = W.disc; render(); }
  function go(n){
    if (W.step === 2 && W.bibDirty && !confirm("Нагрудные номера изменены, но не сохранены. Уйти с шага без сохранения?")) return;
    W.bibDirty = false; W.deferred = false; W.step = Math.max(1, Math.min(5, n)); save(); render();
    if (W.step === 2 || W.step === 3) bgReload(W.step); }
  // на шагах 2 и 3 заявки и список перезагружаем в фоне (их мог изменить другой секретарь); экран перерисовываем, только если человек ничего не вводит
  async function bgReload(step){ await load(); if (W.step === step && !busyEditing() && document.body.dataset.view === "wizard") render(); }
  // перерисовка тела Мастера без прыжков: высота держится до конца отрисовки, прокрутка не трогается, фокус возвращается в ту же ячейку
  const focusKey = () => { const a = document.activeElement, b = $("wzpBody"); if (!a || !b.contains(a) || a === b) return null;
    const tr = a.closest("tr[data-bib]"); return {id: a.id || "", bib: tr ? tr.dataset.bib : "", cls: a.className || "", i: a.dataset.i ?? "", pos: a.selectionStart}; };
  const restoreFocus = (k) => { if (!k) return; const b = $("wzpBody"); let el = null;
    if (k.id) el = document.getElementById(k.id);
    else if (k.bib) { const tr = [...b.querySelectorAll("tr[data-bib]")].find(x => x.dataset.bib === k.bib);
      if (tr) el = [...tr.querySelectorAll("input,select")].find(x => x.className === k.cls && (x.dataset.i ?? "") === k.i); }
    if (!el) return; el.focus({preventScroll: true}); if (k.pos != null && el.setSelectionRange) try{ el.setSelectionRange(k.pos, k.pos); }catch(x){} };
  function render(){
    const fk = focusKey(), bd = $("wzpBody"); bd.style.minHeight = bd.offsetHeight + "px";
    draw(); restoreFocus(fk); markLane();
    requestAnimationFrame(() => { bd.style.minHeight = ""; });
  }
  function draw(){
    const k = kind(), t = STEP_T;
    $("wzpAll").classList.toggle("hide", W.step !== 3);      // кнопка «ВСЕ протоколы» — рядом со списком дисциплин, на шаге 3
    if (W.step !== 3) $("wzpAllOut").classList.add("hide");
    $("wzpKind").className = "wzp-kind " + k;
    $("wzpKind").textContent = !W.disc ? "" : k === "tech" ? "Техника" : "Бег" + (isPoints(W.disc) ? " (очки)" : "");
    $("wzpSteps").innerHTML = t.map((x, i) => `<button type="button" data-s="${i + 1}" class="${W.step === i + 1 ? "on" : W.step > i + 1 ? "done" : ""}" role="tab"><b>${i + 1}</b>${esc(x)}</button>`).join("");
    const body = $("wzpBody");
    if (!W.disc) { body.innerHTML = '<p class="muted">В этом соревновании пока нет дисциплин. Добавьте их на этапе «Подготовка» и примите заявки.</p>'; return; }
    ({1: step1, 2: step2, 3: step3, 4: step4, 5: step5})[W.step](body, k);
  }
  const nav = (prev, nextTxt) => `<div class="wzp-nav">${prev ? '<button type="button" data-g="-1">← Назад</button>' : ""}${nextTxt ? `<button type="button" class="primary" data-g="1">${nextTxt} →</button>` : ""}</div>`;
  // вкладки «Все / Мальчики / Девочки» и возрастные группы — просто быстрый просмотр состава: проходить шаг ими не нужно
  function filterBar(){
    const cnt = (x) => W.regs.filter(r => r.distance === W.disc && r.status === "approved" && (!x || String(r.sex||"").toUpperCase() === x) && ageOk(r)).length;
    const tab = (v, t) => `<button type="button" role="tab" class="ftab${W.sex === v ? " on" : ""}" aria-selected="${W.sex === v}" data-sexf="${v}">${t} <i>${cnt(v)}</i></button>`;
    const ages = (DISC.ages || []).map(a => `<button type="button" class="ftab age${W.ages.includes(a.id) ? " on" : ""}" aria-pressed="${W.ages.includes(a.id)}" data-agef="${esc(a.id)}">${esc(a.name)}</button>`).join("");
    return `<div class="wzp-filter" role="tablist" aria-label="Состав дисциплины">${tab("", "Все")}${tab("М", "Мальчики")}${tab("Ж", "Девочки")}<span class="fsep" aria-hidden="true"></span>${ages}</div>`;
  }
  function step1(body, k){
    const all = W.regs.filter(r => r.distance === W.disc && r.status === "approved").length;
    const pend = W.regs.filter(r => r.distance === W.disc && r.status === "pending").length;
    body.innerHTML = `${stepHead(1, k)}
      <p style="margin:0"><b>Подтверждённых участников: ${all}</b> <span class="small muted">— все уже загружены по выбранной дисциплине${pend ? `; ещё ${pend} заявок ждут проверки на этапе «2. Регистрация»` : ""}</span></p>
      ${filterBar()}
      <p class="small muted" style="margin:0">Вкладки — только для просмотра состава (можно ничего не нажимать): без выбора в сетку идут все участники дисциплины.</p>
      ${nav(false, "К нагрудным номерам")}`;
  }
  function heatsTable(){
    const hs = myHeats();
    if (!hs.length) return '<p class="muted">Сетки по этой дисциплине пока нет.</p>';
    return `<div class="tbl"><table><thead><tr><th>Забег</th><th>Категория</th><th>Участников</th><th>Мальчиков</th><th>Девочек</th></tr></thead><tbody>${hs.map(h => {
      const es = h.entries.filter(e => (e.distance || h.distance) === W.disc);
      return `<tr><td><b>${esc(h.name)}</b></td><td>${esc(h.category || "")}</td><td>${es.length}</td><td>${es.filter(e => sexOfE(e) === "М").length}</td><td>${es.filter(e => sexOfE(e) === "Ж").length}</td></tr>`; }).join("")}</tbody></table></div>`;
  }
  // шаг 2: «Регистрация номеров» — судья вписывает нагрудный номер каждому подтверждённому участнику сам.
  // Автоматической выдачи номеров нет; в базу номера попадают только по кнопке «Сохранить нагрудные номера».
  const bibQ = () => `distance=${encodeURIComponent(W.disc)}&sex=${encodeURIComponent(W.sex)}&ages=${encodeURIComponent(W.ages.join(","))}`;
  async function loadBibs(){ W.bibs = await api(`/api/events/${ev().id}/bibs?${bibQ()}`); return W.bibs; }
  function step2(body, k){
    const pend = W.regs.filter(r => r.distance === W.disc && r.status === "pending").length;
    body.innerHTML = `${stepHead(2, k)}
      <p class="small muted" style="margin:0">${esc(W.disc)} · возраст: ${W.ages.length ? W.ages.map(a => (DISC.ages.find(x => x.id === a) || {}).name).join(", ") : "любой"} · пол: ${esc(sexWord(W.sex))}.
        Впишите нагрудный номер каждому участнику с клавиатуры (Enter — к следующему) и нажмите «Сохранить нагрудные номера». Номера можно менять в любой момент — вернитесь сюда, исправьте и сохраните снова: стартовый список, отметки и результаты переедут на новый номер.</p>
      <p class="small" style="margin:0"><b>Номер спортсмена, заявленного на несколько видов, один на все виды:</b> впишите его один раз — он запишется во все дисциплины.</p>
      ${pend ? `<div class="wzp-lock">⏳ Ещё ${pend} заявок ждут проверки во вкладке «Регистрация» — их здесь нет, пока их не подтвердить.</div>` : ""}
      ${filterBar()}
      <div id="bibBox"><p class="muted">Загружаю участников…</p></div>
      <div class="row wzp-ctl bibctl"><button class="primary big" type="button" id="bibSave" disabled>💾 Сохранить нагрудные номера</button>
        <button class="danger big redbtn" type="button" id="bibClear" disabled>❌ Очистить все номера дисциплины</button>
        <span class="wzp-sync" id="bibSync" role="status" aria-live="polite"></span></div>
      ${nav(true, "К стартовому протоколу")}`;
    loadBibs().then(renderBibs).catch(err => { $("bibBox").innerHTML = `<p class="wzp-lock">Не удалось загрузить участников: ${esc(err.message)}</p>`; });
  }
  function renderBibs(){
    const d = W.bibs, box = $("bibBox"); if (!box || !d) return;
    if (!d.rows.length) { box.innerHTML = '<div class="card empty">Подтверждённых участников по фильтру шага 1 нет. Подтвердите заявки во вкладке «Регистрация» или измените фильтр.</div>'; return; }
    let last = null;
    const rows = d.rows.map((r, i) => { const c = r.category || "без категории", hd = c !== last ? `<tr class="wzp-cat"><td colspan="7">${esc(c)}</td></tr>` : ""; last = c;
      const also = r.also || [], other = also.map(a => a.distance).join(", ");
      const from = r.inherited ? (also.find(a => a.bib && a.bib === r.bib) || {}).distance : "";
      const alsoHtml = also.length ? `<div class="small muted">также: ${esc(other)}</div>` : "";
      const note = r.mismatch ? `<div class="small bibwarn">В других видах номер другой (${esc(also.map(a => a.distance + " — " + (a.bib || "без номера")).join("; "))}) — при сохранении выровняется</div>`
        : r.inherited ? `<div class="small muted">Номер подставлен${from ? " из «" + esc(from) + "»" : " из другой дисциплины"}</div>` : "";
      return hd + `<tr data-ids="${r.ids.join(",")}" data-orig="${esc(r.bib)}"${r.mismatch || r.inherited ? ' data-pending="1"' : ""}${r.mismatch ? ' class="mismatch"' : ""}>
        <td class="n">${i + 1}</td>
        <td><input class="bibin2" value="${esc(r.bib)}" maxlength="10" inputmode="numeric" autocomplete="off" aria-label="Нагрудный номер: ${esc(r.name)}" placeholder="№"></td>
        <td><b>${esc(r.name)}</b>${r.members ? `<div class="small muted">${esc(r.members)}</div>` : ""}${alsoHtml}${note}</td><td>${esc(r.birth_year)}</td><td class="small">${esc(r.rank)}</td><td class="small">${esc(r.team)}</td>
        <td class="small muted">${r.has_result ? "есть результат" : r.in_grid ? "в сетке" : ""}</td></tr>`; }).join("");
    box.innerHTML = `<p class="small" id="bibStat"></p>
      <div class="tbl"><table class="wzp-grid bibtbl"><thead><tr><th>№ п/п</th><th>Нагрудный номер</th><th>Фамилия, имя</th><th>Год рожд.</th><th>Разряд</th><th>Команда</th><th></th></tr></thead><tbody id="bibRows">${rows}</tbody></table></div>`;
    bibCheck();
  }
  // живая проверка: пустые, повторы, несохранённые — до нажатия кнопки
  function bibCheck(){
    const trs = [...document.querySelectorAll("#bibRows tr[data-ids]")]; if (!trs.length) return;
    const cnt = {}; trs.forEach(tr => { const v = tr.querySelector("input").value.trim(); if (v) cnt[v] = (cnt[v] || 0) + 1; });
    let empty = 0, dup = 0, dirty = 0, changed = 0; const mism = trs.filter(tr => tr.classList.contains("mismatch")).length;
    trs.forEach(tr => { const i = tr.querySelector("input"), v = i.value.trim();
      const isDup = v && cnt[v] > 1, isDirty = v !== tr.dataset.orig || tr.dataset.pending === "1";   // расхождение или подставленный номер тоже нужно сохранить
      i.classList.toggle("err", !!isDup); tr.classList.toggle("dirty", isDirty); tr.classList.toggle("nobib", !v);
      if (!v) empty++; if (isDup) dup++; if (isDirty) dirty++; if (v !== tr.dataset.orig) changed++; });
    $("bibStat").innerHTML = `Участников: <b>${trs.length}</b> · с номером: <b>${trs.length - empty}</b>${empty ? ` · <span class="bad">без номера: ${empty}</span>` : ""}${dup ? ` · <span class="bad">повторяются: ${dup}</span>` : ""}${mism ? ` · <span class="warn">разные номера в видах: ${mism}</span>` : ""}${dirty ? ` · <span class="warn">не сохранено: ${dirty}</span>` : ""}`;
    $("bibSave").disabled = !dirty || dup > 0;
    const bc = $("bibClear"); if (bc) bc.disabled = !(W.bibs && W.bibs.rows.some(r => r.bib));
    W.bibDirty = changed > 0;          // предупреждение при уходе — только если человек что-то изменил руками
  }
  // полная очистка номеров дисциплины: на сервере bib = NULL у всех её участников, поля на экране пустеют за один клик
  async function clearBibsAll(){
    const d = W.bibs, also = d && d.rows.some(r => r.also && r.also.length);
    if (!confirm("Вы уверены, что хотите ПОЛНОСТЬЮ стереть и очистить все нагрудные номера в этой дисциплине?"
        + (also ? "\n\nУ спортсменов, заявленных и на другие виды, номер один на все виды — он сотрётся и там, а их строки в сетках будут убраны." : "")
        + "\n\nСтартовый список этой дисциплины будет убран; формировать его придётся заново после ввода номеров.")) return;
    try{
      const r = await api(`/api/events/${ev().id}/clear-bibs`, {distance: W.disc});
      W.bibDirty = false; toast(`Номера очищены: заявок ${r.cleared}${r.also.length ? "; также в: " + r.also.join(", ") : ""}`);
      loadEvents._sig = null; await loadEvents(); await load(); render();
    }catch(err){ alert("Номера не очищены:\n" + err.message); }
  }
  async function saveBibs(){
    const rows = [...document.querySelectorAll("#bibRows tr.dirty")].map(tr => ({ids: tr.dataset.ids.split(",").map(Number), bib: tr.querySelector("input").value.trim()}));
    if (!rows.length) return;
    $("bibSave").disabled = true; const s = $("bibSync"); s.textContent = "Сохраняю…"; s.className = "wzp-sync busy";
    try{
      const res = await fetch(`/api/events/${ev().id}/bibs`, {method: "POST", headers: {"X-Requested-With": "timing-hub", "Content-Type": "application/json"}, body: JSON.stringify({rows})});
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        (j.errors || []).forEach(x => { const tr = document.querySelector(`#bibRows tr[data-ids="${x.ids.join(",")}"]`); if (tr) tr.querySelector("input").classList.add("err"); });
        s.textContent = (j.error || "Не сохранено") + (j.errors && j.errors.length ? ": " + j.errors.map(x => x.error).join("; ") : ""); s.className = "wzp-sync bad"; $("bibSave").disabled = false; return; }
      s.textContent = `Сохранено ${new Date().toLocaleTimeString("ru-RU")}: номеров ${j.saved}`; s.className = "wzp-sync ok";
      toast(`Нагрудные номера сохранены: ${j.saved}`);
      await loadBibs(); renderBibs(); await load(); loadEvents._sig = null; loadEvents();
    }catch(err){ s.textContent = "Нет связи с сервером — номера не сохранены, нажмите кнопку ещё раз"; s.className = "wzp-sync bad"; $("bibSave").disabled = false; }
  }
  // шаг 3: сетка и стартовый протокол на одном экране — ровно две кнопки управления сеткой, ниже бланк с вкладками групп
  function step3(body, k){
    const tech = k === "tech", n = regsIn().length, q = `kind=start&smode=${tech ? "list" : "heats"}&orient=${tech ? "landscape" : "portrait"}`;
    body.innerHTML = `${stepHead(3, k)}
      ${tech ? '<div class="wzp-lock">🔒 Техника: дорожек нет. Каждая категория — отдельный сквозной «Общий список» в порядке выполнения попыток; лист альбомный, 6 попыток и «Лучший результат».</div>'
        : `<p class="small muted" style="margin:0">Бег: посев по заявленному результату — сильнейшие в последнем забеге, на центральных дорожках. Лист книжный, графы «Сек. 1 | Сек. 2 | Сек. 3».</p>
           <label class="small">Дорожек на стадионе <input type="number" id="wzpLanes" min="1" max="50" value="${W.lanes}" style="width:80px"></label>`}
      <div id="bibWarn"></div>
      <div class="row wzp-ctl"><button class="primary" type="button" id="wzpGen" ${n ? "" : "disabled"}>${tech ? "⚡ Сформировать общий список" : "⚡ Сформировать забеги"}</button>
        <button class="danger" type="button" id="wzpReset" ${myHeats().length ? "" : "disabled"}>❌ Сбросить сетку / Удалить забеги</button>
        <span class="small muted">${n} подтверждённых участников по фильтру шага 1</span></div>
      ${myHeats().length ? `<div class="row xlsrow"><a class="btn xls" id="wzpXlsx" href="/api/events/${ev().id}/startlist.xlsx?${bibQ()}">📊 Выгрузить стартовый протокол в Excel (.xlsx)</a>
        <span class="small muted">${tech ? "Порядок выполнения, 6 попыток и «Лучший результат» — пустые графы для записи ручкой на секторе." : "Забег, дорожка и три пустые графы «Секундомер 1–3» — для записи времени ручкой на финише."}</span></div>` : ""}
      ${myHeats().length ? `<p class="small muted" style="margin:0">Над бланком — вкладки: «Все участники», «Мальчики», «Девочки» и каждая категория. Нужную вкладку можно сразу положить в корзину печати.</p>
        <iframe class="wzp-frame" src="${protoUrl(q, true)}" title="Предпросмотр стартового протокола"></iframe>
        <div class="row"><a class="btn" target="_blank" href="${protoUrl(q, false)}">Открыть для печати ↗</a></div>`
        : '<div class="card empty">Сетки по этой дисциплине пока нет — нажмите «⚡ Сформировать…».</div>'}
      ${nav(true, "К вводу результатов")}`;
    // без ручных номеров сетку не построить: показываем, сколько не хватает, и ведём на шаг 2
    // кнопка «Сформировать» доступна всегда, когда есть подтверждённые участники; нехватку номеров только показываем
    loadBibs().then(d => { const miss = d.total - d.with_bib, w = $("bibWarn"); if (!w) return;
      w.innerHTML = miss ? `<div class="wzp-lock">✍️ У ${miss} из ${d.total} участников нет нагрудного номера. <button type="button" class="sm" data-s="2">Вписать номера на шаге 2</button></div>` : ""; }).catch(() => {});
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
  // пакетная генерация: все дисциплины с одобренными заявками — за один клик; вид программы сервер определяет сам
  async function genAll(){
    const e0 = ev(); if (!e0) return;
    const n = W.regs.filter(r => r.status === "approved").length;
    if (!n) return toast("Нет подтверждённых заявок: сначала одобрите их на этапе «2. Регистрация»");
    if (!confirm(`Сформировать стартовые протоколы по ВСЕМ дисциплинам соревнования (подтверждённых заявок: ${n})?\n\nУже собранные сетки будут пересобраны с учётом новых участников; введённые результаты и номера сохранятся. Дисциплины, где не хватает нагрудных номеров или уже стоит время старта, будут пропущены — причины покажу ниже.`)) return;
    const btn = $("wzpAll"); btn.disabled = true; const old = btn.textContent; btn.textContent = "Формирую…";
    try{
      W.lanes = +($("wzpLanes") || {}).value || W.lanes;
      const r = await api(`/api/events/${e0.id}/heats-all`, {lanes: W.lanes});
      const out = $("wzpAllOut");
      out.innerHTML = `<b>Готово: сформировано дисциплин ${r.done.length} из ${r.disciplines}, участников ${r.entries}.</b>`
        + (r.done.length ? `<ul>${r.done.map(x => `<li>${esc(x.distance)} — ${x.mode === "list" ? "общий список (6 попыток)" : "забеги: " + x.heats}, участников ${x.entries}</li>`).join("")}</ul>` : "")
        + (r.skipped.length ? `<div class="wzp-lock">Пропущено:<ul>${r.skipped.map(x => `<li><b>${esc(x.distance)}</b>: ${esc(x.reason)}</li>`).join("")}</ul>Впишите недостающие номера на шаге 2 нужной дисциплины и нажмите кнопку ещё раз.</div>` : "");
      out.classList.remove("hide"); toast(`Сформировано: дисциплин ${r.done.length}, участников ${r.entries}`);
      loadEvents._sig = null; await loadEvents(); regLoaded = null; await load(); render();
    }catch(err){ toast("Ошибка: " + err.message); alert("Протоколы не сформированы:\n" + err.message); }
    finally{ btn.disabled = false; btn.textContent = old; }
  }
  async function reset(){
    const e0 = ev();
    if (!confirm(`Сбросить сетку дисциплины «${W.disc}»? Время старта будет обнулено, забеги удалены. Введённые результаты и номера сохранятся. После этого список можно сформировать заново — в него войдут все подтверждённые участники.`)) return;
    try{ const r = await api(`/api/events/${e0.id}/resetheats`, {distance: W.disc}); toast(`Сетка сброшена: забегов ${r.waves ?? 0}`); loadEvents._sig = null; await loadEvents(); regLoaded = null; await load(); render(); }
    catch(err){ toast("Ошибка: " + err.message); }
  }
  const protoUrl = (q, embed) => `/protocol?event=${ev().id}&dist=${encodeURIComponent(W.disc)}&sexf=${W.sex}&grp=${embed ? "&embed=1" : ""}&t=${Date.now()}&${q}`;
  const label = (pre) => `${pre}: ${W.disc}${W.sex ? " — " + (W.sex === "М" ? "мальчики" : "девочки") : ""}`;
  function step5(body, k){
    const tech = k === "tech", q = `kind=results&mode=overall`;
    body.innerHTML = `${stepHead(5, k)}
      <p class="small muted" style="margin:0">${tech ? "Горизонтальный лист: на каждое место видны все шесть попыток спортсмена и лучший результат." : "Вертикальный лист: места, результаты и выполненные разряды."}</p>
      <label class="small">Статус соревнований — от него зависит, какой разряд можно выполнить
        <select id="wzpLevel" style="max-width:420px">${[["mass","Муниципальные, массовые — до II разряда"],["region","Субъекта РФ (областные) — до I разряда"],["interregion","Межрегиональные — до КМС"],["dfo","Федерального округа — до МС"],["russia","Всероссийские — до МС"]].map(([v, t]) => `<option value="${v}" ${(ev().level || "region") === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>
      <fieldset class="pmode wzp-pub"><legend>Публикация</legend>
        <label><input type="checkbox" id="wzpPubG" ${ev().pub_regs ? "checked" : ""}> <b>Открытый список «прошли регистрацию»</b><span class="small muted"> — на странице соревнования без входа: только «Фамилия И.», возрастная группа и дисциплины одобренных заявок. Номеров, дорожек и данных рождения там нет</span></label>
        <label><input type="checkbox" id="wzpPubS" ${ev().pub_start ? "checked" : ""}> <b>Стартовый протокол — для тренеров</b><span class="small muted"> — только в личном кабинете тренера (нужен вход)</span></label>
        <label><input type="checkbox" id="wzpPubR" ${ev().pub_results ? "checked" : ""}> <b>Итоговый протокол — для тренеров</b><span class="small muted"> — только в личном кабинете тренера (нужен вход)</span></label>
        <span class="small muted">${ev().page_url ? `Страница соревнования: <a id="wzpPubLink" target="_blank" href="${esc(ev().page_url)}">${esc(ev().page_url)}</a>` : "Ссылка появится после первой публикации."}</span>
      </fieldset>
      <p class="small muted" style="margin:0">Закрытые протоколы для тренеров открываются в личном кабинете тренера; обработка персональных данных — по политике <a href="/privacy" target="_blank" rel="noopener">/privacy</a>.</p>
      <iframe class="wzp-frame" src="${protoUrl(q, true)}" title="Предпросмотр итогового протокола"></iframe>
      <div class="row"><a class="btn" target="_blank" href="${protoUrl(q, false)}">Открыть для печати ↗</a></div>
      <div class="row wzp-ctl" style="margin-top:14px"><button type="button" id="wzpFinish" class="${ev().status === "finished" ? "primary" : ""}">${ev().status === "finished" ? "↩️ Возобновить соревнование" : "🏁 Завершить соревнование"}</button>
        <span class="small muted">Завершение закрывает регистрацию и делает протокол итоговым; ошибочное завершение отменяется кнопкой «Возобновить».</span></div>${nav(true, "")}`;
  }
  // «Вып. разряд»: пусто — считает система по нормам ЕВСК (видно в подписи); «—» — вручную «не выполнен»; иначе — разряд секретаря
  const DONE_RANKS = ["МСМК", "МС", "КМС", "1 р.", "2 р.", "3 р.", "1 юн.", "2 юн.", "3 юн."];
  const drSel = (r) => { const cur = r.done_rank || "", auto = (W.auto || {})[r.bib + "|" + W.disc] || "";
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
    body.innerHTML = `${stepHead(4, k)}
      <p class="small muted" style="margin:0">${tech ? "Запишите шесть попыток: расстояние в метрах (7.85 или 7,85), X — заступ, «-» — пропуск. Сервер сам найдёт лучшую попытку, проверит её по правилам и выставит итог." : pts ? "Введите сумму очков — целое число." : "Впишите время с ручных секундомеров (12.84 или 1:05.3) — одно, два или три, сколько было судей. Одно время — это и есть официальный результат; из двух берётся худшее, из трёх — среднее по величине; округление вверх до 0,1 с. На табло и в итоговом протоколе показывается один официальный результат — ячейки секундомеров туда не попадают."}
        «Вып. разряд»: «Авто» — разряд по нормам ЕВСК (обновляется после сохранения); выберите разряд или «Не выполнен», чтобы задать его вручную — ручное значение главнее расчёта.</p>
            <div class="tbl"><table class="wzp-grid"><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody id="wzpRows">${rowsHtml || `<tr><td colspan="${head.length}" class="empty">Нет участников: сформируйте сетку на шаге 3.</td></tr>`}</tbody></table></div>
      <div class="row wzp-ctl"><button class="primary" type="button" id="wzpSave">Сохранить результаты</button>
        <span class="wzp-sync" id="wzpSync" role="status" aria-live="polite">Каждая строка сохраняется сама, как только вы переходите к следующему полю.</span>
        ${!sorted.length ? "" : '<button class="danger" type="button" id="wzpClear">❌ Удалить все результаты / Очистить протокол</button>'}</div>
      ${startedBox()}${nav(true, "К итоговому протоколу")}`;
  }
  // экстренная отмена старта (фальстарт, старт по ошибке): время старта забега обнуляется, сетку снова можно пересобрать
  function startedBox(){
    const ws = ((ev() || {}).waves || []).filter(w => w.start_time && (w.distance === W.disc || myHeats().some(h => h.name === w.name)));
    if (!ws.length) return "";
    return `<fieldset class="pmode wzp-start"><legend>Старт дан</legend>${ws.map(w => `<div class="row">
      <span><b>${esc(w.name)}</b> <span class="small muted">старт в ${esc(String(w.start_time).slice(11, 19))}${w.state === "finished" ? " · финиш закрыт" : ""}</span></span>
      <button class="danger" type="button" id="wzpStartReset" data-wave="${esc(w.name)}">🛑 Отменить старт / Сбросить время</button></div>`).join("")}
      <span class="small muted">Отмена обнуляет время старта забега: отметки после него не считаются, сетку дисциплины снова можно пересобрать на шаге 3. Введённые вручную результаты не стираются.</span></fieldset>`;
  }
  async function startReset(wave){
    if (!confirm(`Отменить старт «${wave}» и сбросить его время?\n\nИспользуйте при фальстарте или старте по ошибке. После этого забег можно стартовать заново, а сетку — пересобрать.`)) return;
    try{ await api(`/api/events/${ev().id}/reset`, {wave}); toast(`Старт «${wave}» отменён`); loadEvents._sig = null; await loadEvents(); await load(); render(); }
    catch(err){ toast("Ошибка: " + err.message); }
  }
  const rowData = (tr) => {
    const row = {bib: tr.dataset.bib, distance: W.disc, status: tr.querySelector("select.stsel").value, auto: true, done_rank: tr.querySelector("select.dr").value};
    const sw = [...tr.querySelectorAll("input.sw")], at = [...tr.querySelectorAll("input.att")], one = tr.querySelector("input.one");
    if (sw.length) row.t = sw.map(i => i.value.trim()); if (at.length) row.a = at.map(i => i.value.trim()); if (one) row.result = one.value.trim();
    return row; };
  // 6.0: арифметики и правил секундомеров в браузере нет — сырые цифры уходят на сервер (POST /api/calc), в ячейку ставится его ответ
  function calcRow(tr){
    const out = tr.querySelector("[data-out]"); if (!out) return;
    const sw = [...tr.querySelectorAll("input.sw")], at = [...tr.querySelectorAll("input.att")]; if (!sw.length && !at.length) return;
    const row = {key: tr.dataset.bib}; if (sw.length) row.t = sw.map(i => i.value.trim()); else row.a = at.map(i => i.value.trim());
    const sig = JSON.stringify(row); clearTimeout(tr._calcT);
    tr._calcT = setTimeout(async () => {
      try{ const d = await api("/api/calc", {distance: W.disc, rows: [row]}); const r0 = d.rows[0];
        if (!r0 || !tr.isConnected || JSON.stringify(Object.assign({key: tr.dataset.bib}, sw.length ? {t: [...tr.querySelectorAll("input.sw")].map(i => i.value.trim())} : {a: [...tr.querySelectorAll("input.att")].map(i => i.value.trim())})) !== sig) return;
        out.textContent = r0.result; out.title = r0.errors.join("; "); out.classList.toggle("err", !!r0.errors.length); }catch(e){ /* нет связи — итог посчитает сервер при сохранении */ } }, 120);
  }
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
      refreshRows();          // 6.0: без render() — экран и фокус остаются на месте; обновляются только расчётные клетки
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
      const dr = tr.querySelector("select.dr"); if (dr && dr.options[0]) { const a = (W.auto || {})[e.bib + "|" + W.disc] || ""; dr.options[0].textContent = a ? `Авто: ${a}` : "Авто: нет"; }
    });
  }
  async function clearAll(){
    const bibs = [...document.querySelectorAll("#wzpRows tr[data-bib]")].map(tr => tr.dataset.bib);
    if (!bibs.length) return;
    const lbl = `${W.disc}${W.sex ? " — " + (W.sex === "М" ? "мальчики" : "девочки") : ""}`;
    if (!confirm(`Удалить все результаты дисциплины «${lbl}» (${bibs.length} участников)?\n\nСотрутся секундомеры, попытки, отметки DNS/DNF и ручные разряды. Участники и сетка останутся. Это действие нельзя отменить.`)) return;
    try{ const r = await api(`/api/events/${curId}/clearresults`, {bibs, distance: W.disc, label: lbl}); toast(`Протокол очищен: ${r.cleared}`); await load(); render(); loadResults(); }
    catch(err){ toast("Ошибка: " + err.message); }
  }
  async function setPub(kind2, on){
    try{ await api(`/api/events/${ev().id}/publish`, {[kind2]: on});
      toast(kind2 === "regs" ? (on ? "Открытый список «прошли регистрацию» опубликован" : "Открытый список снят с сайта")
        : (on ? "Протокол открыт тренерам в личном кабинете" : "Протокол закрыт для тренеров")); loadEvents._sig = null; await loadEvents(); render(); }
    catch(err){ toast("Ошибка: " + err.message); render(); }
  }
  const root = $("tab-wizard");
  root.addEventListener("click", (e) => {
    const s = e.target.closest("[data-s]"); if (s) return go(+s.dataset.s);
    const g = e.target.closest("[data-g]"); if (g) return go(W.step + +g.dataset.g);
    const sf = e.target.closest("[data-sexf]"); if (sf) { W.sex = sf.dataset.sexf; save(); return render(); }
    const af = e.target.closest("[data-agef]"); if (af) { const a = af.dataset.agef; W.ages = W.ages.includes(a) ? W.ages.filter(x => x !== a) : [...W.ages, a]; save(); return render(); }
    if (e.target.id === "wzpGen") return gen();
    if (e.target.id === "wzpAll") return genAll();
    if (e.target.id === "bibClear") return clearBibsAll();
    if (e.target.id === "bibSave") return saveBibs();
    if (e.target.id === "wzpFinish") return finToggle().then(() => render());
    if (e.target.id === "wzpStartReset") return startReset(e.target.dataset.wave);
    if (e.target.id === "wzpReset") return reset();
    if (e.target.id === "wzpSave") { clearTimeout(autoT); return saveRows(false); }
    if (e.target.id === "wzpClear") return clearAll();
  });
  root.addEventListener("change", (e) => {
    if (e.target.dataset.age) { const a = e.target.dataset.age; W.ages = e.target.checked ? [...new Set([...W.ages, a])] : W.ages.filter(x => x !== a); save(); return render(); }
    if (e.target.name === "wzpSex") { W.sex = e.target.value; save(); return render(); }
    if (e.target.id === "wzpLanes") W.lanes = +e.target.value || 8;
    if (e.target.id === "wzpLevel") { api(`/api/events/${ev().id}`, {level: e.target.value}).then(async () => { toast("Статус соревнований сохранён — разряды пересчитаны"); loadEvents._sig = null; await loadEvents(); render(); }).catch(err => toast("Ошибка: " + err.message)); return; }
    if (e.target.id === "wzpPubG") return setPub("regs", e.target.checked);
    if (e.target.id === "wzpPubS") return setPub("start", e.target.checked);
    if (e.target.id === "wzpPubR") return setPub("results", e.target.checked);
    const tr = e.target.closest("#wzpRows tr"); if (tr) { tr.classList.add("dirty"); queueAuto(); }
  });
  root.addEventListener("input", (e) => {
    if (e.target.classList.contains("bibin2")) { e.target.classList.remove("err"); return bibCheck(); }
    const tr = e.target.closest("#wzpRows tr"); if (!tr) return; tr.classList.add("dirty"); e.target.classList.remove("err");
    calcRow(tr);
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.classList.contains("bibin2")) { e.preventDefault();
      const all = [...document.querySelectorAll("#bibRows input")], i = all.indexOf(e.target);
      if (all[i + 1]) { all[i + 1].focus(); all[i + 1].select(); } else if (!$("bibSave").disabled) saveBibs(); return; }
    if (e.key !== "Enter" || !e.target.matches("#wzpRows input")) return; e.preventDefault();
    const all = [...document.querySelectorAll("#wzpRows input")], i = all.indexOf(e.target);
    if (all[i + 1]) { all[i + 1].focus(); all[i + 1].select(); } else $("wzpSave").click();
  });
  $("wzpDisc").onchange = (e) => {
    if (W.step === 2 && W.bibDirty && !confirm("Нагрудные номера изменены, но не сохранены. Перейти к другой дисциплине без сохранения?")) { e.target.value = W.disc; return; }
    W.bibDirty = false; W.disc = e.target.value; W.step = 2; W.ages = []; W.sex = ""; save(); render(); };      // участники подтягиваются сами — сразу к номерам
  window.addEventListener("beforeunload", (e) => { if (W.step === 2 && W.bibDirty) { e.preventDefault(); e.returnValue = ""; } });
  // этап «Ввод результатов» стадиона с ручным вводом = шаг 4 Мастера (один экран ввода вместо двух)
  function setStep(n){ const e0 = ev(); if (!e0) return;
    if (W.evId !== e0.id) { W.forceStep = n; return; }        // Мастер ещё не открывался для этого соревнования — шаг применит open()
    W.step = n; save(); }
  return {open, setStep, go, remote, step: () => W.step};
})();
```

### 4.5 Расчёт официального результата — только на сервере (`hub/hub.py`)

#### `Hub.official_from_raw` — `hub/hub.py` строки 1661–1700

```python
    def official_from_raw(self, dn, rt: str, rw: dict) -> tuple:
        """ЕДИНСТВЕННОЕ место, где считается официальный результат по сырым цифрам (6.0).
        rw["t"] — до трёх показаний секундомеров (бег): 3 — среднее по величине, 2 — худшее, 1 — само значение,
        округление вверх до 0,1 с; rw["a"] — попытки (прыжки, метания, высота): лучшая.
        → (detail для базы, есть ли detail, официальный результат текстом или None, ошибки [текст]).
        Клиенты (админка, планшет сектора) арифметики не знают: шлют сырые цифры и показывают ответ сервера."""
        detail, set_detail, auto_txt, errs = {}, False, None, []
        if isinstance(rw.get("t"), list):
            set_detail = True
            secs, tclean = [], []
            for i, raw in enumerate(rw["t"][:3], 1):
                t = str(raw or "").strip()
                if not t:
                    tclean.append("")
                    continue
                pr = self.parse_result(t) if rt == "time" else None
                if not pr:
                    errs.append(f"секундомер {i}: не понял «{t[:12]}» — пример: 12.84 или 1:05.3")
                    tclean.append("")
                    continue
                secs.append(pr[0])
                tclean.append(pr[1])
            if errs:
                return detail, set_detail, auto_txt, errs
            while tclean and not tclean[-1]:
                tclean.pop()
            if tclean:
                detail["t"] = tclean
            m = self.stopwatch_main(secs)
            auto_txt = self.fmt_result(m) if m is not None else None
        if isinstance(rw.get("a"), list):
            set_detail = True
            slots = self.attempt_slots(dn) or 6
            aclean, best, aerr = self.parse_attempts(rt, rw["a"][:slots], dn)
            if aerr:
                return detail, set_detail, auto_txt, [m_ for _, m_ in aerr]
            if aclean:
                detail["a"] = aclean
            auto_txt = best[1] if best else None
        return detail, set_detail, auto_txt, errs
```

#### `Hub.calc_official` — `hub/hub.py` строки 1702–1711

```python
    def calc_official(self, distance: str, rows: list) -> dict:
        """POST /api/calc: официальный результат для строк ввода без записи в базу (живой пересчёт на экране)."""
        rt = self.result_type(distance)
        out = []
        for rw in rows[:200]:
            if not isinstance(rw, dict):
                continue
            _, _, txt, errs = self.official_from_raw(distance, rt, rw)
            out.append({"key": rw.get("key"), "result": txt or "", "errors": errs})
        return {"rows": out}
```

Браузеры (админка, планшет сектора) арифметики не содержат: сырые цифры уходят в `POST /api/calc`, в ячейку ставится ответ сервера.

### 4.6 Обязательное поле «Разряд / Звание» — `hub/ui.html`

#### `rankOpts` — `hub/ui.html` строки 1500–1500

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

Результат прогона при формировании дампа: **Итого: 324 из 324 проверок пройдено. · Всё работает.** (код возврата 0).

Проверки, относящиеся к Мастеру (имена из вывода):

- ✅ 3.4: у участника в списке своя дисциплина, тип результата и число попыток (для бланка техники); поля chip нет
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
- ✅ 3.5: у соревнования с бегом и техникой прыжок читается как расстояние (5.45), а не как время
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
a623134 2026-10-14 major: исправлен баг пустых полей тренеров в базе данных и геолокация манежа на Сахалине v7.4.5
2fc4372 2026-10-14 major: исправлена верстка кнопки участников, колонка номеров на сайте и автоподтягивание тренеров в базу v7.4.0
ea25612 2026-10-14 docs: история версий 1.3.0 – 7.3.5 (CHANGELOG.md)
70a3176 2026-10-14 ui: кнопка «Участники соревнований» вверху страницы по центру, в списке — фамилия и имя, год рождения, тренер
5af8369 2026-10-14 ui: публичные участники MyRace перенесены в выделенное окно соревнований v7.3.5
3b71676 2026-10-14 ui: оптимизирована компактность публичных списков участников и убран хаос кнопок на этапе подготовки v7.3.0
315339e 2026-10-14 major: внедрена пакетная генерация всех протоколов соревнований и публичный модуль участников по эталону MyRace v7.2.0
a7f6476 2026-10-14 ui: оптимизирован Шаг 1 Мастера, добавлена кнопка очистки номеров и безопасные публичные списки участников v7.1.0
658ec56 2026-10-14 chore: убраны остатки разбора ридеров (регулярные выражения, комментарии, имена VPN-доступов)
3d0a05f 2026-10-14 major: запущен чистый стадионно-манежный монолит SakhStart v7.0.0, вырезан код чипового хронометража
6233695 2026-10-14 release: глобальная реконструкция платформы, запущен монолитный SakhStart v6.0.0
39c6600 2026-10-14 audit: сформирован глобальный архитектурный дамп системы для ревизии
d0ab416 2026-10-13 major: сквозной аудит АРМ секретаря, ручной ввод нагрудных номеров и экспорт протоколов в Excel v5.2.0
c888b7b 2026-10-13 major: согласие отдельно от Политики, архив редакций согласий, обезличивание заявок и зашифрованные внешние копии v5.1.0
```

