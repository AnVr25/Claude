# system_architecture_snapshot — полная спецификация архитектуры SakhStart timing-hub

- **Версия сервера (`VERSION`):** `7.6.0`
- **Дата сборки (`BUILD_DATE`):** `2026-10-14`
- **Ветка / коммит:** `claude/greeting-d2g8ji` / `200fb44`
- **Сформирован:** 2026-10-14 12:34 скриптом `tools/make_architecture.py` (код — дословно из исходников)
- **Автопроверки (`tools/selftest.py`):** Итого: 336 из 336 проверок пройдено. · Всё работает.
- **Объём:** `hub/hub.py` 6116 строк, `hub/ui.html` 2859, `hub/reg.html` 962, `hub/board.html` 200

> Для ИИ-аудитора. Разделы: 1 — назначение; 2 — что исправлено в 7.4.5 и где; 3 — схема SQLite (снята с живой базы); 4 — Python (ключевые функции дословно); 5 — HTML/JS/CSS (дословно); 6 — маршруты и права; 7 — допущения и известные ограничения.
> В документе нет персональных данных и секретов: только код и структура.

## 1. Назначение и концепция

**SakhStart timing-hub** — стадионно-манежный монолит РСОО «ФЛАСО» для лёгкой атлетики (Южно-Сахалинск). Один процесс Python (`hub/hub.py`, asyncio, собственный HTTP-сервер без фреймворков) + SQLite (один файл) + статические HTML-страницы без сборки.

| Часть | Что делает | Файл |
|---|---|---|
| Секретариат (АРМ секретаря) | события, заявки, нагрудные номера (вручную), Мастер протоколов (шаги 1–5), забеги/общий список, Excel, печать, итоговый протокол | `hub/ui.html` |
| АРМ судьи на секторе | планшет: ввод попыток/секундомеров, очередь с повтором при обрыве связи | `hub/sector.html`, маршрут `/sector` |
| Табло | `auto` / `fixed` / `rotate`, автопрокрутка длинных таблиц, 6 ячеек попыток с подсветкой заступа и лучшей попытки | `hub/board.html`, пульт `hub/scoreboard.html` |
| Публичная страница соревнования | регистрация по ссылке, блок документов, кнопка «Участники соревнований», окно `/r/<slug>/participants` (модуль в духе MyRace) | `hub/reg.html` |
| Личный кабинет тренера | регистрация по e-mail с подтверждением, вход, закрытые стартовые и итоговые протоколы | `hub/reg.html` (`trainerPage`), `Hub.trainer_api` |
| Протоколы / печать | стартовые, итоговые, корзина печати, альбомные бланки техники на 6 попыток | `hub/protocol.html` |

**Принципы.** (1) Официальный результат считается только на сервере (`official_from_raw`, `POST /api/calc`). (2) Нагрудные номера только вручную, один человек (ФИО + год) — один номер на все его дисциплины. (3) Чипового хронометража нет с 7.0.0 (удалены ридеры, IPICO, Wiclax; миграция `_migrate_v7`). (4) ФЗ-152: согласие отдельно от Политики, архив редакций (`consent_texts`), обезличивание ПДн через 180 дней после соревнования, открытый список участников — только по включённому тумблеру и с учётом текста согласия (`PUBLIC_LIST_MARK`), протоколы закрыты без входа. (5) Общее состояние Мастера и корзины печати хранится на сервере (`ui_state`), а не в браузере.

## 2. Исправления и функции версии 7.4.x — что и где

| Требование | Реализация | Статус |
|---|---|---|
| Восстановление года рождения / тренера: жёсткая связь `entries.reg_id` ↔ `registrations.id`, затем ключ ФИО (`_name_key`: без регистра, пробелов, NBSP, «ё»=«е»); принудительно при каждом старте | `Store._migrate_v74`, `_name_key` (раздел 4.6) | ✅ |
| Публичный `/participants`: год, номер (Bib) и тренер у каждого, без пустых клеток | `Hub.participants_list` (резервное чтение из `entries`), `reg.html` выводит «—» вместо пустого | ✅ с оговоркой ↓ |
| Смена номера на шаге 2 мгновенно видна на сайте | номер берётся из БД при каждом запросе (`_reg_bib`), ответ `Cache-Control: no-cache`, страница сама обновляется раз в 20 с (`plRefresh`) | ✅ |
| Яндекс.Карты: манеж Горького, 39 не уходит в Хабаровск | `Hub.venue_for`: центр карты `ll=142.760570,46.928092`, метка `pt=`, масштаб 17, текст «Южно-Сахалинск, улица Горького, 39, Легкоатлетический манеж» | ✅ |
| Адаптивная кнопка «Участники соревнований» | `reg.html`: `a.btn.pbtn` (по центру, на всю ширину формы; на узком экране тот же центр) | ✅ |
| Пакетная генерация «⚡ Сформировать ВСЕ» | `Hub.generate_all`, `POST /api/events/<id>/heats-all`, `wzp.genAll` | ✅ |

**Оговорка.** Год рождения и тренер в открытом списке скрыты для заявок, поданных по тексту согласия без пункта о публикации (это требование 152-ФЗ, а не пустые данные в БД). Секретарь снимает скрытие тумблером «Показывать год рождения и тренера у всех» (`events.pub_regs_full`) после подтверждения, что согласия получены. Без тумблера для таких заявок на сайте «—».

## 3. Схема SQLite (снята с реальной свежей базы через `sqlite_master`)

Таблицы (13): `audit`, `consent_texts`, `entries`, `events`, `files`, `manual`, `registrations`, `scoreboard`, `sessions`, `trainers`, `ui_state`, `users`, `waves`

### `audit`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `ts` | TEXT | да |  |  |
| 2 | `actor` | TEXT |  |  |  |
| 3 | `event_id` | INTEGER |  |  |  |
| 4 | `action` | TEXT | да |  |  |
| 5 | `details` | TEXT |  |  |  |

### `consent_texts`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `hash` | TEXT |  |  | да |
| 1 | `kind` | TEXT | да |  |  |
| 2 | `text` | TEXT | да |  |  |
| 3 | `created_at` | TEXT | да |  |  |

### `entries`

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

### `events`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `name` | TEXT | да |  |  |
| 2 | `date` | TEXT |  |  |  |
| 3 | `place` | TEXT |  |  |  |
| 4 | `finish_device` | TEXT |  |  |  |
| 5 | `start_time` | TEXT |  |  |  |
| 6 | `status` | TEXT | да | `'planned'` |  |
| 7 | `notes` | TEXT |  |  |  |
| 8 | `created_at` | TEXT | да |  |  |
| 9 | `archived` | INTEGER | да | `0` |  |
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
| 21 | `reg_open` | INTEGER | да | `0` |  |
| 22 | `reg_slug` | TEXT |  |  |  |
| 23 | `reg_deadline` | TEXT |  |  |  |
| 24 | `reg_distances` | TEXT |  |  |  |
| 25 | `reg_rules` | TEXT |  |  |  |
| 26 | `reg_lanes` | INTEGER |  |  |  |
| 27 | `reg_info` | TEXT |  |  |  |
| 28 | `reg_consent` | TEXT |  |  |  |
| 29 | `kind` | TEXT |  |  |  |
| 30 | `timing` | TEXT |  |  |  |
| 31 | `pub_site` | INTEGER | да | `0` |  |
| 32 | `ours` | INTEGER | да | `1` |  |
| 33 | `level` | TEXT |  |  |  |
| 34 | `adaptive` | INTEGER | да | `0` |  |
| 35 | `date_end` | TEXT |  |  |  |
| 36 | `city` | TEXT |  |  |  |
| 37 | `note` | TEXT |  |  |  |
| 38 | `live_url` | TEXT |  |  |  |
| 39 | `photo_url` | TEXT |  |  |  |
| 40 | `links` | TEXT |  |  |  |
| 41 | `pub_start` | INTEGER | да | `0` |  |
| 42 | `pub_results` | INTEGER | да | `0` |  |
| 43 | `pub_regs` | INTEGER | да | `0` |  |
| 44 | `pub_regs_full` | INTEGER | да | `0` |  |

### `files`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `event_id` | INTEGER | да |  |  |
| 2 | `name` | TEXT | да |  |  |
| 3 | `stored` | TEXT | да |  |  |
| 4 | `size` | INTEGER | да |  |  |
| 5 | `kind` | TEXT | да | `'protocol'` |  |
| 6 | `created_at` | TEXT | да |  |  |
| 7 | `author` | TEXT |  |  |  |
| 8 | `folder` | TEXT |  |  |  |
| 9 | `public` | INTEGER | да | `0` |  |

### `manual`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `event_id` | INTEGER | да |  |  |
| 2 | `device` | TEXT | да |  |  |
| 3 | `ts` | TEXT | да |  |  |
| 4 | `bib` | TEXT | да | `''` |  |
| 5 | `judge` | TEXT |  |  |  |
| 6 | `client_id` | TEXT |  |  |  |
| 7 | `created_at` | TEXT | да |  |  |
| 8 | `deleted` | INTEGER | да | `0` |  |
| 9 | `wave` | TEXT |  |  |  |

### `registrations`

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
| 15 | `status` | TEXT | да | `'pending'` |  |
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

### `scoreboard`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `event_id` | INTEGER |  |  | да |
| 1 | `state` | TEXT | да |  |  |
| 2 | `updated_at` | TEXT | да |  |  |

### `sessions`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `token` | TEXT |  |  | да |
| 1 | `login` | TEXT | да |  |  |
| 2 | `created_at` | TEXT | да |  |  |
| 3 | `expires_at` | TEXT | да |  |  |
| 4 | `ip` | TEXT |  |  |  |

### `trainers`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `name` | TEXT | да |  |  |
| 2 | `team` | TEXT | да |  |  |
| 3 | `email` | TEXT | да |  |  |
| 4 | `password_hash` | TEXT | да |  |  |
| 5 | `is_verified` | INTEGER | да | `0` |  |
| 6 | `verification_token` | TEXT |  |  |  |
| 7 | `created_at` | TEXT | да |  |  |
| 8 | `token_expires` | TEXT |  |  |  |
| 9 | `token_attempts` | INTEGER | да | `0` |  |
| 10 | `token_sent_at` | TEXT |  |  |  |
| 11 | `active` | INTEGER | да | `1` |  |
| 12 | `last_login` | TEXT |  |  |  |
| 13 | `verified_at` | TEXT |  |  |  |
| 14 | `verified_by` | TEXT |  |  |  |
| 15 | `consent_accepted` | INTEGER | да | `0` |  |
| 16 | `consent_at` | TEXT |  |  |  |
| 17 | `consent_hash` | TEXT |  |  |  |
| 18 | `policy_hash` | TEXT |  |  |  |

### `ui_state`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `event_id` | INTEGER | да |  | да |
| 1 | `key` | TEXT | да |  | да |
| 2 | `value` | TEXT | да |  |  |
| 3 | `rev` | INTEGER | да | `1` |  |
| 4 | `who` | TEXT |  |  |  |
| 5 | `cid` | TEXT |  |  |  |
| 6 | `updated_at` | TEXT | да |  |  |

### `users`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `login` | TEXT |  |  | да |
| 1 | `name` | TEXT |  |  |  |
| 2 | `role` | TEXT | да | `'judge'` |  |
| 3 | `pwd` | TEXT | да |  |  |
| 4 | `created_at` | TEXT |  |  |  |
| 5 | `last_login` | TEXT |  |  |  |
| 6 | `note` | TEXT |  |  |  |
| 7 | `active` | INTEGER | да | `1` |  |

### `waves`

| # | поле | тип | NOT NULL | по умолчанию | PK |
|---|---|---|---|---|---|
| 0 | `id` | INTEGER |  |  | да |
| 1 | `event_id` | INTEGER | да |  |  |
| 2 | `name` | TEXT | да |  |  |
| 3 | `start_time` | TEXT |  |  |  |
| 4 | `category` | TEXT |  |  |  |
| 5 | `distance` | TEXT |  |  |  |
| 6 | `finished_at` | TEXT |  |  |  |

### Индексы и триггеры (`sqlite_master`)

```sql
-- index idx_entries_event (entries)
CREATE INDEX idx_entries_event ON entries(event_id, bib);
-- index idx_events_slug (events)
CREATE UNIQUE INDEX idx_events_slug ON events(reg_slug);
-- index idx_files_event (files)
CREATE INDEX idx_files_event ON files(event_id);
-- index idx_manual_event (manual)
CREATE INDEX idx_manual_event ON manual(event_id);
-- index idx_reg_event (registrations)
CREATE INDEX idx_reg_event ON registrations(event_id);
```

Триггеров в схеме: **0** (бизнес-логика целиком в Python; целостность — индексами и транзакциями).

### Полный DDL (для воспроизведения)

```sql
CREATE TABLE audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT,
                event_id INTEGER,
                action TEXT NOT NULL,
                details TEXT
            );

CREATE TABLE consent_texts(
            hash TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE entries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                bib TEXT NOT NULL
            , points REAL, picked_at TEXT, members TEXT, rank TEXT, detail TEXT, done_rank TEXT, result_at TEXT, wave TEXT, name TEXT, birth_year TEXT, team TEXT, category TEXT, lane INTEGER, coach TEXT, seed TEXT, reg_id INTEGER, sex TEXT, result TEXT, status TEXT);

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
            , archived INTEGER NOT NULL DEFAULT 0, finished_at TEXT, organizer TEXT, chief_judge TEXT, chief_secretary TEXT, start_clock TEXT, heats_sequential INTEGER, team_best INTEGER, cover TEXT, program TEXT, contacts TEXT, series TEXT, reg_open INTEGER NOT NULL DEFAULT 0, reg_slug TEXT, reg_deadline TEXT, reg_distances TEXT, reg_rules TEXT, reg_lanes INTEGER, reg_info TEXT, reg_consent TEXT, kind TEXT, timing TEXT, pub_site INTEGER NOT NULL DEFAULT 0, ours INTEGER NOT NULL DEFAULT 1, level TEXT, adaptive INTEGER NOT NULL DEFAULT 0, date_end TEXT, city TEXT, note TEXT, live_url TEXT, photo_url TEXT, links TEXT, pub_start INTEGER NOT NULL DEFAULT 0, pub_results INTEGER NOT NULL DEFAULT 0, pub_regs INTEGER NOT NULL DEFAULT 0, pub_regs_full INTEGER NOT NULL DEFAULT 0);

CREATE TABLE files(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                stored TEXT NOT NULL,
                size INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'protocol',
                created_at TEXT NOT NULL,
                author TEXT
            , folder TEXT, public INTEGER NOT NULL DEFAULT 0);

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
            , wave TEXT);

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
            , relay TEXT, leg INTEGER, rank TEXT, policy_hash TEXT, anonymized_at TEXT);

CREATE TABLE scoreboard(event_id INTEGER PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE sessions(
                token TEXT PRIMARY KEY,
                login TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ip TEXT
            );

CREATE TABLE trainers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 0,
            verification_token TEXT,
            created_at TEXT NOT NULL, token_expires TEXT, token_attempts INTEGER NOT NULL DEFAULT 0, token_sent_at TEXT, active INTEGER NOT NULL DEFAULT 1, last_login TEXT, verified_at TEXT, verified_by TEXT, consent_accepted INTEGER NOT NULL DEFAULT 0, consent_at TEXT, consent_hash TEXT, policy_hash TEXT);

CREATE TABLE ui_state(
            event_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 1,
            who TEXT, cid TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(event_id, key));

CREATE TABLE users(
                login TEXT PRIMARY KEY,
                name TEXT,
                role TEXT NOT NULL DEFAULT 'judge',
                pwd TEXT NOT NULL,
                created_at TEXT,
                last_login TEXT,
                note TEXT,
                active INTEGER NOT NULL DEFAULT 1
            );

CREATE TABLE waves(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                start_time TEXT, category TEXT, distance TEXT, finished_at TEXT,
                UNIQUE(event_id, name)
            );

CREATE INDEX idx_entries_event ON entries(event_id, bib);

CREATE UNIQUE INDEX idx_events_slug ON events(reg_slug);

CREATE INDEX idx_files_event ON files(event_id);

CREATE INDEX idx_manual_event ON manual(event_id);

CREATE INDEX idx_reg_event ON registrations(event_id);
```

Примечание: таблица `waves` — забеги/группы соревнования (имя, категория, дистанция, время старта); участник привязан к забегу полем `entries.wave` (по имени). Связь «один человек — одна строка на дисциплину»: `entries.id` (строка) ≠ нагрудный номер (`entries.bib`, может повторяться у одного человека).

## 4. Python: ключевые функции дословно (`hub/hub.py`)

### 4.1 Генерация и сброс сетки

`generate_heats` удалён в 6.0.0 — единственный генератор `generate_scoped` (одна дисциплина) вызывается из `generate_all`.

### `Hub.generate_scoped` — `hub/hub.py` строки 4089–4190 (сетка одной дисциплины: бег — забеги и дорожки, техника — общий список)

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

### `Hub.reset_heats` — `hub/hub.py` строки 4211–4251 (принудительный сброс, обнуляет время старта)

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

### 4.2 Пакетная генерация «heats-all»

### `Hub.generate_all` — `hub/hub.py` строки 4192–4209 (все дисциплины с одобренными заявками одним проходом)

```python
    def generate_all(self, ev: dict, lanes: int) -> dict:
        """«⚡ Сформировать ВСЕ стартовые протоколы»: за один проход — сетки по каждой дисциплине, на которую есть одобренные
        заявки. Вид программы определяется сам (бег — забеги с дорожками, техника — сквозной общий список на 6 попыток);
        работает тот же generate_scoped, что и поштучно. Дисциплина, у которой не хватает вписанных вручную номеров или уже
        стоит время старта, пропускается с понятной причиной — остальные формируются."""
        eid = ev["id"]
        order = self.reg_distances(ev)
        have = {r["distance"] for r in self.store.registrations(eid) if r["status"] == "approved" and r.get("distance")}
        dists = [d for d in order if d in have] + sorted(have - set(order))
        done, skipped = [], []
        for d in dists:
            try:
                out = self.generate_scoped(self.store.get_event(eid), lanes, {"distance": d})
            except ValueError as e:
                skipped.append({"distance": d, "reason": str(e)})
                continue
            done.append({"distance": d, "kind": out["kind"], "mode": out["mode"], "heats": len(out["heats"]), "entries": out["entries"]})
        return {"done": done, "skipped": skipped, "disciplines": len(dists), "entries": sum(x["entries"] for x in done)}
```

Ветка `POST /api/events/<id>/heats-all` (`Hub._api…`, `hub/hub.py` строки 2843–2857):

```python
        if action == "heats-all":
            out = self.generate_all(ev, data.get("lanes") or ev.get("reg_lanes") or 8)
            if not out["disciplines"]:
                return err("нет подтверждённых заявок: сначала одобрите их на этапе «2. Регистрация»")
            if data.get("lanes"):
                self.store.update_event(eid, {"reg_lanes": data["lanes"]})
            self.store.audit(who, eid, "Сформированы все стартовые протоколы",
                             f"дисциплин {len(out['done'])} из {out['disciplines']}, участников {out['entries']}"
                             + (f"; пропущено: {'; '.join(x['distance'] for x in out['skipped'])}" if out["skipped"] else ""))
            try:
                self.save_file(eid, f"Стартовый список {now_local():%Y-%m-%d %H-%M}.csv",
                               self._startlist_csv(self.store.get_event(eid)).encode("utf-8"), "startlist", who, "Для судей")
            except Exception:
                log.exception("стартовый список в папку «Для судей»")
            return ok(out)
```

### 4.3 Нагрудные номера: сохранение, очистка, единая картина

### `Hub._bib_state` — `hub/hub.py` строки 3129–3147

```python
    def _bib_state(self, eid: int) -> dict:
        """Единая картина номеров соревнования: заявки, строки участников, ключи людей и номер каждого человека."""
        regs = {r["id"]: r for r in self.store.registrations(eid)}
        entries = self.store.entries_rows(eid)
        live = [r for r in regs.values() if r.get("status") != "rejected"]
        key_of = self._people(live)
        ent_by_reg = {e["reg_id"]: e for e in entries if e.get("reg_id")}
        members: dict = {}
        for r in live:
            members.setdefault(key_of[r["id"]], []).append(r["id"])
        person_bib: dict = {}
        for k, ids in members.items():
            for i in sorted(ids, key=lambda i: (i not in ent_by_reg, i)):        # сначала заявка, уже стоящая в сетке
                b = self._own_bib(regs[i], ent_by_reg.get(i))
                if b:
                    person_bib[k] = b
                    break
        return {"regs": regs, "entries": entries, "key_of": key_of, "ent_by_reg": ent_by_reg,
                "members": members, "person_bib": person_bib}
```

### `Hub._own_bib` — `hub/hub.py` строки 3149–3151

```python
    @staticmethod
    def _own_bib(r: dict, e: Optional[dict]) -> str:
        return str(r.get("bib") or (e or {}).get("bib") or "").strip()
```

### `Hub._reg_bib` — `hub/hub.py` строки 3153–3156

```python
    def _reg_bib(self, r: dict, st: dict) -> str:
        """Номер участника для сетки: свой (вписан в заявку или уже стоит в сетке), иначе — номер того же человека
        из другой его дисциплины (вписывать второй раз не нужно)."""
        return self._own_bib(r, st["ent_by_reg"].get(r["id"])) or st["person_bib"].get(st["key_of"].get(r["id"], ""), "")
```

### `Hub._need_bibs` — `hub/hub.py` строки 3158–3170

```python
    def _need_bibs(self, regs: list, st: dict) -> None:
        """Сетка строится только когда у всех участников есть номера, вписанные вручную, и номера не повторяются у разных людей."""
        missing = [r for r in regs if not self._reg_bib(r, st)]
        if missing:
            names = ", ".join(" ".join(x for x in (m["last_name"], m["first_name"]) if x) for m in missing[:5])
            raise ValueError(f"нет нагрудных номеров у {len(missing)} участников ({names}{'…' if len(missing) > 5 else ''}) — "
                             f"впишите их на шаге 2 «Нагрудные номера» и нажмите «Сохранить нагрудные номера»")
        seen: dict = {}
        for r in regs:
            b, k = self._reg_bib(r, st), st["key_of"].get(r["id"], f"r{r['id']}")
            if seen.get(b, k) != k:
                raise ValueError(f"номер {b} стоит у двух участников — исправьте на шаге 2")
            seen[b] = k
```

### `Hub.save_bibs` — `hub/hub.py` строки 3252–3331

```python
    def save_bibs(self, ev: dict, items: list, who: str, dry: bool = False) -> tuple:
        """Сохранить номера, вписанные вручную. Номер человека записывается во ВСЕ его заявки и строки сетки
        (все дисциплины). Ничего не пишется, пока весь набор не прошёл проверку."""
        eid = ev["id"]
        st = self._bib_state(eid)
        regs, entries, key_of, members, ent_by_reg = st["regs"], st["entries"], st["key_of"], st["members"], st["ent_by_reg"]
        errors, plan = [], {}          # plan: ключ человека → (все его заявки, текущие номера, новый номер, имя)
        for it in items[:3000]:
            if not isinstance(it, dict):
                continue
            ids = [int(x) for x in (it.get("ids") or []) if str(x).isdigit() and int(x) in regs]
            if not ids or ids[0] not in key_of:
                continue
            r0 = regs[ids[0]]
            k = key_of[ids[0]]
            group = members.get(k, ids)
            who_ = " ".join(x for x in (r0.get("relay") or r0["last_name"], "" if r0.get("relay") else r0["first_name"]) if x)
            new = str(it.get("bib") or "").strip()
            if new and not self.BIB_RE.fullmatch(new):
                errors.append({"ids": ids, "error": f"{who_}: номер — до 10 цифр или букв, без пробелов"})
                continue
            if not new and any(i in ent_by_reg for i in group):
                errors.append({"ids": ids, "error": f"{who_}: уже в стартовом списке — номер нельзя стереть, только заменить"})
                continue
            cur = {self._own_bib(regs[i], ent_by_reg.get(i)) for i in group}
            if cur != {new}:
                plan[k] = (group, cur, new, who_)
        # итоговая раскладка по всему соревнованию: у двух разных людей один номер стоять не может
        owners: dict = {}
        for k, ids in members.items():
            if k in plan:
                continue
            for i in ids:
                b = self._own_bib(regs[i], ent_by_reg.get(i))
                if b:
                    owners.setdefault(b, set()).add(k)
        for e in entries:
            if not e.get("reg_id") or e["reg_id"] not in regs:
                owners.setdefault(e["bib"], set()).add(f"e{e['bib']}")
        for k, (group, cur, new, who_) in plan.items():
            if new:
                if owners.get(new, set()) - {k}:
                    errors.append({"ids": group, "error": f"{who_}: номер {new} уже у другого участника"})
                owners.setdefault(new, set()).add(k)
        if errors:
            return 400, {"error": "Номера не сохранены — исправьте отмеченные строки", "errors": errors}
        if dry:                                  # только проверка (CSV-корректор): ничего не пишем
            return 200, {"ok": True, "saved": len(plan), "dry": True}
        # запись: сначала временные номера (обмен номерами двух участников не конфликтует), потом настоящие
        con = self.store.con
        con.execute("BEGIN")
        try:
            moves, n_ = [], 0
            for k, (group, cur, new, _) in plan.items():
                if not new:
                    continue
                for i in group:
                    e = ent_by_reg.get(i)
                    if e and e["bib"] != new:
                        con.execute("UPDATE entries SET bib = ? WHERE id = ?", (f"~{n_}~{e['id']}", e["id"]))
                        moves.append((e["id"], new))
                        n_ += 1
            for entry_id, new in moves:
                con.execute("UPDATE entries SET bib = ? WHERE id = ?", (new, entry_id))
            for k, (group, cur, new, _) in plan.items():
                for i in group:
                    con.execute("UPDATE registrations SET bib = ? WHERE id = ? AND event_id = ?", (new or None, i, eid))
                for old in cur - {"", new}:        # ручные отметки судьи со старым номером переезжают на новый
                    if new and not con.execute("SELECT 1 FROM entries WHERE event_id = ? AND bib = ?", (eid, old)).fetchone():
                        con.execute("UPDATE manual SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        spread = sum(len(g) - 1 for g, _, _, _ in plan.values())
        if plan:
            ch = [f"{w}: {','.join(sorted(c - {''})) or '—'} → {n or '—'}" for _, c, n, w in plan.values()][:30]
            self.store.audit(who, eid, "Нагрудные номера сохранены",
                             f"{len(plan)}: " + "; ".join(ch) + (f"; продублировано на другие дисциплины: {spread}" if spread else ""))
        return 200, {"ok": True, "saved": len(plan), "spread": spread}
```

### `Hub.clear_bibs` — `hub/hub.py` строки 3210–3250

```python
    def clear_bibs(self, ev: dict, distance, who: str) -> dict:
        """«❌ Очистить все номера дисциплины» (шаг 2): у всех участников дисциплины номер стирается (bib = NULL).
        Номер принадлежит человеку, поэтому стирается и в других его дисциплинах — иначе он вернулся бы как «подставленный».
        Строки сетки этих людей удаляются, забеги пустеют (старт и часы сбрасываются). Если у кого-то уже введён
        результат — очистка отклоняется целиком: сначала «Очистить протокол» на шаге 4."""
        eid, dist = ev["id"], str(distance or "").strip()
        if not dist:
            raise ValueError("выберите дисциплину")
        st = self._bib_state(eid)
        scope = [r for r in st["regs"].values() if r["status"] != "rejected" and r["distance"] == dist]
        if not scope:
            return {"cleared": 0, "people": 0, "entries": 0, "also": []}
        keys = {st["key_of"][r["id"]] for r in scope}
        ids = sorted({i for k in keys for i in st["members"][k]})
        ents = [st["ent_by_reg"][i] for i in ids if i in st["ent_by_reg"]]
        locked = [e for e in ents if e.get("result") or e.get("status") or e.get("detail")]
        if locked:
            raise ValueError(f"у {len(locked)} участников уже введены результаты (№ {', '.join(sorted({e['bib'] for e in locked})[:8])}) — "
                             "сначала очистите протокол на шаге 4, затем номера")
        also = sorted({st["regs"][i]["distance"] for i in ids if st["regs"][i]["distance"] != dist})
        con = self.store.con
        con.execute("BEGIN")
        try:
            for e in ents:
                con.execute("DELETE FROM entries WHERE id = ?", (e["id"],))
            for i in ids:
                con.execute("UPDATE registrations SET bib = NULL WHERE id = ? AND event_id = ?", (i, eid))
            for w in self.store.waves(eid):          # опустевшие забеги и списки убираем вместе с метками старта
                if not con.execute("SELECT 1 FROM entries WHERE event_id = ? AND wave = ?", (eid, w["name"])).fetchone() \
                        and (w.get("distance") in (dist, *also) or not w.get("distance")):
                    con.execute("DELETE FROM waves WHERE event_id = ? AND name = ?", (eid, w["name"]))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        if not any(w.get("start_time") for w in self.store.waves(eid)):
            self.store.set_event_field(eid, start_time=None, status="finished" if ev.get("status") == "finished" else "planned")
        self.store.audit(who, eid, "Номера дисциплины очищены",
                         f"{dist}: людей {len(keys)}, заявок {len(ids)}, строк сетки удалено {len(ents)}"
                         + (f"; также у этих людей в: {', '.join(also)}" if also else ""))
        return {"cleared": len(ids), "people": len(keys), "entries": len(ents), "also": also}
```

### 4.4 Публичный список участников

### `Hub.participants_list` — `hub/hub.py` строки 1411–1458

```python
    def participants_list(self, ev: dict) -> dict:
        """7.2: открытый модуль «Заявленные участники» (по образцу списков MyRace): одна строка на заявку, одобренную секретарём.
        Полные данные (Фамилия Имя, год рождения, разряд, команда, тренер) выдаются только по тем заявкам, где согласие участника
        охватывало размещение в открытом списке (текст согласия содержит PUBLIC_LIST_MARK); по остальным — «Фамилия И.» без
        года, разряда и тренера (если секретарь не подтвердил согласия: pub_regs_full). Нагрудный номер — актуальный из базы. Дорожек, дат рождения, контактов и представителей нет никогда."""
        regs = [r for r in self.store.registrations(ev["id"]) if r["status"] == "approved"]
        bst = self._bib_state(ev["id"])
        ent_of = {e["reg_id"]: e for e in self.store.entries_rows(ev["id"]) if e.get("reg_id")}
        confirmed = bool(ev.get("pub_regs_full"))      # 7.4: секретарь подтвердил, что согласия на распространение получены
        covered = {t["hash"] for t in self.store.consent_texts() if self.PUBLIC_LIST_MARK in (t.get("text") or "")}
        year = int(ev["date"][:4]) if ev.get("date") else dt.date.today().year
        ages = [a for a in (self.disciplines()["data"].get("ages") or []) if a.get("id")]
        ordered = sorted([a for a in ages if a["id"] != "sen"], key=lambda a: int(a.get("max", 200))) + [a for a in ages if a["id"] == "sen"]

        def group_of(birth) -> str:
            try:
                age = year - int(str(birth)[:4])
            except ValueError:
                return ""
            for a in ordered:
                if int(a.get("min", 0)) <= age <= int(a.get("max", 200)):
                    return a["id"]
            return ""
        dists = self.reg_distances(ev)
        order = {d: i for i, d in enumerate(dists)}
        rows, relays = [], {}
        for r in regs:
            if r.get("relay"):
                relays.setdefault((r["relay"], r["distance"]), None)
                continue
            last, first = str(r["last_name"]).strip(), str(r.get("first_name") or "").strip()
            full = confirmed or r.get("consent_hash") in covered
            ent = ent_of.get(r["id"]) or {}
            year_ = str(r.get("birth_date") or "")[:4] or str(ent.get("birth_year") or "")[:4]     # 7.4.5: нет в заявке — берём из строки сетки
            coach_ = (r.get("coach") or "").strip() or str(ent.get("coach") or "").strip()
            rows.append({"b": self._reg_bib(r, bst), "d": r["distance"], "s": str(r.get("sex") or "").upper(), "g": group_of(r.get("birth_date")),
                         "n": f"{last} {first}".strip() if full else (f"{last} {first[:1]}." if first else last),
                         "y": year_ if full else "", "r": (r.get("rank") or "") if full else "",
                         "t": (r.get("team") or ""), "c": coach_ if full else "", "m": 0 if full else 1})
        rows.sort(key=lambda x: (order.get(x["d"], 99), x["d"], x["n"].lower()))
        seen_d = [d for d in dists if any(x["d"] == d for x in rows)] + sorted({x["d"] for x in rows} - set(dists))
        used_g = {x["g"] for x in rows}
        people = len({(x["n"], x["y"], x["t"]) for x in rows}) if rows else 0
        return {"event": {"name": ev["name"], "date": ev.get("date"), "place": ev.get("place") or ""},
                "updated": fmt_db(now_local())[:16], "total": len(rows), "people": people,
                "disciplines": [{"name": d, "count": sum(1 for x in rows if x["d"] == d)} for d in seen_d],
                "ages": [{"id": a["id"], "name": a["name"]} for a in ordered if a["id"] in used_g],
                "rows": rows, "relays": [{"team": t, "discipline": d} for (t, d) in sorted(relays)]}
```

Маршрут отдачи (фрагмент `_public_route`):

```python
if method == "GET" and sub == "/participants.json":
            # открыто без входа, но только если секретарь включил публикацию; данные минимальны (см. registered_list)
            if not self._rate_ok("rl:" + client, 120, 600):
                return js({"error": "Слишком много запросов, попробуйте через минуту"}, 429)
            if not self._event_view(ev)["pub_regs"]:
                return js({"error": "Список заявленных участников пока не опубликован"}, 404)
            code, ctype, data_, _ = js(self.participants_list(ev))
            return code, ctype, data_, {"Cache-Control": "no-cache"}
```

### 4.5 Карты (Яндекс.Карты)

### `Hub.venue_for` — `hub/hub.py` строки 1202–1229

```python
    def venue_for(self, ev: dict) -> Optional[dict]:
        """Где проходит старт: указанное место или (если не указано) правило федерации для Южно-Сахалинска:
        кросс — ЛБК «Триумф»; апрель–октябрь — стадион «Спартак»; остальное и «в помещении» — манеж.
        Массовые забеги по улицам и старты в других городах не угадываем."""
        from urllib.parse import quote
        def ymap(q, ll=None, bias=True):
            """Ссылка на Яндекс.Карты. Без привязки к месту поиск шёл по региону посетителя (карта Хабаровска), поэтому в ссылку
            всегда кладётся центр карты: точные координаты площадки или центр Южно-Сахалинска; для площадки — ещё и метка."""
            if not ll and not bias:
                return "https://yandex.ru/maps/?text=" + quote(q)
            lon, lat = ll or self.YS_CENTER
            pt = f"&pt={lon:.6f},{lat:.6f},pm2rdm" if ll else ""
            return f"https://yandex.ru/maps/?ll={lon:.6f}%2C{lat:.6f}&z={17 if ll else 13}{pt}&text={quote(q)}"
        place = (ev.get("place") or "").strip()
        city = (ev.get("city") or "").strip()
        pick = next((v for v in self.VENUES if any(m in place.lower() for m in v["match"])), None)
        if not pick and not place and (not city or city.startswith("Южно-Сахалинск")):
            name = (ev.get("name") or "").lower()
            mass = ev.get("level") == "mass" or (ev.get("kind") or "") == "mass"
            month = int((ev.get("date") or "0000-01")[5:7] or 1)
            key = ("triumf" if "кросс" in name else None if mass
                   else "spartak" if 4 <= month <= 10 and "помещени" not in name else "manezh")
            pick = next((v for v in self.VENUES if v["key"] == key), None)
        if pick:
            return {"name": pick["name"], "address": pick["address"], "map": pick.get("map") or ymap(pick["q"], pick.get("ll"))}
        if place:
            return {"name": place, "address": city, "map": ymap(", ".join(x for x in (place, city) if x), None, not city or city.startswith("Южно-Сахалинск"))}
        return None
```

Площадки и координаты:

```python
    YS_CENTER = (142.738100, 46.959100)           # центр Южно-Сахалинска: карта открывается здесь, а не в регионе посетителя
```

```python
    VENUES = (
        {"key": "manezh", "name": "Легкоатлетический манеж", "address": "Южно-Сахалинск, ул. Горького, 39",
         "match": ("манеж",), "q": "Южно-Сахалинск, улица Горького, 39, Легкоатлетический манеж",
         "ll": (142.760570, 46.928092)},        # 7.4.5: точные координаты (Яндекс.Карты, дом Горького, 39) — карта не уходит в другой город
        {"key": "spartak", "name": "Стадион «Спартак»", "address": "Южно-Сахалинск, ул. Горького, 7",
         "match": ("спартак",), "q": "Южно-Сахалинск, улица Горького, 7, Стадион Спартак"},
        {"key": "triumf", "name": "ЛБК «Триумф»", "address": "Южно-Сахалинск, ул. Горького, 25А",
         "match": ("триумф",), "map": "https://yandex.ru/maps/org/biatlonny_kompleks_triumf/227359721489/"},
    )
```

### 4.6 Миграции: восстановление пустых полей тренеров и годов

### `_name_key` — `hub/hub.py` строки 48–50

```python
def _name_key(name) -> str:
    """Ключ для сопоставления ФИО: без регистра, лишних пробелов (в т.ч. неразрывных), «ё» = «е»."""
    return " ".join(str(name or "").replace("\u00a0", " ").lower().replace("ё", "е").split())
```

### `Store._migrate_v74` — `hub/hub.py` строки 604–635 (запускается из `_migrate()` при каждом старте)

```python
    def _migrate_v74(self) -> None:
        """7.4: у участников, загруженных старыми версиями, в строке сетки (entries) могли остаться пустыми год рождения,
        тренер и команда. При каждом старте недостающее подтягивается из заявок (registrations): сначала по связи reg_id,
        затем по ФИО в том же соревновании. Заполненные поля не трогаются."""
        regs = {}
        by_name: dict = {}
        for r in self.con.execute("SELECT id, event_id, last_name, first_name, middle_name, birth_date, team, coach FROM registrations "
                                  "WHERE status != 'rejected' ORDER BY id"):
            rid, eid, ln, fn, mn, bd, team, coach = r
            rec = {"year": str(bd or "")[:4], "team": team or "", "coach": coach or ""}
            regs[rid] = rec
            for nm in (f"{ln} {fn}", f"{ln} {fn} {mn or ''}"):
                by_name.setdefault((eid, _name_key(nm)), rec)
        upd = 0
        for eid_, id_, reg_id, name, by, team, coach in self.con.execute(
                "SELECT event_id, id, reg_id, name, birth_year, team, coach FROM entries").fetchall():
            if by and team and coach:
                continue
            rec = regs.get(reg_id) or by_name.get((eid_, _name_key(name)))
            if not rec:
                continue
            new = (by or rec["year"], team or rec["team"], coach or rec["coach"])
            if new != (by or "", team or "", coach or ""):
                self.con.execute("UPDATE entries SET birth_year = ?, team = ?, coach = ? WHERE id = ?", (*new, id_))
                upd += 1
        # обратно: если в заявке тренер пуст, а в строке сетки он есть (загружен списком) — заявка получает его
        for rid, ecoach in self.con.execute("SELECT r.id, e.coach FROM registrations r JOIN entries e ON e.reg_id = r.id "
                                            "WHERE TRIM(COALESCE(r.coach,'')) = '' AND TRIM(COALESCE(e.coach,'')) != ''").fetchall():
            self.con.execute("UPDATE registrations SET coach = ? WHERE id = ?", (ecoach, rid))
            upd += 1
        if upd:
            log.info("миграция 7.4: в %s строках участников восстановлены год рождения, команда и тренер", upd)
```

### `Store._migrate_v7` — `hub/hub.py` строки 571–602 (7.0: удаление чипового хронометража, пересборка entries с собственным id)

```python
    def _migrate_v7(self) -> None:
        """7.0: чипового хронометража в системе больше нет — из базы уходят таблицы reads, raw, readers, wiclax_ports,
        ключ chip у участников и устаревшие поля соревнований. Строка участника (entries) получает собственный
        номер id: один нагрудный номер может стоять у спортсмена в нескольких дисциплинах (по строке на дисциплину)."""
        def cols(t):
            return {r[1] for r in self.con.execute(f"PRAGMA table_info({t})")}
        for t in ("reads", "raw", "readers", "wiclax_ports"):
            self.con.execute(f"DROP TABLE IF EXISTS {t}")
        if "chip" in cols("entries"):
            k = ", ".join(self.ENTRY_KEEP)
            self.con.execute("BEGIN")
            try:
                self.con.execute("DROP TABLE IF EXISTS entries_v7")
                self.con.execute("CREATE TABLE entries_v7(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, "
                                 "bib TEXT NOT NULL, wave TEXT, name TEXT, birth_year TEXT, team TEXT, category TEXT, lane INTEGER, "
                                 "coach TEXT, seed TEXT, reg_id INTEGER, sex TEXT, result TEXT, status TEXT, points REAL, "
                                 "picked_at TEXT, members TEXT, rank TEXT, detail TEXT, done_rank TEXT, result_at TEXT)")
                self.con.execute(f"INSERT INTO entries_v7(event_id, {k}) SELECT event_id, {k} FROM entries "
                                 "ORDER BY event_id, CAST(bib AS INTEGER), bib, chip")
                self.con.execute("DROP TABLE entries")
                self.con.execute("ALTER TABLE entries_v7 RENAME TO entries")
                self.con.execute("COMMIT")
            except Exception:
                self.con.execute("ROLLBACK")
                raise
        self.con.execute("CREATE INDEX IF NOT EXISTS idx_entries_event ON entries(event_id, bib)")
        for col in ("push_wiclax", "check_since", "min_time_sec", "alert_silence_min"):
            if col in cols("events"):
                try:
                    self.con.execute(f"ALTER TABLE events DROP COLUMN {col}")
                except sqlite3.Error:
                    pass          # старый SQLite без DROP COLUMN — столбец остаётся, сервер его не использует
```

### 4.7 Тренеры: регистрация и подтверждение e-mail, вход, сессии

### `Hub.trainer_api` — `hub/hub.py` строки 5331–5450 (consent / register / verify / resend / login / logout)

```python
    def trainer_api(self, method: str, sub: str, headers: dict, body: bytes, ip: str) -> tuple:
        """(код, ответ, доп. заголовки). sub: consent | register | verify | resend | login | logout | me | events."""
        if sub == "consent" and method == "GET":         # текст согласия — показывается в форме отдельно от Политики
            text = self.trainer_consent_text()
            return 200, {"text": text, "hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]}, None
        if sub in ("me", "events") and method == "GET":
            u = self.protocol_viewer(headers)
            if not u:
                return 401, {"error": "нужно войти", "login": "/r/trainer"}, None
            if sub == "me":
                return 200, {"name": u.get("name") or u["login"], "team": u.get("team") or "", "email": u["login"]
                             if u["role"] == "trainer" else "", "role": u["role"]}, None
            return 200, {"events": self.trainer_events()}, None
        if method != "POST":
            return 405, {"error": "метод не поддерживается"}, None
        if headers.get("x-requested-with") != "timing-hub":
            return 403, {"error": "нужен заголовок X-Requested-With"}, None
        if sub == "logout":
            tok = self._cookie(headers, self.SESSION_COOKIE)
            if tok:
                self.store.delete_session(hashlib.sha256(tok.encode()).hexdigest())
            return 200, {"ok": True}, {"Set-Cookie": f"{self.SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"}
        try:
            d = json.loads(body.decode("utf-8") or "{}")
            if not isinstance(d, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return 400, {"error": "неверные данные"}, None
        email = str(d.get("email") or "").strip().lower()[:254]
        if sub == "register":
            if str(d.get("website") or "").strip():                     # ловушка для ботов
                return 200, {"ok": True, "email": email, "sent": True}, None
            if not (self._rate_ok("treg-ip:" + ip, 10, 3600) and self._rate_ok("treg-all", 100, 3600)):
                return 429, {"error": "Слишком много регистраций подряд. Попробуйте через час."}, None
            name = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()[:80]
            team = re.sub(r"\s+", " ", str(d.get("team") or "")).strip()[:120]
            pwd = str(d.get("password") or "")[:200]
            errs = {}
            if len(name.split(" ")) < 2:
                errs["name"] = "Укажите фамилию и имя"
            if len(team) < 2:
                errs["team"] = "Укажите спортивную школу или клуб"
            if not self.EMAIL_RE.fullmatch(email):
                errs["email"] = "Проверьте адрес почты: например, coach@mail.ru"
            if len(pwd) < 8:
                errs["password"] = "Пароль — не короче 8 символов"
            if not (d.get("consent_accepted") is True or d.get("consent") is True):
                errs["consent"] = "Нужно согласие на обработку персональных данных"
            if not (d.get("policy_accepted") is True or d.get("policy") is True):
                errs["policy"] = "Подтвердите, что ознакомились с Политикой конфиденциальности"
            if errs:
                return 400, {"error": "Проверьте поля формы", "fields": errs}, None
            t = self.store.trainer_by_email(email)
            if t and t["is_verified"]:
                return 409, {"error": "Эта почта уже зарегистрирована — войдите с паролем", "login": True}, None
            if t:     # не подтвердил в прошлый раз — обновляем данные и шлём новый код
                if t.get("token_sent_at") and (now_local() - parse_db(t["token_sent_at"])).total_seconds() < 60:
                    return 429, {"error": "Код уже отправлен — новый можно запросить через минуту", "verify": True}, None
                self.store.update_trainer(t["id"], name=name, team=team, password_hash=self.hash_password(pwd))
            else:
                self.store.add_trainer(name, team, email, self.hash_password(pwd))
            t = self.store.trainer_by_email(email)
            ctext = self.trainer_consent_text()
            chash = hashlib.sha256(ctext.encode("utf-8")).hexdigest()[:16]
            self.store.save_consent_text(chash, "Тренер · личный кабинет", ctext)
            self.store.update_trainer(t["id"], consent_accepted=1, consent_at=fmt_db(now_local()),
                                      consent_hash=chash, policy_hash=self.privacy_hash())
            sent = self._issue_code(t)
            self.store.audit(f"тренер {email}@{ip}", None, "Тренер: регистрация",
                             f"{name} · {team}" + ("" if sent else " · почта не настроена, нужно подтверждение администратора"))
            return 200, {"ok": True, "email": email, "sent": sent}, None
        if sub == "resend":
            if not (self._rate_ok("tres-ip:" + ip, 10, 3600) and self._rate_ok("tres-e:" + email, 5, 3600)):
                return 429, {"error": "Слишком много запросов кода. Попробуйте через час."}, None
            t = self.store.trainer_by_email(email)
            if not t or t["is_verified"]:
                return 400, {"error": "Для этой почты код не нужен: зарегистрируйтесь или войдите"}, None
            if t.get("token_sent_at") and (now_local() - parse_db(t["token_sent_at"])).total_seconds() < 60:
                return 429, {"error": "Код уже отправлен — новый можно запросить через минуту"}, None
            return 200, {"ok": True, "sent": self._issue_code(t)}, None
        if sub == "verify":
            if not (self._rate_ok("tver-ip:" + ip, 30, 600) and self._rate_ok("tver-all", 300, 600)):
                return 429, {"error": "Слишком много попыток. Подождите 10 минут."}, None
            code = re.sub(r"\D", "", str(d.get("code") or ""))[:6]
            t = self.store.trainer_by_email(email)
            if not t:
                return 400, {"error": "Неверная почта или код"}, None
            if not t.get("active", 1):
                return 403, {"error": "Учётная запись заблокирована — обратитесь к организатору"}, None
            if not t["is_verified"]:
                if not t.get("verification_token") or not t.get("token_expires") or now_local() > parse_db(t["token_expires"]):
                    return 400, {"error": "Код устарел — нажмите «Отправить код ещё раз»", "expired": True}, None
                if int(t.get("token_attempts") or 0) >= self.CODE_TRIES:
                    return 429, {"error": "Слишком много неверных попыток — запросите новый код", "expired": True}, None
                if len(code) != 6 or not hmac.compare_digest(self._code_hash(email, code), t["verification_token"]):
                    left = self.CODE_TRIES - int(t.get("token_attempts") or 0) - 1
                    self.store.update_trainer(t["id"], token_attempts=int(t.get("token_attempts") or 0) + 1)
                    return 400, {"error": "Неверный код" + (f" — осталось попыток: {left}" if left > 0 else " — запросите новый")}, None
                self.store.update_trainer(t["id"], is_verified=1, verification_token=None, token_expires=None,
                                          verified_at=fmt_db(now_local()), verified_by="код из письма")
                self.store.audit(f"тренер {email}@{ip}", None, "Тренер: почта подтверждена", f"{t['name']} · {t['team']}")
            t = self.store.trainer_by_email(email)
            return 200, {"ok": True, "name": t["name"]}, self._trainer_session(t, headers, ip)
        if sub == "login":
            pwd = str(d.get("password") or "")[:200]
            if not (self._rate_ok("tlog-ip:" + ip, 10, 600) and self._rate_ok("tlog-e:" + email, 10, 600)
                    and self._rate_ok("login-all", 200, 600)):
                return 429, {"error": "Слишком много попыток. Подождите 10 минут."}, None
            t = self.store.trainer_by_email(email) if email and pwd else None
            if not t or not self.verify_password(pwd, t["password_hash"]):
                self.store.audit(f"тренер {email or '?'}@{ip}", None, "Тренер: неудачный вход")
                return 401, {"error": "Неверная почта или пароль"}, None
            if not t.get("active", 1):
                return 403, {"error": "Учётная запись заблокирована — обратитесь к организатору"}, None
            if not t["is_verified"]:
                return 403, {"error": "Почта ещё не подтверждена — введите код из письма", "verify": True}, None
            self.store.audit(f"тренер {email}@{ip}", None, "Тренер: вход")
            return 200, {"ok": True, "name": t["name"], "next": self._safe_next(d.get("next"))}, \
                self._trainer_session(t, headers, ip)
        return 404, {"error": "нет такого адреса"}, None
```

### `Hub.send_mail` — `hub/hub.py` строки 5196–5235

```python
    def send_mail(self, to: str, subject: str, text: str) -> bool:
        """Письмо отправляется в отдельном потоке — приём отметок и страницы не ждут почтовый сервер."""
        from email.message import EmailMessage
        import secrets
        import threading
        m = self.cfg.get("mail") or {}
        mode = self.mail_mode()
        if not mode:
            return False
        msg = EmailMessage()
        msg["From"] = m.get("from") or m.get("user") or "SakhStart <noreply@localhost>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if mode == "outbox":
            os.makedirs(m["outbox_dir"], exist_ok=True)
            fn = os.path.join(m["outbox_dir"], f"{now_local():%Y%m%d-%H%M%S}-{secrets.token_hex(4)}.eml")
            with open(fn, "wb") as fh:
                fh.write(bytes(msg))
            return True

        def run():
            import smtplib
            import ssl
            try:
                port = int(m.get("port") or 587)
                sec = str(m.get("security") or ("ssl" if port == 465 else "starttls"))
                ctx = ssl.create_default_context()
                srv = (smtplib.SMTP_SSL(m["host"], port, timeout=20, context=ctx) if sec == "ssl"
                       else smtplib.SMTP(m["host"], port, timeout=20))
                with srv as s:
                    if sec == "starttls":
                        s.starttls(context=ctx)
                    if m.get("user"):
                        s.login(m["user"], m.get("password") or "")
                    s.send_message(msg)
            except Exception as e:  # сеть, авторизация, отказ сервера
                log.warning("Почта: письмо не отправлено: %s", e)
        threading.Thread(target=run, daemon=True).start()
        return True
```

### `Hub.protocol_viewer` — `hub/hub.py` строки 5297–5302

```python
    def protocol_viewer(self, headers: dict) -> Optional[dict]:
        """Кто может смотреть протоколы: администратор, судья или тренер с подтверждённой почтой."""
        u = self.session_user(headers)
        if not u:
            return None
        return u if u["role"] == "trainer" or self._role(u["role"]) in ("admin", "judge") else None
```

### `Hub.role_allows` — `hub/hub.py` строки 5132–5142

```python
    def role_allows(self, role: str, method: str, path: str) -> bool:
        if role == "trainer":
            return path in self.TRAINER_PANEL
        role = self._role(role)
        if role == "admin":
            return True
        if path in self.JUDGE_OPEN:
            return True
        if self.ADMIN_ONLY.fullmatch(path):
            return False
        return not (method == "POST" and self.JUDGE_DENY_POST.fullmatch(path))
```


## 5. HTML / JavaScript / CSS дословно

### 5.1 `hub/reg.html` — публичный модуль «Участники» (окно `/r/<slug>/participants`)

**CSS модуля и адаптивной кнопки:**

```css
a.btn.pbtn{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:4px;width:min(640px,calc(100% - 32px));box-sizing:border-box;margin:14px auto;padding:14px 18px;font-size:18px;line-height:1.25}
a.btn.pbtn small{font-weight:500;font-size:13px;opacity:.9;max-width:34em}
@media(max-width:480px){a.btn.pbtn{font-size:17px;padding:14px 12px}}
.pl h2{font-size:22px;margin:0 0 10px}.pl-ctl{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px 14px;margin-bottom:10px}
.pl input#pQ{display:block;font:inherit;font-size:16px;color:var(--ink);background:var(--field);border:1px solid var(--field-line);border-radius:var(--r);padding:11px 12px;min-height:48px;width:100%;box-sizing:border-box}
.pl .pl-tabs{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
.pl .pl-tabs button{width:auto;min-height:40px;margin:0;padding:8px 14px;border-radius:99px;border:1px solid var(--field-line);background:var(--panel);color:var(--ink);font:600 14px/1.2 var(--body)}
.pl .pl-tabs button:hover{background:var(--soft)}
.pl .pl-tabs button i{font-style:normal;font-weight:700;margin-left:6px;padding:1px 7px;border-radius:99px;background:var(--soft);color:var(--ink);font-size:12px}
.pl .pl-tabs button.on{background:#0B1D37;border-color:#0B1D37;color:#fff}.pl .pl-tabs button.on i{background:#E71E25;color:#fff}
.pl .pl-tabs.ages button{font-weight:500;min-height:34px;padding:5px 12px}
.pl-cnt{margin:8px 0 4px;font-size:14px}.pl-tbl{width:100%;border-collapse:collapse;font-size:14px;line-height:1.25}.pl-tbl th{text-align:left;font-size:12px;color:var(--muted);font-weight:600;padding:4px 6px;border-bottom:1px solid var(--line)}
.pl-tbl td{padding:4px 6px;border-top:1px solid var(--line);text-align:left;vertical-align:top}.pl-tbl .no{width:32px;color:var(--muted);font-variant-numeric:tabular-nums}.pl-tbl .nm{font-weight:700;color:var(--ink)}
.pl-tbl .na{color:var(--muted)}.pl-tbl .bb{width:110px;font-weight:700;font-variant-numeric:tabular-nums}
@media(max-width:700px){.pl-tbl thead{display:none}.pl-tbl,.pl-tbl tbody{display:block}.pl-tbl tr{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 10px;position:relative;padding:6px 0 6px 36px;border-top:1px solid var(--line)}.pl-tbl td{border:0;padding:0}.pl-tbl td.no{position:absolute;left:0;top:6px;width:30px}.pl-tbl td.nm{order:1;width:100%;font-size:15px}.pl-tbl td.bb{order:2;width:auto;font-size:13px}.pl-tbl td.bb::before{content:'№ '}.pl-tbl td.yr{order:3}.pl-tbl td.co{order:4}.pl-tbl td.yr,.pl-tbl td.co{font-size:13px;color:var(--muted)}.pl-tbl td.yr:has(.na),.pl-tbl td.co:has(.na){display:none}.pl-tbl td.yr::after{content:' г.р.'}.pl-tbl td.co::before{content:'тренер: '}.pl-tbl td:empty{display:none}.pl-tbl td.yr:empty::after,.pl-tbl td.co:empty::before{content:none}}
.pl-h3{margin:16px 0 6px;font-size:16px}.pl-rel{list-style:none;margin:0;padding:0}.pl-rel li{padding:8px 0;border-top:1px solid var(--line)}
```

**Кнопка на главной странице (фрагмент `layout()`) и страница модуля:**

```javascript
function layout(){
  const d=INFO,c=CARD;
  const regFirst=d.open&&c.status==="planned"&&!c.results;
  const ev=eventBlock(regFirst);
  let reg="";
  if(d.open) reg=(ev&&!regFirst?'<h2 class="sect">Регистрация</h2>':"")+(d.info?`<div class="info">${esc(d.info)}</div>`:"")+'<section id="regbox"></section>';
  else if(c.status==="planned"&&c.ours!==false) reg=`<div class="card state calm"><span class="ic" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></span><div><b>Приём заявок пока не открыт</b><div class="muted">Регистрация появится на этой странице — следите за новостями федерации.</div></div></div>`;
  else if(c.reg&&c.status!=="finished") reg=`<div class="card state calm"><span class="ic" aria-hidden="true"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></span><div><b>${esc(d.reason||"Регистрация закрыта")}</b><div class="muted">Вопросы — к организатору соревнований.</div></div></div>`;
  const about=aboutBlock();
  const part=d.regs_public?`<a class="btn pbtn" id="participantsLink" href="/r/${esc(slug)}/participants">👥 Участники соревнований<small>кто уже заявился: по дисциплинам, полу и возрасту</small></a>`:"";
  const empty=!ev&&!reg&&!about&&!d.regs_public?'<div class="card muted">Стартовый протокол, результаты и документы появятся на этой странице.</div>':"";
  const cov=href(c.cover);
  $("root").innerHTML=headerCard()+(cov?`<div class="cover"><img src="${esc(cov)}" alt="" loading="lazy" onerror="this.parentNode.remove()"></div>`:"")
    +part+(regFirst?reg+ev:ev+reg)+about+empty;
  lockHint();
  if(d.open) render();
}
```

`participantsPage` — `hub/reg.html` строки 500–507
```javascript
function participantsPage(){
  const d=INFO;
  document.title="Участники — "+d.name; $("root").classList.add("wide");
  $("root").innerHTML=band(`<h1>${esc(d.name)}</h1>`)+`<a class="back" href="/r/${esc(slug)}">← К странице соревнования</a>
    <section class="card pl pl-wide" id="participants" aria-labelledby="plH"><h2 id="plH">👥 Участники соревнований</h2>
    <div id="plBody" class="muted">${d.regs_public?"Загружаю список…":"Список заявленных участников пока не опубликован организатором."}</div></section>`;
  if(d.regs_public) loadParticipants();
}
```

Весь JS модуля участников (`PL`, `PS`, `loadParticipants`, `plRefresh`, `plRows`, `drawPl`, обработчики) — `hub/reg.html` строки 595–649:

```javascript
// 7.2: открытый модуль «Заявленные участники» (по образцу списков MyRace): дисциплина → пол → возрастная группа → сквозной список
let PL=null; const PS={d:"",s:"",g:"",q:"",n:100};
async function loadParticipants(){
  const box=$("plBody"); if(!box) return;
  try{ const r=await fetch(`/r/${slug}/participants.json`); if(!r.ok) throw new Error("нет"); PL=await r.json();
    PS.d=(PL.disciplines.find(x=>x.count)||PL.disciplines[0]||{}).name||""; drawPl(true); if(!plTimer){ plTimer=setInterval(()=>{ if(!document.hidden) plRefresh(); },20000); } }
  catch(e){ const s=$("participants"); if(s) s.remove(); }
}
let plTimer=null;
async function plRefresh(){ // 7.4: номера и состав обновляются сами — правки секретариата видны без перезагрузки
  try{ const r=await fetch(`/r/${slug}/participants.json`,{cache:"no-store"}); if(!r.ok) return; const n=await r.json();
    if(JSON.stringify(n.rows)!==JSON.stringify(PL&&PL.rows)){ PL=n; if(!PL.disciplines.some(x=>x.name===PS.d)) PS.d=(PL.disciplines[0]||{}).name||""; drawPl(!document.activeElement||document.activeElement.id!=="pQ"&&document.activeElement.id!=="pDisc"); } }catch(e){}
}
function plRows(skip){ // строки с учётом выбора; skip — какой фильтр не применять (для счётчиков вкладок)
  return PL.rows.filter(x=>x.d===PS.d&&(skip==="s"||!PS.s||x.s===PS.s)&&(skip==="g"||!PS.g||x.g===PS.g)&&(!PS.q||x.n.toLowerCase().includes(PS.q.toLowerCase())||String(x.b||"")===PS.q.trim()));
}
function drawPl(full){
  const box=$("plBody"), d=PL; if(!box||!d) return;
  if(full||!$("plList")){
    box.innerHTML=`<div class="pl-ctl"><div><label class="f" for="pDisc">Дисциплина</label>
        <select id="pDisc" class="sel">${d.disciplines.map(x=>`<option value="${esc(x.name)}"${x.name===PS.d?" selected":""}>${esc(x.name)} · ${x.count}</option>`).join("")}</select></div>
      <div><label class="f" for="pQ">Найти по фамилии или номеру</label><input id="pQ" class="sel" type="search" autocomplete="off" placeholder="например, Иванов или 125" value="${esc(PS.q)}"></div></div>
      <div class="pl-tabs" role="tablist" aria-label="Пол" id="pSex"></div>
      <div class="pl-tabs ages" role="group" aria-label="Возрастная группа" id="pAge"></div>
      <div class="muted pl-cnt" id="plCnt" role="status" aria-live="polite"></div><div id="plList"></div>`;
  }
  const bySex=x=>plRows("s").filter(r=>!x||r.s===x).length;
  $("pSex").innerHTML=[["","Все"],["М","М"],["Ж","Ж"]].map(([v,t])=>`<button type="button" role="tab" aria-selected="${PS.s===v}" class="${PS.s===v?"on":""}" data-ps="${v}">${t} <i>${bySex(v)}</i></button>`).join("");
  const ageCnt=g=>plRows("g").filter(r=>!g||r.g===g).length;
  $("pAge").innerHTML=d.ages.length?[["","Все возрасты"],...d.ages.map(a=>[a.id,a.name])].map(([v,t])=>`<button type="button" aria-pressed="${PS.g===v}" class="${PS.g===v?"on":""}" data-pg="${esc(v)}">${esc(t)} <i>${ageCnt(v)}</i></button>`).join(""):"";
  const rows=plRows(), shown=rows.slice(0,PS.n);
  $("plCnt").textContent=`Заявлено: ${rows.length} · всего в этой дисциплине: ${PL.rows.filter(x=>x.d===PS.d).length} · обновлено ${d.updated}`;
  $("plList").innerHTML=(shown.length?`<table class="pl-tbl"><thead><tr><th class="no">№</th><th>Нагрудный №</th><th>Фамилия Имя</th><th>Год рождения</th><th>Тренер</th></tr></thead><tbody>${shown.map((x,i)=>`<tr><td class="no">${i+1}</td><td class="bb">${esc(x.b)}</td><td class="nm">${esc(x.n)}</td><td class="yr">${x.y?esc(x.y):'<span class="na">—</span>'}</td><td class="co">${x.c?esc(x.c):'<span class="na">—</span>'}</td></tr>`).join("")}</tbody></table>`
    :'<div class="muted" style="padding:12px 0">Никого не найдено. Если спортсмена нет в списке, заявка ещё не одобрена секретарём или не подана.</div>')
    +(rows.length>shown.length?`<button type="button" class="ghost" id="plMore" style="margin-top:10px">Показать ещё (${rows.length-shown.length})</button>`:"")
    +(d.relays&&d.relays.length&&!PS.q?`<h3 class="pl-h3">Эстафетные команды</h3><ul class="pl-rel">${d.relays.filter(x=>!PS.d||x.discipline===PS.d).map(x=>`<li><b>${esc(x.team)}</b> <span class="muted">· ${esc(x.discipline)}</span></li>`).join("")}</ul>`:"");
}
document.addEventListener("click",e=>{
  const b=e.target.closest&&e.target.closest("[data-ps],[data-pg],#plMore"); if(!b||!PL) return;
  if(b.id==="plMore") PS.n+=100; else if(b.dataset.ps!==undefined){ PS.s=b.dataset.ps; PS.n=100; } else { PS.g=b.dataset.pg; PS.n=100; }
  drawPl(false);
});
document.addEventListener("input",e=>{ if(e.target&&e.target.id==="pQ"){ PS.q=e.target.value; PS.n=100; drawPl(false); } });
document.addEventListener("change",e=>{ if(e.target&&e.target.id==="pDisc"){ PS.d=e.target.value; PS.s=PS.g=""; PS.n=100; drawPl(false); } });
// программа дня и контакты организатора
function aboutBlock(){
  const c=CARD, prog=Array.isArray(c.program)?c.program.filter(p=>p&&p.title):[], cont=Array.isArray(c.contacts)?c.contacts.filter(x=>x&&x.text):[];
  const ico=h=>/^tel:/.test(h)?'<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/>'
    :/^mailto:/.test(h)?'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>':IC.link;
  const link=x=>{const h=/^(tel:|mailto:)/.test(x.href||"")?x.href:href(x.href);
    return h?`<a href="${esc(h)}"${isExt(h)?' target="_blank" rel="noopener"':""}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ico(h)}</svg>${esc(x.text)}</a>`:`<span>${esc(x.text)}</span>`;};
  return (prog.length?`<div class="card"><h2>Программа</h2><dl class="prog">${prog.map(p=>`<dt>${esc(p.time||"")}</dt><dd>${esc(p.title)}</dd>`).join("")}</dl></div>`:"")
    +(cont.length?`<div class="card"><h2>Контакты организатора</h2><div class="cont">${cont.map(link).join("")}</div></div>`:"");
}
// куда рисовать форму: на странице события — в блок регистрации, иначе (старый сервер) — вся страница
```

### 5.2 `hub/board.html` — табло: автопрокрутка, 6 попыток, заступы (целиком)

```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Табло финиша</title>
<link rel="stylesheet" href="/assets/brand.css">
<style>
/* Табло у финиша: тёмно-синий фон, крупный Oswald, масштаб от размера экрана (TV/проектор). */
:root{color-scheme:dark;
  --bd-bg:var(--night);--bd-ink:#fff;--bd-muted:var(--night-muted);--bd-line:var(--night-line);
  --bd-pad:clamp(16px,2.6vw,56px);
  /* строка результатов: влезают 10 строк по высоте и ширине экрана */
  --bd-row:clamp(18px,min(3.5vw,4.55vh),80px)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bd-bg);color:var(--bd-ink);font-family:var(--body)}
body{overflow:hidden;-webkit-font-smoothing:antialiased}
.wrap{display:flex;flex-direction:column;height:100%}

/* Верхняя полоса: логотип SakhStart · название · часы, под ней красная линия 3px */
.top{display:flex;align-items:center;gap:clamp(14px,2vw,40px);padding:clamp(10px,1.6vh,26px) var(--bd-pad);border-bottom:3px solid var(--track);flex-wrap:wrap}
.top .lg-ss{display:block;height:clamp(30px,3.4vw,72px);width:auto;flex:none}
.ttl{flex:1 1 30%;min-width:0}
.name{font:600 clamp(20px,2.6vw,56px)/1.1 var(--head);letter-spacing:.005em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.meta{margin-top:.25em;color:var(--bd-muted);font-size:clamp(13px,1.15vw,24px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.meta:empty{display:none}
.clock{margin-left:auto;min-width:4.1em;text-align:right;font:600 clamp(40px,6.2vw,132px)/1 var(--head);font-variant-numeric:tabular-nums;letter-spacing:-.005em;white-space:nowrap}
.clock.idle{min-width:0;color:var(--bd-muted);font-weight:500;font-size:clamp(20px,2.4vw,52px)}

/* Список последних финишировавших */
main{flex:1;min-height:0;display:flex;flex-direction:column;padding:clamp(8px,1.6vh,26px) var(--bd-pad) 0}
h2{margin:0 0 .5em;font:500 clamp(13px,1.15vw,24px)/1.2 var(--head);color:var(--bd-muted);letter-spacing:.06em}
.list{flex:1;min-height:0;overflow:hidden}
.r,.hd{position:relative;display:grid;grid-template-columns:2.4em 2.9em minmax(0,1fr) minmax(0,.62fr) 4.6em;align-items:center;column-gap:.55em;
  padding:.11em .3em;border-bottom:1px solid var(--bd-line);font:500 var(--bd-row)/1.2 var(--head);font-variant-numeric:tabular-nums}
.r>span{position:relative;z-index:1;min-width:0}
.r .p{color:var(--bd-muted)}
.r .b{color:var(--start);font-weight:600}
.r .n{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.r .t{text-align:right;font-weight:600;white-space:nowrap}
.r .d{color:var(--bd-muted);font-size:.62em;line-height:1.15;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* подписи колонок */
.hd{font:500 var(--bd-row)/1.2 var(--head);color:var(--bd-muted);padding:0 .3em .1em;border-bottom:2px solid var(--bd-line);align-items:end}
.hd span{font-size:max(12px,.36em);letter-spacing:.04em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hd span:last-child{text-align:right}
.hd.hide{display:none}
/* самый свежий финишёр — верхняя строка: красная растяжка в прозрачность */
.r:first-child{background:linear-gradient(90deg,rgba(231,30,37,.42),rgba(231,30,37,.12) 45%,transparent 85%);box-shadow:inset 4px 0 0 var(--track)}
/* вспышка при появлении нового результата */
.r.new::after{content:"";position:absolute;inset:0;background:var(--track);opacity:0;animation:flash 1.4s ease-out}
@keyframes flash{from{opacity:.6}to{opacity:0}}
.r.top .p{color:var(--start);font-weight:700}
.none{padding:.6em 0;color:var(--bd-muted);font:500 clamp(18px,2.4vw,48px)/1.2 var(--head)}
body[data-mode=fixed] .r:first-child,body[data-mode=rotate] .r:first-child{background:none;box-shadow:none}
/* техника: столбец «Попытки» — шесть микро-ячеек через вертикальную черту; X — красный, «–» и r — серые, лучшая — белая */
body[data-tech="1"] .r,body[data-tech="1"] .hd{grid-template-columns:2.4em 2.9em minmax(0,1fr) 11.4em 4.6em}
.att{display:grid;grid-template-columns:repeat(var(--n,6),1fr);font-size:calc(.56em * 6 / max(6, var(--n,6)));line-height:1.5;font-variant-numeric:tabular-nums;
  border:1px solid var(--bd-line);border-radius:4px;overflow:hidden}
.att i{font-style:normal;text-align:center;padding:0 .2em;color:#C9D3E3;white-space:nowrap;border-left:1px solid var(--bd-line)}
.att i:first-child{border-left:0}
.att i.x{color:#FF5A5F;font-weight:700;background:rgba(231,30,37,.14)}
.att i.s{color:var(--bd-muted)}
.att i.e{color:var(--bd-line)}
.att i.best{color:#fff;font-weight:700;background:rgba(255,255,255,.1);box-shadow:inset 0 -2px 0 var(--start)}
/* длинная таблица: шапка на месте, лента участников плавно едет вниз и возвращается к лидерам */
.track{will-change:transform}
.list.fade-b{-webkit-mask-image:linear-gradient(to bottom,#000 calc(100% - 1.6em),transparent);mask-image:linear-gradient(to bottom,#000 calc(100% - 1.6em),transparent)}
.track:empty::before{content:"Финишировавших пока нет";display:block;padding:.6em 0;color:var(--bd-muted);font:500 clamp(18px,2.4vw,48px)/1.2 var(--head)}

/* Низ: подпись и логотипы Сахалин → ФЛАСО */
.foot{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:clamp(8px,1.4vh,22px) var(--bd-pad);color:var(--bd-muted);font-size:clamp(12px,1vw,20px)}
.foot .logos{gap:clamp(12px,1.2vw,26px)}
.foot .logos .lg-sakh{height:clamp(30px,4.6vh,64px)}
.foot .logos .lg-flaso{height:clamp(26px,3.9vh,54px)}
.foot .logos .lg-sep{height:clamp(22px,3vh,42px)}

:focus-visible{outline:3px solid var(--start);outline-offset:3px}
@media (max-width:640px){.top .lg-ss{display:none}.clock{margin-left:0;width:100%}.foot .txt{display:none}.foot{justify-content:flex-end}}
@media (prefers-reduced-motion:reduce){.r.new::after{animation:none}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <img class="lg-ss" src="/assets/sakhstart-dark.svg" alt="SakhStart">
    <div class="ttl"><div class="name" id="name">Табло</div><div class="meta" id="meta"></div></div>
    <div class="clock idle" id="clock">ожидание старта</div>
  </header>
  <main>
    <h2 id="title">Последние финишировавшие — новые сверху</h2>
    <div class="hd hide" id="hd"><span id="hdPlace">Место</span><span>Номер</span><span>Участник</span><span id="hdD">Дисциплина</span><span>Результат</span></div>
    <div class="list" id="list"><div class="track" id="track"></div></div>
  </main>
  <footer class="foot">
    <span class="txt">Предварительные результаты · F11 — во весь экран</span>
    <span class="logos"><img class="lg-sakh" src="/assets/sakhalin-light.png" alt="Сахалин"><span class="lg-sep"></span><img class="lg-flaso" src="/assets/flaso-dark.png" alt="ФЛАСО"></span>
  </footer>
</div>
<script>
"use strict";
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const eid=new URLSearchParams(location.search).get("event");
let offset=0,startMs=null,seen=new Set(),first=true;
function fmt(ms){const n=ms<0;ms=Math.abs(ms);const t=Math.floor(ms/100),h=Math.floor(t/36000),m=Math.floor(t%36000/600),s=Math.floor(t%600/10),d=t%10;
  return (n?"-":"")+h+":"+String(m).padStart(2,"0")+":"+String(s).padStart(2,"0")+"."+d;}
async function get(p){const r=await fetch(p,{headers:{"X-Requested-With":"timing-hub"}});if(r.status===401){location.href="/login?next="+encodeURIComponent(location.pathname+location.search);throw new Error(401);}if(!r.ok)throw new Error(r.status);return r.json();}
const MON=["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"];
const dRu=d=>{const m=/^(\d{4})-(\d\d)-(\d\d)/.exec(d||"");return m?`${+m[3]} ${MON[+m[2]-1]} ${m[1]}`:(d||"");};
async function sync(){try{const c=await get("/api/clock");offset=c.server_epoch_ms-Date.now();}catch(e){}}
// Табло слушается пульта (/scoreboard): auto — последние результаты, fixed — таблица лидеров одной группы,
// rotate — группы по кругу. Состояние спрашивается у сервера раз в 1,5 с, страница не перезагружается.
let SB={mode:"auto"}, lastKey="";
const PER_PAGE=10;
// Автопрокрутка длинной таблицы лидеров: топ стоит HOLD_TOP, затем лента плавно и равномерно едет вниз
// до последнего участника, стоит HOLD_END и мягко возвращается к лидерам — по кругу. Шрифт не уменьшается.
// Если в системе включено «уменьшить движение» — вместо плавной ленты листаем экранами раз в 8 с.
const HOLD_TOP=7000, HOLD_END=4000, BACK=1400, ROWS_PER_S=0.6, STEP_MS=8000;
const RM=matchMedia("(prefers-reduced-motion: reduce)");
const SC={on:false,t0:performance.now()};
function scrollY(over,row,vis){
  const t=performance.now()-SC.t0;
  if(RM.matches){const step=Math.max(row,Math.floor(vis/row)*row),n=Math.ceil(over/step)+1;return Math.min(over,Math.floor(t/STEP_MS)%n*step);}
  const run=over/(row*ROWS_PER_S)*1000,k=t%(HOLD_TOP+run+HOLD_END+BACK);
  if(k<HOLD_TOP)return 0;
  if(k<HOLD_TOP+run)return over*(k-HOLD_TOP)/run;
  if(k<HOLD_TOP+run+HOLD_END)return over;
  const b=(k-HOLD_TOP-run-HOLD_END)/BACK;return over*(1-(1-Math.pow(1-b,3)));
}
function frame(){
  const box=$("list"),tr=$("track"),over=SC.on?Math.max(0,tr.scrollHeight-box.clientHeight):0;
  let y=0;
  if(over>2){const r0=tr.querySelector(".r");y=scrollY(over,r0?r0.offsetHeight:40,box.clientHeight);}
  tr.style.transform=y?`translateY(${-y.toFixed(1)}px)`:"";
  const fb=over>2&&y<over-2; if(box.classList.contains("fade-b")!==fb)box.classList.toggle("fade-b",fb);
  requestAnimationFrame(frame);
}
// попытки: 6 ячеек (или сколько положено виду), X — заступ, «–» — пропуск, r — отказ, лучшая подсвечена
const nv=v=>String(v??"").replace(",",".").trim();
function attCells(x){
  const a=(x.attempts||[]).slice(),n=Math.max(6,a.length);while(a.length<n)a.push("");
  const best=nv(x.result);let hit=false;
  return `<span class="att" style="--n:${n}" aria-label="Попытки: ${esc(a.map(v=>v||"нет").join(", "))}">${a.map(v=>{const s=nv(v);
    if(!s)return '<i class="e">·</i>';
    if(/^[xх]$/i.test(s))return '<i class="x">X</i>';
    if(/^[-–—]$/.test(s))return '<i class="s">–</i>';
    if(/^[rр]$/i.test(s))return '<i class="s">r</i>';
    if(!hit&&s===best){hit=true;return `<i class="best">${esc(s)}</i>`;}
    return `<i>${esc(s)}</i>`;}).join("")}</span>`;
}
function renderAuto(r,hasW){
  SC.on=false; lastKey=""; document.body.dataset.tech="";
  $("title").textContent="Последние результаты — новые сверху";
  $("hdPlace").textContent=hasW?"Место в забеге":"Место"; $("hdD").textContent="Дисциплина";
  // свежие сверху: финиш по судье или время ввода результата с сектора (метания, прыжки, секундомеры)
  const last=r.finished.slice().sort((a,b)=>(b.finish_epoch_ms||b.entered_epoch_ms||0)-(a.finish_epoch_ms||a.entered_epoch_ms||0)).slice(0,PER_PAGE);
  $("hd").classList.toggle("hide",!last.length);
  $("track").innerHTML=last.map(x=>{const k=x.bib+x.time+x.result,isNew=!first&&!seen.has(k);seen.add(k);
    const disc=[x.distance,x.category].filter(Boolean).join(" · ")||x.wave||"";
    return `<div class="r ${isNew?"new":""}"><span class="p">${x.place}</span><span class="b">${esc(x.bib||"")}</span><span class="n">${esc(x.name||"")}</span><span class="d">${esc(disc)}${hasW&&x.wave&&disc!==x.wave?`<br>${esc(x.wave)}`:""}</span><span class="t">${esc(x.result||x.time)}</span></div>`;}).join("");
}
// таблица лидеров одной группы: от 1-го места до последнего; не влезает — плавная автопрокрутка (frame)
function renderGroup(r,key,suffix){
  const [d,c]=key.split("|"), tech=r.finished.some(x=>x.distance===d&&(x.rt==="distance"||x.rt==="height"||(x.attempts||[]).length));
  const list=r.finished.filter(x=>(x.distance||"")===d&&(x.category||"")===c).sort((a,b)=>(a.place_overall||999)-(b.place_overall||999));
  if(key!==lastKey){SC.t0=performance.now();lastKey=key;}
  SC.on=true; document.body.dataset.tech=tech?"1":"";
  $("title").textContent=`${[d,c].filter(Boolean).join(" · ")} — таблица лидеров${list.length>PER_PAGE?` · ${list.length} участников`:""}${suffix||""}`;
  $("hdPlace").textContent="Место"; $("hdD").textContent=tech?"Попытки":"Команда";
  $("hd").classList.toggle("hide",!list.length);
  $("track").innerHTML=list.map(x=>{const k=key+x.bib+x.result,isNew=!first&&!seen.has(k);seen.add(k);
    return `<div class="r ${isNew?"new":""}${x.place_overall<=3?" top":""}"><span class="p">${x.place_overall}</span><span class="b">${esc(x.bib)}</span><span class="n">${esc(x.name||"")}</span>${tech?attCells(x):`<span class="d">${esc(x.team||"")}</span>`}<span class="t">${esc(x.result||x.time)}</span></div>`;}).join("")
    ||`<div class="none">В группе «${esc([d,c].filter(Boolean).join(" · "))}» результатов пока нет</div>`;
}
async function load(){
  if(!eid){$("name").textContent="Не выбрано соревнование";return;}
  try{
    const [r,st]=await Promise.all([get(`/api/events/${encodeURIComponent(eid)}/results`),get(`/api/scoreboard/state?event=${encodeURIComponent(eid)}`).catch(()=>SB)]);
    SB=st||SB;
    const ev=r.event; startMs=SB.mode==="auto"?ev.start_epoch_ms:null;
    $("name").textContent=ev.name;
    $("meta").textContent=[dRu(ev.date),ev.place,`результатов: ${r.finished.length}`].filter(Boolean).join(" · ");
    const hasW=(ev.waves||[]).length>0;
    document.body.dataset.mode=SB.mode;
    if(SB.mode==="fixed"&&SB.group) renderGroup(r,SB.group,"");
    else if(SB.mode==="rotate"&&SB.rotate&&SB.rotate.groups.length){
      // все табло на стадионе показывают одну и ту же группу: номер слайда считается от времени сервера
      const g=SB.rotate.groups, iv=(SB.rotate.interval||15)*1000, i=Math.floor((Date.now()+offset)/iv)%g.length;
      renderGroup(r,g[i],` · ${i+1} / ${g.length}`);
    } else renderAuto(r,hasW);
    first=false;
  }catch(e){$("meta").textContent="нет связи с сервером…";}
}
function tick(){const c=$("clock");
  if(SB.mode!=="auto"){c.classList.remove("idle");const t=new Date(Date.now()+offset);c.textContent=t.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});return;}
  if(startMs){c.classList.remove("idle");c.textContent=fmt(Date.now()+offset-startMs);}else{c.classList.add("idle");c.textContent="ожидание старта";}}
sync();load();requestAnimationFrame(frame);setInterval(tick,100);setInterval(load,1500);setInterval(sync,60000);
</script>
</body>
</html>
```

### 5.3 `hub/ui.html` — Мастер протоколов (`wzp`, шаги 1–5), целиком

`hub/ui.html` строки 1752–2222. Шаги: 1 «Участники» (фильтры), 2 «Нагрудные номера» (ввод вручную, живая проверка, сохранение одним запросом), 3 «Стартовые протоколы» (сетка, Excel, «⚡ Сформировать ВСЕ»), 4 «Ввод результатов», 5 «Итоговый протокол».

```javascript
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
  // 7.5.1: шаг 1 — сводка по дисциплине (только чтение из базы, без кнопок-фильтров): состав, пол, возрастные группы, номера
  function ageGroupOf(r){
    const e = ev(), y = e && e.date ? +e.date.slice(0, 4) : new Date().getFullYear(), age = y - (+String(r.birth_date || r.birth_year || "").slice(0, 4) || 0);
    const gs = (DISC.ages || []).filter(a => a.id !== "sen").sort((a, b) => a.max - b.max).concat((DISC.ages || []).filter(a => a.id === "sen"));
    return (gs.find(a => age >= a.min && age <= a.max) || {}).id || ""; }
  function step1(body, k){
    const mine = W.regs.filter(r => r.distance === W.disc), ok = mine.filter(r => r.status === "approved");
    const pend = mine.filter(r => r.status === "pending").length;
    const boys = ok.filter(r => String(r.sex || "").toUpperCase() === "М").length, girls = ok.filter(r => String(r.sex || "").toUpperCase() === "Ж").length;
    const bands = (DISC.ages || []).map(a => [a, ok.filter(r => ageGroupOf(r) === a.id).length]).filter(x => x[1]);
    const withBib = ok.filter(r => String(r.bib || "").trim()).length;
    const chip = (t, n) => `<span class="ftab stat"><span>${esc(t)}</span> <i>${n}</i></span>`;
    body.innerHTML = `${stepHead(1, k)}
      <div class="card wzp-dash" role="group" aria-label="Сводка по дисциплине">
        <p class="wzp-dash-main"><b>${esc(W.disc)}</b></p>
        <p class="wzp-dash-main">Всего подтверждено: <b>${ok.length} участн.</b> (Мальчиков: ${boys}, Девочек: ${girls})${bands.map(([a, n]) => ` · ${esc(a.name)}: ${n}`).join("")}</p>
        <div class="wzp-filter" aria-label="Структура состава">${chip("Все", ok.length)}${chip("Мальчики", boys)}${chip("Девочки", girls)}<span class="fsep" aria-hidden="true"></span>${bands.map(([a, n]) => chip(a.name, n)).join("")}</div>
        <p class="small muted" style="margin:6px 0 0">Каждый участник учтён один раз — в самой узкой возрастной группе. Это только сводка: выбирать здесь ничего не нужно, в сетку идут все подтверждённые участники дисциплины.</p>
        <p class="small" style="margin:6px 0 0">Нагрудные номера: вписано <b>${withBib}</b> из ${ok.length}${pend ? ` · ещё <b>${pend}</b> заявок ждут проверки во вкладке «Регистрация»` : ""}.</p>
      </div>
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
        <span class="wzp-sync" id="wzpSync" role="status" aria-live="polite">Каждая строка сохраняется сама, как только вы переходите к следующему полю. Отметки можно набрать буквами: днс, днф, дк, нр.</span>
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
  // 7.5: буквенные отметки, набранные в ячейке результата (днс, dns, нс, н/с → DNS; днф, dnf → DNF; dq, дк → DQ; нр, nm → NM),
  // не уходят на сервер как «результат»: поле очищается, в списке «Отметка» ставится статус, строка сразу сохраняется
  const TYPED_STATUS = {"днс":"DNS","dns":"DNS","нс":"DNS","н/с":"DNS","днф":"DNF","dnf":"DNF","dq":"DQ","дк":"DQ","нр":"NM","nm":"NM"};
  function interceptStatus(inp){
    if (!inp || !inp.matches("input.sw, input.att, input.one")) return false;
    const code = TYPED_STATUS[inp.value.replace(/\s+/g, "").toLowerCase()]; if (!code) return false;
    const tr = inp.closest("#wzpRows tr"), sel = tr && tr.querySelector("select.stsel"); if (!sel) return false;
    inp.value = ""; inp.classList.remove("err"); sel.value = code;
    tr.classList.add("dirty"); calcRow(tr); queueAuto(150);
    sync(`Отметка ${code} поставлена для № ${tr.dataset.bib} — сохраняю`, "busy");
    return true; }
  root.addEventListener("change", (e) => {
    if (interceptStatus(e.target)) return;
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
    const tr = e.target.closest("#wzpRows tr"); if (!tr) return;
    if (interceptStatus(e.target)) return;
    tr.classList.add("dirty"); e.target.classList.remove("err");
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
    W.bibDirty = false; W.disc = e.target.value; W.step = 2; W.ages = []; W.sex = ""; save(); render(); load().then(render); };      // участники подтягиваются сами — сразу к номерам
  window.addEventListener("beforeunload", (e) => { if (W.step === 2 && W.bibDirty) { e.preventDefault(); e.returnValue = ""; } });
  // этап «Ввод результатов» стадиона с ручным вводом = шаг 4 Мастера (один экран ввода вместо двух)
  function setStep(n){ const e0 = ev(); if (!e0) return;
    if (W.evId !== e0.id) { W.forceStep = n; return; }        // Мастер ещё не открывался для этого соревнования — шаг применит open()
    W.step = n; save(); }
  return {open, setStep, go, remote, step: () => W.step};
})();
```

### 5.4 Тумблеры публикации на этапе «1. Подготовка» (`hub/ui.html`)

```html
<label class="switch"><input type="checkbox" id="sPubRegs"><i></i>👥 Опубликовать список заявившихся участников на сайте</label>
        <label class="switch" style="margin-top:8px"><input type="checkbox" id="sPubFull"><i></i>Показывать год рождения и тренера у всех (согласия на распространение получены)</label>
        <div class="small muted" style="margin-top:4px">Выключено — для заявок, поданных до появления пункта о публикации в согласии, видно только «Фамилия И.» и команду. Включайте, только если согласие на размещение этих данных в интернете уже получено.
```


## 6. Маршруты API и права доступа

### 6.1 Роли и правила (код дословно)

```python
    ROLES = {"admin": "Администратор", "judge": "Судья"}
```

```python
    # только администратор: сервер и обновления, VPN, учётные записи, сырые отметки
    ADMIN_ONLY = re.compile(r"/api/(system|users|trainers|consents)(/.*)?|/simple")
    JUDGE_OPEN = ("/api/system/scoreboard/control",)                 # пульт табло — судейский, хоть и под /api/system
    JUDGE_DENY_POST = re.compile(r"/api/events/\d+/delete")          # удалить соревнование целиком
```

### `Hub.role_allows` — `hub/hub.py` строки 5132–5142

```python
    def role_allows(self, role: str, method: str, path: str) -> bool:
        if role == "trainer":
            return path in self.TRAINER_PANEL
        role = self._role(role)
        if role == "admin":
            return True
        if path in self.JUDGE_OPEN:
            return True
        if self.ADMIN_ONLY.fullmatch(path):
            return False
        return not (method == "POST" and self.JUDGE_DENY_POST.fullmatch(path))
```

Сводная таблица прав (следует из `role_allows`, `ADMIN_ONLY`, `JUDGE_OPEN`, `JUDGE_DENY_POST`, `TRAINER_PANEL`, `protocol_viewer`):

| Область | admin | judge | trainer | без входа |
|---|---|---|---|---|
| `/api/events/*` (кроме удаления), ввод результатов, номера, сетка | ✅ | ✅ | ✖ | ✖ |
| `POST /api/events/<id>/delete` | ✅ | ✖ | ✖ | ✖ |
| `/api/system/*` (обновление, резервные копии, VPN), `/api/users*`, `/api/trainers*`, `/api/consents*`, `/simple` | ✅ | ✖ | ✖ | ✖ |
| `POST /api/system/scoreboard/control` (пульт табло) | ✅ | ✅ | ✖ | ✖ |
| `/api/me`, `/api/logout`, `/protocol` | ✅ | ✅ | ✅ | ✖ |
| `/r/<slug>` страница, `/info`, `POST` заявка, `/participants`, `/participants.json` (если включена публикация) | ✅ | ✅ | ✅ | ✅ |
| `/r/<slug>/protocol`, `/startlist.json`, `/results.json` | ✅ | ✅ | ✅ (подтверждённая почта) | ✖ (401) |
| `/r/trainer/api/*` (consent, register, verify, resend, login, logout, me, events) | — | — | ✅ | ✅ (первые пять) |
| `/board`, `/api/clock` | экран табло открыт для показа на стадионе | | | см. `_public_route` |

### 6.2 Перечень роутов (автоизвлечение из исходника: строка, шаблон, метод по условию рядом)

Таблица собрана скриптом по литералам `/api/…`, `/r/…` и сравнениям `path ==` / `sub ==` в `hub/hub.py`; метод указан, если он есть в той же строке условия, иначе `GET|POST` (определяется в теле ветки).

| Шаблон | Метод | `hub/hub.py` |
|---|---|---|
| `/api/` | GET | 5654 |
| `/api/` | GET|POST | 5632 |
| `/api/auth/trainer/(consent|register|verify|resend|login|logout|me)` | GET|POST | 5614 |
| `/api/calc` | POST | 2366 |
| `/api/calendar` | GET|POST | 2373 |
| `/api/clock` | GET|POST | 2312 |
| `/api/consents` | GET | 5695 |
| `/api/default-rules` | GET | 2368 |
| `/api/disciplines` | GET | 2363 |
| `/api/events` | GET|POST | 2378 |
| `/api/events/` | GET|POST | 4324 |
| `/api/events/(\d+)(?:/([a-z.-]+))?(?:/(\d+))?` | GET|POST | 2396 |
| `/api/events/(\d+)/bibs-csv` | GET|POST | 2277 |
| `/api/events/(\d+)/files` | GET|POST | 2289 |
| `/api/events/(\d+)/import` | GET|POST | 2251 |
| `/api/events/(\d+)/regs-csv` | GET|POST | 2269 |
| `/api/log` | GET|POST | 2321 |
| `/api/login` | POST | 5603 |
| `/api/logout` | POST | 5607 |
| `/api/me` | GET|POST | 5483 |
| `/api/me/password` | GET|POST | 5666 |
| `/api/me/password` | POST | 5485 |
| `/api/readers/scan` | POST | 5731 |
| `/api/scoreboard/state` | GET|POST | 2332 |
| `/api/status` | GET|POST | 5661 |
| `/api/system` | GET|POST | 2314 |
| `/api/system/audit` | GET | 2323 |
| `/api/system/backup/db` | GET | 5679 |
| `/api/system/backup/latest` | GET | 5670 |
| `/api/system/retention` | POST | 5690 |
| `/api/system/scoreboard/control` | GET|POST | 2330 |
| `/api/system/update` | GET|POST | 2316 |
| `/api/system/update` | POST | 2285 |
| `/api/system/update/github` | POST | 5709 |
| `/api/system/update/github/check` | GET | 5705 |
| `/api/system/update/install` | POST | 2318 |
| `/api/trainers` | GET | 5454 |
| `/api/trainers` | GET|POST | 5700 |
| `/api/trainers/` | GET|POST | 5700 |
| `/api/trainers/(\d+)/(verify|block|unblock|delete)` | GET|POST | 5456 |
| `/api/users` | GET | 5496 |
| `/api/users` | GET|POST | 5666 |
| `/api/users(?:/([a-z0-9._-]{1,32})/(delete|update))?` | GET|POST | 5506 |
| `/board` | GET|POST | 5748 |
| `/login` | GET | 5600 |
| `/privacy` | GET | 5596 |
| `/protocol` | GET | 5645 |
| `/protocol` | GET|POST | 5636 |
| `/r` | GET | 5830 |
| `/r` | GET|POST | 5626 |
| `/r/` | GET | 5830 |
| `/r/` | GET|POST | 5626 |
| `/r/([A-Za-z0-9]{4,20})(/info|/template\.xlsx|/team-check|/team|/relay|/results\.json|/startlist\.json` | GET|POST | 5867 |
| `/r/api/(?:auth/trainer/(consent|register|verify|resend|login|logout|me)|trainer/(events))` | GET|POST | 5834 |
| `/r/api/calendar` | GET | 5845 |
| `/r/api/open` | GET | 5860 |
| `/r/api/series` | GET | 5850 |
| `/r/assets/` | GET | 5838 |
| `/r/privacy` | GET | 5828 |
| `/r/series` | GET | 5857 |
| `/r/series/` | GET | 5857 |
| `/r/trainer` | GET | 5830 |
| `/r/trainer/` | GET | 5830 |
| `/relay` | POST | 5918 |
| `/results.json` | GET|POST | 5902 |
| `/scoreboard` | GET|POST | 5748 |
| `/sector` | GET|POST | 5748 |
| `/simple` | GET|POST | 5779 |

Внутренние ветки `_api` с разбором `action` (`/api/events/<id>/<action>`, допустимые символы `[a-z.-]+`):

`archive`, `bibs`, `clear-bibs`, `clear-rejected`, `clearresults`, `copy`, `delete`, `entries`, `entry`, `files`, `finish`, `heats`, `heats-all`, `log`, `manual`, `pickup`, `publish`, `qr.png`, `regs`, `regs.csv`, `relay`, `reopen`, `reset`, `resetheats`, `results`, `results.csv`, `snapshot`, `start`, `startlist`, `startlist.xlsx`, `template.xlsx`, `ui`, `waves`

### 6.3 Сессии

Администратор/судья — вход через браузер (`/login`), cookie сессии (SQLite `sessions`), пароли хранятся хэшем (`hash_password`/`verify_password`). Тренер — отдельная таблица `trainers`: e-mail + пароль-хэш + одноразовый код подтверждения (`verification_token`, срок `token_expires`, счётчик попыток `token_attempts`), согласие и Политика отдельными отметками (`consent_*`, `policy_hash`). Тренер без подтверждённой почты протоколы не видит. Ограничение частоты: `Hub._rate_ok` (по IP и по соревнованию).

## 7. Допущения и известные ограничения

- Скрытие года и тренера для старых заявок — осознанное (152-ФЗ); снимается тумблером `pub_regs_full` ответственностью организатора.
- Координаты манежа взяты с карточки дома на Яндекс.Картах (46.928092, 142.760570); для «Спартака» и «Триумфа» точных координат нет — карта центрируется на Южно-Сахалинске.
- Список роутов в 6.2 извлечён автоматически и может содержать лишние служебные строки; источник истины — `Hub._api`, `Hub._public_route`, `Hub.trainer_api`.
- Перечень маршрутов `/r/trainer/api/*`, вход, SMTP-параметры и секреты живут в конфиге сервера (`cfg`), в репозиторий не попадают.
- Запуск и проверка: `python3 tools/selftest.py` (поднимает временный сервер, ~320+ проверок), `python3 tools/make_architecture.py` — пересборка этого файла.
