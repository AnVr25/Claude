# SakhStart timing-hub — глобальный архитектурный дамп

**Отметка ревизии:** `v5.2.0-audit` · дата среза: 14.10.2026 · сборка `VERSION = "5.2.0"`, `BUILD_DATE = "2026-10-13"`
**Исходный коммит:** `d0ab416 major: сквозной аудит АРМ секретаря, ручной ввод нагрудных номеров и экспорт протоколов в Excel v5.2.0`
**Назначение:** полный технический снимок для ревизии перед рефакторингом. Новых функций и правок кода в этом коммите нет.

> Код в разделах 2–4 выгружен **дословно** (функции Python — по синтаксическому дереву, блоки JS — по границам
> верхнеуровневых объявлений), у каждого фрагмента указаны файл и строки. Схема БД снята с базы, которую сервер
> создаёт при запуске (со всеми миграциями `ALTER TABLE`), а не переписана вручную. Персональных данных в дампе нет.

## Содержание
0. Состав проекта и найденные архитектурные проблемы (сводка ревизии)
1. Схема базы SQLite
2. Сервер `hub/hub.py`: сетки, сбросы, участники и номера, расчёт результатов, сессии и роли
3. Админка `hub/ui.html`: панель этапов, Мастер протоколов, шаги 2 и 4, вкладки групп, корзина печати
4. Табло, пульт, планшет сектора
5. Справочники `hub/seed/`


## 0. Состав проекта

| Файл | Строк | Назначение |
|---|---:|---|
| `hub/announcer.html` | 121 | экран диктора |
| `hub/board.html` | 200 | табло финиша (большой экран) |
| `hub/hub.py` | 7383 | сервер: HTTP, API, SQLite, ридеры IPICO, Wiclax, расчёт результатов, xlsx/csv, почта |
| `hub/judge.html` | 444 | судья на финише (отметки, ручной ввод) |
| `hub/login.html` | 74 | вход |
| `hub/privacy.html` | 213 | политика обработки ПДн |
| `hub/protocol.html` | 636 | стартовые и итоговые протоколы, вкладки групп, корзина печати |
| `hub/reg.html` | 887 | публичная регистрация и кабинет тренера (/r/) |
| `hub/scoreboard.html` | 149 | пульт табло (режимы, ротация) |
| `hub/sector.html` | 264 | планшет судьи на секторе (техника, ручной секундомер) |
| `hub/series.html` | 111 | серия/кубок |
| `hub/ui.html` | 3439 | админка (АРМ секретаря): этапы 1–7, Мастер протоколов, система |


## 0.1 Сводка ревизии: конфликты, дубли, причины «прыжков» интерфейса

Ниже — только то, что подтверждено чтением кода (ссылки на функции из разделов 2–4). Исправлений в этом коммите нет.

### А. Почему интерфейс скрывается и прыгает

| # | Что происходит | Где в коде | Эффект |
|---|---|---|---|
| А1 | Любая смена вкладки идёт через `hashchange` → `showTab(); window.scrollTo(0, 0)` | `ui.html`, строка после `showTab` | Каждый переход между этапами и шагами, меняющий адрес, бросает страницу наверх |
| А2 | Панель этапов прячется вне этапов: `$("lane").classList.toggle("hide", !STEPS.includes(tab))` | `showTab` | Главная, «Система», «Журнал» — без панели, этапы — с панелью: шапка меняет высоту примерно на 70 px, контент сдвигается. Комментарий над строкой («в мастере… общая панель скрыта») устарел: `wizard` входит в `STEPS`, поэтому в Мастере панель **видна** |
| А3 | Номера этапов в разметке зашиты (1,2,**3,3**,4,5,6), затем `renderLane` прячет/показывает «Протоколы» и «Чипы/Выдача» и перенумеровывает | разметка `#lane` + `renderLane` | До первой отрисовки видны неверные номера; у массового забега и стадиона один и тот же этап имеет разные номера |
| А4 | Для стадиона с ручным вводом этап «5. Ввод результатов» (`#timing`) перенаправляется: `wzp.setStep(4); history.replaceState(…, "#wizard")` | `showTab` | Нажали этап 5 — подсветился этап 3 «Протоколы», адрес сменился без события. Сохранённый шаг Мастера затирается на 4 |
| А5 | `defaultStep` для идущего соревнования возвращает `timing` | `defaultStep`, `openEvent` | Открытие идущего стадиона = два перехода подряд (`#timing` → `#wizard`) |
| А6 | `wzp.open()` вызывается при каждом входе во вкладку и заново грузит заявки, стартовый список и результаты, затем `render()` целиком переписывает `#wzpBody.innerHTML` | `wzp.open`, `wzp.render`, `wzp.go` | Потеря прокрутки и фокуса при каждом шаге; пустое тело на время загрузки |
| А7 | После ручного сохранения на шаге 4 — полная перерисовка: `if (!auto && !bad.size) render()`, затем `loadEvents._sig = null; loadEvents()` | `wzp.saveRows` | Таблица ввода перестраивается, следом `renderEvents` перерисовывает меню, панель этапов и шапки |
| А8 | Фоновые таймеры: `loadStatus` 4 с, `pollFeed` 1 с, ветка этапов 3 с, `loadEvents` 15 с (при изменении — `renderEvents` → `renderWaves`, `renderTimingHead`, `renderRegHead`, `renderLane`, `renderFinState`, а без выбранного события ещё и `showTab`) | блок «запуск» | Подписи этапов и шапки меняются сами по себе; при потере события — внезапный уход на главную |

### Б. Дублирующийся код и логика

| # | Дубль | Где | Риск |
|---|---|---|---|
| Б1 | Правило ручного хронометража (3 → средний, 2 → худший, 1 → сам, вверх до 0,1) | `Hub.stopwatch_main` (сервер), `swMain` в `ui.html`, `swMain` в `sector.html` | Три реализации; правка в одном месте разведёт табло, планшет и протокол |
| Б2 | Разбор и печать времени, лучшая попытка | `parseT` / `fmtT` / `attBest` — в `ui.html` и `sector.html`; на сервере `parse_result` / `parse_attempts` / `fmt_result` | То же |
| Б3 | Границы возрастных групп | `Hub.AGE_LIMITS` (сервер) и `AGE_LIM` в `wzp` (ui); в `seed/disciplines.json → ages` только id и названия, без границ | Справочник не управляет фильтром; три источника правды |
| Б4 | Три экрана ввода результатов в одну точку `POST /results` | шаг 4 Мастера (`wzp.step4`), планшет `sector.html`, старый экран вкладки «timing» (`loadEntry` / `renderEntry` / `recalcRow`) | Старый экран для режима ручного ввода больше недостижим (А4), но код (~130 строк) и его ветка в 3-секундном таймере остались — мёртвый код |
| Б5 | Два генератора сетки | `generate_heats` (всё соревнование, старый путь вкладки «Регистрация») и `generate_scoped` (Мастер, одна дисциплина); выбор — по наличию `distance` в `POST /heats` | Две логики раскладки по дорожкам и номеров |
| Б6 | Четыре похожих «сброса» | `resetheats` (удалить забеги), `reset` (отменить старт / время), `clearresults` (стереть результаты), `wzp.clearAll` | Легко перепутать в интерфейсе и в API |
| Б7 | Два «Итоговых протокола» | шаг 5 Мастера и этап «6. Результаты» / «7. Документы» | Две точки входа к одному документу |
| Б8 | Две функции `setStep` | глобальная `setStep(id, cls, text)` (панель этапов) и `wzp.setStep(n)` (Мастер) | Одинаковое имя, разный смысл |

### В. Логические конфликты и остатки

- **Роли:** в `ROLES` только `admin` и `judge`. `sector` и `secretary` — устаревшие названия, на сервере сводятся к `judge` (`LEGACY_ROLES`). `trainer` живёт отдельно (`TRAINER_PANEL`, кабинет `/r/`). Отдельной роли «судья на секторе» нет: страница `/sector` открыта любому судье.
- **Нагрудные номера:** `get_next_bib` / `next_bib` удалены (5.2.0). Поле `bib_from` в описании дистанции (`dist_specs`) по-прежнему разбирается, но нигде не используется. Номер уникален в соревновании, поэтому спортсмен в двух дисциплинах получает два номера.
- **Разряды:** три поля — `registrations.rank` (из заявки), `entries.rank` (в сетке, правится) и `entries.done_rank` (выполненный, ручной). Автоматический выполненный разряд в базе не хранится, считается на лету (`rank_for`).
- **Состояние Мастера** хранится в `localStorage` (`ss.wzp.<id>`) и на сервер не попадает: у двух секретарей на разных компьютерах разные шаги и фильтры.
- **Корзина печати** тоже хранится в `localStorage` (`ss.cart.<id>`): заполняется и в `ui.html` (`cartAdd`), и в `protocol.html` (`addTabToCart`), печатается через `protocol.html?kind=cart`, на сервер не попадает.


## 1. Схема базы SQLite

Снято с базы, созданной `Store.__init__` на чистом диске (все `CREATE TABLE` + миграции `ALTER TABLE ... ADD COLUMN`).

Таблицы: `reads`, `raw`, `events`, `entries`, `waves`, `manual`, `files`, `audit`, `registrations`, `readers`, `wiclax_ports`, `users`, `sessions`, `scoreboard`, `trainers`, `consent_texts`


### `reads`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | source | TEXT | да |  |  |
| 2 | device | TEXT | да |  |  |
| 3 | **chip** | TEXT | да |  |  |
| 4 | ts | TEXT | да |  |  |
| 5 | antenna | TEXT |  |  |  |
| 6 | rssi | TEXT |  |  |  |
| 7 | **time_from_receive** | INTEGER | да | `0` |  |
| 8 | received_at | TEXT | да |  |  |

```sql
CREATE TABLE reads(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                device TEXT NOT NULL,
                chip TEXT NOT NULL,
                ts TEXT NOT NULL,
                antenna TEXT,
                rssi TEXT,
                time_from_receive INTEGER NOT NULL DEFAULT 0,
                received_at TEXT NOT NULL
            );
CREATE INDEX idx_reads_ts ON reads(ts);
CREATE INDEX idx_reads_chip ON reads(chip);
CREATE UNIQUE INDEX uq_reads ON reads(source, device, chip, ts);
```

### `raw`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | source | TEXT | да |  |  |
| 2 | line | TEXT | да |  |  |
| 3 | parsed | INTEGER | да |  |  |
| 4 | received_at | TEXT | да |  |  |

```sql
CREATE TABLE raw(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                line TEXT NOT NULL,
                parsed INTEGER NOT NULL,
                received_at TEXT NOT NULL
            );
CREATE INDEX idx_raw_received ON raw(received_at);
```

### `events`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | name | TEXT | да |  |  |
| 2 | date | TEXT |  |  |  |
| 3 | place | TEXT |  |  |  |
| 4 | **finish_device** | TEXT |  |  |  |
| 5 | **min_time_sec** | REAL | да | `0` |  |
| 6 | push_wiclax | INTEGER | да | `1` |  |
| 7 | **start_time** | TEXT |  |  |  |
| 8 | **status** | TEXT | да | `'planned'` |  |
| 9 | notes | TEXT |  |  |  |
| 10 | created_at | TEXT | да |  |  |
| 11 | check_since | TEXT |  |  |  |
| 12 | alert_silence_min | REAL | да | `10` |  |
| 13 | archived | INTEGER | да | `0` |  |
| 14 | **finished_at** | TEXT |  |  |  |
| 15 | organizer | TEXT |  |  |  |
| 16 | chief_judge | TEXT |  |  |  |
| 17 | chief_secretary | TEXT |  |  |  |
| 18 | **start_clock** | TEXT |  |  |  |
| 19 | heats_sequential | INTEGER |  |  |  |
| 20 | team_best | INTEGER |  |  |  |
| 21 | cover | TEXT |  |  |  |
| 22 | program | TEXT |  |  |  |
| 23 | contacts | TEXT |  |  |  |
| 24 | series | TEXT |  |  |  |
| 25 | reg_open | INTEGER | да | `0` |  |
| 26 | reg_slug | TEXT |  |  |  |
| 27 | reg_deadline | TEXT |  |  |  |
| 28 | reg_distances | TEXT |  |  |  |
| 29 | reg_rules | TEXT |  |  |  |
| 30 | **reg_lanes** | INTEGER |  |  |  |
| 31 | reg_info | TEXT |  |  |  |
| 32 | **reg_consent** | TEXT |  |  |  |
| 33 | kind | TEXT |  |  |  |
| 34 | timing | TEXT |  |  |  |
| 35 | pub_site | INTEGER | да | `0` |  |
| 36 | ours | INTEGER | да | `1` |  |
| 37 | level | TEXT |  |  |  |
| 38 | adaptive | INTEGER | да | `0` |  |
| 39 | date_end | TEXT |  |  |  |
| 40 | city | TEXT |  |  |  |
| 41 | note | TEXT |  |  |  |
| 42 | live_url | TEXT |  |  |  |
| 43 | photo_url | TEXT |  |  |  |
| 44 | links | TEXT |  |  |  |
| 45 | **pub_start** | INTEGER | да | `0` |  |
| 46 | **pub_results** | INTEGER | да | `0` |  |

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
            , check_since TEXT, alert_silence_min REAL NOT NULL DEFAULT 10, archived INTEGER NOT NULL DEFAULT 0, finished_at TEXT, organizer TEXT, chief_judge TEXT, chief_secretary TEXT, start_clock TEXT, heats_sequential INTEGER, team_best INTEGER, cover TEXT, program TEXT, contacts TEXT, series TEXT, reg_open INTEGER NOT NULL DEFAULT 0, reg_slug TEXT, reg_deadline TEXT, reg_distances TEXT, reg_rules TEXT, reg_lanes INTEGER, reg_info TEXT, reg_consent TEXT, kind TEXT, timing TEXT, pub_site INTEGER NOT NULL DEFAULT 0, ours INTEGER NOT NULL DEFAULT 1, level TEXT, adaptive INTEGER NOT NULL DEFAULT 0, date_end TEXT, city TEXT, note TEXT, live_url TEXT, photo_url TEXT, links TEXT, pub_start INTEGER NOT NULL DEFAULT 0, pub_results INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX idx_events_slug ON events(reg_slug);
```

### `entries`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | event_id | INTEGER | да |  | 1 |
| 1 | **bib** | TEXT | да |  |  |
| 2 | **chip** | TEXT | да |  | 2 |
| 3 | **points** | REAL |  |  |  |
| 4 | **picked_at** | TEXT |  |  |  |
| 5 | members | TEXT |  |  |  |
| 6 | **rank** | TEXT |  |  |  |
| 7 | **detail** | TEXT |  |  |  |
| 8 | **done_rank** | TEXT |  |  |  |
| 9 | **result_at** | TEXT |  |  |  |
| 10 | **wave** | TEXT |  |  |  |
| 11 | name | TEXT |  |  |  |
| 12 | birth_year | TEXT |  |  |  |
| 13 | team | TEXT |  |  |  |
| 14 | category | TEXT |  |  |  |
| 15 | **lane** | INTEGER |  |  |  |
| 16 | coach | TEXT |  |  |  |
| 17 | seed | TEXT |  |  |  |
| 18 | reg_id | INTEGER |  |  |  |
| 19 | sex | TEXT |  |  |  |
| 20 | **result** | TEXT |  |  |  |
| 21 | **status** | TEXT |  |  |  |

```sql
CREATE TABLE entries(
                event_id INTEGER NOT NULL,
                bib TEXT NOT NULL,
                chip TEXT NOT NULL, points REAL, picked_at TEXT, members TEXT, rank TEXT, detail TEXT, done_rank TEXT, result_at TEXT, wave TEXT, name TEXT, birth_year TEXT, team TEXT, category TEXT, lane INTEGER, coach TEXT, seed TEXT, reg_id INTEGER, sex TEXT, result TEXT, status TEXT,
                PRIMARY KEY(event_id, chip)
            );
-- sqlite_autoindex_entries_1 (автоиндекс PRIMARY KEY/UNIQUE)
```

### `waves`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | event_id | INTEGER | да |  |  |
| 2 | name | TEXT | да |  |  |
| 3 | **start_time** | TEXT |  |  |  |
| 4 | category | TEXT |  |  |  |
| 5 | distance | TEXT |  |  |  |
| 6 | **finished_at** | TEXT |  |  |  |

```sql
CREATE TABLE waves(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                start_time TEXT, category TEXT, distance TEXT, finished_at TEXT,
                UNIQUE(event_id, name)
            );
-- sqlite_autoindex_waves_1 (автоиндекс PRIMARY KEY/UNIQUE)
```

### `manual`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | event_id | INTEGER | да |  |  |
| 2 | device | TEXT | да |  |  |
| 3 | ts | TEXT | да |  |  |
| 4 | **bib** | TEXT | да | `''` |  |
| 5 | judge | TEXT |  |  |  |
| 6 | client_id | TEXT |  |  |  |
| 7 | created_at | TEXT | да |  |  |
| 8 | deleted | INTEGER | да | `0` |  |
| 9 | **wave** | TEXT |  |  |  |

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
            , wave TEXT);
-- sqlite_autoindex_manual_1 (автоиндекс PRIMARY KEY/UNIQUE)
CREATE INDEX idx_manual_event ON manual(event_id);
```

### `files`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | event_id | INTEGER | да |  |  |
| 2 | name | TEXT | да |  |  |
| 3 | stored | TEXT | да |  |  |
| 4 | size | INTEGER | да |  |  |
| 5 | kind | TEXT | да | `'protocol'` |  |
| 6 | created_at | TEXT | да |  |  |
| 7 | author | TEXT |  |  |  |
| 8 | folder | TEXT |  |  |  |
| 9 | public | INTEGER | да | `0` |  |

```sql
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
CREATE INDEX idx_files_event ON files(event_id);
```

### `audit`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | ts | TEXT | да |  |  |
| 2 | actor | TEXT |  |  |  |
| 3 | event_id | INTEGER |  |  |  |
| 4 | action | TEXT | да |  |  |
| 5 | **details** | TEXT |  |  |  |

```sql
CREATE TABLE audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                actor TEXT,
                event_id INTEGER,
                action TEXT NOT NULL,
                details TEXT
            );
```

### `registrations`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | event_id | INTEGER | да |  |  |
| 2 | last_name | TEXT | да |  |  |
| 3 | first_name | TEXT | да |  |  |
| 4 | middle_name | TEXT |  |  |  |
| 5 | birth_date | TEXT | да |  |  |
| 6 | sex | TEXT | да |  |  |
| 7 | team | TEXT |  |  |  |
| 8 | coach | TEXT |  |  |  |
| 9 | distance | TEXT | да |  |  |
| 10 | best | TEXT |  |  |  |
| 11 | best_sec | REAL |  |  |  |
| 12 | category | TEXT |  |  |  |
| 13 | representative | TEXT |  |  |  |
| 14 | contact | TEXT |  |  |  |
| 15 | **status** | TEXT | да | `'pending'` |  |
| 16 | note | TEXT |  |  |  |
| 17 | **bib** | TEXT |  |  |  |
| 18 | **consent_at** | TEXT | да |  |  |
| 19 | **consent_hash** | TEXT |  |  |  |
| 20 | created_at | TEXT | да |  |  |
| 21 | updated_at | TEXT |  |  |  |
| 22 | relay | TEXT |  |  |  |
| 23 | leg | INTEGER |  |  |  |
| 24 | **rank** | TEXT |  |  |  |
| 25 | policy_hash | TEXT |  |  |  |
| 26 | **anonymized_at** | TEXT |  |  |  |

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
            , relay TEXT, leg INTEGER, rank TEXT, policy_hash TEXT, anonymized_at TEXT);
CREATE INDEX idx_reg_event ON registrations(event_id);
```

### `readers`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | TEXT |  |  | 1 |
| 1 | name | TEXT |  |  |  |
| 2 | box | TEXT |  |  |  |
| 3 | host | TEXT | да |  |  |
| 4 | port | INTEGER | да |  |  |
| 5 | device | TEXT | да |  |  |
| 6 | parser | TEXT | да | `'ipico'` |  |
| 7 | enabled | INTEGER | да | `0` |  |
| 8 | created_at | TEXT |  |  |  |
| 9 | updated_at | TEXT |  |  |  |
| 10 | wiclax_port | INTEGER |  |  |  |

```sql
CREATE TABLE readers(
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
-- sqlite_autoindex_readers_1 (автоиндекс PRIMARY KEY/UNIQUE)
```

### `wiclax_ports`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | port | INTEGER |  |  | 1 |
| 1 | devices | TEXT | да |  |  |
| 2 | name | TEXT |  |  |  |

```sql
CREATE TABLE wiclax_ports(
                port INTEGER PRIMARY KEY,
                devices TEXT NOT NULL,
                name TEXT
            );
```

### `users`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | login | TEXT |  |  | 1 |
| 1 | name | TEXT |  |  |  |
| 2 | role | TEXT | да | `'judge'` |  |
| 3 | pwd | TEXT | да |  |  |
| 4 | created_at | TEXT |  |  |  |
| 5 | last_login | TEXT |  |  |  |
| 6 | note | TEXT |  |  |  |
| 7 | active | INTEGER | да | `1` |  |

```sql
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
-- sqlite_autoindex_users_1 (автоиндекс PRIMARY KEY/UNIQUE)
```

### `sessions`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | token | TEXT |  |  | 1 |
| 1 | login | TEXT | да |  |  |
| 2 | created_at | TEXT | да |  |  |
| 3 | expires_at | TEXT | да |  |  |
| 4 | ip | TEXT |  |  |  |

```sql
CREATE TABLE sessions(
                token TEXT PRIMARY KEY,
                login TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ip TEXT
            );
-- sqlite_autoindex_sessions_1 (автоиндекс PRIMARY KEY/UNIQUE)
```

### `scoreboard`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | event_id | INTEGER |  |  | 1 |
| 1 | state | TEXT | да |  |  |
| 2 | updated_at | TEXT | да |  |  |

```sql
CREATE TABLE scoreboard(event_id INTEGER PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL);
```

### `trainers`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | id | INTEGER |  |  | 1 |
| 1 | name | TEXT | да |  |  |
| 2 | team | TEXT | да |  |  |
| 3 | email | TEXT | да |  |  |
| 4 | password_hash | TEXT | да |  |  |
| 5 | is_verified | INTEGER | да | `0` |  |
| 6 | verification_token | TEXT |  |  |  |
| 7 | created_at | TEXT | да |  |  |
| 8 | token_expires | TEXT |  |  |  |
| 9 | token_attempts | INTEGER | да | `0` |  |
| 10 | token_sent_at | TEXT |  |  |  |
| 11 | active | INTEGER | да | `1` |  |
| 12 | last_login | TEXT |  |  |  |
| 13 | verified_at | TEXT |  |  |  |
| 14 | verified_by | TEXT |  |  |  |
| 15 | **consent_accepted** | INTEGER | да | `0` |  |
| 16 | **consent_at** | TEXT |  |  |  |
| 17 | **consent_hash** | TEXT |  |  |  |
| 18 | policy_hash | TEXT |  |  |  |

```sql
CREATE TABLE trainers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_verified INTEGER NOT NULL DEFAULT 0,
            verification_token TEXT,
            created_at TEXT NOT NULL, token_expires TEXT, token_attempts INTEGER NOT NULL DEFAULT 0, token_sent_at TEXT, active INTEGER NOT NULL DEFAULT 1, last_login TEXT, verified_at TEXT, verified_by TEXT, consent_accepted INTEGER NOT NULL DEFAULT 0, consent_at TEXT, consent_hash TEXT, policy_hash TEXT);
-- sqlite_autoindex_trainers_1 (автоиндекс PRIMARY KEY/UNIQUE)
```

### `consent_texts`

| # | Поле | Тип | NOT NULL | По умолчанию | PK |
|---:|---|---|:-:|---|:-:|
| 0 | hash | TEXT |  |  | 1 |
| 1 | kind | TEXT | да |  |  |
| 2 | text | TEXT | да |  |  |
| 3 | created_at | TEXT | да |  |  |

```sql
CREATE TABLE consent_texts(
            hash TEXT PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
-- sqlite_autoindex_consent_texts_1 (автоиндекс PRIMARY KEY/UNIQUE)
```

### Где хранятся номера, разряды, выдача и результаты

| Что | Таблица.поле | Комментарий |
|---|---|---|
| Нагрудный номер участника сетки | entries.bib (+ entries.chip = "#номер" для стадиона) | PK (event_id, chip); номер уникален в пределах соревнования |
| Номер, вписанный на шаге 2 Мастера | registrations.bib | источник истины для генерации сетки (`_reg_bib`) |
| Разряд спортсмена (имеющийся) | entries.rank, registrations.rank | из заявки; правится в сетке |
| Выполненный разряд | entries.done_rank | ручной выбор судьи; «Авто» считается на лету `rank_for` по seed/rank_norms.json |
| Выдача номера на руки | entries.picked_at | этап «4. Выдача номеров» (`pickup`) |
| Результат ручного ввода | entries.result, entries.status, entries.points, entries.detail, entries.result_at | detail — JSON: {"t": [секундомеры], "a": [попытки]} (в API отдаются как sw и attempts); result_at — время ввода (порядок «свежих» на табло) |
| Отметки чипов / финиш | reads, raw, manual | IPICO/Wiclax и ручные отметки судьи на финише |
| Старт забега | waves.start_time, waves.state | сброс — действие `reset` |

## 2. Сервер `hub/hub.py`

> `get_next_bib` и `next_bib` **в коде отсутствуют** — удалены в 5.2.0 (поиск по файлу: 0 совпадений: `get_next_bib` — 0, `next_bib(` — 0). Ниже — то, что их заменило (`_reg_bib`, `_need_bibs`, `bibs_view`, `save_bibs`).


### 2.1 Генерация стартовых сеток и списков


#### Hub.AGE_LIMITS
`hub/hub.py:4505-4505`
```python
    AGE_LIMITS = {"u12": (0, 12), "u14": (0, 14), "u16": (0, 16), "u18": (0, 18), "u20": (0, 20), "u23": (0, 23), "sen": (19, 200)}
```


#### Hub.relay_entry
`hub/hub.py:4447-4454`
```python
    def relay_entry(self, members: list) -> dict:
        """Заявки участников одной эстафетной команды → одна «заявка-команда» для забега."""
        members = sorted(members, key=lambda r: (r.get("leg") or 0, r["id"]))
        r0 = members[0]
        cats = {m.get("category") or "" for m in members}
        return {**r0, "last_name": r0["relay"], "first_name": "", "birth_date": "    ", "best_sec": None, "best": None,
                "category": cats.pop() if len(cats) == 1 else (r0.get("category") or None),
                "members": self.relay_members(members), "_ids": [m["id"] for m in members]}
```


#### Hub.collapse_relays
`hub/hub.py:4456-4468`
```python
    def collapse_relays(self, ev: dict, regs: list) -> list:
        relays = {d["name"] for d in self.dist_specs(ev) if d["legs"]}
        out, teams = [], {}
        for r in regs:
            if r["distance"] in relays and r.get("relay"):
                key = (r["distance"], r["relay"].lower())
                if key not in teams:
                    teams[key] = []
                    out.append(key)
                teams[key].append(r)
            else:
                out.append(r)
        return [self.relay_entry(teams[x]) if isinstance(x, tuple) else x for x in out]
```


#### Hub.generate_scoped
`hub/hub.py:4507-4615`
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
        self._need_bibs(regs, old)                      # 5.2: без ручных номеров сетку не строим
        theirs = {e["bib"] for e in entries if e.get("reg_id") not in mine}
        clash = [self._reg_bib(r, old.get(r["id"])) for r in regs if self._reg_bib(r, old.get(r["id"])) in theirs]
        if clash:
            raise ValueError(f"номер {clash[0]} уже у участника другой дисциплины — исправьте на шаге 2")
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
                bib = self._reg_bib(r, e)
                chip = e["chip"] if e and e["bib"] == bib else "#" + bib
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


#### Hub.generate_heats
`hub/hub.py:4617-4685`
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
        self._need_bibs(regs, old)                      # 5.2: номера только ручные

        def bib_for(r):
            e = old.get(r["id"])
            b = self._reg_bib(r, e)
            return b, (e["chip"] if e and e["bib"] == b else "#" + b)

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


#### Hub.startlist
`hub/hub.py:4744-4763`
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


### 2.1a Маршрут генерации


#### POST /api/events/{id}/heats
`hub/hub.py:3621-3638`
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


### 2.2 Сброс сетки и отмена стартов


#### Hub.reset_heats
`hub/hub.py:4687-4704`
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


#### Hub.start_event
`hub/hub.py:2837-2866`
```python
    def start_event(self, ev: dict, when: Optional[str], wave: Optional[str] = None,
                    epoch_ms: Optional[float] = None) -> dict:
        if when:
            st = self._parse_clock(ev, when)
        elif epoch_ms:
            st = dt.datetime.fromtimestamp(float(epoch_ms) / 1000.0)
            if abs((st - now_local()).total_seconds()) > 600:
                raise ValueError("время старта с устройства расходится с сервером больше чем на 10 минут")
        else:
            st = now_local()
        if wave:
            if wave not in {w["name"] for w in self.store.waves(ev["id"])}:
                raise ValueError(f"нет забега «{wave}»")
            seq = ev.get("heats_sequential")
            if seq is None:
                seq = (ev.get("finish_device") or "").upper() == "JUDGE"
            for w in (self.store.waves(ev["id"]) if seq else []):
                if w["name"] != wave and w.get("start_time") and not w.get("finished_at"):
                    self.store.update_wave(ev["id"], w["name"], finished_at=fmt_db(st))   # предыдущий забег закрыт
            self.store.set_wave_start(ev["id"], wave, fmt_db(st))
            self._refresh_event_start(ev["id"])
        else:
            self.store.set_event_field(ev["id"], start_time=fmt_db(st), status="running")
        if ev.get("push_wiclax"):
            line = f"RACESTART {st:%H:%M:%S},{st.microsecond // 1000:03d}"
            for c in list(self.wiclax_clients):
                c.command(line)
            log.info("Старт «%s»%s в %s отправлен в Wiclax (%d подключений)", ev["name"],
                     f" / {wave}" if wave else "", fmt_db(st), len(self.wiclax_clients))
        return self._event_view(self.store.get_event(ev["id"]))
```


#### Hub._refresh_event_start
`hub/hub.py:2213-2221`
```python
    def _refresh_event_start(self, eid: int) -> None:
        """Общее время старта соревнования = самый ранний старт забега."""
        starts = [w["start_time"] for w in self.store.waves(eid) if w.get("start_time")]
        ev = self.store.get_event(eid)
        if starts:
            self.store.set_event_field(eid, start_time=min(starts),
                                       status="finished" if ev["status"] == "finished" else "running")
        elif self.store.waves(eid):
            self.store.set_event_field(eid, start_time=None, status="planned")
```


### 2.2a Маршруты сброса


#### POST …/resetheats — удалить забеги дисциплины
`hub/hub.py:3611-3617`
```python
        if action == "resetheats":
            try:
                out = self.reset_heats(ev, data.get("distance"))
            except ValueError as e:
                return err(str(e))
            self.store.audit(who, eid, "Сброшена сетка забегов", f"забегов удалено: {out['waves']}, участников возвращено в нераспределённые: {out['entries']}")
            return ok(out)
```


#### POST …/start — дать старт
`hub/hub.py:3268-3276`
```python
        if action == "start":
            wave = str(data.get("wave") or "").strip() or None
            try:
                out = self.start_event(ev, data.get("time"), wave, data.get("epoch_ms"))
            except (ValueError, TypeError, OverflowError, OSError) as e:
                return err(str(e))
            st = next((w["start_time"] for w in out["waves"] if w["name"] == wave), None) if wave else out["start_time"]
            self.store.audit(who, eid, "СТАРТ" + (f" «{wave}»" if wave else ""), st or "")
            return ok(out)
```


#### POST …/reset — отменить старт / сбросить время
`hub/hub.py:3277-3287`
```python
        if action == "reset":
            wave = str(data.get("wave") or "").strip() or None
            if wave:
                self.store.set_wave_start(eid, wave, None)
                self._refresh_event_start(eid)
            else:
                for w in self.store.waves(eid):
                    self.store.set_wave_start(eid, w["name"], None)
                self.store.set_event_field(eid, start_time=None, status="planned")
            self.store.audit(who, eid, "Сброс старта" + (f" «{wave}»" if wave else ""))
            return ok(self._event_view(self.store.get_event(eid)))
```


#### POST …/clearresults — стереть результаты
`hub/hub.py:3577-3589`
```python
        if action == "clearresults":
            # «Очистить протокол»: результаты, отметки, секундомеры, попытки и ручные разряды выбранных участников
            bibs = {str(b) for b in (data.get("bibs") or []) if str(b).strip()}
            if not bibs:
                return err("не указано, чьи результаты очистить")
            have = {e["bib"] for e in self.store.entries_rows(eid)}
            n = 0
            for b in sorted(bibs & have):
                self.store.set_entry_result(eid, b, None, None, None, True)
                self.store.update_entry(eid, b, done_rank=None)
                n += 1
            self.store.audit(who, eid, "Очищены результаты", f"{data.get('label') or ''} участников: {n}".strip())
            return ok({"cleared": n})
```


### 2.3 Участники и нагрудные номера (Store)


#### Store.add_entry
`hub/hub.py:1257-1273`
```python
    def add_entry(self, eid: int, r: dict) -> None:
        # 5.2: нагрудный номер вписывает только судья/секретарь — автоматической выдачи номеров нет
        bib = str(r.get("bib") or "").strip()
        if not bib:
            raise ValueError("нет нагрудного номера — впишите его на шаге 2 «Регистрация номеров»")

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


#### Store.update_entry
`hub/hub.py:1245-1255`
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


#### Store.set_entry_result
`hub/hub.py:1225-1236`
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


#### Store.rename_bib
`hub/hub.py:1275-1280`
```python
    def rename_bib(self, eid: int, old: str, new: str) -> None:
        """Сменить нагрудный номер участника везде: в списке, заявках и ручных отметках судей."""
        self.con.execute("UPDATE entries SET bib = ?, chip = CASE WHEN chip = ? THEN ? ELSE chip END"
                         " WHERE event_id = ? AND bib = ?", (new, "#" + old, "#" + new, eid, old))
        self.con.execute("UPDATE registrations SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
        self.con.execute("UPDATE manual SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
```


#### Store.delete_entry
`hub/hub.py:1282-1283`
```python
    def delete_entry(self, eid: int, bib: str) -> None:
        self.con.execute("DELETE FROM entries WHERE event_id = ? AND bib = ?", (eid, bib))
```


### 2.3a Ручные номера (Hub, 5.2)


#### Hub._reg_bib
`hub/hub.py:3891-3894`
```python
    @staticmethod
    def _reg_bib(r: dict, old_entry: Optional[dict]) -> str:
        """Номер участника для сетки: вписанный секретарём в заявку, иначе — уже стоящий в стартовом списке."""
        return str(r.get("bib") or (old_entry or {}).get("bib") or "").strip()
```


#### Hub._need_bibs
`hub/hub.py:3896-3908`
```python
    def _need_bibs(self, regs: list, old: dict) -> None:
        """Сетка строится только когда у всех участников есть номера, вписанные вручную, и номера не повторяются."""
        missing = [r for r in regs if not self._reg_bib(r, old.get(r["id"]))]
        if missing:
            names = ", ".join(" ".join(x for x in (m["last_name"], m["first_name"]) if x) for m in missing[:5])
            raise ValueError(f"нет нагрудных номеров у {len(missing)} участников ({names}{'…' if len(missing) > 5 else ''}) — "
                             f"впишите их на шаге 2 «Регистрация номеров» и нажмите «Сохранить нагрудные номера»")
        seen: dict = {}
        for r in regs:
            b = self._reg_bib(r, old.get(r["id"]))
            if b in seen:
                raise ValueError(f"номер {b} стоит у двух участников — исправьте на шаге 2")
            seen[b] = r
```


#### Hub.bibs_view
`hub/hub.py:3910-3942`
```python
    def bibs_view(self, ev: dict, scope: dict) -> dict:
        """Шаг 2: подтверждённые участники дисциплины (с фильтром шага 1) и их нагрудные номера."""
        eid, dist = ev["id"], str(scope.get("distance") or "").strip()
        sex = str(scope.get("sex") or "").strip().upper()[:1]
        ages = [a for a in (scope.get("ages") or []) if a in self.AGE_LIMITS]
        year = int(ev["date"][:4]) if ev.get("date") else dt.date.today().year

        def ok_(r):
            if r["status"] != "approved" or (dist and r["distance"] != dist):
                return False
            if sex in ("М", "Ж") and str(r.get("sex") or "").upper() != sex:
                return False
            if ages:
                try:
                    age = year - int(str(r["birth_date"])[:4])
                except ValueError:
                    return False
                return any(self.AGE_LIMITS[a][0] <= age <= self.AGE_LIMITS[a][1] for a in ages)
            return True
        regs = self.collapse_relays(ev, [r for r in self.store.registrations(eid) if ok_(r)])
        ent = {e["reg_id"]: e for e in self.store.entries_rows(eid) if e.get("reg_id")}
        cat_order = {r["name"]: i for i, r in enumerate(self.parse_rules(ev.get("reg_rules") or ""))}
        rows = []
        for r in sorted(regs, key=lambda r: (cat_order.get(r.get("category") or "", 99), r.get("category") or "",
                                             r["last_name"].lower(), r["first_name"].lower())):
            e = ent.get(r["id"])
            rows.append({"ids": r.get("_ids") or [r["id"]], "bib": self._reg_bib(r, e),
                         "name": " ".join(x for x in (r["last_name"], r["first_name"]) if x),
                         "birth_year": str(r["birth_date"])[:4].strip(), "sex": r.get("sex") or "",
                         "category": r.get("category") or "", "team": r.get("team") or "", "rank": r.get("rank") or "",
                         "members": r.get("members") or "", "in_grid": bool(e and e.get("wave")),
                         "has_result": bool(e and (e.get("result") or e.get("detail") or e.get("status")))})
        return {"distance": dist, "rows": rows, "total": len(rows), "with_bib": sum(1 for x in rows if x["bib"])}
```


#### Hub.save_bibs
`hub/hub.py:3944-4012`
```python
    def save_bibs(self, ev: dict, items: list, who: str) -> tuple:
        """Сохранить номера, вписанные вручную. Ничего не пишется, пока весь набор не прошёл проверку."""
        eid = ev["id"]
        regs = {r["id"]: r for r in self.store.registrations(eid)}
        entries = self.store.entries_rows(eid)
        ent_by_reg = {e["reg_id"]: e for e in entries if e.get("reg_id")}
        errors, plan = [], []          # plan: (ids, старый номер, новый номер)
        for it in items[:3000]:
            if not isinstance(it, dict):
                continue
            ids = [int(x) for x in (it.get("ids") or []) if str(x).isdigit() and int(x) in regs]
            if not ids:
                continue
            r0 = regs[ids[0]]
            who_ = " ".join(x for x in (r0.get("relay") or r0["last_name"], "" if r0.get("relay") else r0["first_name"]) if x)
            new = str(it.get("bib") or "").strip()
            old = self._reg_bib(r0, ent_by_reg.get(ids[0]))
            if new and not self.BIB_RE.fullmatch(new):
                errors.append({"ids": ids, "error": f"{who_}: номер — до 10 цифр или букв, без пробелов"})
                continue
            if not new and ent_by_reg.get(ids[0]):
                errors.append({"ids": ids, "error": f"{who_}: уже в стартовом списке — номер нельзя стереть, только заменить"})
                continue
            if new != old:
                plan.append((ids, old, new, who_))
        # итоговая раскладка номеров по всему соревнованию: повторов быть не должно
        final: dict = {}
        changing = {i for p in plan for i in p[0]}
        for rid, r in regs.items():
            if rid in changing:
                continue
            b = self._reg_bib(r, ent_by_reg.get(rid))
            if b:
                final.setdefault(b, set()).add((r.get("relay") or "").lower() or f"r{rid}")
        for e in entries:
            if not e.get("reg_id") or e["reg_id"] not in regs:
                final.setdefault(e["bib"], set()).add(f"e{e['bib']}")
        for ids, old, new, who_ in plan:
            if new:
                key = (regs[ids[0]].get("relay") or "").lower() or f"r{ids[0]}"
                if final.get(new, set()) - {key}:
                    errors.append({"ids": ids, "error": f"{who_}: номер {new} уже у другого участника"})
                final.setdefault(new, set()).add(key)
        if errors:
            return 400, {"error": "Номера не сохранены — исправьте отмеченные строки", "errors": errors}
        # запись: сначала временные номера (чтобы обмен номерами двух участников не конфликтовал), потом настоящие
        self.store.con.execute("BEGIN")
        try:
            moves = []
            for n_, (ids, old, new, _) in enumerate(plan):
                e = ent_by_reg.get(ids[0])
                if e and new and e["bib"] != new:
                    tmp = f"~{n_}~{e['bib']}"
                    self.store.rename_bib(eid, e["bib"], tmp)
                    moves.append((tmp, new))
            for tmp, new in moves:
                self.store.rename_bib(eid, tmp, new)
            for ids, old, new, _ in plan:
                for rid in ids:
                    self.store.con.execute("UPDATE registrations SET bib = ? WHERE id = ? AND event_id = ?",
                                           (new or None, rid, eid))
            self.store.con.execute("COMMIT")
        except Exception:
            self.store.con.execute("ROLLBACK")
            raise
        if plan:
            ch = [f"{w}: {o or '—'} → {n or '—'}" for _, o, n, w in plan[:30]]
            self.store.audit(who, eid, "Нагрудные номера сохранены", f"{len(plan)}: " + "; ".join(ch))
        return 200, {"ok": True, "saved": len(plan)}
```


### 2.3b Маршруты участников и номеров


#### GET …/bibs и GET …/startlist.xlsx
`hub/hub.py:3208-3210`
```python
            if action == "bibs":            # 5.2: шаг 2 Мастера — ручные нагрудные номера
                ages = [a for a in str(qs.get("ages") or "").split(",") if a]
                return ok(self.bibs_view(ev, {"distance": qs.get("distance"), "sex": qs.get("sex"), "ages": ages}))
```


#### POST …/bibs
`hub/hub.py:3618-3620`
```python
        if action == "bibs":
            code, out = self.save_bibs(ev, data.get("rows") if isinstance(data.get("rows"), list) else [], who)
            return code, J, json.dumps(out, ensure_ascii=False), None
```


#### POST …/entry — поздняя заявка / правка участника
`hub/hub.py:3639-3714`
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
                # 5.2: номер только ручной — из поля рядом с заявкой или вписанный на шаге 2 «Регистрация номеров»
                bib, e_ = clean_bib(data.get("set_bib") or r.get("bib"), {e["bib"] for e in rows})
                if not str(data.get("set_bib") or r.get("bib") or "").strip():
                    return err("впишите нагрудный номер участника (шаг 2 Мастера «Регистрация номеров»)")
                if e_:
                    return err(e_)
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


### 2.4 Расчёт результатов: секундомеры, попытки, разряды


#### Hub.fmt_result
`hub/hub.py:2224-2235`
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


#### Hub.norm_rank
`hub/hub.py:2245-2250`
```python
    @classmethod
    def norm_rank(cls, v) -> str:
        """Разряд как в протоколах: «1р», «1 разряд», «кмс» → «1 р.», «КМС». Пустое — пустая строка."""
        t = re.sub(r"\s+", " ", str(v or "")).strip()[:20]
        key = re.sub(r"[\s./]+", "", t.lower()).replace("первый", "1").replace("второй", "2").replace("третий", "3")
        return cls._RANK_ALIAS.get(key) or cls._RANK_ALIAS.get(key.rstrip("."), "") or t
```


#### Hub.stopwatch_main
`hub/hub.py:2257-2266`
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


#### Hub.attempt_slots
`hub/hub.py:2270-2276`
```python
    @classmethod
    def attempt_slots(cls, name) -> int:
        """Сколько ячеек попыток: 6 в прыжках и метаниях; в высоте и шесте — до 12 покорённых высот."""
        d = cls.discipline(name)
        if not d or not d.get("attempts"):
            return 0
        return 12 if d.get("result") == "height" else 6
```


#### Hub.parse_attempts
`hub/hub.py:2278-2301`
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


#### Hub.parse_result
`hub/hub.py:2306-2323`
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


#### Hub.result_type
`hub/hub.py:2478-2482`
```python
    @classmethod
    def result_type(cls, name) -> str:
        """time · distance · height · points. Неизвестная дисциплина — время, как раньше."""
        d = cls.discipline(name)
        return d["result"] if d else "time"
```


#### Hub.parse_typed
`hub/hub.py:2484-2503`
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


#### Hub.parse_best
`hub/hub.py:3818-3832`
```python
    @staticmethod
    def parse_best(text: str) -> Optional[float]:
        """12.5 · 12,5 · 4:05.2 · 1:02:05 → секунды."""
        t = (text or "").strip().replace(",", ".").replace(" ", "")
        if not t:
            return None
        m = re.fullmatch(r"(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,2}(?:\.\d{1,3})?)", t)
        if not m:
            return None
        a, b, c = m.groups()
        if a is not None and b is not None:
            return int(a) * 3600 + int(b) * 60 + float(c)
        if a is not None:
            return int(a) * 60 + float(c)
        return float(c)
```


#### Hub.rank_norms
`hub/hub.py:2397-2410`
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


#### Hub.rank_for
`hub/hub.py:2419-2459`
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


#### Hub.compute
`hub/hub.py:2555-2818`
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


### 2.4a Приём результатов ручного ввода


#### POST …/results {rows}
`hub/hub.py:3306-3383`
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


### 2.5 Сессии, вход и роли


#### Store.add_session
`hub/hub.py:951-956`
```python
    def add_session(self, token_hash: str, login: str, days: int, ip: str) -> None:
        now = now_local()
        self.con.execute("DELETE FROM sessions WHERE expires_at < ?", (fmt_db(now),))
        self.con.execute("INSERT INTO sessions(token, login, created_at, expires_at, ip) VALUES (?,?,?,?,?)",
                         (token_hash, login, fmt_db(now), fmt_db(now + dt.timedelta(days=days)), ip))
        self.con.execute("UPDATE users SET last_login = ? WHERE login = ?", (fmt_db(now), login))
```


#### Store.get_session
`hub/hub.py:958-961`
```python
    def get_session(self, token_hash: str) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM sessions WHERE token = ? AND expires_at > ?",
                                           (token_hash, fmt_db(now_local()))))
        return rows[0] if rows else None
```


#### Store.delete_session
`hub/hub.py:963-964`
```python
    def delete_session(self, token_hash: str) -> None:
        self.con.execute("DELETE FROM sessions WHERE token = ?", (token_hash,))
```


#### Hub.ROLES
`hub/hub.py:6136-6136`
```python
    ROLES = {"admin": "Администратор", "judge": "Судья"}
```


#### Hub.LEGACY_ROLES
`hub/hub.py:6137-6137`
```python
    LEGACY_ROLES = {"secretary": "judge", "sector": "judge"}     # роли до 4.5.0 — сводятся к судье
```


#### Hub.TRAINER_PANEL
`hub/hub.py:6235-6235`
```python
    TRAINER_PANEL = ("/api/me", "/api/logout", "/protocol")
```


#### Hub.JUDGE_OPEN
`hub/hub.py:6227-6227`
```python
    JUDGE_OPEN = ("/api/system/scoreboard/control",)                 # пульт табло — судейский, хоть и под /api/system
```


#### Hub.ADMIN_ONLY
`hub/hub.py:6226-6226`
```python
    ADMIN_ONLY = re.compile(r"/api/(system|readers|wiclax-ports|users|trainers|consents)(/.*)?|/raw|/simple")
```


#### Hub.JUDGE_DENY_POST
`hub/hub.py:6228-6228`
```python
    JUDGE_DENY_POST = re.compile(r"/api/events/\d+/delete")          # удалить соревнование целиком
```


#### Hub._auth_ok
`hub/hub.py:6116-6133`
```python
    def _auth_ok(self, headers: dict, allow_api_key: bool) -> bool:
        web = self.cfg["web"]
        pwd = web.get("password") or ""
        key = web.get("api_key") or ""
        if allow_api_key and key:
            got = headers.get("x-api-key", "")
            if got and hmac.compare_digest(got, key):
                return True
        if not pwd:
            return not (allow_api_key and key)
        auth = headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                u, _, p = base64.b64decode(auth[6:].strip()).decode("utf-8").partition(":")
            except Exception:
                return False
            return hmac.compare_digest(u, web.get("user", "admin")) and hmac.compare_digest(p, pwd)
        return False
```


#### Hub.hash_password
`hub/hub.py:6141-6150`
```python
    @staticmethod
    def hash_password(pwd: str) -> str:
        """scrypt; если его нет в сборке Python/OpenSSL на сервере — PBKDF2-SHA256 (600 000 итераций)."""
        salt = os.urandom(16)
        try:
            h = hashlib.scrypt(pwd.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
            return f"scrypt${salt.hex()}${h.hex()}"
        except (AttributeError, ValueError, MemoryError):
            h = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, 600_000)
            return f"pbkdf2$600000${salt.hex()}${h.hex()}"
```


#### Hub.verify_password
`hub/hub.py:6152-6167`
```python
    @staticmethod
    def verify_password(pwd: str, stored: str) -> bool:
        try:
            parts = stored.split("$")
            if parts[0] == "scrypt":
                _, salt, h = parts
                got = hashlib.scrypt(pwd.encode("utf-8"), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32,
                                     maxmem=64 * 1024 * 1024)
            elif parts[0] == "pbkdf2":
                _, it, salt, h = parts
                got = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), bytes.fromhex(salt), int(it))
            else:
                return False
            return hmac.compare_digest(got.hex(), h)
        except (AttributeError, ValueError, TypeError, MemoryError):
            return False
```


#### Hub.check_login
`hub/hub.py:6169-6179`
```python
    def check_login(self, login: str, pwd: str) -> Optional[dict]:
        """Пользователь из таблицы или учётка из настроек (web.user / web.password) — администратор."""
        u = self.store.get_user(login)
        if u:
            ok = self.verify_password(pwd, u["pwd"]) and u.get("active", 1)
            return {"login": u["login"], "name": u["name"] or u["login"], "role": self._role(u["role"])} if ok else None
        web = self.cfg["web"]
        cfg_pwd = web.get("password") or ""
        if cfg_pwd and hmac.compare_digest(login, web.get("user", "admin")) and hmac.compare_digest(pwd, cfg_pwd):
            return {"login": login, "name": "Администратор", "role": "admin"}
        return None
```


#### Hub._user_by_login
`hub/hub.py:6181-6194`
```python
    def _user_by_login(self, login: str) -> Optional[dict]:
        if login.startswith("trainer:"):
            t = self.store.trainer_by_id(int(login[8:])) if login[8:].isdigit() else None
            if not t or not t.get("active", 1) or not t.get("is_verified"):
                return None     # заблокирован или почта не подтверждена — сеанса нет
            return {"login": t["email"], "name": t["name"], "role": "trainer", "team": t["team"], "trainer_id": t["id"]}
        u = self.store.get_user(login)
        if u:
            if not u.get("active", 1):
                return None     # заблокирован
            return {"login": u["login"], "name": u["name"] or u["login"], "role": self._role(u["role"])}
        if login == self.cfg["web"].get("user", "admin"):
            return {"login": login, "name": "Администратор", "role": "admin"}
        return None
```


#### Hub.session_user
`hub/hub.py:6204-6209`
```python
    def session_user(self, headers: dict) -> Optional[dict]:
        tok = self._cookie(headers, self.SESSION_COOKIE)
        if not tok or len(tok) > 100:
            return None
        sess = self.store.get_session(hashlib.sha256(tok.encode()).hexdigest())
        return self._user_by_login(sess["login"]) if sess else None
```


#### Hub.request_user
`hub/hub.py:6211-6223`
```python
    def request_user(self, headers: dict, proxied: bool) -> Optional[dict]:
        u = self.session_user(headers)
        if u:
            return u
        # Basic-авторизация — только напрямую (VPN, скрипты, самопроверка), не через nginx из интернета
        if not proxied and self._auth_ok(headers, allow_api_key=False) and self.cfg["web"].get("password"):
            blocked = self.store.get_user(self._auth_user(headers))
            if blocked and not blocked.get("active", 1):
                return None
            return self._user_by_login(self._auth_user(headers)) or {"login": self._auth_user(headers), "name": "", "role": "admin"}
        if not self.cfg["web"].get("password") and not proxied:
            return {"login": "-", "name": "", "role": "admin"}
        return None
```


#### Hub._role
`hub/hub.py:6230-6232`
```python
    def _role(self, role: str) -> str:
        role = self.LEGACY_ROLES.get(role, role)
        return role if role in self.ROLES else "judge"
```


#### Hub.role_allows
`hub/hub.py:6237-6247`
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


#### Hub._auth_user
`hub/hub.py:6249-6257`
```python
    @staticmethod
    def _auth_user(headers: dict) -> str:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                return base64.b64decode(auth[6:].strip()).decode("utf-8").partition(":")[0] or "?"
            except Exception:
                return "?"
        return "-"
```


#### Hub.do_login
`hub/hub.py:6267-6289`
```python
    def do_login(self, body: bytes, headers: dict, ip: str, secure: bool) -> tuple:
        if headers.get("x-requested-with") != "timing-hub":
            return 403, {"error": "нужен заголовок X-Requested-With"}, None
        try:
            d = json.loads(body.decode("utf-8") or "{}")
            login, pwd = str(d.get("login") or "").strip()[:64], str(d.get("password") or "")[:200]
        except (ValueError, UnicodeDecodeError, AttributeError):
            return 400, {"error": "неверные данные"}, None
        if not (self._rate_ok("login-ip:" + ip, 10, 600) and self._rate_ok("login-u:" + login.lower(), 10, 600)
                and self._rate_ok("login-all", 200, 600)):
            return 429, {"error": "Слишком много попыток. Подождите 10 минут."}, None
        u = self.check_login(login, pwd) if login and pwd else None
        if not u:
            self.store.audit(f"{login or '?'}@{ip}", None, "Неудачный вход")
            return 401, {"error": "Неверный логин или пароль"}, None
        import secrets
        tok = secrets.token_urlsafe(32)
        self.store.add_session(hashlib.sha256(tok.encode()).hexdigest(), u["login"], self.SESSION_DAYS, ip)
        self.store.audit(f"{u['login']}@{ip}", None, "Вход")
        cookie = (f"{self.SESSION_COOKIE}={tok}; Path=/; Max-Age={self.SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax"
                  + ("; Secure" if secure else ""))
        nxt = self._safe_next(d.get("next"))
        return 200, {"ok": True, "user": u, "next": nxt}, {"Set-Cookie": cookie}
```


#### Hub._trainer_session
`hub/hub.py:6414-6419`
```python
    def _trainer_session(self, t: dict, headers: dict, ip: str) -> dict:
        import secrets
        tok = secrets.token_urlsafe(32)
        self.store.add_session(hashlib.sha256(tok.encode()).hexdigest(), f"trainer:{t['id']}", self.SESSION_DAYS, ip)
        self.store.update_trainer(t["id"], last_login=fmt_db(now_local()))
        return {"Set-Cookie": self._trainer_cookie(tok, headers)}
```


#### Точка проверки роли в обработчике HTTP
`hub/hub.py:6752-6767`
```python
                    from urllib.parse import quote
                    nxt = "" if path == "/" else "?next=" + quote(target, safe="")
                    await self._send(writer, 302, "text/plain", "", extra={"Location": "/login" + nxt})
                return
            if user["role"] == "trainer" and path == "/protocol" and method == "GET":
                # тренер видит протокол только в закрытой части /r/: без чипов, и только выложенный организатором
                ev_ = self.store.get_event(int(qs["event"])) if str(qs.get("event", "")).isdigit() else None
                v_ = self._event_view(ev_) if ev_ else None
                ok_ = v_ and ev_.get("reg_slug") and v_["ours"] and (v_["pub_start"] or v_["pub_results"])
                await self._send(writer, 302, "text/plain", "",
                                 extra={"Location": f"/r/{ev_['reg_slug']}/protocol" if ok_ else "/r/trainer"})
                return
            if not self.role_allows(user["role"], method, path):
                if method == "GET" and not path.startswith("/api/"):
                    await self._send(writer, 302, "text/plain", "",
                                     extra={"Location": "/r/trainer" if user["role"] == "trainer" else "/"})
```


## 3. Админка `hub/ui.html`


### 3.1 Верхняя панель этапов 1–7 и маршрутизация вкладок


#### Разметка панели этапов
`hub/ui.html:618-626`
```html
<nav class="lane" id="lane" aria-label="Этапы соревнования">
  <a href="#prep" data-step="prep" class="st" id="stPrep"><span class="pin">1</span><b>Подготовка</b><small></small></a>
  <a href="#reg" data-step="reg" class="st" id="stReg"><span class="pin">2</span><b>Регистрация</b><small></small></a>
  <a href="#wizard" data-step="wizard" class="st hide" id="stWiz"><span class="pin">3</span><b>Протоколы</b><small>мастер</small></a>
  <a href="#check" data-step="check" class="st" id="stCheck"><span class="pin">3</span><b>Чипы</b><small></small></a>
  <a href="#timing" data-step="timing" class="st" id="stTiming"><span class="pin">4</span><b>Старт и финиш</b><small></small></a>
  <a href="#results" data-step="results" class="st" id="stResults"><span class="pin">5</span><b>Результаты</b><small></small></a>
  <a href="#files" data-step="files" class="st" id="stFiles"><span class="pin">6</span><b>Документы</b><small></small></a>
</nav>
```


#### Разметка вкладки Мастера
`hub/ui.html:1030-1041`
```html
<section id="tab-wizard" class="hide">
  <div class="wzp-head">
    <div class="wzp-title"><h1>Мастер протоколов</h1><span class="small muted" id="wzpEv"></span></div>
  </div>
  <div class="wzp-top">
    <label class="wzp-disc"><span class="small muted">Дисциплина</span><select id="wzpDisc" aria-label="Дисциплина"></select></label>
    <span class="wzp-kind" id="wzpKind"></span>
  </div>
  <div class="wzp-steps" id="wzpSteps" role="tablist"></div>
  <div class="wzp-body" id="wzpBody"></div>
  <div class="cartbox cartmount"></div>
</section>
```


#### STEPS / ALIAS
`hub/ui.html:1284-1285`
```javascript
const STEPS = ["prep","reg","wizard","check","timing","results","files"];
const ALIAS = {overview:"home", events:"home", archive:"home", "":"welcome", "protocol-master":"wizard"};
```


#### showTab — переключение вкладок (+ hashchange → scrollTo(0,0))
`hub/ui.html:1328-1363`
```javascript
function showTab(){
  let tab = tabName(), pane = "";
  // 5.2: у стадиона с ручным вводом один экран ввода — шаг 4 Мастера; старый экран «Ввод результатов» не открываем
  if (tab === "timing" && isEntryMode(curEvent())) { wzp.setStep(4); history.replaceState(null, "", "#wizard"); tab = "wizard"; }
  if (/^hw-(timing|net)$/.test(tab)) { pane = tab.slice(3); tab = "hw"; } else if (tab === "hw") pane = "gen";
  if (!document.getElementById("tab-"+tab)) tab = "home";
  if ((tab === "hw" || tab === "users") && ME && ME.role !== "admin") tab = "log";
  if (STEPS.includes(tab) && !curEvent()) tab = "home";
  document.body.dataset.view = tab; applyDir();
  document.querySelectorAll("main>section").forEach(s => s.classList.toggle("hide", s.id !== "tab-"+tab));
  document.querySelectorAll(".lane .st").forEach(a => a.classList.toggle("on", a.dataset.step === tab));
  const onStep = document.querySelector(".lane .st.on"), lane = $("lane");
  if (onStep && lane.scrollWidth > lane.clientWidth) lane.scrollLeft = onStep.offsetLeft - (lane.clientWidth - onStep.offsetWidth) / 2;
  // в мастере протоколов своя навигация (шаги 1–5) — общая панель этапов скрыта, чтобы шаги не задваивались
  $("lane").classList.toggle("hide", !STEPS.includes(tab));
  renderFinState();
  if (STEPS.includes(tab) && tab !== "wizard") store.set("ss.lastStep", tab);
  $("gear").classList.toggle("on", tab === "hw" || tab === "log" || tab === "users");
  closeMenus();
  if (tab === "home") { renderEvents(); }
  if (tab === "prep") { openForm(curEvent(), "prep"); loadEntries(); }
  if (tab === "results" || tab === "timing") loadResults();
  if (tab === "timing") { loadManual(); applyTimingMode(); }
  if (tab !== "timing") document.body.dataset.mode = "";
  if (tab === "users") { loadUsers(); loadTrainers(); loadConsents(); }
  if (tab === "prep") renderSite();
  if (tab === "files") renderPub();
  if (tab === "check") { loadCheck(); loadPickup(); }
  if (tab === "log") loadLog();
  if (tab === "hw") { document.querySelectorAll("#tab-hw .syspane").forEach(p => p.classList.toggle("hide", p.dataset.pane !== pane)); loadHw(); loadReaders(); loadUpdate(); loadLast(); }
  if (tab === "hw" || tab === "users" || tab === "log") renderSysNav(tab === "hw" ? (pane === "gen" ? "hw" : "hw-" + pane) : tab);
  if (tab === "files") renderFilesTab();
  if (tab === "reg") { renderRegHead(true); loadRegs(); }
  if (tab === "wizard") wzp.open();
}
window.addEventListener("hashchange", () => { showTab(); window.scrollTo(0, 0); });
```


#### defaultStep / openEvent
`hub/ui.html:1364-1370`
```javascript
function defaultStep(ev){ return !ev ? "home" : ev.status==="running" ? "timing" : ev.status==="finished" ? "results" : (ev.reg_open || ev.regs_pending) ? "reg" : "prep"; }
function openEvent(id){
  const e0 = events.find(x => x.id === id); if (e0) setDir(e0.kind === "stadium" ? "stadium" : "ipico");
  selectEvent(id);
  const t = tabName(), step = STEPS.includes(t) ? t : defaultStep(curEvent());
  if (location.hash !== "#"+step) location.hash = "#"+step; else showTab();
}
```


#### loadEvents — опрос раз в 15 с
`hub/ui.html:1423-1434`
```javascript
async function loadEvents(){
  const r = await api("/api/events");
  const sig = JSON.stringify(r.events);
  if (sig === loadEvents._sig && curEvent()) return;
  loadEvents._sig = sig;
  events = r.events;
  if (curId == null || !curEvent()) {
    const saved = parseInt(store.get("timing.event")||"", 10);
    curId = events.some(e=>e.id===saved) ? saved : ((events.find(e=>e.status==="running")||events[0]||{}).id ?? null);
  }
  renderEvents();
}
```


#### renderEvents — перерисовывает меню, панель этапов, шапки
`hub/ui.html:1452-1478`
```javascript
function renderEvents(){
  const td = localDate(), active = events.filter(e => !e.archived && inDir(e));
  renderHome();
  const now = active.filter(e => e.status === "running" || (e.date && e.date <= td && (e.date_end || e.date) >= td));
  const soon = active.filter(e => !now.includes(e) && e.date && e.date > td).sort((a,b) => a.date.localeCompare(b.date));
  const rest = active.filter(e => !now.includes(e) && !soon.includes(e));
  const grp = (t, l) => l.length ? `<h2 class="group">${t}</h2>` + l.map(e => evRow(e, td)).join("") : "";
  $("evList").innerHTML = grp("Сегодня", now) + grp("Скоро", soon) + grp("Прошли — ещё не в архиве", rest)
    || `<div class="panel empty">${events.length ? (DIR && !dirAll && events.some(e => !e.archived) ? "В этом направлении соревнований пока нет — создайте новое кнопкой выше или нажмите «показать все»." : "Все соревнования в архиве. Создайте новое или верните из архива.") : "Соревнований пока нет — создайте первое кнопкой «Новое соревнование»."}</div>`;
  $("calImport").classList.toggle("hide", events.some(e => e.pub_site));
  const ev = curEvent();
  $("evBtnName").textContent = ev ? ev.name : "Выберите соревнование";
  $("evBtnMeta").textContent = ev ? ([fmtDate(ev.date), ev.place].filter(Boolean).join(" · ") || "без даты") + (ev.archived ? " · архив" : "") : "все соревнования и архив";
  const mlist = events.filter(e => !e.archived); if (ev && ev.archived) mlist.unshift(ev);
  $("evMenu").innerHTML = mlist.map(e => `<button class="mi ${e.id===curId?"sel":""}" data-id="${e.id}"><b class="${e.status==="running"?"live":""}">${esc(e.name)}</b><small>${esc([fmtDate(e.date), e.place].filter(Boolean).join(" · ") || "без даты")}${e.archived?" · архив":""}</small></button>`).join("")
    + `${mlist.length?"<hr>":""}<a href="#home"><b>Все соревнования и архив</b></a><button class="mi" data-new="1"><b>+ Новое соревнование</b></button>`;
  $("lnkJudge").href = ev ? "/judge?event="+ev.id : "/judge";
  $("lnkSector").href = ev ? "/sector?event="+ev.id : "/sector";
  $("lnkScore").href = ev ? "/scoreboard?event="+ev.id : "/scoreboard";
  $("lnkAnn").href = ev ? "/announcer?event="+ev.id : "/announcer";
  $("lnkBoard").href = ev ? "/board?event="+ev.id : "/board";
  $("lnkProto").href = ev ? "/protocol?event="+ev.id : "/protocol";
  if (tabName()==="files") renderFilesTab();
  renderWaves(); renderTimingHead(); renderRegHead(); renderLane(); renderFinState();
  if (tabName()==="home") renderArchive();
  if (STEPS.includes(tabName()) && !ev && document.body.dataset.view !== "home") showTab();
}
```


#### setStep (панель этапов) и renderLane
`hub/ui.html:1480-1506`
```javascript
function setStep(id, cls, text){ const a = $(id); const hid = a.classList.contains("hide"); a.className = "st " + (cls||"") + (a.dataset.step === document.body.dataset.view ? " on" : "") + (hid ? " hide" : ""); a.querySelector("small").textContent = text || ""; }
function renderLane(){
  const ev = curEvent(); if (!ev) return;
  const stadium = ev.kind === "stadium", entry = isEntryMode(ev);
  $("stCheck").querySelector("b").textContent = stadium ? "Выдача номеров" : "Номера и чипы";
  $("chipSect").classList.toggle("hide", stadium);
  $("stTiming").querySelector("b").textContent = entry ? "Ввод результатов" : stadium ? "Забеги" : "Старт и финиш";
  $("stWiz").classList.toggle("hide", !stadium);
  let n = 0; document.querySelectorAll(".lane .st").forEach(a => { if (!a.classList.contains("hide")) a.querySelector(".pin").textContent = ++n; });
  const w = ev.waves.length, rp = ev.regs_pending || 0, rc = ev.regs_count || 0;
  setStep("stPrep", ev.finish_device && (ev.entries_count || rc) ? "done" : "",
    [ev.entries_count ? `${ev.entries_count} в списке` : "список пуст", w ? `${w} ${plural(w, ["забег","забега","забегов"])}` : ""].filter(Boolean).join(" · "));
  setStep("stReg", rp ? "warn" : rc ? "done" : "", rp ? `${rp} ждут проверки` : rc ? `${rc} ${plural(rc, ["заявка","заявки","заявок"])}` : ev.reg_open ? "приём открыт" : "приём не открыт");
  const c = chkCache && chkCache.ev === ev.id ? chkCache : null;
  const pk = pkCache && pkCache.ev === ev.id ? pkCache : null;
  if (stadium || (pk && pk.picked && !(c && c.since))) setStep("stCheck", pk && pk.total && pk.picked >= pk.total ? "done" : "",
    pk && pk.total ? (pk.picked ? `выдано ${pk.picked} из ${pk.total}` : "номера не выданы") : "перед стартом");
  else setStep("stCheck", c && c.total ? (c.checked >= c.total ? "done" : c.since ? "warn" : "") : "",
    c && c.total ? (c.checked >= c.total ? "все проверены" : `${c.total - c.checked} не проверены`) : "перед стартом");
  const run = ev.waves.filter(x => x.state === "running").map(x => x.name);
  setStep("stTiming", ev.status === "running" ? "live" : ev.status === "finished" ? "done" : "",
    entry ? (ev.status === "finished" ? "завершено" : "ручной секундомер") :
    ev.status === "running" ? (run.length ? "идёт: " + run.join(", ") : "идёт") : ev.status === "finished" ? "завершено" : "старт не дан");
  const r = lastRes && lastRes._ev === ev.id ? lastRes : null;
  setStep("stResults", ev.status === "finished" ? "done" : "", r && r.finished.length ? `финишировали: ${r.finished.length}` : "появятся после старта");
  setStep("stFiles", "", ev.files_count ? `${ev.files_count} ${plural(ev.files_count, ["файл","файла","файлов"])}` : "протоколы, файлы");
}
```


#### Запуск и таймеры опроса
`hub/ui.html:3418-3436`
```javascript
/* ---------- запуск ---------- */
(async function init(){
  loadDisc();
  ["nRank", "mRank"].forEach(i => $(i).innerHTML = rankOpts("", "Разряд *"));
  await loadMe();
  await loadStatus(); await loadDevices();
  try { await loadEvents(); await loadEntries(); } catch(e){ toast("Не удалось загрузить соревнования"); }
  showTab();
  setInterval(tick, 100);
  setInterval(loadStatus, 4000);
  setInterval(() => { if (tabName()==="hw-timing") loadLast(); }, 2000);
  setInterval(() => { if (tabName()==="reg") loadRegs(); }, 10000);
  setInterval(loadHw, 10000);
  loadHw();
  setInterval(pollFeed, 1000);
  setInterval(() => { const t=tabName(); if (t==="check") { loadCheck(); loadPickup(); } if (t==="timing") { loadManual(); if (isEntryMode(curEvent())) loadEntry(); } if ((t==="timing"||t==="results") && curEvent()?.status==="running") loadResults(); }, 3000);
  setInterval(async () => { try{ const id=curId; await loadEvents(); if (id!==curId) loadEntries(); }catch(e){} }, 15000);
  pollFeed();
})();
```


### 3.2 Мастер протоколов (модуль `wzp`, шаги 1–5 целиком)

Шаг 2 — функции `bibQ`, `loadBibs`, `step2`, `renderBibs`, `bibCheck`, `saveBibs`; шаг 4 — `step4`, `startedBox`, `startReset`, `queueAuto`, `saveRows`, `refreshRows`, `clearAll`.


#### const wzp = (() => { … })()
`hub/ui.html:2133-2462`
```javascript
const wzp = (() => {
  const W = {disc: "", step: 1, ages: [], sex: "", lanes: 8, regs: [], sl: null, ev: null};
  const AGE_LIM = {u12:[0,12], u14:[0,14], u16:[0,16], u18:[0,18], u20:[0,20], u23:[0,23], sen:[19,200]};
  const STEP_T = {
    run:   ["Фильтр участников", "Нагрудные номера", "Забеги и стартовый протокол", "Ввод на финише", "Итоговый протокол"],
    tech:  ["Фильтр участников", "Нагрудные номера", "Общий список и стартовый протокол", "Ввод с сектора", "Итоговый протокол"]};
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
  function go(n){
    if (W.step === 2 && W.bibDirty && !confirm("Нагрудные номера изменены, но не сохранены. Уйти с шага без сохранения?")) return;
    W.bibDirty = false; W.step = Math.max(1, Math.min(5, n)); save(); render(); }
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
  // шаг 2: «Регистрация номеров» — судья вписывает нагрудный номер каждому подтверждённому участнику сам.
  // Автоматической выдачи номеров нет; в базу номера попадают только по кнопке «Сохранить нагрудные номера».
  const bibQ = () => `distance=${encodeURIComponent(W.disc)}&sex=${encodeURIComponent(W.sex)}&ages=${encodeURIComponent(W.ages.join(","))}`;
  async function loadBibs(){ W.bibs = await api(`/api/events/${ev().id}/bibs?${bibQ()}`); return W.bibs; }
  function step2(body, k){
    const pend = W.regs.filter(r => r.distance === W.disc && r.status === "pending").length;
    body.innerHTML = `<h2>Шаг 2. Регистрация нагрудных номеров</h2>
      <p class="small muted" style="margin:0">${esc(W.disc)} · возраст: ${W.ages.length ? W.ages.map(a => (DISC.ages.find(x => x.id === a) || {}).name).join(", ") : "любой"} · пол: ${esc(sexWord(W.sex))}.
        Впишите нагрудный номер каждому участнику с клавиатуры (Enter — к следующему) и нажмите «Сохранить нагрудные номера». Номера можно менять в любой момент — вернитесь сюда, исправьте и сохраните снова: стартовый список, отметки и результаты переедут на новый номер.</p>
      ${pend ? `<div class="wzp-lock">⏳ Ещё ${pend} заявок ждут проверки во вкладке «Регистрация» — их здесь нет, пока их не подтвердить.</div>` : ""}
      <div id="bibBox"><p class="muted">Загружаю участников…</p></div>
      <div class="row wzp-ctl bibctl"><button class="primary big" type="button" id="bibSave" disabled>💾 Сохранить нагрудные номера</button>
        <span class="wzp-sync" id="bibSync" role="status" aria-live="polite"></span></div>
      ${nav(true, k === "tech" ? "К общему списку" : "К забегам")}`;
    loadBibs().then(renderBibs).catch(err => { $("bibBox").innerHTML = `<p class="wzp-lock">Не удалось загрузить участников: ${esc(err.message)}</p>`; });
  }
  function renderBibs(){
    const d = W.bibs, box = $("bibBox"); if (!box || !d) return;
    if (!d.rows.length) { box.innerHTML = '<div class="card empty">Подтверждённых участников по фильтру шага 1 нет. Подтвердите заявки во вкладке «Регистрация» или измените фильтр.</div>'; return; }
    let last = null;
    const rows = d.rows.map((r, i) => { const c = r.category || "без категории", hd = c !== last ? `<tr class="wzp-cat"><td colspan="7">${esc(c)}</td></tr>` : ""; last = c;
      return hd + `<tr data-ids="${r.ids.join(",")}" data-orig="${esc(r.bib)}">
        <td class="n">${i + 1}</td>
        <td><input class="bibin2" value="${esc(r.bib)}" maxlength="10" inputmode="numeric" autocomplete="off" aria-label="Нагрудный номер: ${esc(r.name)}" placeholder="№"></td>
        <td><b>${esc(r.name)}</b>${r.members ? `<div class="small muted">${esc(r.members)}</div>` : ""}</td><td>${esc(r.birth_year)}</td><td class="small">${esc(r.rank)}</td><td class="small">${esc(r.team)}</td>
        <td class="small muted">${r.has_result ? "есть результат" : r.in_grid ? "в сетке" : ""}</td></tr>`; }).join("");
    box.innerHTML = `<p class="small" id="bibStat"></p>
      <div class="tbl"><table class="wzp-grid bibtbl"><thead><tr><th>№ п/п</th><th>Нагрудный номер</th><th>Фамилия, имя</th><th>Год рожд.</th><th>Разряд</th><th>Команда</th><th></th></tr></thead><tbody id="bibRows">${rows}</tbody></table></div>`;
    bibCheck();
  }
  // живая проверка: пустые, повторы, несохранённые — до нажатия кнопки
  function bibCheck(){
    const trs = [...document.querySelectorAll("#bibRows tr[data-ids]")]; if (!trs.length) return;
    const cnt = {}; trs.forEach(tr => { const v = tr.querySelector("input").value.trim(); if (v) cnt[v] = (cnt[v] || 0) + 1; });
    let empty = 0, dup = 0, dirty = 0;
    trs.forEach(tr => { const i = tr.querySelector("input"), v = i.value.trim();
      const isDup = v && cnt[v] > 1, isDirty = v !== tr.dataset.orig;
      i.classList.toggle("err", !!isDup); tr.classList.toggle("dirty", isDirty); tr.classList.toggle("nobib", !v);
      if (!v) empty++; if (isDup) dup++; if (isDirty) dirty++; });
    $("bibStat").innerHTML = `Участников: <b>${trs.length}</b> · с номером: <b>${trs.length - empty}</b>${empty ? ` · <span class="bad">без номера: ${empty}</span>` : ""}${dup ? ` · <span class="bad">повторяются: ${dup}</span>` : ""}${dirty ? ` · <span class="warn">не сохранено: ${dirty}</span>` : ""}`;
    $("bibSave").disabled = !dirty || dup > 0;
    W.bibDirty = dirty > 0;
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
    body.innerHTML = `<h2>Шаг 3. ${tech ? "Общий список и стартовый протокол" : "Забеги и стартовый протокол"}</h2>
      ${tech ? '<div class="wzp-lock">🔒 Техника: дорожки заблокированы. Каждая категория — отдельный сквозной «Общий список» в порядке выполнения попыток; лист альбомный, 6 попыток и «Лучший результат».</div>'
        : `<p class="small muted" style="margin:0">Бег: посев по заявленному результату — сильнейшие в последнем забеге, на центральных дорожках. Лист книжный, графы «Сек. 1 | Сек. 2 | Сек. 3».</p>
           <label class="small">Дорожек на стадионе <input type="number" id="wzpLanes" min="1" max="50" value="${W.lanes}" style="width:80px"></label>`}
      <div id="bibWarn"></div>
      <div class="row wzp-ctl"><button class="primary" type="button" id="wzpGen" ${n ? "" : "disabled"}>${tech ? "⚡ Сформировать общий список" : "⚡ Сформировать забеги"}</button>
        <button class="danger" type="button" id="wzpReset" ${myHeats().length ? "" : "disabled"}>❌ Сбросить сетку / Удалить забеги</button>
        <span class="small muted">${n} участников по фильтру шага 1</span></div>
      ${myHeats().length ? `<div class="row xlsrow"><a class="btn xls" id="wzpXlsx" href="/api/events/${ev().id}/startlist.xlsx?${bibQ()}">📊 Выгрузить стартовый протокол в Excel (.xlsx)</a>
        <span class="small muted">${tech ? "Порядок выполнения, 6 попыток и «Лучший результат» — пустые графы для записи ручкой на секторе." : "Забег, дорожка и три пустые графы «Секундомер 1–3» — для записи времени ручкой на финише."}</span></div>` : ""}
      ${myHeats().length ? `<p class="small muted" style="margin:0">Над бланком — вкладки: «Все участники», «Мальчики», «Девочки» и каждая категория. Нужную вкладку можно сразу положить в корзину печати.</p>
        <iframe class="wzp-frame" src="${protoUrl(q, true)}" title="Предпросмотр стартового протокола"></iframe>
        <div class="row"><a class="btn" target="_blank" href="${protoUrl(q, false)}">Открыть для печати ↗</a></div>`
        : '<div class="card empty">Сетки по этой дисциплине пока нет — нажмите «⚡ Сформировать…».</div>'}
      ${nav(true, "К вводу результатов")}`;
    // без ручных номеров сетку не построить: показываем, сколько не хватает, и ведём на шаг 2
    loadBibs().then(d => { const miss = d.total - d.with_bib, w = $("bibWarn"); if (!w) return;
      w.innerHTML = miss ? `<div class="wzp-lock">✍️ У ${miss} из ${d.total} участников нет нагрудного номера — сетку не сформировать. <button type="button" class="sm" data-s="2">Вписать номера на шаге 2</button></div>` : "";
      const g = $("wzpGen"); if (g && miss) g.disabled = true; }).catch(() => {});
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
      <div class="row"><a class="btn" target="_blank" href="${protoUrl(q, false)}">Открыть для печати ↗</a></div>
      <div class="row wzp-ctl" style="margin-top:14px"><button type="button" id="wzpFinish" class="${ev().status === "finished" ? "primary" : ""}">${ev().status === "finished" ? "↩️ Возобновить соревнование" : "🏁 Завершить соревнование"}</button>
        <span class="small muted">Завершение закрывает регистрацию и делает протокол итоговым; ошибочное завершение отменяется кнопкой «Возобновить».</span></div>${nav(true, "")}`;
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
      <p class="small muted" style="margin:0">${tech ? "Запишите шесть попыток: расстояние в метрах (7.85 или 7,85), X — заступ, «-» — пропуск. Сервер сам найдёт лучшую попытку, проверит её по правилам и выставит итог." : pts ? "Введите сумму очков — целое число." : "Впишите время с ручных секундомеров (12.84 или 1:05.3) — одно, два или три, сколько было судей. Одно время — это и есть официальный результат; из двух берётся худшее, из трёх — среднее по величине; округление вверх до 0,1 с. На табло и в итоговый протокол идёт только официальный результат."}
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
    if (e.target.id === "wzpPubS") return setPub("start", e.target.checked);
    if (e.target.id === "wzpPubR") return setPub("results", e.target.checked);
    const tr = e.target.closest("#wzpRows tr"); if (tr) { tr.classList.add("dirty"); queueAuto(); }
  });
  root.addEventListener("input", (e) => {
    if (e.target.classList.contains("bibin2")) { e.target.classList.remove("err"); return bibCheck(); }
    const tr = e.target.closest("#wzpRows tr"); if (!tr) return; tr.classList.add("dirty"); e.target.classList.remove("err");
    const out = tr.querySelector("[data-out]"); if (!out) return;
    const sw = [...tr.querySelectorAll("input.sw")], at = [...tr.querySelectorAll("input.att")];
    out.textContent = sw.length ? swMain(sw.map(i => i.value)) : at.length ? attBest(at.map(i => i.value)) : out.textContent;
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
    W.bibDirty = false; W.disc = e.target.value; W.step = 1; W.ages = []; W.sex = ""; save(); render(); };
  window.addEventListener("beforeunload", (e) => { if (W.step === 2 && W.bibDirty) { e.preventDefault(); e.returnValue = ""; } });
  // этап «Ввод результатов» стадиона с ручным вводом = шаг 4 Мастера (один экран ввода вместо двух)
  function setStep(n){ W.step = n; const e0 = ev(); if (!e0) return;
    try{ const k = "ss.wzp." + e0.id, sv = JSON.parse(localStorage.getItem(k) || "{}"); sv.step = n; localStorage.setItem(k, JSON.stringify(sv)); }catch(x){} }
  return {open, setStep};
})();
```


### 3.3 Старый экран «Ввод результатов» (вкладка timing) — дублирует шаг 4


#### isEntryMode … recalcRow
`hub/ui.html:3192-3321`
```javascript
function isEntryMode(ev){ return !!ev && ev.kind === "stadium" && (ev.timing === "manual" || ev.timing === "lynx"); }
function applyTimingMode(){
  const entry = isEntryMode(curEvent());
  $("resEntry").classList.toggle("hide", !entry);
  document.querySelector("#tab-timing .race").classList.toggle("hide", entry);
  document.body.dataset.mode = entry ? "entry" : "";
  if (entry) loadEntry();
}
let eData = null, eHeat = null;
const STATUS_NAMES = {DNS:"DNS — не стартовал", DNF:"DNF — сошёл", DQ:"DQ — дисквалифицирован", NM:"NM — без результата"};
async function loadEntry(){
  const ev = curEvent(); if (!ev) return;
  if (document.querySelector("#eBody tr.dirty")) return;      // не затираем то, что вписывают сейчас
  try{
    const [sl, rs] = await Promise.all([api(`/api/events/${ev.id}/startlist`), api(`/api/events/${ev.id}/results`)]);
    const place = {}; rs.finished.forEach(r => place[r.bib] = r.place);
    const groups = sl.heats.map(h => ({name: h.name, sub: [h.category, h.distance].filter(Boolean).join(" · "), entries: h.entries}));
    if (sl.no_heat.length) groups.push({name: groups.length ? "Без забега" : "Все участники", sub: "", entries: sl.no_heat});
    eData = {groups, place};
    if (!groups.some(g => g.name === eHeat)) eHeat = groups[0] ? groups[0].name : null;
    renderEntry();
  }catch(e){ console.warn(e); }
}
/* показания трёх секундомеров и попытки: главный результат считается сам, как на сервере */
const T_RE = /^(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,5})(?:[.,](\d{1,3}))?$/;
function parseT(t){
  t = String(t || "").replace(/\s+/g, ""); const m = T_RE.exec(t); if (!m || !t) return null;
  const [, a, b, c, f] = m, h = b != null ? +a : 0, mi = b != null ? +b : (a != null ? +a : 0), sec = +c;
  if ((a != null || b != null) && sec >= 60) return null;
  const tot = h * 3600 + mi * 60 + sec + (f ? +f / Math.pow(10, f.length) : 0); return tot > 0 ? tot : null;
}
function fmtT(sec){
  const tn = Math.round(sec * 10), h = Math.floor(tn / 36000), m = Math.floor(tn % 36000 / 600), s = Math.floor(tn % 600 / 10), t = tn % 10;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${t}` : m ? `${m}:${String(s).padStart(2, "0")}.${t}` : `${s}.${t}`;
}
function swMain(vals){
  const v = vals.map(parseT).filter(x => x != null).sort((a, b) => a - b); if (!v.length) return "";
  const main = v.length >= 3 ? v[1] : v[v.length - 1];
  return fmtT(Math.ceil(+(main * 10).toFixed(6)) / 10);
}
function attBest(vals, hi){
  let best = null; vals.forEach(x => { const m = /^(\d{1,3})(?:[.,](\d{1,2}))?$/.exec(String(x || "").replace(/\s+/g, "")); if (m) { const v = +(m[1] + "." + (m[2] || "0")); if (v > 0 && (best == null || v > best)) best = v; } });
  return best == null ? "" : best.toFixed(2);
}
// что вводить в забеге: «time» — три секундомера, «att» — попытки (6 или 12 для высоты), «one» — одно поле (очки и т.п.)
function entryMode(g){
  const dd = g && g.sub ? discBy(g.sub.split(" · ").pop()) : null;
  if (!dd || dd.result === "time") return {kind: "sw", rt: "time", dd};
  if (dd.attempts) return {kind: "att", rt: dd.result, n: dd.result === "height" ? 12 : 6, dd};
  return {kind: "one", rt: dd.result, dd};
}
const RT_HINT = {
  sw: "Три ручных секундомера: главный результат считается сам — среднее из трёх (если два совпали, это их время), из двух — худшее. Округление вверх до 0,1 с. Можно вписать главный результат вручную: он станет главным.",
  distance: "Попытки: расстояние в метрах (7.85 или 7,85), X — неудачная, «-» — пропуск. Лучший результат определяется сам; его можно поправить вручную.",
  height: "Покорённые высоты в метрах по порядку (1.80, 1.85 …), X — неудачная попытка. Лучшая высота определяется сама; детальные попытки по высотам ведутся в протоколе судей.",
  points: "Результат — сумма очков многоборья по таблице: целое число, например 7250."};
function renderEntry(){
  if (!eData) return;
  $("eHeats").innerHTML = eData.groups.map(g => `<button data-h="${esc(g.name)}" class="${g.name===eHeat?"on":""}">${esc(g.name)}${g.sub?` <span class="small muted" style="font-family:var(--body)">${esc(g.sub)}</span>`:""}<i>${g.entries.length}</i></button>`).join("");
  const g = eData.groups.find(x => x.name === eHeat), md = entryMode(g);
  $("eHint").textContent = md.kind === "sw" ? RT_HINT.sw : md.kind === "att" ? RT_HINT[md.rt] : RT_HINT[md.rt] || "";
  const head = md.kind === "sw" ? ["Дор.", "№", "Участник", "Разряд", "Секундомер 1", "Секундомер 2", "Секундомер 3", "Результат", "Отметка", "Место"]
    : md.kind === "att" ? ["№", "Участник", "Разряд", ...Array.from({length: md.n}, (_, i) => "П" + (i + 1)), "Лучший", "Отметка", "Место"]
    : ["Дор.", "№", "Участник", "Разряд", "Результат", "Отметка", "Место"];
  $("eHead").innerHTML = "<tr>" + head.map(h => `<th>${esc(h)}</th>`).join("") + "</tr>";
  const cells = (r) => {
    const d = r.detail || {}, ph = md.rt === "points" ? "очки" : md.rt === "time" ? "—" : "м";
    const main = `<td><input class="res" value="${esc(r.result||"")}" inputmode="decimal" placeholder="${ph}" aria-label="Результат ${esc(r.bib)}"><span class="mtag hide" title="Считать результат автоматически">вручную · авто</span></td>`;
    if (md.kind === "sw") return [0, 1, 2].map(i => `<td><input class="sw" data-i="${i}" value="${esc((d.t || [])[i] || "")}" inputmode="decimal" placeholder="—" aria-label="Секундомер ${i + 1}, ${esc(r.bib)}"></td>`).join("") + main;
    if (md.kind === "att") return Array.from({length: md.n}, (_, i) => `<td><input class="att" data-i="${i}" value="${esc((d.a || [])[i] || "")}" placeholder="—" aria-label="Попытка ${i + 1}, ${esc(r.bib)}"></td>`).join("") + main;
    return main;
  };
  $("eBody").innerHTML = g ? g.entries.map(r => `<tr data-bib="${esc(r.bib)}" class="${r.status?"st-out":""}">
      ${md.kind === "att" ? "" : `<td>${r.lane ?? ""}</td>`}<td class="bib">${esc(r.bib)}</td>
      <td><b>${esc(r.name||"")}</b><div class="small muted">${esc(r.birth_year||"")}${r.team ? " · " + esc(r.team) : ""}</div></td><td class="small">${esc(r.rank||"")}</td>
      ${cells(r)}
      <td><select class="stsel" aria-label="Отметка ${esc(r.bib)}"><option value="">—</option>${Object.entries(STATUS_NAMES).map(([k,t]) => `<option value="${k}" ${r.status===k?"selected":""}>${t}</option>`).join("")}</select></td>
      <td class="pl p${eData.place[r.bib]||""}">${eData.place[r.bib] ?? ""}</td></tr>`).join("")
    : `<tr><td colspan="${head.length}" class="empty">Участников нет. Загрузите стартовый список на этапе «Подготовка» или сформируйте забеги из заявок.</td></tr>`;
  // главный результат введён вручную, если он не совпадает с автоматическим
  if (g) g.entries.forEach(r => { const d = r.detail || {}; const tr = $("eBody").querySelector(`tr[data-bib="${CSS.escape(String(r.bib))}"]`); if (!tr) return;
    const calc = md.kind === "sw" ? swMain(d.t || []) : md.kind === "att" ? attBest(d.a || []) : null;
    if (calc != null && r.result && (d.t || d.a) && calc !== r.result) setManual(tr, true); });
}
function setManual(tr, on){ const res = tr.querySelector("input.res"); res.dataset.man = on ? "1" : ""; const t = tr.querySelector(".mtag"); if (t) t.classList.toggle("hide", !on); }
function recalcRow(tr){
  const res = tr.querySelector("input.res"); if (res.dataset.man === "1") return;
  const sw = [...tr.querySelectorAll("input.sw")].map(i => i.value), at = [...tr.querySelectorAll("input.att")].map(i => i.value);
  if (sw.length) res.value = swMain(sw); else if (at.length) res.value = attBest(at);
}
$("eHeats").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-h]"); if (!b) return;
  if (document.querySelector("#eBody tr.dirty") && !confirm("Есть несохранённые результаты в этом забеге. Перейти без сохранения?")) return;
  eHeat = b.dataset.h; renderEntry();
});
$("eBody").addEventListener("input", (e) => { const tr = e.target.closest("tr"); if (!tr) return; tr.classList.add("dirty");
  if (e.target.classList.contains("res")) setManual(tr, !!e.target.value.trim() && (tr.querySelector("input.sw,input.att") != null));
  else if (e.target.matches("input.sw,input.att")) recalcRow(tr); });
$("eBody").addEventListener("click", (e) => { const t = e.target.closest(".mtag"); if (!t) return; const tr = t.closest("tr"); setManual(tr, false); recalcRow(tr); tr.classList.add("dirty"); });
$("eBody").addEventListener("change", (e) => { const tr = e.target.closest("tr"); if (tr) tr.classList.add("dirty"); });
$("eBody").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.matches("input.res,input.sw,input.att")) return;
  e.preventDefault();
  // в строке с секундомерами или попытками главный результат пропускаем, пока он считается сам
  const all = [...document.querySelectorAll("#eBody input.res,#eBody input.sw,#eBody input.att")].filter(i => !(i.classList.contains("res")
    && i.closest("tr").querySelector("input.sw,input.att") && i.dataset.man !== "1" && i !== e.target)), i = all.indexOf(e.target);
  if (all[i+1]) { all[i+1].focus(); all[i+1].select(); } else $("eSave").click();
});
$("eSave").onclick = async () => {
  const rows = [...document.querySelectorAll("#eBody tr.dirty")].map(tr => {
    const row = {bib: tr.dataset.bib, result: tr.querySelector("input.res").value.trim(), status: tr.querySelector("select.stsel").value,
      auto: tr.querySelector("input.res").dataset.man !== "1"};
    const sw = [...tr.querySelectorAll("input.sw")], at = [...tr.querySelectorAll("input.att")];
    if (sw.length) row.t = sw.map(i => i.value.trim());
    if (at.length) row.a = at.map(i => i.value.trim());
    return row; });
  if (!rows.length) return toast("Нет изменений");
  try{
    const r = await api(`/api/events/${curId}/results`, {rows});
    if (r.errors.length) alert("Не сохранены:\n" + r.errors.join("\n"));
    toast(`Сохранено: ${r.saved}`);
    document.querySelectorAll("#eBody tr.dirty").forEach(tr => { if (!r.errors.some(x => x.startsWith(tr.dataset.bib + ":"))) tr.classList.remove("dirty"); });
    if (!document.querySelector("#eBody tr.dirty")) await loadEntry();
    loadResults(); loadEvents._sig = null; loadEvents();
  }catch(e){ toast("Ошибка: "+e.message); }
};
$("eFinish").onclick = finToggle;

/* ---------- пользователи и вход ---------- */
let ME = null;
```


### 3.4 Корзина пакетной печати (админка)


#### cartGet / cartSet / cartAdd / renderCart
`hub/ui.html:2087-2132`
```javascript
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

/* ---------- Мастер протоколов: бег и техника — две ветки по пять шагов ---------- */
```


### 3.5 Вкладки групп (пол / возраст) и корзина в протоколе — `hub/protocol.html`


#### groupList / tabsFor / currentItem / sheetsFor / showSheets / fitPages / drawTabs / addTabToCart / renderStart / renderCart
`hub/protocol.html:414-510`
```javascript
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
function tabsFor(start){
  const gs=groupList(start), n=gs.reduce((a,g)=>a+g.n,0), M=gs.reduce((a,g)=>a+g.M,0), F=gs.reduce((a,g)=>a+g.F,0);
  const tabs=[{id:"",label:"Все участники",n}];
  if(M) tabs.push({id:"М",label:"Мальчики / Мужчины",n:M});
  if(F) tabs.push({id:"Ж",label:"Девочки / Женщины",n:F});
  const multiD=new Set(gs.map(g=>g.dist)).size>1;
  if(gs.length>1) gs.forEach(g=>tabs.push({id:g.key,label:multiD?gtitle(g.dist,g.cat):(g.cat||"Без категории"),n:g.n}));
  return tabs;
}
// что сейчас на экране — в том же виде, что и запись корзины печати
function currentItem(start){
  return {type:start?"start":"final", dist:DIST, gk:TAB.includes("|")?TAB:"", sf:TAB==="М"||TAB==="Ж"?TAB:"",
          mode:start?($("smode").value==="list"?"list":"heats"):($("mode").value==="heats"?"heats":"overall"), orient:$("orient").value};
}
// запись (вкладка или лист корзины) → листы: по одному на каждую группу; пол — фильтр внутри группы
function sheetsFor(it){
  const start=it.type!=="final", coach=$("showCoach").checked;
  let keys=it.gk?[it.gk]:groupList(start).filter(g=>!it.sf||(it.sf==="М"?g.M:g.F)).map(g=>g.key);
  if(!keys.length) keys=[null];
  const out=keys.map(k=>start
    ? startSheet({gf:k??"__none__",sf:it.sf,list:it.mode==="list",coach,landscape:it.orient==="landscape"})
    : (f=>({html:f.html,land:f.land,empty:/class="empty"/.test(f.html)&&!/<table/.test(f.html)}))(buildFinal({gf:k??"__none__",sf:it.sf,mode:it.mode==="heats"?"heats":"overall"})));
  return out.filter(r=>!r.empty).length?out.filter(r=>!r.empty):out.slice(0,1);
}
// листы на экран и в печать: каждый — с новой страницы; альбомные и книжные листы в одном документе
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
// «Один лист — одна страница»: если лист вылезает за страницу не больше чем на четверть (обычно — подписи и колонтитул),
// при печати он чуть уменьшается целиком. Ширина листа на экране равна ширине печатной области, поэтому замер честный.
// Длинные списки (больше 1,25 страницы) не сжимаются — переносятся, шапка таблицы повторяется, подписи не отрываются.
const PAGE_MM={land:210-10-12, port:297-12-14};
function fitPages(){
  const mm=96/25.4;
  document.querySelectorAll("#sheet > section.cp").forEach(s=>{
    s.classList.remove("fit"); s.style.removeProperty("--z");
    const page=(s.classList.contains("land")?PAGE_MM.land:PAGE_MM.port)*mm, h=s.scrollHeight;
    if(h>page&&h<=page*1.25){ s.style.setProperty("--z",String(Math.floor(page/h*100)/100-0.01)); s.classList.add("fit"); }
  });
}
function drawTabs(tabs){
  const box=$("ptabs");
  if(!tabs){ box.innerHTML=""; box.hidden=true; return; }
  box.hidden=false;
  box.innerHTML=`<div class="tl" role="tablist" aria-label="Группы протокола">${tabs.map(t=>`<button type="button" role="tab" aria-selected="${t.id===TAB}" class="${t.id===TAB?"on":""}" data-tab="${esc(t.id)}">${esc(t.label)}<i>${t.n}</i></button>`).join("")}</div>`
    +(PUB?"":`<button type="button" class="cartadd" id="tabCart">🛒 Добавить текущую вкладку в корзину печати</button><span class="cartmsg" id="cartMsg" role="status"></span>`);
}
$("ptabs").addEventListener("click",e=>{
  const b=e.target.closest("[data-tab]"); if(b){ TAB=b.dataset.tab; render(); return; }
  if(e.target.id==="tabCart") addTabToCart();
});
function addTabToCart(){
  const start=isStartView(), it=currentItem(start), tab=tabsFor(start).find(t=>t.id===TAB)||{label:"Все участники"};
  const label=`${start?"Старт":"Итоги"}: ${DIST||"все дисциплины"} — ${tab.label}${start?(it.mode==="list"?" · общий список":" · по забегам"):""}`;
  let a=LS.get("ss.cart."+eid,[]); a=Array.isArray(a)?a:[];
  const same=a.some(x=>["type","dist","gk","sf","mode","orient"].every(k=>(x[k]||"")===(it[k]||"")));
  if(!same){ a.push(Object.assign({id:Date.now().toString(36)+Math.random().toString(36).slice(2,6),on:true,label},it)); LS.set("ss.cart."+eid,a); }
  const n=sheetsFor(it).length;
  $("cartMsg").textContent=same?"Эта вкладка уже в корзине":`В корзине: «${tab.label}» — ${n} ${n===1?"лист":n<5?"листа":"листов"}`;
}
function renderStart(){
  if(!SL){ $("sheet").innerHTML='<div class="empty">Загрузка…</div>'; loadStart(); return; }
  const tabs=tabsFor(true); if(!tabs.some(t=>t.id===TAB)) TAB="";
  drawTabs(tabs);
  const secs=sheetsFor(currentItem(true));
  showSheets(secs);
}
// «Корзина печати»: набор листов из админки (ss.cart.<событие>) — один документ, каждый лист с новой страницы
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


## 4. Табло, пульт и планшет сектора

| Страница | Кто открывает | Данные (API) | Обновление | Устройство |
|---|---|---|---|---|
| `/board` — `board.html` | экран на стадионе, без ввода | `GET /api/events/{id}/results`, `GET /api/scoreboard/state`, `GET /api/clock` | опрос каждые 1,5 с, часы — 100 мс, синхронизация времени — 60 с | Три режима от пульта: `auto` — свежие результаты сверху; `fixed` — таблица лидеров одной группы; `rotate` — группы по кругу, номер слайда считается от времени сервера, поэтому все табло синхронны. Длинная таблица — автопрокрутка в `requestAnimationFrame`: лидеры стоят `HOLD_TOP` = 7 с, лента едет `ROWS_PER_S` = 0,6 строки/с, внизу пауза `HOLD_END` = 4 с, возврат за `BACK` = 1,4 с. При «уменьшить движение» — листание экранами раз в `STEP_MS` = 8 с. Попытки — 6 ячеек, лучшая подсвечена. Секундомеры на табло не выводятся, только официальный результат |
| `/scoreboard` — `scoreboard.html` | судья (пульт) | `GET/POST /api/scoreboard/state`, `GET /api/events` | опрос 3 с (не перерисовывает, пока фокус в настройках ротации) | Выбор соревнования; карточки режимов `auto` / `fixed` / `rotate`; список групп для фиксации и ротации; живой предпросмотр — `/board` в масштабированном `iframe` 1600 px. Состояние хранится в таблице `scoreboard` |
| `/sector` — `sector.html` | судья на секторе с планшета | `GET /api/events`, `GET …/startlist`, `GET …/results`, `POST …/results` | фоновое обновление 8 с, пока вкладка видима | Выбор соревнования и дисциплины; строки участников: попытки (техника) или 1–3 секундомера (бег); «Итог» считается на устройстве (`swMain`, `attBest` — копия серверной логики, см. Б1) и сохраняется автоматически очередью `queue` → `flush` (400 мс); при обрыве связи — повтор, строка остаётся помеченной. Заявки (ПДн) судье на секторе не выдаются — только стартовый список |


#### hub/board.html — Автопрокрутка табло
`hub/board.html:118-139`
```javascript
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
```


#### hub/board.html — Загрузка и таймеры
`hub/board.html:175-197`
```javascript
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
```


#### hub/scoreboard.html — render / send / poll
`hub/scoreboard.html:109-138`
```javascript
function render(){
  if(!ST)return;
  const cur=ST.mode==="fixed"?gname(ST.group):ST.mode==="rotate"?`${ST.rotate.groups.length} групп по ${ST.rotate.interval} с`:"последние результаты";
  $("now").innerHTML=`<span class="live">на табло</span><b>${MODE[ST.mode]}</b><span>${esc(cur)}</span><span class="muted">${ST.updated_at?"переключено "+esc(ST.updated_at.slice(11,16))+(ST.by?" · "+esc(ST.by.split("@")[0]):""):"по умолчанию"}</span>`;
  document.querySelectorAll(".mode").forEach(b=>{const on=b.dataset.mode===ST.mode;b.classList.toggle("on",on);b.setAttribute("aria-checked",String(on));});
  $("iv").value=String(ST.rotate.interval);
  const chosen=new Set(ST.rotate.chosen||[]);
  $("groups").innerHTML=ST.groups.map(g=>{const on=ST.mode==="fixed"&&ST.group===g.key, inRot=ST.mode==="rotate"&&ST.rotate.groups.includes(g.key);
    return `<div class="g${on||inRot?" on":""}"><div class="t"><b>${esc(gname(g.key))}</b><small><span class="tag${g.tech?" tech":""}">${g.tech?"техника":"бег"}</span>результатов ${g.results} из ${g.total}${g.last_ms?" · "+ago(g.last_ms):""}</small></div>
      <label><input type="checkbox" data-rot="${esc(g.key)}" ${chosen.has(g.key)?"checked":""}> в ротации</label>
      <button type="button" class="btn${on?" primary":""}" data-fix="${esc(g.key)}">${on?"📌 На табло":"📌 Зафиксировать"}</button></div>`;}).join("")
    ||'<div class="empty">В соревновании пока нет участников в стартовом протоколе.</div>';
}
async function send(body){
  if(!EID)return; busy=true;
  try{ST=await api("/api/scoreboard/state",Object.assign({event_id:EID},body));render();toast("Табло переключено: "+MODE[ST.mode]);}
  catch(e){toast("Ошибка: "+e.message);}finally{busy=false;}
}
const rotBody=()=>({rotate:{interval:+$("iv").value,groups:[...document.querySelectorAll("[data-rot]:checked")].map(x=>x.dataset.rot)}});
document.querySelector(".modes").addEventListener("click",e=>{const b=e.target.closest("[data-mode]");if(!b)return;
  if(b.dataset.mode==="fixed"){const g=ST&&(ST.group||(ST.groups.find(x=>x.results)||ST.groups[0]||{}).key);if(!g)return toast("Нет групп для фиксации");return send({mode:"fixed",group:g,...rotBody()});}
  send({mode:b.dataset.mode,...rotBody()});});
$("groups").addEventListener("click",e=>{const b=e.target.closest("[data-fix]");if(b)send({mode:"fixed",group:b.dataset.fix,...rotBody()});});
$("groups").addEventListener("change",e=>{if(e.target.matches("[data-rot]")&&ST&&ST.mode==="rotate")send({mode:"rotate",...rotBody()});});
$("rotGo").onclick=()=>send({mode:"rotate",...rotBody()});
$("iv").onchange=()=>{if(ST&&ST.mode==="rotate")send({mode:"rotate",...rotBody()});};
function scalePrev(){const p=$("prev"),f=$("frame");f.style.transform=`scale(${p.clientWidth/1600})`;}
window.addEventListener("resize",scalePrev);
async function poll(){if(busy||!EID)return;try{ST=await api(`/api/scoreboard/state?event=${EID}`);if(!document.querySelector("[data-rot]:focus"))render();}catch(e){$("now").innerHTML='<b>Нет связи с сервером</b>';}}
function setEvent(id){EID=id;history.replaceState(null,"","/scoreboard?event="+id);$("lnkBoard").href="/board?event="+id;$("frame").src="/board?event="+id;scalePrev();poll();}
```


#### hub/sector.html — Расчёт секундомеров и попыток (копия логики сервера)
`hub/sector.html:142-149`
```javascript
function parseT(t){t=String(t||"").replace(/\s+/g,"");const m=T_RE.exec(t);if(!m||!t)return null;const[,a,b,c,f]=m,h=b!=null?+a:0,mi=b!=null?+b:(a!=null?+a:0),sec=+c;
  if((a!=null||b!=null)&&sec>=60)return null;const tot=h*3600+mi*60+sec+(f?+f/Math.pow(10,f.length):0);return tot>0?tot:null;}
function fmtT(sec){const tn=Math.round(sec*10),h=Math.floor(tn/36000),m=Math.floor(tn%36000/600),s=Math.floor(tn%600/10),t=tn%10;
  return h?`${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}.${t}`:m?`${m}:${String(s).padStart(2,"0")}.${t}`:`${s}.${t}`;}
function swMain(v){v=v.map(parseT).filter(x=>x!=null).sort((a,b)=>a-b);if(!v.length)return "";const m=v.length>=3?v[1]:v[v.length-1];return fmtT(Math.ceil(+(m*10).toFixed(6))/10);}
function attBest(v){let b=null;v.forEach(x=>{const m=/^(\d{1,3})(?:[.,](\d{1,2}))?$/.exec(String(x||"").replace(/\s+/g,""));if(m){const n=+(m[1]+"."+(m[2]||"0"));if(n>0&&(b==null||n>b))b=n;}});return b==null?"":b.toFixed(2);}

// ---- загрузка: соревнования → стартовый список и результаты с сервера
```


#### hub/sector.html — Сохранение: queue / flush
`hub/sector.html:207-227`
```javascript
function queue(ms){clearTimeout(saveT);saveT=setTimeout(flush,ms??400);}
async function flush(){
  if(S.saving){queue(700);return;}
  const bibs=Object.keys(S.pending);if(!bibs.length||!S.ev)return;
  const rows=bibs.map(b=>S.pending[b]);S.saving=true;sync("busy","Сохраняю…");
  try{
    const r=await api(`/api/events/${S.ev.id}/results`,{rows});
    const bad=new Map(r.errors.map(x=>[x.split(":")[0],x]));
    rows.forEach(row=>{const el=document.querySelector(`.r[data-bib="${CSS.escape(row.bib)}"]`);
      if(bad.has(row.bib)){el&&el.querySelectorAll("input").forEach(i=>i.classList.add("err"));return;}
      if(JSON.stringify(S.pending[row.bib])===JSON.stringify(row)){delete S.pending[row.bib];if(el){el.classList.remove("dirty");el.classList.add("saved");setTimeout(()=>el.classList.remove("saved"),1300);}}});
    savePending();
    $("err").textContent=r.errors.length?"Не сохранено: "+r.errors.join("; "):"";
    if(r.errors.length)sync("warn","⚠️ Есть ошибки ввода — исправьте выделенные клетки");else sync("ok",OK_TXT());
    await refresh(true);
  }catch(e){
    if(e.http===403){sync("off","Нет прав на ввод результатов — войдите под учётной записью судьи на секторе");}
    else{sync("off","🔴 Нет связи с сервером — введённое сохранено на планшете и уйдёт само");queue(5000);}
  }finally{S.saving=false;}
}
// фоновое обновление: результаты коллег и расчёт сервера; строки, которые сейчас вводят, не трогаем
```


## 5. Справочники `hub/seed/`

### `disciplines.json` — версия `2`, обновлён `2026-10-13`

Корневые ключи: `version`, `updated`, `sources`, `groups`, `result_types`, `ages`, `disciplines`, `presets`

**ages** (возрастные группы шага 1 Мастера; границ лет в справочнике нет — они в коде, см. раздел 0):
```json
[
 {
  "id": "u12",
  "name": "до 12 лет"
 },
 {
  "id": "u14",
  "name": "до 14 лет"
 },
 {
  "id": "u16",
  "name": "до 16 лет"
 },
 {
  "id": "u18",
  "name": "до 18 лет"
 },
 {
  "id": "u20",
  "name": "юниоры до 20 лет"
 },
 {
  "id": "u23",
  "name": "молодёжь до 23 лет"
 },
 {
  "id": "sen",
  "name": "взрослые"
 }
]
```
**result_types:**
```json
{
 "time": {
  "name": "Время",
  "unit": "с",
  "hint": "12.84 · 1:05.32 · 2:05:31",
  "better": "lower"
 },
 "distance": {
  "name": "Расстояние",
  "unit": "м",
  "hint": "7.85 (метры)",
  "better": "higher"
 },
 "height": {
  "name": "Высота",
  "unit": "м",
  "hint": "1.95 (метры)",
  "better": "higher"
 },
 "points": {
  "name": "Очки",
  "unit": "очк.",
  "hint": "7250 (целое число)",
  "better": "higher"
 }
}
```
**groups:**
```json
[
 {
  "id": "sprint",
  "name": "Спринт",
  "hint": "30–400 м"
 },
 {
  "id": "middle",
  "name": "Средние дистанции",
  "hint": "500 м – 2000 м"
 },
 {
  "id": "long",
  "name": "Длинные дистанции",
  "hint": "3000 м и дальше"
 },
 {
  "id": "hurdles",
  "name": "Барьерный бег",
  "hint": "с/б"
 },
 {
  "id": "steeple",
  "name": "Стипль-чез",
  "hint": "с/п"
 },
 {
  "id": "relay",
  "name": "Эстафеты",
  "hint": "команда из нескольких этапов"
 },
 {
  "id": "walk",
  "name": "Спортивная ходьба",
  "hint": "по стадиону"
 },
 {
  "id": "jumps",
  "name": "Прыжки",
  "hint": "высота, шест, длина, тройной"
 },
 {
  "id": "throws",
  "name": "Метания",
  "hint": "ядро, диск, молот, копьё, мяч"
 },
 {
  "id": "combined",
  "name": "Многоборья",
  "hint": "результат — очки по таблице"
 }
]
```
**presets** (кнопки быстрого набора программы на этапе «Подготовка»):
```json
[
 {
  "id": "indoor",
  "name": "Манеж: основная программа",
  "hint": "бег до 3000 м, 60 м с/б, прыжки, ядро",
  "venue": "indoor",
  "disciplines": [
   "60m",
   "200m",
   "400m",
   "800m",
   "1500m",
   "3000m",
   "60mh",
   "hj",
   "pv",
   "lj",
   "tj",
   "sp"
  ]
 },
 {
  "id": "outdoor",
  "name": "Стадион: основная программа",
  "hint": "бег, барьеры, стипль, прыжки, метания, эстафеты",
  "venue": "outdoor",
  "disciplines": [
   "100m",
   "200m",
   "400m",
   "800m",
   "1500m",
   "5000m",
   "100mh",
   "110mh",
   "400mh",
   "3000msc",
   "hj",
   "pv",
   "lj",
   "tj",
   "sp",
   "dt",
   "ht",
   "jt",
   "4x100",
   "4x400"
  ]
 },
 {
  "id": "cup",
  "name": "Кубок: бег и прыжки",
  "hint": "компактная программа на один день",
  "disciplines": [
   "60m",
   "100m",
   "200m",
   "400m",
   "800m",
   "1500m",
   "lj",
   "hj"
  ]
 },
 {
  "id": "kids",
  "name": "Дети до 14 лет",
  "hint": "60 м, 300 м, 600 м, 1000 м, барьеры, длина, высота, мяч, ядро",
  "disciplines": [
   "60m",
   "300m",
   "600m",
   "1000m",
   "60mh",
   "lj",
   "hj",
   "ball",
   "sp"
  ]
 },
 {
  "id": "boys-combined",
  "name": "Многоборье юношей",
  "hint": "десятиборье и восьмиборье",
  "disciplines": [
   "dec",
   "oct"
  ]
 },
 {
  "id": "girls-combined",
  "name": "Многоборье девушек",
  "hint": "семиборье и пятиборье в зале",
  "disciplines": [
   "hep",
   "peni"
  ]
 },
 {
  "id": "jumps",
  "name": "Прыжки",
  "hint": "высота, шест, длина, тройной",
  "disciplines": [
   "hj",
   "pv",
   "lj",
   "tj"
  ]
 },
 {
  "id": "throws",
  "name": "Метания",
  "hint": "ядро, диск, молот, копьё, мяч",
  "disciplines": [
   "sp",
   "dt",
   "ht",
   "jt",
   "ball"
  ]
 },
 {
  "id": "relays",
  "name": "Эстафеты",
  "hint": "4×100 м и 4×400 м",
  "disciplines": [
   "4x100",
   "4x400"
  ]
 },
 {
  "id": "walk",
  "name": "Спортивная ходьба",
  "hint": "3000 м и 5000 м",
  "disciplines": [
   "walk3000",
   "walk5000"
  ]
 }
]
```
**disciplines** — 56 записей. Поля: aliases, attempts, group, id, legs, max, name, note, parts, result, sex, specs, venue. Полный список:

| id | Название | Группа | Результат | Пол | Площадка | Попытки | Прочее |
|---|---|---|---|---|---|---|---|
| `30m` | 30 м | sprint | time | MF | indoor,outdoor |  | {"note": "для детей, нормативы и тесты"} |
| `50m` | 50 м | sprint | time | MF | indoor,outdoor |  | {"note": "для детей, нормативы и тесты"} |
| `60m` | 60 м | sprint | time | MF | indoor,outdoor |  | {"aliases": ["60", "60м"]} |
| `100m` | 100 м | sprint | time | MF | outdoor |  | {"aliases": ["100", "100м"]} |
| `200m` | 200 м | sprint | time | MF | indoor,outdoor |  | {"aliases": ["200", "200м"]} |
| `300m` | 300 м | sprint | time | MF | indoor,outdoor |  | {"aliases": ["300", "300м"]} |
| `400m` | 400 м | sprint | time | MF | indoor,outdoor |  | {"aliases": ["400", "400м"]} |
| `500m` | 500 м | middle | time | MF | indoor,outdoor |  | {"aliases": ["500", "500м"]} |
| `600m` | 600 м | middle | time | MF | indoor,outdoor |  | {"aliases": ["600", "600м"]} |
| `800m` | 800 м | middle | time | MF | indoor,outdoor |  | {"aliases": ["800", "800м"]} |
| `1000m` | 1000 м | middle | time | MF | indoor,outdoor |  | {"aliases": ["1000", "1000м"]} |
| `1500m` | 1500 м | middle | time | MF | indoor,outdoor |  | {"aliases": ["1500", "1500м"]} |
| `mile` | 1 миля | middle | time | MF | indoor,outdoor |  | {"aliases": ["Миля"]} |
| `2000m` | 2000 м | middle | time | MF | indoor,outdoor |  | {"aliases": ["2000", "2000м"]} |
| `3000m` | 3000 м | long | time | MF | indoor,outdoor |  | {"aliases": ["3000", "3000м"]} |
| `5000m` | 5000 м | long | time | MF | outdoor |  | {"aliases": ["5000", "5000м"]} |
| `10000m` | 10000 м | long | time | MF | outdoor |  | {"aliases": ["10000", "10000м", "10 000 м"]} |
| `60mh` | 60 м с/б | hurdles | time | MF | indoor |  | {"specs": [{"who": "Мужчины", "text": "106,7 см · 13,72 / 9,14 / 9,72 м"}, {"who": "Юниоры до 20", "text": "99,1 см"}, {"who": "Юноши до 18", "text": "91,4 см"}, {"who": "Женщины и юниорки", "text": "83,8 см · 13,00 / 8,50 / 13,00 м"}, {"who": "Девушки до 18", "text": "76,2 см"}, {"who": "Мальчики до 14 (ЕВСК)", "text": "84 см"}, {"who": "Девочки до 14 (ЕВСК)", "text": "65 см"}], "aliases": ["60 с/б", "60 м/б", "60м с/б"]} |
| `80mh` | 80 м с/б | hurdles | time | F | outdoor |  | {"aliases": ["80 с/б"], "note": "девочки младших возрастов, параметры — по положению соревнований"} |
| `100mh` | 100 м с/б | hurdles | time | F | outdoor |  | {"specs": [{"who": "Женщины и юниорки до 20", "text": "высота 83,8 см · 13,00 / 8,50 / 10,50 м"}, {"who": "Девушки до 18", "text": "высота 76,2 см · 13,00 / 8,50 / 10,50 м"}, {"who": "Девочки до 14 (ЕВСК)", "text": "высота 65 см"}], "aliases": ["100 с/б", "100 м/б"]} |
| `110mh` | 110 м с/б | hurdles | time | M | outdoor |  | {"specs": [{"who": "Мужчины", "text": "высота 106,7 см · 13,72 / 9,14 / 14,02 м"}, {"who": "Юниоры до 20", "text": "высота 99,1 см · 13,72 / 9,14 / 14,02 м"}, {"who": "Юноши до 18", "text": "высота 91,4 см · 13,72 / 9,14 / 14,02 м"}], "aliases": ["110 с/б", "110 м/б"]} |
| `300mh` | 300 м с/б | hurdles | time | MF | indoor,outdoor |  | {"aliases": ["300 с/б"], "note": "молодёжные и юношеские возрасты, параметры — по положению соревнований"} |
| `400mh` | 400 м с/б | hurdles | time | MF | outdoor |  | {"specs": [{"who": "Мужчины и юниоры до 20", "text": "высота 91,4 см · 45 / 35 / 40 м"}, {"who": "Юноши до 18", "text": "высота 83,8 см"}, {"who": "Женщины, юниорки, девушки", "text": "высота 76,2 см"}], "aliases": ["400 с/б", "400 м/б"]} |
| `2000msc` | 2000 м с/п | steeple | time | MF | outdoor |  | {"specs": [{"who": "Мужчины и юниоры до 20", "text": "барьер 91,4 см"}, {"who": "Юноши до 18", "text": "барьер 83,8 см"}, {"who": "Женщины, юниорки, девушки", "text": "барьер 76,2 см"}], "aliases": ["2000 с/п", "2000 стипль"]} |
| `3000msc` | 3000 м с/п | steeple | time | MF | outdoor |  | {"specs": [{"who": "Мужчины и юниоры до 20", "text": "барьер 91,4 см"}, {"who": "Юноши до 18", "text": "барьер 83,8 см"}, {"who": "Женщины, юниорки, девушки", "text": "барьер 76,2 см"}], "aliases": ["3000 с/п", "3000 стипль"]} |
| `4x60` | 4×60 м | relay | time | MF | indoor |  | {"legs": 4, "aliases": ["4x60"]} |
| `4x100` | 4×100 м | relay | time | MF | outdoor |  | {"legs": 4, "aliases": ["4x100", "4х100", "4*100"]} |
| `4x200` | 4×200 м | relay | time | MF | indoor,outdoor |  | {"legs": 4, "aliases": ["4x200", "4х200"]} |
| `4x400` | 4×400 м | relay | time | MF | indoor,outdoor |  | {"legs": 4, "aliases": ["4x400", "4х400"]} |
| `4x400mix` | 4×400 м смешанная | relay | time | MF | indoor,outdoor |  | {"legs": 4, "aliases": ["4x400 микст"], "note": "два юноши и две девушки"} |
| `4x800` | 4×800 м | relay | time | MF | outdoor |  | {"legs": 4, "aliases": ["4x800"]} |
| `4x1500` | 4×1500 м | relay | time | MF | outdoor |  | {"legs": 4, "aliases": ["4x1500"]} |
| `swedish` | Шведская эстафета | relay | time | MF | outdoor |  | {"legs": 4, "aliases": ["Шведская"], "note": "этапы 100, 200, 300 и 400 м"} |
| `walk1500` | Ходьба 1500 м | walk | time | MF | indoor,outdoor |  | {"aliases": ["Ходьба 1500"], "note": "судейство по правилам спортивной ходьбы: предупреждения и дисквалификация"} |
| `walk2000` | Ходьба 2000 м | walk | time | MF | indoor,outdoor |  | {"aliases": ["Ходьба 2000"], "note": "судейство по правилам спортивной ходьбы: предупреждения и дисквалификация"} |
| `walk3000` | Ходьба 3000 м | walk | time | MF | indoor,outdoor |  | {"aliases": ["Ходьба 3000"], "note": "судейство по правилам спортивной ходьбы: предупреждения и дисквалификация"} |
| `walk5000` | Ходьба 5000 м | walk | time | MF | indoor,outdoor |  | {"aliases": ["Ходьба 5000"], "note": "судейство по правилам спортивной ходьбы: предупреждения и дисквалификация"} |
| `walk10000` | Ходьба 10000 м | walk | time | MF | outdoor |  | {"aliases": ["Ходьба 10000"], "note": "судейство по правилам спортивной ходьбы: предупреждения и дисквалификация"} |
| `hj` | Прыжок в высоту | jumps | height | MF | indoor,outdoor | True | {"max": 2.7, "aliases": ["Высота", "Прыжок в высоту"], "note": "лучшая взятая высота; попытки по высотам — в протоколе судей"} |
| `pv` | Прыжок с шестом | jumps | height | MF | indoor,outdoor | True | {"max": 7.0, "aliases": ["Шест", "Прыжок с шестом"], "note": "лучшая взятая высота"} |
| `lj` | Прыжок в длину | jumps | distance | MF | indoor,outdoor | True | {"max": 10.0, "aliases": ["Длина", "Прыжок в длину"], "note": "лучший результат из попыток; ветер — в протоколе судей"} |
| `tj` | Тройной прыжок | jumps | distance | MF | indoor,outdoor | True | {"max": 19.5, "aliases": ["Тройной", "Тройной прыжок"], "note": "лучший результат из попыток"} |
| `sp` | Толкание ядра | throws | distance | MF | indoor,outdoor | True | {"max": 25.0, "specs": [{"who": "Мужчины", "text": "7,26 кг"}, {"who": "Юниоры до 20", "text": "6 кг"}, {"who": "Юноши до 18", "text": "5 кг"}, {"who": "Юноши до 14 (ЕВСК)", "text": "4 кг"}, {"who": "Женщины и юниорки", "text": "4 кг"}, {"who": "Девушки до 18", "text": "3 кг"}], "aliases": ["Ядро", "Толкание ядра"], "note": "лучший результат из попыток"} |
| `dt` | Метание диска | throws | distance | MF | outdoor | True | {"max": 82.0, "specs": [{"who": "Мужчины", "text": "2 кг"}, {"who": "Юниоры до 20", "text": "1,75 кг"}, {"who": "Юноши до 18", "text": "1,5 кг"}, {"who": "Юноши до 14 (ЕВСК)", "text": "1 кг"}, {"who": "Женщины, юниорки, девушки", "text": "1 кг"}, {"who": "Девочки до 14 (ЕВСК)", "text": "0,75 кг"}], "aliases": ["Диск", "Метание диска"], "note": "лучший результат из попыток"} |
| `ht` | Метание молота | throws | distance | MF | outdoor | True | {"max": 92.0, "specs": [{"who": "Мужчины", "text": "7,26 кг"}, {"who": "Юниоры до 20", "text": "6 кг"}, {"who": "Юноши до 18", "text": "5 кг"}, {"who": "Женщины и юниорки", "text": "4 кг"}, {"who": "Девушки до 18", "text": "3 кг"}], "aliases": ["Молот", "Метание молота"], "note": "лучший результат из попыток"} |
| `jt` | Метание копья | throws | distance | MF | outdoor | True | {"max": 105.0, "specs": [{"who": "Мужчины и юниоры до 20", "text": "800 г"}, {"who": "Юноши до 18", "text": "700 г"}, {"who": "Женщины и юниорки", "text": "600 г"}, {"who": "Девушки до 18", "text": "500 г"}], "aliases": ["Копьё", "Копье", "Метание копья", "Метание копья"], "note": "лучший результат из попыток"} |
| `ball` | Метание мяча | throws | distance | MF | outdoor | True | {"max": 90.0, "specs": [{"who": "Дети", "text": "мяч 140 г"}], "aliases": ["Мяч", "Метание мяча 140 г"], "note": "дети до 14 лет"} |
| `ballimpl` | Метание мяча/снаряда | throws | distance | MF | outdoor,indoor | True | {"max": 120.0, "specs": [{"who": "Дети и подростки", "text": "мяч 140–150 г или снаряд 500/700 г — вес указывается в положении"}], "aliases": ["Метание снаряда", "Метание спортивного снаряда", "Мяч/снаряд", "Снаряд", "Метание мяча (снаряда)", "Метание мяча или снаряда", "Метание мяча 150 г", "Метание теннисного мяча"], "note": "техническая дисциплина: попытки, лучший результат"} |
| `dec` | Десятиборье | combined | points | M | outdoor |  | {"max": 9500, "specs": [{"who": "Участники", "text": "Юниоры до 20, юноши до 18 (с 16 лет), мужчины"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["100 м", "Длина", "Ядро", "Высота", "400 м"]}, {"day": 2, "events": ["110 м с/б", "Диск", "Шест", "Копьё", "1500 м"]}]} |
| `oct` | Восьмиборье | combined | points | M | outdoor |  | {"max": 7500, "specs": [{"who": "Участники", "text": "Юноши до 16 лет"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["100 м", "Длина", "Ядро", "400 м"]}, {"day": 2, "events": ["110 м с/б", "Высота", "Копьё", "1000 м"]}]} |
| `hep` | Семиборье | combined | points | F | outdoor |  | {"max": 7500, "specs": [{"who": "Участники", "text": "Девушки, юниорки, женщины (с 14 лет)"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["100 м с/б", "Высота", "Ядро", "200 м"]}, {"day": 2, "events": ["Длина", "Копьё", "800 м"]}]} |
| `hepi` | Семиборье (зал) | combined | points | M | indoor |  | {"max": 7000, "specs": [{"who": "Участники", "text": "Юниоры, юноши, мужчины в помещении"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["60 м", "Длина", "Ядро", "Высота"]}, {"day": 2, "events": ["60 м с/б", "Шест", "1000 м"]}]} |
| `peni` | Пятиборье (зал) | combined | points | F | indoor |  | {"max": 5500, "specs": [{"who": "Участники", "text": "Девушки, юниорки, женщины в помещении"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["60 м с/б", "Высота", "Ядро", "Длина", "800 м"]}]} |
| `hex` | Шестиборье | combined | points | M | indoor,outdoor |  | {"max": 6000, "specs": [{"who": "Участники", "text": "Юноши до 14–15 лет"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["60 м с/б", "Длина", "Ядро"]}, {"day": 2, "events": ["Высота", "Копьё", "1000 м"]}]} |
| `tet` | Четырёхборье | combined | points | MF | indoor,outdoor |  | {"max": 4500, "specs": [{"who": "Участники", "text": "Дети до 14 лет"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["60 м", "Прыжок (длина или высота)"]}, {"day": 2, "events": ["Мяч", "600 м (девочки), 800 м (мальчики)"]}]} |
| `tri` | Троеборье | combined | points | MF | indoor,outdoor |  | {"max": 3500, "specs": [{"who": "Участники", "text": "Дети до 13 лет, юноши и девушки до 18 лет: бег, прыжок и метание по выбору"}], "note": "очки по таблице многоборий World Athletics", "parts": [{"day": 1, "events": ["Бег", "Прыжок", "Ядро или метание"]}]} |

### `rank_norms.json`
Источник: Нормы ЕВСК по виду спорта «лёгкая атлетика» — приложение № 16 к приказу Минспорта России от 10.03.2026. Норм: 264, пропущено: ['М · Бег с барьерами 60 м  · Высота барьеров: юноши (до 18 лет) - 0,914 м, расстояние меж · 3 юн.: 11.94 (строже, чем 2 юн.: 12.64)', 'Ж · 7-борье  · Девушки (до 16 лет) · 3 р.: 3850.0 (строже, чем 2 р.: 3450.0)']. Пример записи:
```json
[
 {
  "key": "run:30",
  "sex": "М",
  "timing": "hand",
  "lap": null,
  "ages": [],
  "var": "",
  "better": "lower",
  "v": {
   "3 р.": 4.2,
   "1 юн.": 4.4,
   "2 юн.": 4.7,
   "3 юн.": 5.0
  },
  "src": "Бег 30-50 м · 30 м · Ручной хронометраж"
 },
 {
  "key": "run:50",
  "sex": "М",
  "timing": "hand",
  "lap": null,
  "ages": [],
  "var": "",
  "better": "lower",
  "v": {
   "1 р.": 6.1,
   "2 р.": 6.3,
   "3 р.": 6.6,
   "1 юн.": 7.0,
   "2 юн.": 7.4,
   "3 юн.": 8.0
  },
  "src": "Бег 30-50 м · 50 м · Ручной хронометраж"
 }
]
```

### `calendar-2026.json`
Источник: https://fla65.ru/competitions (календарный план минспорта Сахалинской области на 2026 год). Событий: 36. Поля события: `name`, `date`, `date_end`, `level`, `adaptive`, `place`, `city`, `note`, `kind`, `links`. Используется кнопкой «Импорт календаря» (публикация на сайте).


### Связь справочников с этапом «Подготовка»


#### Hub._dkey
`hub/hub.py:2328-2331`
```python
    @staticmethod
    def _dkey(name) -> str:
        t = re.sub(r"(?<=\d)[xх*](?=\d)", "×", str(name or "").lower())
        return re.sub(r"[\s.\-]+", "", t).replace("ё", "е")
```


#### Hub.disciplines
`hub/hub.py:2333-2348`
```python
    @classmethod
    def disciplines(cls) -> dict:
        """Справочник: группы, дисциплины (бег, ходьба, прыжки, метания, многоборья, эстафеты), пресеты."""
        if cls._DISC is None:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed", "disciplines.json")
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {"groups": [], "disciplines": [], "presets": [], "result_types": {}, "ages": []}
            idx: dict = {}
            for d in data["disciplines"]:
                for n in [d["name"], *(d.get("aliases") or [])]:
                    idx.setdefault(cls._dkey(n), d)
            cls._DISC = {"data": data, "index": idx}
        return cls._DISC
```


#### Hub.discipline
`hub/hub.py:2350-2352`
```python
    @classmethod
    def discipline(cls, name) -> Optional[dict]:
        return cls.disciplines()["index"].get(cls._dkey(name)) if name else None
```


#### ui.html — loadDisc (загрузка справочника в админку)
`hub/ui.html:1614-1620`
```javascript
function loadDisc(){
  if (DISC) return Promise.resolve(DISC);
  return discLoading || (discLoading = api("/api/disciplines").then(d => {
    d.index = new Map(); d.disciplines.forEach(x => [x.name, ...(x.aliases || [])].forEach(n => d.index.has(discKey(n)) || d.index.set(discKey(n), x)));
    return (DISC = d);
  }).catch(() => (discLoading = null, { groups: [], disciplines: [], presets: [], result_types: {}, index: new Map() })));
}
```


#### ui.html — discPicker (выбор дисциплин и пресетов)
`hub/ui.html:1625-1663`
```javascript
async function discPicker(root, api2){
  const D = await loadDisc();
  const st = {q: "", venue: ""};
  root.innerHTML = `<div class="dp"><div class="dp-top"><input type="search" class="dp-q" placeholder="Найти дисциплину: 100, шест, ядро…" aria-label="Поиск дисциплины">
    <div class="dp-seg" role="group" aria-label="Где проходит"><button type="button" data-v="" class="on">Все</button><button type="button" data-v="indoor">Манеж</button><button type="button" data-v="outdoor">Стадион</button></div></div>
    <div class="small muted" style="margin-bottom:4px">Готовые программы — добавят свои дисциплины в выбор:</div>
    <div class="dp-pre">${D.presets.map(p => `<button type="button" data-p="${esc(p.id)}" title="${esc(p.hint)}">${esc(p.name)}</button>`).join("")}</div>
    <div class="dp-list"></div><div class="dp-sum"><span class="dp-cnt"></span><button type="button" class="sm dp-clear">Очистить выбор</button></div></div>`;
  const list = root.querySelector(".dp-list");
  const sel = () => new Set(api2.get().map(l => { const d = discBy(l); return d ? d.id : null; }).filter(Boolean));
  function draw(){
    const on = sel(), q = discKey(st.q), cnt = api2.get().length;
    root.querySelector(".dp-cnt").textContent = cnt ? `Выбрано: ${cnt}` : "Пока ничего не выбрано";
    root.querySelector(".dp-clear").classList.toggle("hide", !cnt);
    const html = D.groups.map(g => {
      const items = D.disciplines.filter(d => d.group === g.id && (!st.venue || (d.venue || []).includes(st.venue))
        && (!q || discKey(d.name).includes(q) || (d.aliases || []).some(a => discKey(a).includes(q))));
      if (!items.length) return "";
      const n = items.filter(d => on.has(d.id)).length;
      return `<div class="dp-g"><h4>${esc(g.name)} <small>${esc(g.hint || "")}</small>${n ? `<span class="dp-n">выбрано ${n}</span>` : ""}</h4><div class="dp-chips">${items.map(d => {
        const tip = [d.note, ...(d.specs || []).map(x => x.who + ": " + x.text)].filter(Boolean).join("\n");
        return `<button type="button" class="dp-chip${on.has(d.id) ? " on" : ""}" data-did="${esc(d.id)}" aria-pressed="${on.has(d.id)}"${tip ? ` title="${esc(tip)}"` : ""}>${esc(d.name)}${RT_BADGE[d.result] ? `<i>${RT_BADGE[d.result]}</i>` : ""}</button>`; }).join("")}</div></div>`; }).join("");
    list.innerHTML = html || '<div class="dp-empty">Ничего не найдено. Свою дисциплину можно дописать в поле ниже.</div>';
  }
  const toggle = (id, force) => {
    const d = D.disciplines.find(x => x.id === id), lines = api2.get(), i = lines.findIndex(l => { const x = discBy(l); return x && x.id === id; });
    if (i >= 0 && force !== true) lines.splice(i, 1); else if (i < 0) lines.push(discLine(d));
    api2.set(lines); draw();
  };
  list.addEventListener("click", (e) => { const b = e.target.closest("[data-did]"); if (!b) return; toggle(b.dataset.did); const nb = list.querySelector(`[data-did="${b.dataset.did}"]`); nb && nb.focus({preventScroll:true}); });
  root.querySelector(".dp-pre").addEventListener("click", (e) => { const b = e.target.closest("[data-p]"); if (!b) return;
    const p = D.presets.find(x => x.id === b.dataset.p); p.disciplines.forEach(id => toggle(id, true)); toast(`«${p.name}»: добавлено ${p.disciplines.length}`); });
  root.querySelector(".dp-q").addEventListener("input", (e) => { st.q = e.target.value; draw(); });
  root.querySelector(".dp-seg").addEventListener("click", (e) => { const b = e.target.closest("[data-v]"); if (!b) return; st.venue = b.dataset.v;
    root.querySelectorAll(".dp-seg button").forEach(x => x.classList.toggle("on", x === b)); draw(); });
  root.querySelector(".dp-clear").onclick = () => { api2.set([]); draw(); };
  root._dpDraw = draw; draw();
  return draw;
}
```
