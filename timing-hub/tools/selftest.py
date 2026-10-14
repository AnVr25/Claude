#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Самопроверка сервера SakhStart 7.0 (судейско-секретарский АРМ стадиона и манежа).

Запускает отдельную копию сервера на 127.0.0.1 со своей временной базой (рабочий сервер не трогает)
и проходит всю цепочку: вход и роли, регистрация и кабинет тренера (152-ФЗ), Мастер протоколов
(номера, сетки, сброс сетки), ручной ввод результатов, разряды ЕВСК, командный зачёт, табло и пульт,
протоколы и Excel, публикация, файлы, архив, журнал, обновление, миграцию базы с версии 6.x.
Чипового хронометража (IPICO, Wiclax) в 7.0 нет — проверяется и то, что его адресов больше нет.

    python3 selftest.py                    # из папки комплекта
    python3 selftest.py --hub /opt/timing-hub/hub.py   # на установленном сервере
"""

import argparse
import base64
import datetime as dt
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    mark = "OK  " if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail and not cond else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, timeout: float = 10) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False



def start_server(hub_path: str, cfg_path: str):
    return subprocess.Popen([sys.executable, hub_path, "--config", cfg_path],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def stop_server(proc):
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out


def migration_test(hub_path: str, tmp: str) -> None:
    """База версии 6.x (reads/raw/readers/wiclax_ports, entries с ключом (event_id, chip)) открывается сервером 7.0:
    чиповые таблицы и колонка chip уходят, участники и их данные остаются."""
    import sqlite3
    d = os.path.join(tmp, "old")
    os.makedirs(d, exist_ok=True)
    dbp = os.path.join(d, "reads.db")
    con = sqlite3.connect(dbp)
    con.executescript("""
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, date TEXT, place TEXT,
            finish_device TEXT, start_time TEXT, status TEXT NOT NULL DEFAULT 'planned', notes TEXT, created_at TEXT NOT NULL,
            push_wiclax INTEGER NOT NULL DEFAULT 0, check_since TEXT, min_time_sec REAL, alert_silence_min INTEGER);
        CREATE TABLE entries(event_id INTEGER NOT NULL, bib TEXT NOT NULL, chip TEXT NOT NULL, wave TEXT, name TEXT,
            birth_year TEXT, team TEXT, category TEXT, lane INTEGER, coach TEXT, seed TEXT, reg_id INTEGER, sex TEXT,
            result TEXT, status TEXT, points REAL, PRIMARY KEY(event_id, chip));
        CREATE TABLE waves(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, name TEXT NOT NULL, start_time TEXT,
            UNIQUE(event_id, name));
        INSERT INTO waves(event_id, name) VALUES (1, 'A'), (1, 'B');
        CREATE TABLE readers(id TEXT PRIMARY KEY, host TEXT, port INTEGER, device TEXT, enabled INTEGER);
        CREATE TABLE reads(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, chip TEXT, ts TEXT, antenna INTEGER);
        CREATE TABLE raw(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, line TEXT, ts TEXT);
        CREATE TABLE wiclax_ports(port INTEGER PRIMARY KEY, devices TEXT, name TEXT);
        INSERT INTO events(id, name, date, finish_device, created_at, push_wiclax) VALUES (1, 'Старый забег', '2026-05-01', 'FINISH', '2026-04-01 10:00:00', 1);
        INSERT INTO events(id, name, date, finish_device, created_at) VALUES (2, 'Другой забег', '2026-06-01', 'FINISH', '2026-04-02 10:00:00');
        INSERT INTO entries(event_id, bib, chip, wave, name, birth_year, team, category, lane, sex, result) VALUES
            (1, '11', 'E2801160600002000000AA01', 'A', 'Иванов Иван', '2008', 'СШОР', 'Юноши', 1, 'М', '12.4'),
            (1, '12', 'E2801160600002000000AA02', 'A', 'Петров Пётр', '2008', 'СШОР', 'Юноши', 2, 'М', NULL),
            (1, '50', '', 'B', 'Сидоров Олег', '2009', 'Холмск', 'Юноши', NULL, 'М', NULL),
            (2, '11', 'E2801160600002000000AA01', NULL, 'Иванов Иван', '2008', 'СШОР', NULL, NULL, 'М', NULL);
        INSERT INTO readers VALUES ('IP1', '10.0.0.5', 10000, 'FINISH', 1);
        INSERT INTO reads(source, chip, ts, antenna) VALUES ('FINISH', 'AA01', '2026-05-01 10:00:00.000', 1);
        INSERT INTO raw(source, line, ts) VALUES ('FINISH', 'AA01,2026-05-01 10:00:00.000', '2026-05-01 10:00:00.000');
        INSERT INTO wiclax_ports VALUES (9861, 'KM10', '10 км');
    """)
    con.commit()
    con.close()
    pw, pp = free_port(), free_port()
    cfg_path = os.path.join(d, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"db_path": dbp, "log_level": "WARNING",
                   "web": {"listen_host": "127.0.0.1", "listen_port": pw, "user": "admin", "password": "test-pass"},
                   "public": {"enabled": False, "listen_host": "127.0.0.1", "listen_port": pp},
                   "mail": {"outbox_dir": os.path.join(d, "outbox")}}, f)
    proc = start_server(hub_path, cfg_path)
    try:
        up = wait_port(pw, 15)
        check("миграция 6.x → 7.0: сервер стартует на старой базе (reads/readers/wiclax_ports, entries с ключом chip)", up)
        hdr = {"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode()}

        def get(path):
            req = urllib.request.Request(f"http://127.0.0.1:{pw}{path}", headers=hdr)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8", "replace")
        code, txt = get("/api/events/1/entries")
        en = json.loads(txt) if code == 200 else {}
        lines = (en.get("text") or "").splitlines()
        check("миграция: участники прежние — те же номера, ФИО, забеги, команды и результат",
              code == 200 and en.get("count") == 3 and sorted(x.split(";")[0] for x in lines) == ["11", "12", "50"]
              and any(x.startswith("11;A;Иванов Иван;2008;СШОР") and "12.4" in x for x in lines)
              and any(x.startswith("50;B;Сидоров Олег") for x in lines), txt[:300])
        code2, txt2 = get("/api/events/2/entries")
        check("миграция: участники второго соревнования с тем же номером и чипом не слиплись", json.loads(txt2).get("count") == 1, txt2[:200])
        code, txt = get("/api/events/1/startlist")
        sl = json.loads(txt)
        ents = [e for h in sl["heats"] for e in h["entries"]] + sl["no_heat"]
        check("миграция: стартовый список читается, у строк появился собственный id, чипа в ответе нет",
              code == 200 and len(ents) == 3 and all(isinstance(e.get("id"), int) for e in ents) and "chip" not in txt.lower(), txt[:300])
        db = sqlite3.connect(dbp)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        ecols = [r[1] for r in db.execute("PRAGMA table_info(entries)")]
        pk = [r[1] for r in db.execute("PRAGMA table_info(entries)") if r[5]]
        evcols = {r[1] for r in db.execute("PRAGMA table_info(events)")}
        cnt = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        db.close()
        check("миграция: таблиц reads, raw, readers, wiclax_ports больше нет",
              not ({"reads", "raw", "readers", "wiclax_ports"} & tables), str(sorted(tables)))
        check("миграция: у entries нет колонки chip, ключ — суррогатный id, 4 строки на месте",
              "chip" not in ecols and "id" in ecols and pk == ["id"] and cnt == 4, f"{ecols} {pk} {cnt}")
        check("миграция: устаревшие поля соревнований (push_wiclax и др.) убраны",
              not ({"push_wiclax", "check_since", "min_time_sec", "alert_silence_min"} & evcols), str(sorted(evcols)))
        c, t = None, None
        req = urllib.request.Request(f"http://127.0.0.1:{pw}/api/events/1/results",
                                     data=json.dumps({"rows": [{"bib": "50", "result": "13.7"}]}).encode(), method="POST",
                                     headers={**hdr, "Content-Type": "application/json", "X-Requested-With": "timing-hub"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            c, t = resp.status, json.loads(resp.read())
        check("миграция: на перенесённой базе работает запись результата", c == 200 and t.get("saved") == 1 and not t.get("errors"), str(t))
    except Exception as e:  # noqa
        check("миграция: непредвиденная ошибка", False, repr(e))
    finally:
        out = stop_server(proc)
        check("миграция: сервер на старой базе корректно останавливается без ошибок в журнале",
              proc.returncode == 0 and "Traceback" not in out, f"код {proc.returncode} {out[-300:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=os.path.join(HERE, "..", "hub", "hub.py"))
    args = ap.parse_args()
    hub_path = os.path.abspath(args.hub)
    if not os.path.exists(hub_path):
        print(f"не найден {hub_path}")
        return 2

    tmp = tempfile.mkdtemp(prefix="timing-hub-selftest-")
    p_web, p_pub, p_old1, p_old2 = free_port(), free_port(), free_port(), free_port()
    cfg = {
        "db_path": os.path.join(tmp, "reads.db"),
        "log_level": "WARNING",
        "web": {"listen_host": "127.0.0.1", "listen_port": p_web, "user": "admin",
                "password": "test-pass", "api_key": "test-key"},
        "public": {"enabled": True, "listen_host": "127.0.0.1", "listen_port": p_pub, "url": "https://reg.example.ru"},
        "mail": {"outbox_dir": os.path.join(tmp, "outbox")},
        "operator": {"name": "РОО «Федерация лёгкой атлетики Сахалинской области»", "email": "pd@example.ru"},
        # ключи прежних версий (чиповые источники и порт Wiclax): 7.0 молча их игнорирует и ничего не слушает
        "sources": [{"id": "FINISH", "name": "Финиш", "mode": "listen", "listen_host": "127.0.0.1",
                     "listen_port": p_old1, "parser": "auto"}],
        "wiclax": {"listen_host": "127.0.0.1", "listen_port": p_old2, "heartbeat_sec": 1},
    }
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)

    # 0. версия и проверка настроек
    r = subprocess.run([sys.executable, hub_path, "--version"], capture_output=True, text=True)
    check("версия сервера 7.1.0 (--version)", r.returncode == 0 and r.stdout.strip() == "7.1.0", r.stdout + r.stderr)
    r = subprocess.run([sys.executable, hub_path, "--config", cfg_path, "--check"],
                       capture_output=True, text=True)
    check("настройки читаются (--check); старые ключи sources и wiclax игнорируются без ошибок",
          r.returncode == 0 and "Traceback" not in r.stderr, r.stdout.strip() + r.stderr.strip())

    # миграция базы 6.x → 7.0 (отдельная копия сервера на отдельной базе)
    migration_test(hub_path, tmp)

    proc = start_server(hub_path, cfg_path)
    failed = False
    try:
        check("сервер запустился", wait_port(p_web) and wait_port(p_pub))
        time.sleep(0.5)
        check("прежние порты чиповых источников и Wiclax не открываются",
              not wait_port(p_old1, 0.5) and not wait_port(p_old2, 0.5))

        now = dt.datetime.now().replace(microsecond=0)
        t0 = now - dt.timedelta(seconds=30)


        def http(method, path, body=None, headers=None, auth=True):
            h = dict(headers or {})
            if auth:
                h["Authorization"] = "Basic " + base64.b64encode(b"admin:test-pass").decode()
            req = urllib.request.Request(f"http://127.0.0.1:{p_web}{path}", data=body, method=method, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8", "replace")

        J = {"Content-Type": "application/json", "X-Requested-With": "timing-hub"}

        def api(method, path, obj=None):
            """Запрос к API от имени администратора: (код, разобранный JSON)."""
            c_, t_ = http(method, path, None if obj is None else json.dumps(obj).encode(), J)
            try:
                return c_, json.loads(t_)
            except ValueError:
                return c_, {"_raw": t_}

        def give_bibs(eid, start=None, distance=None):
            """Имитация шага 2: секретарь вписывает номера тем, у кого их ещё нет (сервер сам их не выдаёт).
            Один человек (ФИО + год) получает один номер на все свои дисциплины."""
            q = "?distance=" + urllib.parse.quote(distance) if distance else ""
            v = json.loads(http("GET", f"/api/events/{eid}/bibs{q}")[1])
            allv = json.loads(http("GET", f"/api/events/{eid}/bibs")[1])
            have = [int(r["bib"]) for r in allv["rows"] if str(r["bib"]).isdigit()]
            n = start or (max(have) + 1 if have else 1)
            num, rows = {}, []
            for r in v["rows"]:
                if r["bib"]:
                    continue
                k = (r["name"], r["birth_year"])
                if k not in num:
                    num[k] = n
                    n += 1
                rows.append({"ids": r["ids"], "bib": str(num[k])})
            if rows:
                c_, t_ = http("POST", f"/api/events/{eid}/bibs", json.dumps({"rows": rows}).encode(), J)
                assert c_ == 200, t_
            return len(num)

        DEF_RULES = "Юноши;М;1980;2020\nДевушки;Ж;1980;2020"

        def seed(name, people, dists, lanes=8, rules=DEF_RULES, grid=True, **evkw):
            """Соревнование на стадионе «под ключ» через настоящий путь секретаря: заявки (подтверждены), номера на шаге 2,
            сетка по каждой дисциплине. people: (номер, 'Фамилия Имя', год, пол, команда, разряд, [дисциплины])."""
            c_, e_ = api("POST", "/api/events", {"name": name, "kind": "stadium", "timing": "manual",
                                                  "finish_device": "JUDGE", **evkw})
            assert c_ == 201, e_
            sid_ = e_["id"]
            api("POST", f"/api/events/{sid_}", {"reg_distances": "\n".join(dists), "reg_rules": rules})
            want = {}
            for bib_, nm_, year_, sex_, team_, rank_, ds_ in people:
                ln_, fn_ = nm_.split(" ", 1)
                c_, o_ = api("POST", f"/api/events/{sid_}/regs", {
                    "last_name": ln_, "first_name": fn_, "birth_date": f"{year_}-06-15", "sex": sex_, "team": team_,
                    "rank": rank_, "representative": "Родитель", "policy": True, "distances": [{"distance": d_} for d_ in ds_]})
                assert c_ == 201, (nm_, c_, o_)
                want[(nm_, str(year_))] = str(bib_)
            rows_ = [{"ids": r_["ids"], "bib": want[(r_["name"], r_["birth_year"])]}
                     for r_ in json.loads(http("GET", f"/api/events/{sid_}/bibs")[1])["rows"]]
            c_, t_ = http("POST", f"/api/events/{sid_}/bibs", json.dumps({"rows": rows_}).encode(), J)
            assert c_ == 200, t_
            if grid:
                for d_ in dists:
                    c_, o_ = api("POST", f"/api/events/{sid_}/heats", {"distance": d_, "lanes": lanes})
                    assert c_ == 200, (d_, o_)
            return sid_

        def sl_entries(eid):
            sl_ = json.loads(http("GET", f"/api/events/{eid}/startlist")[1])
            return [e for h in sl_["heats"] for e in h["entries"]] + sl_["no_heat"]

        def fin_by(eid):
            """Итоги по ключу (номер, дисциплина): один номер стоит у спортсмена в нескольких дисциплинах."""
            return {(x["bib"], x["distance"]): x for x in json.loads(http("GET", f"/api/events/{eid}/results")[1])["finished"]}

        def grid_all(eid, dists, lanes=8):
            """Сформировать сетку по каждой дисциплине (7.0: только через POST …/heats {distance, lanes})."""
            return [api("POST", f"/api/events/{eid}/heats", {"distance": d_, "lanes": lanes}) for d_ in dists]

        def to_wave(eid, bib, wave, distance=None):
            return api("POST", f"/api/events/{eid}/entry", {"bib": bib, "wave": wave, **({"distance": distance} if distance else {})})

        # 9. страница состояния, JSON, CSV
        code, txt = http("GET", "/", auth=False)
        check("без входа — страница входа", code == 200 and "Вход для организаторов" in txt, str(code))
        code, _ = http("GET", "/api/events", auth=False)
        check("API без входа закрыто", code == 401, str(code))

        # 9a. вход через браузер (сессии, роли), в т.ч. через nginx
        def jpost(path, obj, cookie=None, proxied=False):
            h = {"Content-Type": "application/json", "X-Requested-With": "timing-hub"}
            if cookie:
                h["Cookie"] = cookie
            if proxied:
                h.update({"X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"})
            req = urllib.request.Request(f"http://127.0.0.1:{p_web}{path}", data=json.dumps(obj).encode(), method="POST", headers=h)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json.loads(resp.read() or b"{}"), resp.headers.get("Set-Cookie", "")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}"), ""

        def cget(path, cookie, proxied=True):
            h = {"Cookie": cookie}
            if proxied:
                h.update({"X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"})
            req = urllib.request.Request(f"http://127.0.0.1:{p_web}{path}", headers=h)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status
            except urllib.error.HTTPError as e:
                return e.code

        code, d, ck = jpost("/api/login", {"login": "admin", "password": "wrong"}, proxied=True)
        check("вход: неверный пароль отклонён", code == 401, str(code))
        code, d, ck = jpost("/api/login", {"login": "admin", "password": "test-pass"}, proxied=True)
        adm = ck.split(";")[0]
        check("вход: администратор из настроек, cookie Secure+HttpOnly через https",
              code == 200 and adm.startswith("ss_session=") and "Secure" in ck and "HttpOnly" in ck, f"{code} {ck[:60]}")
        check("вход: с сессией панель открывается", cget("/api/events", adm) == 200)
        req = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events", headers={
            "Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode(), "X-Forwarded-Proto": "https"})
        try:
            urllib.request.urlopen(req, timeout=5); code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        check("через nginx из интернета Basic-пароль не принимается", code == 401, str(code))
        code, d, _ = jpost("/api/users", {"login": "judge1", "name": "Судья", "role": "judge", "password": "judge-pass-1"}, adm, True)
        check("пользователи: судья добавлен", code == 200, str(d))
        code, d, _ = jpost("/api/users", {"login": "sec1", "role": "secretary", "password": "123"}, adm, True)
        check("пользователи: короткий пароль отклонён", code == 400, str(d))
        code, d, ck = jpost("/api/login", {"login": "judge1", "password": "judge-pass-1", "next": "/"}, proxied=True)
        jck = ck.split(";")[0]
        check("судья после входа попадает в админку", code == 200 and d.get("next") == "/", str(d))
        check("судья: соревнования и ручные отметки доступны, система — нет",
              cget("/api/events", jck) == 200 and cget("/api/system", jck) == 403 and cget("/api/users", jck) == 403)
        code, _, _ = jpost(f"/api/events/1/delete", {}, jck, True)
        check("судья не может удалить соревнование", code == 403, str(code))
        jpost("/api/logout", {}, jck, True)
        check("после выхода сессия не действует", cget("/api/events", jck) == 401)
        code, d, _ = jpost("/api/users", {"login": "judge1", "role": "judge", "password": "other-pass-2", "create": True}, adm, True)
        check("пользователи: повторный логин при добавлении — 409", code == 409, str(code))
        code, d, _ = jpost("/api/users/judge1/update", {"note": "  финиш,   до 30.10 ", "name": "Судья Петров"}, adm, True)
        req = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/users",
                                     headers={"Cookie": adm, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            ul = {u["login"]: u for u in json.loads(resp.read())["users"]}
        j1 = ul.get("judge1", {})
        check("пользователи: примечание и имя сохранены", code == 200 and j1.get("note") == "финиш, до 30.10"
              and j1.get("name") == "Судья Петров" and j1.get("active") == 1, str(j1))
        code, d, ck = jpost("/api/login", {"login": "judge1", "password": "judge-pass-1"}, proxied=True)
        jck = ck.split(";")[0]
        code, d, _ = jpost("/api/users/judge1/update", {"active": False}, adm, True)
        code2, _, _ = jpost("/api/login", {"login": "judge1", "password": "judge-pass-1"}, proxied=True)
        check("пользователи: заблокированный не входит, его сессии закрыты",
              code == 200 and code2 == 401 and cget("/api/events", jck) == 401, f"{code} {code2}")
        code, d, _ = jpost("/api/users/judge1/update", {"active": True, "password": "judge-pass-9"}, adm, True)
        code2, _, _ = jpost("/api/login", {"login": "judge1", "password": "judge-pass-9"}, proxied=True)
        check("пользователи: разблокирован, новый пароль работает", code == 200 and code2 == 200, f"{code} {code2}")
        code, d, _ = jpost("/api/users/admin/update", {"active": False}, adm, True)
        code, txt = http("GET", "/")
        check("страница состояния открывается", code == 200 and "SakhStart" in txt, str(code))
        code, txt = http("GET", "/api/status")
        st = json.loads(txt) if code == 200 else {}
        check("JSON-статус 7.0: только версия, дата сборки, время сервера и запуск — никаких считываний и источников",
              set(st) == {"version", "build_date", "server_epoch_ms", "server_time", "timezone", "started_at"}
              and st["version"] == "7.1.0" and st["build_date"] == "2026-10-14", txt[:300])
        gone = {}
        for pth in ("/api/readers", "/api/wiclax-ports", "/api/live", "/api/devices", "/raw", "/export.csv",
                    "/api/readers/scan", "/api/events/1/clax", "/api/events/1/event.clax", "/api/events/1/wiclax.csv",
                    "/api/events/1/check"):
            gone[pth] = http("GET", pth)[0]
        gone["POST /api/reads"] = http("POST", "/api/reads?source=HTTP", b"AA01 10:00:00.000\n", {"X-Api-Key": "test-key"}, auth=False)[0]
        check("чиповые адреса удалены: /api/readers, /api/wiclax-ports, /api/live, /api/devices, /raw, /export.csv, POST /api/reads, "
              ".clax, wiclax.csv, check — все дают 404 или отказ",
              all(c_ in (401, 404) for c_ in gone.values()), str(gone))
        code, txt = http("GET", "/api/system")
        sy0 = json.loads(txt)
        check("«Система»: ни ридеров, ни Wiclax — только сервер, службы, клиенты",
              code == 200 and "readers" not in sy0 and "wiclax" not in sy0 and sy0["server"]["version"] == "7.1.0", txt[:200])


        # 9b. соревнование на стадионе: создание, номера, сетка, старт, отсечки судьи, результаты
        code, _ = http("POST", "/api/events", json.dumps({"name": "x"}).encode(), {"Content-Type": "application/json"})
        check("API: POST без X-Requested-With отклонён", code == 403, str(code))
        code, ev = api("POST", "/api/events", {"name": "Проверка видов", "kind": "mass", "timing": "chips"})
        check("7.0: вид соревнования kind=mass не принимается — всегда «стадион»", code == 201 and ev.get("kind") == "stadium", str(ev.get("kind")))
        check("7.0: хронометраж timing=chips не принимается (допустимы judge|manual|lynx)",
              code == 201 and ev.get("timing") in (None, "", "judge", "manual", "lynx"), str(ev.get("timing")))
        code, ev = api("POST", "/api/events", {"name": "Проверка поля", "kind": "stadium", "timing": "lynx"})
        check("7.0: хронометраж lynx принимается", code == 201 and ev.get("timing") == "lynx", str(ev)[:200])
        e1 = seed("Тестовый забег", [(1, "Иванов Иван", 2008, "М", "СШОР", "1р", ["100 м"]),
                                     (2, "Петров Пётр", 2008, "М", "СШОР", "Б/р", ["100 м"]),
                                     (9, "Сидоров Олег", 2008, "М", "СШОР", "Б/р", ["100 м"])],
                  ["100 м"], date=t0.strftime("%Y-%m-%d"))
        ev1 = json.loads(http("GET", f"/api/events/{e1}")[1])
        check("API: соревнование создано без чиповых полей (finish_device, push_wiclax, check_since)",
              ev1["id"] == e1 and ev1.get("kind") == "stadium" and "push_wiclax" not in ev1 and "check_since" not in ev1
              and "chip" not in json.dumps(ev1).lower(), str(ev1)[:300])
        code, txt = http("POST", f"/api/events/{e1}/entries", json.dumps({"text": "1;AA01"}).encode(), J)
        check("импорт списка текстом (POST …/entries) удалён", code in (404, 405), f"{code} {txt[:100]}")
        code, txt = http("GET", f"/api/events/{e1}/entries")
        check("GET …/entries остался (только чтение): 3 участника, у номера 1 — «Иванов Иван»",
              code == 200 and json.loads(txt)["count"] == 3 and any(x.startswith("1;Забег 1;Иванов Иван") for x in json.loads(txt)["text"].splitlines()),
              txt[:300])
        base1 = int(time.time() * 1000) - 60000
        code, txt = api("POST", f"/api/events/{e1}/start", {"wave": "Забег 1", "epoch_ms": base1})
        check("API: старт забега дан", code == 200 and txt.get("status") == "running", str(txt)[:200])
        api("POST", f"/api/events/{e1}/manual", {"bib": "1", "epoch_ms": base1 + 1000, "client_id": "e1a"})
        api("POST", f"/api/events/{e1}/manual", {"bib": "2", "epoch_ms": base1 + 3000, "client_id": "e1b"})
        code, r = api("GET", f"/api/events/{e1}/results")
        fin = [(x["place"], x["bib"], x["time"]) for x in r.get("finished", [])]
        check("результаты: финиш по порядку с номерами",
              fin == [(1, "1", "0:00:01.0"), (2, "2", "0:00:03.0")], str(fin))
        check("результаты: не отмеченные в списке; «на трассе» всегда пусто; без поля chip",
              [x["bib"] for x in r.get("not_seen", [])] == ["9"] and r.get("on_course") == [] and '"chip"' not in json.dumps(r),
              json.dumps(r, ensure_ascii=False)[:400])
        check("результаты: devices — только точки ручных отметок судьи", r.get("devices") == ["JUDGE"], str(r.get("devices")))
        code, txt = http("GET", f"/api/events/{e1}/results.csv")
        check("результаты: CSV без колонки «Чип»", code == 200 and "Место общее" in txt and "Чип" not in txt and "Иванов Иван" in txt, txt[:200])
        code, txt = http("GET", "/board?event=" + str(e1))
        check("табло открывается", code == 200 and "Табло" in txt, str(code))
        code, txt = http("GET", "/api/events")
        check("список соревнований", code == 200 and len(json.loads(txt)["events"]) >= 3, txt[:200])

        # 9c. два забега, ручные отметки судьи без номера, предупреждения, журнал
        e2 = seed("Волны", [(1, "Иванов Иван", 2008, "М", "СШОР", "Б/р", ["100 м"]),
                            (2, "Петров Пётр", 2008, "М", "СШОР", "Б/р", ["100 м"]),
                            (50, "Сидоров Сидор", 2008, "М", "СШОР", "Б/р", ["100 м"])],
                  ["100 м"], date=t0.strftime("%Y-%m-%d"))
        api("POST", f"/api/events/{e2}/waves", {"name": "Забег 2", "category": "Юноши", "distance": "100 м"})
        to_wave(e2, "2", "Забег 2")
        to_wave(e2, "50", "Забег 2")
        w2_ = json.loads(http("GET", f"/api/events/{e2}")[1])["waves"]
        check("забеги: «Забег 1» из сетки и добавленный «Забег 2»", sorted(w["name"] for w in w2_) == ["Забег 1", "Забег 2"], str(w2_)[:300])
        tA = (t0 - dt.timedelta(seconds=1)).strftime("%H:%M:%S")
        tB = (t0 + dt.timedelta(seconds=1)).strftime("%H:%M:%S")
        http("POST", f"/api/events/{e2}/start", json.dumps({"wave": "Забег 1", "time": tA}).encode(), J)
        code, txt = http("POST", f"/api/events/{e2}/start", json.dumps({"wave": "Забег 2", "time": tB}).encode(), J)
        check("забеги: старт каждого забега", code == 200 and all(w["start_time"] for w in json.loads(txt)["waves"]), txt[:300])
        tm = (t0 + dt.timedelta(seconds=10)).strftime("%H:%M:%S")
        http("POST", f"/api/events/{e2}/manual", json.dumps({"bib": "1", "time": t0.strftime("%H:%M:%S"), "client_id": "w1"}).encode(), J)
        http("POST", f"/api/events/{e2}/manual", json.dumps({"bib": "2", "time": (t0 + dt.timedelta(seconds=2)).strftime("%H:%M:%S"),
                                                             "client_id": "w2"}).encode(), J)
        code, txt = http("POST", f"/api/events/{e2}/manual", json.dumps({"bib": "50", "time": tm, "judge": "Иванов",
                         "client_id": "c1"}).encode(), J)
        check("ручная отметка с номером", code == 201, txt)
        http("POST", f"/api/events/{e2}/manual", json.dumps({"bib": "50", "time": tm, "client_id": "c1"}).encode(), J)
        code, txt = http("POST", f"/api/events/{e2}/manual", json.dumps({"epoch_ms": int(t0.timestamp() * 1000) + 20000,
                         "client_id": "c2"}).encode(), J)
        pend_id = json.loads(txt)["mark"]["id"] if code == 201 else None
        _, txt = http("GET", f"/api/events/{e2}/manual")
        check("повторная отправка с тем же client_id не дублирует", len(json.loads(txt)["marks"]) == 4, txt[:300])
        _, txt = http("GET", f"/api/events/{e2}/results")
        r2 = json.loads(txt)
        got = sorted((x["wave"], x["place"], x["bib"], x["time"]) for x in r2["finished"])
        check("забеги: места и время считаются от старта своего забега",
              got == [("Забег 1", 1, "1", "0:00:01.0"), ("Забег 2", 1, "2", "0:00:01.0"), ("Забег 2", 2, "50", "0:00:09.0")], str(got))
        texts = " | ".join(a["text"] for a in r2["alerts"])
        check("предупреждения: отсечка без номера", r2["manual_pending"] == 1 and "без номера" in texts, texts)
        code, txt = http("POST", f"/api/events/{e2}/manual/{pend_id}", json.dumps({"bib": "77"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e2}/results")
        r2 = json.loads(txt)
        texts = " | ".join(a["text"] for a in r2["alerts"])
        check("номер вписан в отсечку позже; номера 77 нет в списке участников — предупреждение",
              code == 200 and r2["manual_pending"] == 0 and "77" in texts and "нет в списке" in texts, f"{code} {texts}")
        _, txt = http("GET", f"/api/events/{e2}/log")
        acts = [a["action"] for a in json.loads(txt)["log"]]
        check("журнал действий", "СТАРТ «Забег 1»" in acts and "Ручная отметка" in acts and "Номер в ручной отметке" in acts,
              str(acts))

        for page in ("/judge", "/announcer?event=1"):
            code, txt = http("GET", page)
            check(f"страница {page} открывается", code == 200 and "<html" in txt, str(code))
        code, txt = http("GET", "/assets/brand.css")
        check("фирменный стиль /assets/brand.css отдаётся", code == 200 and "@font-face" in txt, str(code))
        for bad in ("/assets/hub.py", "/assets/..%2Fhub.py", "/assets/.hidden.css", "/assets/nope.png"):
            code, _ = http("GET", bad)
            check(f"/assets не отдаёт лишнего: {bad}", code == 404, str(code))

        # 9d. файлы, снимок результатов, архив
        req = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e2}/files", data="Протокол;1\n".encode("utf-8"),
              method="POST", headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode(),
              "X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream",
              "X-File-Name": urllib.parse.quote("Протокол Кросс 2026.csv")})
        with urllib.request.urlopen(req, timeout=5) as resp:
            fid = json.loads(resp.read())["file"]["id"]
        code, txt = http("GET", f"/files/{fid}")
        check("файл: загрузка и скачивание", code == 200 and "Протокол;1" in txt, f"{code} {txt[:80]}")
        code, txt = http("POST", f"/api/events/{e2}/finish", b"{}", J)
        _, txt = http("GET", f"/api/events/{e2}/files")
        kinds = sorted(f["kind"] for f in json.loads(txt)["files"])
        check("при завершении сохраняется снимок результатов (рядом — загруженный протокол и стартовый список сетки)",
              kinds == ["protocol", "snapshot", "startlist"], str(kinds))
        snap = [f for f in json.loads(txt)["files"] if f["kind"] == "snapshot"][0]
        code, txt = http("GET", f"/files/{snap['id']}")
        check("снимок результатов читается", code == 200 and "Дистанция;Категория;Место общее" in txt and "Иванов Иван" in txt, txt[:120])
        code, txt = http("POST", f"/api/events/{e2}/archive", b"{}", J)
        check("перенос в архив", code == 200 and json.loads(txt)["archived"] == 1 and json.loads(txt)["files_count"] == 3, txt[:200])
        code, txt = http("POST", f"/api/events/{e2}/files/{fid}", json.dumps({"delete": True}).encode(), J)
        code2, _ = http("GET", f"/files/{fid}")
        check("удаление файла", code == 200 and code2 == 404, f"{code} {code2}")

        # 9e. стадион: судья, забеги по очереди, финиш забега, общий протокол
        e3 = seed("Первенство города", [(11, "Иванов Иван", 2008, "М", "СШОР", "Б/р", ["100 м"]),
                                        (12, "Петров Пётр", 2008, "М", "СШОР", "Б/р", ["100 м"]),
                                        (21, "Сидоров Олег", 2009, "М", "Холмск", "Б/р", ["100 м"]),
                                        (31, "Козлов Илья", 2008, "М", "Корсаков", "Б/р", ["100 м"])],
                  ["100 м"], organizer="РСОО ФЛАСО", chief_judge="Иванов И. И.", chief_secretary="Петрова А. А.",
                  place="Стадион «Спартак»")
        check("забеги: судейское соревнование — забеги по очереди",
              json.loads(http("GET", f"/api/events/{e3}")[1]).get("heats_sequential") is True)
        api("POST", f"/api/events/{e3}/waves", {"name": "Забег 2", "category": "Юноши", "distance": "100 м"})
        code, txt = api("POST", f"/api/events/{e3}/waves", {"next": True})
        check("«Следующий забег»: Забег 3 с категорией и дистанцией предыдущего",
              txt.get("created") == "Забег 3" and any(x["name"] == "Забег 3" and x["category"] == "Юноши" and x["distance"] == "100 м"
                                                      for x in txt["waves"]), str(txt)[-300:])
        to_wave(e3, "21", "Забег 2")
        to_wave(e3, "31", "Забег 3")
        base = int(time.time() * 1000) - 120000

        def jp3(path, body):
            return http("POST", f"/api/events/{e3}/{path}", json.dumps(body).encode(), J)
        jp3("start", {"wave": "Забег 1", "epoch_ms": base})
        jp3("manual", {"bib": "11", "epoch_ms": base + 12310, "wave": "Забег 1", "client_id": "h1"})
        jp3("manual", {"bib": "12", "epoch_ms": base + 13000, "wave": "Забег 1", "client_id": "h2"})
        code, txt = jp3("start", {"wave": "Забег 2", "epoch_ms": base + 20000})
        w = {x["name"]: x for x in json.loads(txt)["waves"]}
        check("старт следующего забега завершает предыдущий",
              w["Забег 1"]["state"] == "finished" and w["Забег 1"]["finish_epoch_ms"] == base + 20000 and w["Забег 2"]["state"] == "running",
              str(w)[:300])
        jp3("manual", {"bib": "21", "epoch_ms": base + 32050, "wave": "Забег 2", "client_id": "h3"})
        code, txt = jp3("waves", {"name": "Забег 2", "finish": True, "epoch_ms": base + 34000})
        jp3("manual", {"bib": "99", "epoch_ms": base + 37000, "wave": "Забег 2", "client_id": "h4"})
        jp3("start", {"wave": "Забег 3", "epoch_ms": base + 40000})
        jp3("manual", {"bib": "31", "epoch_ms": base + 51900, "wave": "Забег 3", "client_id": "h5"})
        _, txt = http("GET", f"/api/events/{e3}/results")
        r3 = json.loads(txt)
        got = sorted((x["place_overall"], x["bib"], x["wave"], x["place"], x["result"]) for x in r3["finished"])
        check("общий протокол: место в забеге и общее место, ручное время вверх до 0,1",
              got == [(1, "31", "Забег 3", 1, "11.9"), (2, "21", "Забег 2", 1, "12.1"),
                      (3, "11", "Забег 1", 1, "12.4"), (4, "12", "Забег 1", 2, "13.0")], str(got))
        check("отметка после финиша забега не учитывается", all(x["bib"] != "99" for x in r3["finished"]), str(r3["finished"])[:200])
        f31 = [x for x in r3["finished"] if x["bib"] == "31"]
        check("ФИО, команда и категория забега в результатах",
              f31 and f31[0]["name"] == "Козлов Илья" and f31[0]["team"] == "Корсаков" and f31[0]["category"] == "Юноши", str(f31))
        code, txt = http("GET", f"/protocol?event={e3}")
        check("страница протокола открывается", code == 200 and "Главный судья" in txt, str(code))
        code, txt = http("GET", f"/api/events/{e3}/results.csv")
        check("CSV протокола: общее место и ФИО", code == 200 and "Место общее" in txt and "Козлов Илья" in txt, txt[:200])


        # 9f. регистрация через публичную форму → подтверждение → забеги с посевом
        code, txt = http("POST", "/api/events", json.dumps({"name": "Первенство города", "date": "2026-10-24",
                         "finish_device": "JUDGE", "push_wiclax": False}).encode(), J)
        e4 = json.loads(txt)["id"]
        code, txt = http("POST", f"/api/events/{e4}", json.dumps({"reg_open": True, "reg_distances": "60 м\n300 м",
                         "reg_rules": "Юноши;М;2010;2011\nДевушки;Ж;2010;2011", "reg_lanes": 4}).encode(), J)
        evr = json.loads(txt)
        slug = evr["reg_path"].rsplit("/", 1)[-1]
        check("регистрация: ссылка на форму создана", evr["reg_url"] == f"https://reg.example.ru/r/{slug}" and len(slug) >= 6,
              evr.get("reg_url", ""))

        class _NoFollow(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        _nofollow = urllib.request.build_opener(_NoFollow)

        def pub(method, path, body=None, ctype="application/json", cookie=None, xrw=False, port=None):
            h = {"Content-Type": ctype} if body is not None else {}
            if cookie:
                h["Cookie"] = cookie
            if xrw:
                h["X-Requested-With"] = "timing-hub"
            req = urllib.request.Request(f"http://127.0.0.1:{port or p_pub}{path}", data=body, method=method, headers=h)
            try:
                with _nofollow.open(req, timeout=5) as resp:
                    return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8"), dict(e.headers)

        # 5.0: личный кабинет тренера — регистрация, код из письма, вход; протоколы закрыты для гостей
        import email as _email
        import email.policy as _epol
        import re as _re
        import sqlite3 as _sql
        outbox = os.path.join(tmp, "outbox")

        def tpost(path, obj, cookie=None, xrw=True, port=None):
            c, t, hd = pub("POST", path, json.dumps(obj).encode(), cookie=cookie, xrw=xrw, port=port)
            try:
                return c, json.loads(t), hd
            except ValueError:
                return c, {}, hd

        def last_mail():
            fs = sorted(os.listdir(outbox)) if os.path.isdir(outbox) else []
            if not fs:
                return None, ""
            m = _email.message_from_bytes(open(os.path.join(outbox, fs[-1]), "rb").read(), policy=_epol.default)
            body_ = m.get_content()
            cm = _re.search(r"^\s+(\d{6})\s*$", body_, _re.M)
            return m, cm.group(1) if cm else ""

        TA = "/r/api/auth/trainer/"
        c1, d1, _ = tpost(TA + "register", {"name": "Иванова", "team": "", "email": "не почта", "password": "123"})
        c2, d2, _ = tpost(TA + "register", {"name": "Иванова Мария", "team": "СШОР", "email": "coach@example.ru",
                                             "password": "coach-pass-1", "consent": True, "policy": True}, xrw=False)
        check("5.0: регистрация тренера проверяет ФИО, школу, почту, пароль и согласие; без X-Requested-With — отказ",
              c1 == 400 and set(d1.get("fields", {})) == {"name", "team", "email", "password", "consent", "policy"} and c2 == 403, f"{c1} {d1} {c2}")
        c3, d3, _ = tpost(TA + "register", {"name": "Иванова Мария Петровна", "team": "СШОР по лёгкой атлетике",
                                             "email": "Coach@Example.ru", "password": "coach-pass-1", "consent": True, "policy": True})
        msg_, code_ = last_mail()
        cn1, dn1, _ = tpost(TA + "register", {"name": "Сидоров Олег", "team": "ДЮСШ", "email": "sid@example.ru",
                                               "password": "sid-pass-123", "consent_accepted": False})
        dbc = _sql.connect(cfg["db_path"])
        crow = dbc.execute("SELECT consent_accepted, consent_at, consent_hash FROM trainers WHERE email = 'coach@example.ru'").fetchone()
        nsid = dbc.execute("SELECT COUNT(*) FROM trainers WHERE email = 'sid@example.ru'").fetchone()[0]
        dbc.close()
        check("5.0.1: без согласия (consent_accepted) тренер не регистрируется; согласие записано с датой и отпечатком редакции политики",
              cn1 == 400 and "consent" in dn1.get("fields", {}) and nsid == 0 and crow and crow[0] == 1 and crow[1] and len(crow[2] or "") == 16,
              f"{cn1} {dn1} {crow}")
        pv1, pvt, pvh = pub("GET", "/privacy")
        pv2, pvt2, _ = pub("GET", "/privacy", port=p_web)
        pv3, _, _ = pub("GET", "/r/privacy")
        _, regt, _ = pub("GET", "/r/trainer")
        check("5.0.1: Политика конфиденциальности открыта всем по /privacy (панель и публичная часть): оператор, 152-ФЗ, Россия, TLS, cookie",
              pv1 == 200 and pv2 == 200 and pv3 == 200 and "РОО «Федерация лёгкой атлетики Сахалинской области»" in pvt
              and "pd@example.ru" in pvt and "152-ФЗ" in pvt and "в Российской Федерации" in pvt and "TLS" in pvt and "HttpOnly" in pvt
              and "{{" not in pvt and "ЕВСК" in pvt and "СНИЛС" in pvt and pvt == pvt2 and 'href="/privacy"' in regt, f"{pv1} {pv2} {pv3}")
        check("5.0.2: в Политике — реквизиты РСОО «ФЛАСО» по умолчанию, ответственный за ПДн, сроки хранения; ни слова о Яндексе и аналитике",
              "РСОО «ФЛАСО»" in pvt and "6501159635" in pvt and "1056500009521" in pvt and "Шаронов Виталий Александрович" in pvt
              and "ул. М. Горького, д. 7а" in pvt and "Яндекс" not in pvt and "Метрик" not in pvt and "30 дней" in pvt and "3 лет" in pvt,
              "реквизиты/сроки")
        dbc = _sql.connect(cfg["db_path"])
        trow = dbc.execute("SELECT is_verified, verification_token, password_hash FROM trainers WHERE email = 'coach@example.ru'").fetchone()
        dbc.close()
        check("5.0: тренер записан неподтверждённым, письмо с 6-значным кодом ушло; в базе хеш кода и пароля, не сами значения",
              c3 == 200 and d3.get("sent") is True and msg_ is not None and msg_["To"] == "coach@example.ru" and len(code_) == 6
              and trow and trow[0] == 0 and trow[1] and code_ not in trow[1] and "coach-pass-1" not in trow[2], f"{c3} {d3} {code_}")
        c4, d4, _ = tpost(TA + "login", {"email": "coach@example.ru", "password": "coach-pass-1"})
        bad = "000000" if code_ != "000000" else "111111"
        c5, d5, _ = tpost(TA + "verify", {"email": "coach@example.ru", "code": bad})
        c6, d6, h6 = tpost(TA + "verify", {"email": "coach@example.ru", "code": code_})
        TCK = (h6.get("Set-Cookie") or "").split(";")[0]
        c7, d7, _ = pub("GET", TA + "me", cookie=TCK)
        check("5.0: до подтверждения вход закрыт; неверный код — отказ; верный код подтверждает почту и сразу открывает кабинет",
              c4 == 403 and d4.get("verify") and c5 == 400 and "Неверный код" in d5.get("error", "") and c6 == 200
              and TCK.startswith("ss_session=") and "HttpOnly" in h6.get("Set-Cookie", "") and c7 == 200
              and json.loads(d7)["team"] == "СШОР по лёгкой атлетике", f"{c4} {c5} {c6} {c7} {d6}")
        c8, d8, h8 = tpost(TA + "login", {"email": "coach@example.ru", "password": "wrong-pass"})
        c9, d9, h9 = tpost(TA + "login", {"email": "COACH@example.ru", "password": "coach-pass-1"})
        c10, d10, _ = tpost(TA + "register", {"name": "Иванова Мария", "team": "СШОР", "email": "coach@example.ru",
                                               "password": "other-pass-1", "consent": True, "policy": True})
        check("5.0: вход тренера по почте и паролю; неверный пароль — отказ; повторная регистрация той же почты — «войдите»",
              c8 == 401 and c9 == 200 and (h9.get("Set-Cookie") or "").startswith("ss_session=") and c10 == 409 and d10.get("login"),
              f"{c8} {c9} {c10}")
        # перебор кода: после 5 неверных попыток — только новый код
        tpost(TA + "register", {"name": "Петров Сергей", "team": "ДЮСШ Холмск", "email": "petrov@example.ru",
                                "password": "petrov-pass-1", "consent": True, "policy": True})
        _, code2 = last_mail()
        wrong = [tpost(TA + "verify", {"email": "petrov@example.ru", "code": f"{(int(code2) + i) % 10 ** 6:06d}"})[0] for i in range(1, 6)]
        c11, d11, _ = tpost(TA + "verify", {"email": "petrov@example.ru", "code": code2})
        c12, d12, _ = tpost(TA + "resend", {"email": "petrov@example.ru"})
        check("5.0: подбор кода невозможен — после 5 ошибок даже верный код не принимается, нужен новый (не чаще раза в минуту)",
              wrong == [400] * 5 and c11 == 429 and d11.get("expired") and c12 == 429, f"{wrong} {c11} {c12} {d12}")
        # тренер в панели: только протокол (переадресация в закрытую часть), остальное закрыто
        pc1, _, ph1 = pub("GET", "/", cookie=TCK, port=p_web)
        pc2, _, _ = pub("GET", "/api/events", cookie=TCK, port=p_web)
        pc3, _, _ = pub("GET", "/api/trainers", cookie=TCK, port=p_web)
        pc4, _, _ = tpost("/api/me/password", {"old": "coach-pass-1", "new": "x" * 9}, cookie=TCK, port=p_web)
        pc5, _, ph5 = pub("GET", "/protocol?event=1", port=p_web)
        pc6, _, _ = pub("GET", "/judge", cookie=TCK, port=p_web)
        check("5.0: тренеру в панели закрыто всё, кроме протоколов: админка, API соревнований, тренеры, смена пароля судьи, экран судьи",
              pc1 == 302 and ph1.get("Location") == "/r/trainer" and pc2 == 403 and pc3 == 403 and pc4 == 403 and pc6 == 302,
              f"{pc1} {ph1.get('Location')} {pc2} {pc3} {pc4} {pc6}")
        check("5.0: гость на /protocol панели уходит на вход тренера", pc5 == 302 and ph5.get("Location", "").startswith("/r/trainer?next="),
              f"{pc5} {ph5.get('Location')}")
        # администратор: список, блокировка, ручное подтверждение
        _, txt = http("GET", "/api/trainers")
        tl = {t["email"]: t for t in json.loads(txt)["trainers"]}
        code, _ = http("POST", f"/api/trainers/{tl['coach@example.ru']['id']}/block", b"{}", J)
        cb, _, _ = pub("GET", TA + "me", cookie=TCK)
        cb2, db2, _ = tpost(TA + "login", {"email": "coach@example.ru", "password": "coach-pass-1"})
        http("POST", f"/api/trainers/{tl['coach@example.ru']['id']}/unblock", b"{}", J)
        code_v, _ = http("POST", f"/api/trainers/{tl['petrov@example.ru']['id']}/verify", b"{}", J)
        cv, _, _ = tpost(TA + "login", {"email": "petrov@example.ru", "password": "petrov-pass-1"})
        _, ltxt = http("GET", "/api/log")
        check("5.0: администратор видит тренеров; блокировка сразу закрывает сеанс и вход; ручное подтверждение открывает вход; всё в журнале",
              tl["coach@example.ru"]["is_verified"] == 1 and tl["petrov@example.ru"]["is_verified"] == 0 and "password_hash" not in tl["coach@example.ru"]
              and code == 200 and cb == 401 and cb2 == 403 and code_v == 200 and cv == 200
              and "Тренер: заблокирован" in ltxt and "Тренер: почта подтверждена вручную" in ltxt, f"{code} {cb} {cb2} {code_v} {cv}")
        c13, d13, h13 = tpost(TA + "login", {"email": "coach@example.ru", "password": "coach-pass-1"})
        TCK = (h13.get("Set-Cookie") or "").split(";")[0]

        code, txt, hd = pub("GET", f"/r/{slug}")
        check("форма открывается без пароля, с защитными заголовками",
              code == 200 and "Отправить заявку" in txt and "frame-ancestors" in hd.get("Content-Security-Policy", ""), str(code))
        for bad in ("/api/events", "/judge", "/", f"/api/events/{e4}/regs", "/r/../api/events", "/files/1"):
            code, _, _ = pub("GET", bad)
            check(f"публичный порт не отдаёт {bad}", code == 404, str(code))
        # стадион: результаты вписывает секретарь; публикация на сайте fla65.ru
        es_id = seed("Стадион 60 м", [(11, "Иванов Иван", 2008, "М", "СШОР", "Б/р", ["60 м"]),
                                      (12, "Петров Пётр", 2008, "М", "СШОР", "Б/р", ["60 м"]),
                                      (13, "Сидоров Сидор", 2008, "М", "СШОР", "Б/р", ["60 м"])],
                     ["60 м"], pub_site=True)
        es = json.loads(http("GET", f"/api/events/{es_id}")[1])
        check("стадион: событие создано с форматом и ручным хронометражем",
              es.get("kind") == "stadium" and es.get("timing") == "manual" and es.get("pub_site") and es.get("reg_slug"), str(es)[:200])
        code, txt = http("POST", f"/api/events/{es['id']}/results", json.dumps({"rows": [
            {"bib": "11", "result": "8,15"}, {"bib": "12", "result": "7.94"}, {"bib": "13", "status": "dnf"},
            {"bib": "99", "result": "9"}, {"bib": "11x", "result": "abc"}]}).encode(), J)
        rr = json.loads(txt)
        check("стадион: результаты сохранены, ошибки названы строками «номер: текст»",
              rr["saved"] == 3 and len(rr["errors"]) == 2 and all(isinstance(x, str) and ":" in x for x in rr["errors"])
              and any(x.startswith("99:") for x in rr["errors"]), txt[:300])
        _, txt = http("GET", f"/api/events/{es['id']}/results")
        rs = json.loads(txt)
        check("стадион: места по введённым результатам, DNF отдельно",
              [(x["bib"], x["place"], x["result"]) for x in rs["finished"]] == [("12", 1, "7.94"), ("11", 2, "8.15")]
              and any(x["bib"] == "13" and x.get("status") == "DNF" for x in rs["not_seen"]), txt[:300])
        # командный зачёт: результаты вписаны секретарём, очки — по месту (20, 17, 15, 14 …)
        ek_id = seed("Кросс школьников", [
            (1, "Аа Ая", 2017, "Ж", "Школа 1", "Б/р", ["500 м"]), (2, "Бб Бя", 2017, "Ж", "Школа 2", "Б/р", ["500 м"]),
            (3, "Вв Вя", 2017, "Ж", "Школа 1", "Б/р", ["500 м"]), (4, "Гг Гя", 2018, "Ж", "Школа 1", "Б/р", ["500 м"]),
            (5, "Дд Дя", 2017, "Ж", "Школа 2", "Б/р", ["500 м"]), (6, "Ее Ея", 2017, "М", "Школа 2", "Б/р", ["500 м"]),
            (7, "Жж Жя", 2017, "М", "Школа 1", "Б/р", ["500 м"]), (8, "Зз Зя", 2017, "М", "Школа 1", "Б/р", ["500 м"])],
            ["500 м"], rules="Девочки 2017-2018 г.р.;Ж;2017;2018\nМальчики 2017-2018 г.р.;М;2017;2018", team_best=2)
        ek = {"id": ek_id}
        code, txt = http("POST", f"/api/events/{ek['id']}/results", json.dumps({"rows": [
            {"bib": "1", "result": "1:50,5"}, {"bib": "2", "result": "1:51,5"}, {"bib": "3", "result": "1:52,2"},
            {"bib": "4", "result": "1:53,0"}, {"bib": "5", "status": "dnf"}, {"bib": "6", "result": "1:41,03"},
            {"bib": "7", "result": "1:41,06"}, {"bib": "8", "result": "мимо"}]}).encode(), J)
        check("командный зачёт: 7 результатов принято, строка с ошибкой в результате названа",
              code == 200 and json.loads(txt)["saved"] == 7 and len(json.loads(txt)["errors"]) == 1
              and json.loads(txt)["errors"][0].startswith("8:"), txt)
        _, txt = http("GET", f"/api/events/{ek['id']}/results")
        rk = json.loads(txt)
        fin = {x["bib"]: x for x in rk["finished"]}
        check("протокол: места, результаты, очки по месту, дистанция, DNF",
              fin["1"]["place_overall"] == 1 and fin["4"]["place_overall"] == 4 and fin["6"]["result"] == "1:41.03"
              and fin["2"]["points"] == 17 and fin["1"]["distance"] == "500 м"
              and any(x["bib"] == "5" and x.get("status") == "DNF" for x in rk["not_seen"]), txt[:400])
        tk = rk.get("teams") or [{}]
        rows_k = {r["team"]: r for r in tk[0].get("rows", [])}
        check("командный зачёт: 2 лучших в категории, мальчики и девочки одной таблицей, места",
              tk[0].get("group") == "2017-2018 г.р." and tk[0].get("columns") == ["Мальчики", "Девочки"]
              and rows_k["Школа 1"]["by"] == {"Девочки": 35, "Мальчики": 17} and rows_k["Школа 1"]["total"] == 52
              and rows_k["Школа 1"]["place"] == 1 and rows_k["Школа 2"]["total"] == 37, str(tk)[:400])
        code, txt, hd = pub("GET", "/r/api/calendar")
        cal = json.loads(txt)
        card = next((c for c in cal["events"] if c["name"] == "Стадион 60 м"), None)
        check("календарь для fla65.ru: событие видно, CORS открыт, страница есть",
              card and card["page"] and hd.get("Access-Control-Allow-Origin") == "*" and card["results"] is None, txt[:300])
        sslug = es["reg_slug"]
        code, _, _ = pub("GET", f"/r/{sslug}/results.json", cookie=TCK)
        check("результаты не опубликованы — на сайте не видны", code == 404, str(code))
        http("POST", f"/api/events/{es['id']}", json.dumps({"pub_results": True, "live_url": "https://vk.com/video1",
             "links": "Итоги | https://fla65.ru/news/1\nПлохая | javascript:alert(1)"}).encode(), J)
        code, txt, _ = pub("GET", f"/r/{sslug}/results.json", cookie=TCK)
        check("результаты опубликованы — тренеру без чипов, с результатом", code == 200 and '"chip"' not in txt and "Петров" in txt
              and any(x.get("result") == "7.94" for x in json.loads(txt)["finished"]), txt[:300])
        g1, gt1, _ = pub("GET", f"/r/{sslug}/results.json")
        g2, _, _ = pub("GET", f"/r/{sslug}/startlist.json")
        g3, _, gh3 = pub("GET", f"/r/{sslug}/protocol?kind=start")
        _, ad5, adh5 = tpost("/api/login", {"login": "admin", "password": "test-pass"}, port=p_web)
        ack5 = (adh5.get("Set-Cookie") or "").split(";")[0]
        g4, _, _ = pub("GET", f"/r/{sslug}/results.json", cookie=ack5)
        g5, gt5, _ = pub("GET", f"/r/{sslug}/protocol", cookie=TCK)
        check("5.0: гостю протоколы закрыты — JSON 401, страница протокола уводит на вход тренера и обратно; судье и тренеру открыты",
              g1 == 401 and "Петров" not in gt1 and g2 == 401 and g3 == 302
              and gh3.get("Location") == "/r/trainer?next=" + urllib.parse.quote(f"/r/{sslug}/protocol?kind=start", safe="")
              and g4 == 200 and g5 == 200 and "protocol" in gt5.lower(), f"{g1} {g2} {g3} {gh3.get('Location')} {g4} {g5}")
        _, tev, _ = pub("GET", "/r/api/trainer/events", cookie=TCK)
        tevs = json.loads(tev).get("events", [])
        g6, _, _ = pub("GET", "/r/api/trainer/events")
        pc7, _, ph7 = pub("GET", f"/protocol?event={es['id']}", cookie=TCK, port=p_web)
        check("5.0: в кабинете — выложенные протоколы со ссылкой на закрытую страницу; гостю список закрыт; /protocol панели ведёт тренера туда же",
              any(e["protocol"] == f"/r/{sslug}/protocol" and e["results"] for e in tevs) and g6 == 401
              and pc7 == 302 and ph7.get("Location") == f"/r/{sslug}/protocol", f"{tevs} {g6} {pc7} {ph7.get('Location')}")
        pg, pgt, _ = pub("GET", "/r/trainer")
        check("5.0: страница «Вход для тренеров» открывается без входа", pg == 200 and "trainerPage" in pgt and "Личный кабинет" in pgt, str(pg))
        code, txt, _ = pub("GET", f"/r/{sslug}/info")
        cd = json.loads(txt).get("card", {})
        check("страница события: ссылки только http(s), трансляция, протокол",
              cd.get("live") == "https://vk.com/video1" and [l["url"] for l in cd.get("links", [])] == ["https://fla65.ru/news/1"]
              and cd.get("results", "").endswith(f"/r/{sslug}/protocol"), str(cd)[:300])
        code, txt = http("POST", f"/api/events/{es['id']}", json.dumps({"photo_url": "javascript:alert(1)"}).encode(), J)
        check("ссылка не https — отклонена", code == 400, str(code))
        code, txt = http("POST", "/api/events", json.dumps({"name": "Первенство по кроссу", "date": "2026-09-20", "pub_site": True}).encode(), J)
        code, txt = http("POST", "/api/events", json.dumps({"name": "Кубок области", "date": "2026-06-12", "pub_site": True}).encode(), J)
        code, txt = http("POST", "/api/events", json.dumps({"name": "Первенство области", "date": "2026-12-04", "pub_site": True}).encode(), J)
        code, txt, _ = pub("GET", "/r/api/calendar")
        vmap = {c["name"]: c.get("venue") or {} for c in json.loads(txt)["events"]}
        check("площадка по сезону: кросс — «Триумф», лето — «Спартак», зима — манеж, со ссылкой на карту",
              vmap["Первенство по кроссу"].get("name") == "ЛБК «Триумф»" and vmap["Кубок области"].get("name") == "Стадион «Спартак»"
              and vmap["Первенство области"].get("address") == "Южно-Сахалинск, ул. Горького, 39"
              and vmap["Кубок области"].get("map", "").startswith("https://yandex.ru/maps/"), str(vmap)[:400])
        code, txt, hd = pub("GET", "/r/assets/calendar.js")
        check("виджет календаря для fla65.ru отдаётся с CORS", code == 200 and hd.get("Access-Control-Allow-Origin") == "*", str(code))
        code, txt, hd = pub("GET", "/r/assets/sakhstart-dark.svg")
        check("логотип для формы регистрации отдаётся через /r/assets", code == 200 and "<svg" in txt and "image/svg" in hd.get("Content-Type", ""), str(code))
        for bad in ("/r/assets/hub.py", "/r/assets/..%2F..%2Fhub.py"):
            code, _, _ = pub("GET", bad)
            check(f"публичный /r/assets не отдаёт {bad}", code == 404, str(code))
        tomorrow = (dt.datetime.now() + dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        http("POST", f"/api/events/{e4}", json.dumps({"reg_deadline": tomorrow}).encode(), J)
        code, txt, _ = pub("GET", f"/r/{slug}/info")
        check("срок приёма в будущем — форма открыта", code == 200 and json.loads(txt)["open"] is True, txt[:200])
        yesterday = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        http("POST", f"/api/events/{e4}", json.dumps({"reg_deadline": yesterday}).encode(), J)
        code, txt, _ = pub("GET", f"/r/{slug}/info")
        check("срок приёма прошёл — «Приём заявок окончен»", code == 200 and json.loads(txt)["reason"] == "Приём заявок окончен", txt[:200])
        http("POST", f"/api/events/{e4}", json.dumps({"reg_deadline": None}).encode(), J)
        code, txt, _ = pub("GET", f"/r/{slug}/info")
        info = json.loads(txt)
        check("форма: дистанции и текст согласия", info["distances"] == ["60 м", "300 м"] and "согласие" in info["consent"], txt[:200])

        def reg(last, first, bd, sex, dists, **kw):
            body = {"last_name": last, "first_name": first, "birth_date": bd, "sex": sex, "team": "СШОР",
                    "consent": True, "policy": True, "representative": "Родитель", "distances": dists, "rank": "1р", **kw}
            c, t, _ = pub("POST", f"/r/{slug}", json.dumps(body).encode())
            return c, json.loads(t)

        runners = [("Быстров", "Иван", "7.5"), ("Скоров", "Пётр", "7.9"), ("Ветров", "Олег", "8.4"),
                   ("Лётов", "Илья", ""), ("Ходов", "Глеб", "8.1"), ("Шагов", "Лев", "7.7")]
        for i, (ln, fn, best) in enumerate(runners):
            code, out = reg(ln, fn, f"2010-0{i + 1}-15", "М", [{"distance": "60 м", "best": best}])
        check("заявка принята, категория определена по году и полу", code == 201 and out["category"] == "Юноши", str(out))
        # 5.1: согласие отдельно от Политики; архив редакций согласий; обезличивание заявок по сроку
        body_np = {"last_name": "Безполитики", "first_name": "Иван", "birth_date": "2010-05-05", "sex": "М", "team": "СШОР",
                   "consent": True, "representative": "Родитель", "distances": [{"distance": "60 м"}], "rank": "1р"}
        cnp, tnp, _ = pub("POST", f"/r/{slug}", json.dumps(body_np).encode())
        check("5.1: без отдельной отметки об ознакомлении с Политикой заявка не принимается, согласие — отдельно",
              cnp == 400 and "policy" in json.loads(tnp).get("fields", {}) and "consent" not in json.loads(tnp).get("fields", {}), tnp[:200])
        _, ctx = http("GET", "/api/consents")
        cons = json.loads(ctx)
        cpart = [c for c in cons["consents"] if c["kind"].startswith("Участник")]
        ctr = [c for c in cons["consents"] if c["kind"].startswith("Тренер")]
        dbq = _sql.connect(cfg["db_path"])
        ph = dbq.execute("SELECT consent_hash, policy_hash FROM registrations WHERE last_name = 'Быстров'").fetchone()
        dbq.close()
        cp_b = next((c for c in cpart if ph and c["hash"] == ph[0]), None)       # редакция, под которую подали заявку Быстрова
        check("5.1: тексты согласий хранятся по редакциям (участник, тренер) с числом согласий; у заявки — отпечатки согласия и Политики",
              cpart and cp_b and cp_b["used"] >= 6 and "табло" in cp_b["text"] and "ИНН 6501159635" in cp_b["text"]
              and ctr and ctr[0]["used"] >= 1 and ph and ph[0] == cp_b["hash"] and ph[1] == cons["policy_hash"]
              and cons["retention_days"] == 180, str([(c["kind"], c["used"]) for c in cons["consents"]])[:300])
        ca, cta, _ = pub("GET", "/r/api/auth/trainer/consent")
        check("5.1: текст согласия тренера отдаётся форме отдельно от Политики", ca == 200 and "личного кабинета тренера" in json.loads(cta)["text"], cta[:200])
        code, txt = http("POST", "/api/events", json.dumps({"name": "Старое первенство", "date": "2020-01-10", "kind": "stadium",
                                                             "timing": "manual", "finish_device": "JUDGE"}).encode(), J)
        eo = json.loads(txt)["id"]
        _, txt = http("POST", f"/api/events/{eo}", json.dumps({"reg_open": True, "reg_distances": "60 м"}).encode(), J)
        so = json.loads(txt)["reg_path"].rsplit("/", 1)[-1]
        pub("POST", f"/r/{so}", json.dumps({"last_name": "Давнишний", "first_name": "Пётр", "birth_date": "2012-07-15", "sex": "М",
                                            "team": "СШОР", "consent": True, "policy": True, "representative": "Давнишняя Анна",
                                            "contact": "+7 900 000-00-00", "distances": [{"distance": "60 м"}], "rank": "Б/р"}).encode())
        code, txt = http("POST", "/api/system/retention", b"{}", J)
        ro = json.loads(txt)
        dbq = _sql.connect(cfg["db_path"])
        an = dbq.execute("SELECT birth_date, contact, representative, anonymized_at FROM registrations WHERE last_name = 'Давнишний'").fetchone()
        fresh = dbq.execute("SELECT contact, anonymized_at FROM registrations WHERE last_name = 'Быстров'").fetchone()
        dbq.close()
        check("5.1: заявки прошедших соревнований обезличиваются по сроку: без контактов и представителя, от даты рождения — год; свежие не трогаются",
              code == 200 and ro.get("applications", 0) >= 1 and an and an[0] == "2012-01-01" and an[1] is None and an[2] is None and an[3]
              and fresh and fresh[1] is None, f"{ro} {an} {fresh}")
        code, out = reg("Бегова", "Анна", "2011-03-03", "Ж", [{"distance": "60 м", "best": "8,6"}, {"distance": "300 м", "best": "49.0"}])
        check("одна заявка на две дистанции", code == 201 and len(out["ids"]) == 2 and out["category"] == "Девушки", str(out))
        code, out = reg("Быстров", "Иван", "2010-01-15", "М", ["60 м"])
        check("повторная заявка на ту же дистанцию отклонена", code == 409, str(out))
        code, out = reg("Малов", "Миша", "2011-02-02", "М", ["60 м"], representative="")
        check("до 18 лет без представителя — ошибка поля", code == 400 and "representative" in out.get("fields", {}), str(out))
        code, out = reg("Без", "Согласия", "2000-02-02", "М", ["60 м"], consent=False)
        check("без согласия на обработку ПДн — ошибка", code == 400 and "consent" in out.get("fields", {}), str(out))
        code, out = reg("Чужая", "Дистанция", "2000-02-02", "М", ["42 км"])
        check("дистанция не из списка — ошибка", code == 400 and "distances" in out.get("fields", {}), str(out))
        code, out = reg("Бот", "Бот", "2000-02-02", "М", ["60 м"], website="http://spam")
        _, txt = http("GET", f"/api/events/{e4}/regs")
        rv = json.loads(txt)
        check("ловушка для ботов: заявка не сохранена", rv["counts"]["pending"] == 8 and all(r["last_name"] != "Бот" for r in rv["regs"]),
              str(rv["counts"]))
        code, txt, _ = pub("POST", f"/r/{slug}", b"name=1", "application/x-www-form-urlencoded")
        check("форма принимает только JSON", code == 415, str(code))
        # секретарь: одну отклоняет, остальные подтверждает, формирует забеги на 4 дорожки
        rid_bad = [r["id"] for r in rv["regs"] if r["last_name"] == "Ходов"][0]
        http("POST", f"/api/events/{e4}/regs/{rid_bad}", json.dumps({"status": "rejected"}).encode(), J)
        code, txt = http("POST", f"/api/events/{e4}/regs", json.dumps({"approve_all": True}).encode(), J)
        check("подтверждение заявок", json.loads(txt)["counts"] == {"pending": 0, "approved": 7, "rejected": 1}, txt[-200:])
        # 5.2: номера только вручную — без них сетка не строится; сетка всегда по одной дисциплине
        D60, D300 = "60 м", "300 м"
        code, txt = http("POST", f"/api/events/{e4}/heats", json.dumps({"lanes": 4}).encode(), J)
        codeh, txth = http("POST", f"/api/events/{e4}/heats", json.dumps({"lanes": 4, "mode": "list"}).encode(), J)
        check("7.0: сетка без дисциплины не формируется — 400 «выберите дисциплину» (и с mode=list тоже)",
              code == 400 and "выберите дисциплину" in txt and codeh == 400 and "выберите дисциплину" in txth, f"{code} {txt} {codeh} {txth}")
        code, txt = http("POST", f"/api/events/{e4}/heats", json.dumps({"distance": D60, "lanes": 4}).encode(), J)
        _, txt_sl = http("GET", f"/api/events/{e4}/startlist")
        check("5.2: без вписанных вручную номеров забеги не формируются, автоматической выдачи номеров нет",
              code == 400 and "нет нагрудных номеров у 6 участников" in txt and not json.loads(txt_sl)["heats"]
              and not json.loads(txt_sl)["no_heat"], txt[:200])
        bv = json.loads(http("GET", f"/api/events/{e4}/bibs?distance=" + urllib.parse.quote(D60) + "&sex=" + urllib.parse.quote("М"))[1])
        check("5.2: шаг 2 видит подтверждённых участников дисциплины по фильтру, номеров ещё нет",
              bv["total"] == 5 and bv["with_bib"] == 0 and all(not r["bib"] and r["ids"] for r in bv["rows"]), str(bv)[:300])
        ids5 = [r["ids"] for r in bv["rows"]]
        cd1, td1 = http("POST", f"/api/events/{e4}/bibs", json.dumps({"rows": [{"ids": ids5[0], "bib": "7"}, {"ids": ids5[1], "bib": "7"}]}).encode(), J)
        cd2, td2 = http("POST", f"/api/events/{e4}/bibs", json.dumps({"rows": [{"ids": ids5[0], "bib": "с пробелом"}]}).encode(), J)
        bv2 = json.loads(http("GET", f"/api/events/{e4}/bibs")[1])
        check("5.2: повтор номера и неверный номер отклоняются целиком — в базу ничего не записано",
              cd1 == 400 and "уже у другого участника" in td1 and json.loads(td1).get("errors") and cd2 == 400 and bv2["with_bib"] == 0,
              f"{cd1} {td1[:150]} {cd2}")
        nb4 = give_bibs(e4, 1)
        bv3 = json.loads(http("GET", f"/api/events/{e4}/bibs")[1])
        bg = [r for r in bv3["rows"] if r["name"].startswith("Бегова")]
        check("5.2: секретарь вписал номера 1–6 (по одному на человека) и нажал «Сохранить нагрудные номера»; "
              "у Береговой один номер на 60 м и 300 м", nb4 == 6 and bv3["with_bib"] == 7 and len(bg) == 2 and bg[0]["bib"] == bg[1]["bib"],
              str(bv3)[:300])
        code, txt = http("POST", f"/api/events/{e4}/heats", json.dumps({"distance": D60, "lanes": 4}).encode(), J)
        hs = json.loads(txt)
        code_, txt_ = http("POST", f"/api/events/{e4}/heats", json.dumps({"distance": D300, "lanes": 4}).encode(), J)
        hs3 = json.loads(txt_)
        check("забеги сформированы по дисциплинам: 60 м Юноши ×2, 60 м Девушки, 300 м Девушки",
              code == 200 and code_ == 200 and [(h["distance"], h["category"], h["count"]) for h in hs["heats"] + hs3["heats"]] ==
              [("60 м", "Юноши", 2), ("60 м", "Юноши", 3), ("60 м", "Девушки", 1), ("300 м", "Девушки", 1)], txt + txt_)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        sl = json.loads(txt)
        h2 = {e["name"].split()[0]: e["lane"] for e in sl["heats"][1]["entries"]}
        h1 = [e["name"].split()[0] for e in sl["heats"][0]["entries"]]
        check("посев: сильнейшие в последнем забеге, лучший — на центральной дорожке",
              h2 == {"Быстров": 2, "Шагов": 3, "Скоров": 1} and sorted(h1) == ["Ветров", "Лётов"], f"{h1} {h2}")
        bibs = sorted(int(e["bib"]) for h in sl["heats"] for e in h["entries"])
        check("5.2: в сетке — ровно те номера, что вписал секретарь (у Береговой один и тот же номер в двух дисциплинах)",
              len(bibs) == 7 and set(bibs) == set(range(1, 7)) and len(bibs) - len(set(bibs)) == 1, str(bibs))
        code, txt = http("POST", f"/api/events/{e4}/entry", json.dumps({"bib": [e["bib"] for e in sl["heats"][0]["entries"]
                         if e["name"].startswith("Лётов")][0], "wave": "Забег 2"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        sl = json.loads(txt)
        check("перенос участника в другой забег", len(sl["heats"][1]["entries"]) == 4 and len(sl["heats"][0]["entries"]) == 1
              and sorted(e["lane"] for e in sl["heats"][1]["entries"]) == [1, 2, 3, 4], str(sl["heats"][1]["entries"])[:300])
        # полный сброс сетки забегов
        code, txt = http("POST", f"/api/events/{e4}/resetheats", b"{}", J)
        rs = json.loads(txt)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        sl0 = json.loads(txt)
        check("сброс сетки: забегов нет, все 7 строк участников нераспределены без дорожек; стартовавших не было",
              code == 200 and rs["waves"] == 4 and rs["entries"] == 7 and rs["stopped"] == [] and not sl0["heats"]
              and len(sl0["no_heat"]) == 7 and all(e["wave"] is None and e["lane"] is None for e in sl0["no_heat"]), txt[:300])
        check("сброс сетки: номера сохранены", sorted({int(e["bib"]) for e in sl0["no_heat"]}) == list(range(1, 7)))
        http("POST", f"/api/events/{e4}/heats", json.dumps({"distance": D60, "lanes": 4}).encode(), J)
        http("POST", f"/api/events/{e4}/heats", json.dumps({"distance": D300, "lanes": 4}).encode(), J)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        sl = json.loads(txt)
        check("3.4: у участника в списке своя дисциплина, тип результата и число попыток (для бланка техники); поля chip нет",
              all({"id", "distance", "rtype", "slots"} <= set(e) and "chip" not in e for h in sl["heats"] for e in h["entries"])
              and all(e["rtype"] == "time" and e["slots"] == 0 for h in sl["heats"] for e in h["entries"] if e["distance"]), txt[:300])
        b1 = sl["heats"][0]["entries"][0]["bib"]; b2 = sl["heats"][0]["entries"][1]["bib"]
        code, txt = http("POST", f"/api/events/{e4}/entry", json.dumps({"bib": b1, "new_bib": "501"}).encode(), J)
        code2, txt2 = http("POST", f"/api/events/{e4}/entry", json.dumps({"bib": b2, "new_bib": "501"}).encode(), J)
        code3, _ = http("POST", f"/api/events/{e4}/entry", json.dumps({"bib": b2, "new_bib": "с пробелом"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        bb = {e["bib"]: e for e in json.loads(txt)["heats"][0]["entries"]}
        _, rt = http("GET", f"/api/events/{e4}/regs")
        check("секретарь вручную меняет нагрудный номер; занятый и неверный номера отклоняются",
              code == 200 and "501" in bb and b1 not in bb and code2 == 400 and "уже" in txt2 and code3 == 400
              and '"bib": "501"' in rt.replace('"bib":"501"', '"bib": "501"'), f"{code} {txt2[:200]}")
        http("POST", f"/api/events/{e4}/entry", json.dumps({"bib": "501", "new_bib": b1}).encode(), J)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        sl = json.loads(txt)
        # поздняя заявка после формирования забегов — добавляется вручную
        code, out = reg("Поздняков", "Яков", "2010-09-09", "М", [{"distance": "60 м", "best": "8.0"}])
        late = out["ids"][0]
        http("POST", f"/api/events/{e4}/regs/{late}", json.dumps({"status": "approved"}).encode(), J)
        cl0, tl0 = http("POST", f"/api/events/{e4}/entry", json.dumps({"reg_id": late, "wave": "Забег 1"}).encode(), J)
        code, txt = http("POST", f"/api/events/{e4}/entry", json.dumps({"reg_id": late, "wave": "Забег 1", "set_bib": "8"}).encode(), J)
        check("5.2: поздняя заявка без номера в забег не встаёт; с номером, вписанным вручную, — добавлена",
              cl0 == 400 and "нагрудный номер" in tl0 and code == 200 and json.loads(txt)["bib"] == "8", f"{tl0[:120]} {txt}")
        # судья ведёт забег по стартовому списку — протокол с ФИО и тренером
        b_fast = [e["bib"] for e in sl["heats"][1]["entries"] if e["name"].startswith("Быстров")][0]
        base = int(time.time() * 1000) - 60000
        http("POST", f"/api/events/{e4}/start", json.dumps({"wave": "Забег 2", "epoch_ms": base}).encode(), J)
        http("POST", f"/api/events/{e4}/manual", json.dumps({"bib": b_fast, "epoch_ms": base + 7420, "wave": "Забег 2",
                     "client_id": "r1"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e4}/results")
        fr = json.loads(txt)["finished"]
        check("результат участника из регистрации: ФИО, категория, 7.5",
              fr and fr[0]["name"] == "Быстров Иван" and fr[0]["category"] == "Юноши" and fr[0]["result"] == "7.5", str(fr)[:300])
        code, txt = http("POST", f"/api/events/{e4}/heats", json.dumps({"distance": D60, "lanes": 4}).encode(), J)
        check("после старта пересобрать забеги без сброса нельзя — «стоит время старта — нажмите «Сбросить сетку»»",
              code == 400 and "стоит время старта" in txt and "Сбросить сетку" in txt, txt)
        code, txt = http("GET", f"/api/events/{e4}/regs.csv")
        check("выгрузка заявок CSV", code == 200 and "Быстров" in txt and "Представитель" in txt, txt[:100])
        # командная заявка: шаблон Excel → заполненный файл → проверка → отправка
        import importlib.util
        import zipfile
        spec = importlib.util.spec_from_file_location("hubmod", hub_path)
        hubmod = importlib.util.module_from_spec(spec)
        sys.modules["hubmod"] = hubmod
        spec.loader.exec_module(hubmod)
        req = urllib.request.Request(f"http://127.0.0.1:{p_pub}/r/{slug}/template.xlsx")
        with urllib.request.urlopen(req, timeout=5) as resp:
            tpl, tctype = resp.read(), resp.headers.get("Content-Type", "")
        check("шаблон Excel скачивается с формы", "spreadsheetml" in tctype and tpl[:2] == b"PK", tctype)
        tab = hubmod.xlsx_read(tpl)
        check("шаблон: заголовки и список дистанций", "Фамилия*" in tab[2] and "Дистанция*" in tab[2]
              and b"300" in zipfile.ZipFile(io.BytesIO(tpl)).read("xl/worksheets/sheet2.xml"), str(tab[:3]))
        head = tab[2]
        filled = [["Заявка"], ["подсказка"], head,
                  ["Командов", "Пётр", "", 40365, "м", "60м", "8,1", "", "", "", "кмс"],
                  ["Командова", "Анна", "", "03.03.2011", "Ж", "300 м", "52.4", "", "", "", "б/р"],
                  ["Ошибкин", "", "", "31.02.2011", "X", "42 км", "", "", "", ""]]
        xb = hubmod.xlsx_build([("Заявка", filled)], header_row=3, title_row=1)

        def pub_raw(path, data, headers):
            r = urllib.request.Request(f"http://127.0.0.1:{p_pub}{path}", data=data, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        code, ck = pub_raw(f"/r/{slug}/team-check", xb, {"Content-Type": "application/octet-stream",
                                                          "X-Team": urllib.parse.quote("Корсаков")})
        badrow = [x for x in ck.get("rows", []) if x["errors"]]
        check("проверка файла команды: 2 строки готовы, 1 с ошибками",
              code == 200 and ck["ok"] == 2 and ck["bad"] == 1 and set(badrow[0]["errors"]) >= {"first_name", "birth_date", "sex", "distances"},
              json.dumps(ck, ensure_ascii=False)[:400])
        good = [x for x in ck["rows"] if not x["errors"]]
        check("Excel-дата, «м», «60м», «8,1» распознаны", good[0]["birth_date"] == "2010-07-06" and good[0]["sex"] == "М"
              and good[0]["distance"] == "60 м" and good[0]["best"] == "8,1", str(good[0]))
        rows = [dict(x["raw"], _row=x["row"]) for x in ck["rows"]]
        code, out = pub_raw(f"/r/{slug}/team", json.dumps({"team": "Корсаков", "coach": "Тренеров Т.Т.", "contact": "8-900",
                            "consent": True, "policy": True, "rows": rows}).encode(), {"Content-Type": "application/json"})
        check("команда с ошибками в файле не принимается", code == 400 and out.get("check", {}).get("bad") == 1, str(out)[:200])
        code, out = pub_raw(f"/r/{slug}/team", json.dumps({"team": "Корсаков", "coach": "", "contact": "", "consent": False,
                            "rows": rows[:2]}).encode(), {"Content-Type": "application/json"})
        check("без тренера, контакта, согласия и отметки о Политике — ошибка", code == 400
              and set(out.get("fields", {})) == {"coach", "contact", "consent", "policy"}, str(out))
        code, out = pub_raw(f"/r/{slug}/team", json.dumps({"team": "Корсаков", "coach": "Тренеров Т.Т.", "contact": "8-900",
                            "consent": True, "policy": True, "rows": rows[:2]}).encode(), {"Content-Type": "application/json"})
        check("командная заявка принята: 2 участника", code == 201 and out["added"] == 2, str(out))
        code, out = pub_raw(f"/r/{slug}/team", json.dumps({"team": "Корсаков", "coach": "Тренеров Т.Т.", "contact": "8-900",
                            "consent": True, "policy": True, "rows": rows[:2]}).encode(), {"Content-Type": "application/json"})
        check("повторная отправка той же команды — повторы пропущены", code == 201 and out["added"] == 0 and len(out["duplicates"]) == 2, str(out))
        _, txt = http("GET", f"/api/events/{e4}/regs")
        kr = [r for r in json.loads(txt)["regs"] if r["team"] == "Корсаков"]
        check("3.2: разряд из файла команды нормализован («кмс» → КМС, «б/р» → Б/р)", sorted(r["rank"] for r in kr) == ["Б/р", "КМС"], str(kr)[:200])
        check("заявки команды: статус «на рассмотрении», тренер и категория", len(kr) == 2 and all(
            r["status"] == "pending" and r["coach"] == "Тренеров Т.Т." for r in kr) and {r["category"] for r in kr} == {"Юноши", "Девушки"},
              str(kr)[:300])
        # секретарь: импорт файла в админке — сразу подтверждено
        csvb = "Фамилия;Имя;Дата рождения;Пол;Дистанция;Лучший результат;Команда;Разряд\nИмпортов;Иван;01.01.2010;М;60 м;7,9;Анива;2 разряд\n".encode("cp1251")
        r = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e4}/import?team=", data=csvb, method="POST",
                                   headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode(),
                                            "X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(r, timeout=5) as resp:
            out = json.loads(resp.read())
        _, txt = http("GET", f"/api/events/{e4}/regs")
        imp = [x for x in json.loads(txt)["regs"] if x["last_name"] == "Импортов"]
        check("импорт CSV (windows-1251) секретарём — сразу подтверждено", out["added"] == 1 and imp and imp[0]["status"] == "approved", str(out))
        check("3.2: разряд «2 разряд» в импорте приведён к «2 р.»", imp and imp[0]["rank"] == "2 р.", str(imp)[:200])
        code, out = reg("Безразрядов", "Иван", "2010-09-09", "М", ["60 м"], rank="")
        check("3.2: без разряда заявка не принимается, ошибка у поля «rank»", code == 400 and "rank" in out.get("fields", {}), str(out))
        code, out = reg("Звёздов", "Иван", "2010-09-10", "М", ["60 м"], rank="мс")
        _, txt3 = http("GET", f"/api/events/{e4}/regs")
        zr = [x for x in json.loads(txt3)["regs"] if x["last_name"] == "Звёздов"]
        check("3.2: разряд «мс» записан как МС", code == 201 and zr and zr[0]["rank"] == "МС", str(out))
        rid_z = zr[0]["id"]
        code, txt3 = http("POST", f"/api/events/{e4}/regs/{rid_z}", json.dumps({"rank": "", "team": "Новая"}).encode(), J)
        check("3.2: карточку без разряда сохранить нельзя", code == 400 and "разряд" in txt3, txt3[:200])
        code, txt3 = http("POST", f"/api/events/{e4}/regs/{rid_z}", json.dumps({"rank": "1 р.", "team": "Новая"}).encode(), J)
        check("3.2: с разрядом карточка сохраняется", code == 200 and json.loads(txt3)["reg"]["rank"] == "1 р.", txt3[:200])
        r = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e4}/template.xlsx",
                                   headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode()})
        with urllib.request.urlopen(r, timeout=5) as resp:
            check("шаблон Excel в админке", resp.status == 200 and resp.read()[:2] == b"PK", str(resp.status))
        _, txt = http("GET", f"/api/events/{e4}/regs")
        dr = json.loads(txt)["default_rules"]
        check("образец категорий: до 12/14/16/18/20/23 и взрослые от года соревнований",
              "Мальчики до 12 лет;М;2015;" in dr and "Юноши до 16 лет;М;2011;2012" in dr and "Мужчины до 23 лет;М;2004;2006" in dr
              and "Женщины;Ж;;2003" in dr, dr)

        # обновление из браузера: папки update нет — вежливый отказ; есть — архив принят и проверен
        upd = os.path.join(tmp, "update")
        code, txt = http("POST", "/api/system/update", b"PK", {"X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        check("обновление: без службы обновлений — понятный отказ", code == 400 and "WinSCP" in txt, txt)
        os.makedirs(upd, exist_ok=True)
        code, txt = http("POST", "/api/system/update", b"not a zip", {"X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        check("обновление: не zip — отказ", code == 400, txt)
        zb = io.BytesIO()
        with zipfile.ZipFile(zb, "w") as zf:
            zf.writestr("timing-hub/install.sh", "echo ok")
            zf.writestr("timing-hub/hub/hub.py", 'VERSION = "9.9.9"')
        code, txt = http("POST", "/api/system/update", zb.getvalue(), {"X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        check("обновление: архив принят и ждёт подтверждения (установка не запущена)", code == 200 and json.loads(txt).get("to") == "9.9.9"
              and os.path.exists(os.path.join(upd, "ready.zip")) and not os.path.exists(os.path.join(upd, "incoming.zip")), txt)
        _, txt = http("GET", "/api/system/update")
        ust = json.loads(txt)
        check("обновление: статус для страницы — готово к установке, версия и дата сборки",
              ust.get("ready") is True and ust["ready_info"]["version"] == "9.9.9" and ust["build_date"] == "2026-10-14", txt[:300])
        code, txt = http("POST", "/api/system/update/install", b"{}", J)
        check("обновление: после подтверждения установка передана службе", code == 200 and os.path.exists(os.path.join(upd, "incoming.zip")), txt)
        code, txt = http("POST", "/api/system/update/install", b"{}", J)
        check("обновление: повторное подтверждение, пока идёт установка — отказ", code == 409, txt)
        os.remove(os.path.join(upd, "incoming.zip"))
        _, txt = http("GET", "/api/system/update")
        check("4.5: после запуска установки «готовый» архив не висит — страница не предлагает поставить его ещё раз",
              json.loads(txt)["ready"] is False and not os.path.exists(os.path.join(upd, "ready.zip")), txt[:200])
        zb2 = io.BytesIO()
        with zipfile.ZipFile(zb2, "w") as zf:
            zf.writestr("timing-hub/install.sh", "echo ok")
            zf.writestr("timing-hub/hub/hub.py", 'VERSION = "%s"' % ust["version"])
        http("POST", "/api/system/update", zb2.getvalue(), {"X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        _, txt = http("GET", "/api/system/update")
        check("4.5: архив той же (или старой) версии, что уже стоит, не показывается как «доступное обновление» и удаляется",
              json.loads(txt)["ready"] is False and not os.path.exists(os.path.join(upd, "ready.zip")), txt[:200])

        # файлы по папкам: стартовый список сам попал в «Для судей», загрузка в папку, перенос
        _, txt = http("GET", f"/api/events/{e4}/files?folder=" + urllib.parse.quote("Для судей"))
        fj = json.loads(txt)
        check("стартовый список сохранён в папку «Для судей»", len(fj["files"]) >= 1 and fj["files"][0]["name"].startswith("Стартовый список")
              and "Положение и документы" in fj["folders"], txt[:200])
        req = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e4}/files", data=b"%PDF-1.4 test", method="POST",
              headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode(), "X-Requested-With": "timing-hub",
                       "Content-Type": "application/octet-stream", "X-File-Name": urllib.parse.quote("Положение.pdf"),
                       "X-Folder": urllib.parse.quote("Положение и документы")})
        with urllib.request.urlopen(req, timeout=5) as resp:
            fid2 = json.loads(resp.read())["file"]["id"]
        code, _ = http("POST", f"/api/events/{e4}/files/{fid2}", json.dumps({"folder": "Для судей"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e4}/files?folder=" + urllib.parse.quote("Для судей"))
        check("файл загружен в папку и перенесён в «Для судей»", code == 200 and any(f["id"] == fid2 for f in json.loads(txt)["files"]), txt[:200])
        code, txt = http("GET", "/api/system")
        sy = json.loads(txt)
        check("вкладка «Оборудование»: сервер и кто подключён, без ридеров и Wiclax", code == 200 and sy["server"]["disk_total"] > 0
              and "readers" not in sy and "wiclax" not in sy and any(c["ip"] == "127.0.0.1" for c in sy["clients"]), txt[:300])

        http("POST", f"/api/events/{e4}", json.dumps({"reg_open": False}).encode(), J)
        code, out = reg("Опоздал", "Совсем", "2010-09-09", "М", ["60 м"])
        check("регистрация закрыта — заявки не принимаются", code == 403, str(out))

        # 2.8: лимит мест, диапазоны номеров, эстафета, выдача номеров, страница события, копия, серия
        code, txt = http("POST", "/api/events", json.dumps({"name": "Осенний забег 2026", "date": "2026-11-01",
                         "kind": "stadium", "timing": "manual", "finish_device": "JUDGE"}).encode(), J)
        e8 = json.loads(txt)["id"]
        code, txt = http("POST", f"/api/events/{e8}", json.dumps({
            "reg_open": True, "pub_site": True, "reg_rules": "Юноши;М;2008;2012\nДевушки;Ж;2008;2012",
            "reg_distances": "5 км | лимит 2 | номера с 1\n10 км | 3 | 500\n4×100 м | эстафета 4 | лимит 1",
            "cover": "https://example.ru/cover.jpg", "program": "18:30 | Выдача номеров\n19:00 Старт 5 км",
            "contacts": "Секретарь: +7 924 111-22-33\nfla65@mail.ru", "series": "Кубок проверки"}).encode(), J)
        s8 = json.loads(txt)["reg_path"].rsplit("/", 1)[-1]
        code, txt, _ = pub("GET", f"/r/{s8}/info")
        i8 = json.loads(txt)
        di = {d["name"]: d for d in i8["dist_info"]}
        check("2.8: дистанции с лимитом, диапазоном и эстафетой",
              i8["distances"] == ["5 км", "10 км"] and di["5 км"]["left"] == 2 and di["10 км"]["limit"] == 3
              and di["4×100 м"]["legs"] == 4, txt[:400])
        c8 = i8["card"]
        check("2.8: страница события — обложка, программа, контакты, серия, места",
              c8["cover"] == "https://example.ru/cover.jpg" and c8["program"][0] == {"time": "18:30", "title": "Выдача номеров"}
              and c8["program"][1]["time"] == "19:00" and c8["contacts"][0]["href"] == "tel:+79241112233"
              and c8["contacts"][1]["href"] == "mailto:fla65@mail.ru" and c8["series"]["name"] == "Кубок проверки"
              and {p["distance"]: p["left"] for p in c8["places"]} == {"5 км": 2, "10 км": 3, "4×100 м": 1}, str(c8)[:500])

        def reg8(last, bd, dist, sex="М"):
            c, t, _ = pub("POST", f"/r/{s8}", json.dumps({"last_name": last, "first_name": "Тест", "birth_date": bd, "sex": sex,
                          "team": "СШОР", "consent": True, "policy": True, "representative": "Родитель", "distances": [dist], "rank": "Б/р"}).encode())
            return c, json.loads(t)
        r1, r2 = reg8("Первый", "2010-01-01", "5 км"), reg8("Второй", "2010-02-02", "5 км")
        r3 = reg8("Третий", "2010-03-03", "5 км")
        check("2.8: лимит мест — третья заявка на 5 км отклонена",
              r1[0] == 201 and r2[0] == 201 and r3[0] == 400 and "мест больше нет" in r3[1]["fields"]["distances"], str(r3))
        code, txt, _ = pub("GET", f"/r/{s8}/info")
        check("2.8: «осталось мест» обновилось", {d["name"]: d["left"] for d in json.loads(txt)["dist_info"]}["5 км"] == 0, txt[:300])
        r4 = reg8("Длинный", "2009-04-04", "10 км")
        r5 = reg8("Эстафетный", "2009-05-05", "4×100 м")
        check("2.8: эстафету нельзя заявить как личную дистанцию",
              r4[0] == 201 and r5[0] == 400 and "эстафета" in r5[1]["fields"]["distances"], str(r5))
        legs = [{"last_name": f"Бегун{c}", "first_name": "Этап", "birth_date": f"2010-0{i + 1}-10", "sex": "М", "rank": "2 юн."}
                for i, c in enumerate("АБВГ")]
        relay = {"distance": "4×100 м", "team": "СШОР", "relay": "СШОР-1", "coach": "Тренеров", "contact": "+79240000000",
                 "consent": True, "policy": True, "members": legs}
        c, t, _ = pub("POST", f"/r/{s8}/relay", json.dumps({**relay, "members": legs[:3]}).encode())
        check("2.8: эстафета без участника на 4-м этапе — ошибка этапа", c == 400 and "4" in json.loads(t).get("members", {}), t[:300])
        c, t, _ = pub("POST", f"/r/{s8}/relay", json.dumps(relay).encode())
        check("2.8: заявка эстафеты принята", c == 201 and json.loads(t)["relay"] == "СШОР-1" and len(json.loads(t)["ids"]) == 4, t[:300])
        c, t, _ = pub("POST", f"/r/{s8}/relay", json.dumps({**relay, "relay": "СШОР-2", "members": [
            {**m, "last_name": m["last_name"] + "ов"} for m in legs]}).encode())
        check("2.8: лимит эстафеты — вторая команда не влезла", c == 409, t[:200])
        http("POST", f"/api/events/{e8}/regs", json.dumps({"approve_all": True}).encode(), J)
        # секретарь вписывает номера сам, по диапазонам дистанций из положения: 5 км — с 1, 10 км — с 500, эстафета — 501
        bv8 = {r["name"]: r["ids"] for r in json.loads(http("GET", f"/api/events/{e8}/bibs")[1])["rows"]}
        want8 = {"Первый Тест": "1", "Второй Тест": "2", "Длинный Тест": "500", "СШОР-1": "501"}
        c8b, t8b = http("POST", f"/api/events/{e8}/bibs", json.dumps({"rows": [{"ids": bv8[k], "bib": v} for k, v in want8.items()
                                                                                   if k in bv8]}).encode(), J)
        check("5.2: эстафета на шаге 2 — одна строка на команду, номер вписывается один раз",
              c8b == 200 and "СШОР-1" in bv8 and len(bv8["СШОР-1"]) == 4, t8b[:200])
        gr8 = grid_all(e8, ["5 км", "10 км", "4×100 м"])
        code = 200 if all(c_ == 200 for c_, _ in gr8) else 400
        _, txt = http("GET", f"/api/events/{e8}/startlist")
        ents = [e for h in json.loads(txt)["heats"] for e in h["entries"]]
        bibs = {e["name"]: e["bib"] for e in ents}
        rel = [e for e in ents if e["name"] == "СШОР-1"]
        check("2.8: номера, вписанные по диапазонам дистанций, — в сетке; эстафета — одна запись с составом",
              bibs.get("Первый Тест") == "1" and bibs.get("Второй Тест") == "2" and bibs.get("Длинный Тест") == "500"
              and rel and rel[0]["bib"] == "501" and rel[0]["members"].startswith("1. БегунА Этап (2010)") and len(ents) == 4,
              str(bibs) + str(rel)[:200])
        _, txt = http("GET", f"/api/events/{e8}/regs")
        check("2.8: у всех участников эстафеты номер команды",
              sorted(r["entry_bib"] for r in json.loads(txt)["regs"] if r.get("relay")) == ["501"] * 4, txt[:200])
        code, txt = http("POST", f"/api/events/{e8}/pickup", json.dumps({"bib": "500"}).encode(), J)
        pk = json.loads(txt)
        check("2.8: выдача номера отмечена", code == 200 and pk["picked"] == 1 and pk["total"] == 4 and pk["picked_at"], txt)
        grid_all(e8, ["5 км", "10 км", "4×100 м"])
        _, txt = http("GET", f"/api/events/{e8}/pickup")
        pv = json.loads(txt)
        check("2.8: отметка «выдан» сохраняется при пересборке забегов",
              pv["picked"] == 1 and next(r for r in pv["rows"] if r["bib"] == "500")["picked_at"], txt[:300])
        code, txt = http("POST", f"/api/events/{e8}/pickup", json.dumps({"bib": "777"}).encode(), J)
        check("2.8: выдача: нет такого номера", code == 404, txt)
        http("POST", f"/api/events/{e8}", json.dumps({"pub_start": True}).encode(), J)
        code, txt, _ = pub("GET", f"/r/{s8}/startlist.json", cookie=TCK)
        check("2.8: в публичном стартовом протоколе нет отметок выдачи, состав эстафеты есть",
              code == 200 and "picked_at" not in txt and "БегунА" in txt, txt[:200])
        http("POST", f"/api/events/{e8}/pickup", json.dumps({"bib": "500", "undo": True}).encode(), J)
        _, txt = http("GET", f"/api/events/{e8}/pickup")
        check("2.8: выдача отменена", json.loads(txt)["picked"] == 0, txt[:200])
        code, txt = http("POST", f"/api/events/{e8}/copy", b"{}", J)
        cp = json.loads(txt)
        _, txt = http("GET", f"/api/events/{cp['id']}/regs")
        check("2.8: копия на следующий год — настройки есть, участников и заявок нет",
              code == 201 and cp["name"] == "Осенний забег 2027" and cp["date"] == "2027-11-01" and not cp["reg_open"]
              and not cp["pub_site"] and cp["reg_distances"].startswith("5 км | лимит 2") and cp["program"]
              and cp["series"] == "Кубок проверки" and cp["entries_count"] == 0 and not json.loads(txt)["regs"]
              and cp["kind"] == "stadium", str(cp)[:400])
        # серия: два этапа с результатами — сумма очков
        stage_ids = []
        for n, (res_a, res_b) in enumerate((("12.0", "12.5"), ("13.1", "12.9")), 1):
            sid = seed(f"Этап {n}", [(1, "Альфа Аня", 2010, "Ж", "СШОР", "Б/р", ["100 м"]),
                                     (2, "Бета Вера", 2010, "Ж", "Холмск", "Б/р", ["100 м"])], ["100 м"], date=f"2026-0{n}-10")
            stage_ids.append(sid)
            http("POST", f"/api/events/{sid}", json.dumps({"series": "Кубок проверки", "pub_results": True}).encode(), J)
            http("POST", f"/api/events/{sid}/results", json.dumps({"rows": [{"bib": "1", "result": res_a},
                 {"bib": "2", "result": res_b}]}).encode(), J)
        code, txt, _ = pub("GET", "/r/api/series?name=" + urllib.parse.quote("кубок проверки"))
        sr = json.loads(txt)
        g = next((x for x in sr.get("groups", []) if x["group"] == "Девушки"), {"rows": []})
        tot = {r["name"]: (r["total"], r["place"], r["starts"]) for r in g["rows"]}
        check("2.8: зачёт серии — сумма очков за этапы и места",
              code == 200 and tot.get("Альфа Аня") == (37, 1, 2) and tot.get("Бета Вера") == (37, 1, 2)
              and len(sr["stages"]) == 4, str(tot) + txt[:200])
        code, txt, _ = pub("GET", "/r/series?name=x")
        code2, txt2, _ = pub("GET", "/r/api/series")
        check("2.8: страница серии и список серий",
              code == 200 and "Зачёт серии" in txt and any(x["name"] == "Кубок проверки" for x in json.loads(txt2)["series"]), txt2[:200])
        # 3.0: версия, дата сборки, возрастные группы для мастера
        _, txt = http("GET", "/api/status")
        st3 = json.loads(txt)
        check("7.1: версия 7.1.0 и дата сборки 14.10.2026", st3["version"] == "7.1.0" and st3["build_date"] == "2026-10-14", txt[:200])
        code, txt = http("GET", "/api/default-rules?year=2027")
        dr = json.loads(txt)
        check("3.0: возрастные группы для мастера — пары «мальчики / девочки» по году соревнований",
              code == 200 and dr["year"] == 2027 and dr["rules"].splitlines()[0].startswith("Мальчики до 12 лет;М;2016;")
              and len(dr["rules"].splitlines()) == 14, txt[:300])
        code, txt = http("GET", "/")
        wl_ = _re.search(r'<button[^>]*id="wlIpico"[^>]*>.*?</button>', txt, _re.S)       # серая карточка «перенесено в отдельный модуль»
        rest_ = txt.replace(wl_.group(0), "") if wl_ else txt
        bad_w = [w for w in ("IPICO", "Wiclax", "ридер", "Массовый забег с хронометражем") if w in rest_]
        check("7.0: стартовый экран — «Что будем проводить?» с карточкой «Стадион / Манеж»; чиповое направление — только неактивная "
              "карточка-заглушка, про ридеры, Wiclax и настройку оборудования IPICO ни слова",
              code == 200 and "Что будем проводить?" in txt and 'id="wlStadium"' in txt and "Стадион / Манеж" in txt and not bad_w
              and (wl_ is None or "disabled" in wl_.group(0)), str(bad_w))
        # 3.1: справочник дисциплин и типы результата (прыжки, метания, многоборья)
        code, txt = http("GET", "/api/disciplines")
        dj = json.loads(txt)
        dn = [d["name"] for d in dj["disciplines"]]
        grp = {g["id"] for g in dj["groups"]}
        check("3.1: справочник — 10 групп, не меньше 50 дисциплин, названия уникальны и до 20 символов",
              code == 200 and len(dj["groups"]) == 10 and len(dn) >= 50 and len(set(dn)) == len(dn) and all(len(n) <= 20 for n in dn)
              and {d["group"] for d in dj["disciplines"]} <= grp, txt[:200])
        byname = {d["name"]: d for d in dj["disciplines"]}
        check("3.1: есть бег, барьеры, стипль, ходьба, прыжки, метания, многоборья и эстафеты",
              {"100 м", "110 м с/б", "3000 м с/п", "Ходьба 5000 м", "Прыжок в длину", "Толкание ядра", "Десятиборье", "4×100 м"} <= set(dn), str(dn)[:300])
        check("3.1: типы результата — время, расстояние, высота, очки; у метаний попытки; у эстафет этапы",
              byname["100 м"]["result"] == "time" and byname["Прыжок в длину"]["result"] == "distance"
              and byname["Прыжок с шестом"]["result"] == "height" and byname["Десятиборье"]["result"] == "points"
              and byname["Метание копья"].get("attempts") and byname["4×100 м"]["legs"] == 4, "")
        check("3.1: спецификации — массы снарядов и высоты барьеров по возрастам",
              any("7,26" in x["text"] for x in byname["Толкание ядра"]["specs"]) and any("106,7" in x["text"] for x in byname["110 м с/б"]["specs"]), "")
        ids_ = {d["id"] for d in dj["disciplines"]}
        check("3.1: пресеты ссылаются на существующие дисциплины", len(dj["presets"]) >= 8
              and all(set(p["disciplines"]) <= ids_ for p in dj["presets"]), "")
        M_ = "М"
        et = seed("Технические виды", [
            (1, "Альфа Аа", 2008, M_, "СШОР", "Б/р", ["Прыжок в длину"]), (2, "Бета Бб", 2008, M_, "СШОР", "Б/р", ["Прыжок в длину"]),
            (3, "Гамма Вв", 2008, M_, "СШОР", "Б/р", ["Прыжок в длину"]), (4, "Дельта Гг", 2008, M_, "СШОР", "Б/р", ["Прыжок в высоту"]),
            (5, "Эпсилон Дд", 2008, M_, "СШОР", "Б/р", ["Прыжок в высоту"]), (6, "Зета Ее", 2008, M_, "СШОР", "Б/р", ["Десятиборье"]),
            (7, "Эта Жж", 2008, M_, "СШОР", "Б/р", ["Десятиборье"]), (8, "Тета Зз", 2008, M_, "СШОР", "Б/р", ["100 м"]),
            (9, "Йота Ии", 2008, M_, "СШОР", "Б/р", ["100 м"])],
            ["Прыжок в длину", "Прыжок в высоту", "Десятиборье", "100 м"])
        code, txt = http("POST", f"/api/events/{et}/results", json.dumps({"rows": [
            {"bib": "1", "result": "7,85"}, {"bib": "2", "result": "7.2"}, {"bib": "3", "result": "99"},
            {"bib": "4", "result": "1,95"}, {"bib": "5", "result": "2.05"},
            {"bib": "6", "result": "7250"}, {"bib": "7", "result": "8100"},
            {"bib": "8", "result": "11,2"}, {"bib": "9", "result": "10.9"}]}).encode(), J)
        rr = json.loads(txt)
        check("3.1: результаты по типам сохранены, нереальный прыжок 99 м отклонён с подсказкой формата",
              rr["saved"] == 8 and len(rr["errors"]) == 1 and rr["errors"][0].startswith("3:") and "7.85" in rr["errors"][0], txt[:300])
        _, txt = http("GET", f"/api/events/{et}/results")
        fin = {x["bib"]: x for x in json.loads(txt)["finished"]}
        check("3.1: расстояние и высота — больше лучше, текст с сотыми; многоборье — очки; время — меньше лучше",
              fin["1"]["place"] == 1 and fin["1"]["result"] == "7.85" and fin["2"]["place"] == 2
              and fin["5"]["place"] == 1 and fin["5"]["result"] == "2.05" and fin["4"]["place"] == 2
              and fin["7"]["place"] == 1 and fin["7"]["result"] == "8100" and fin["6"]["place"] == 2
              and fin["9"]["place"] == 1 and fin["8"]["place"] == 2 and fin["1"]["rtype"] == "distance"
              and fin["1"]["time"] == "7.85" and fin["9"].get("rtype") is None, str({k: (v["place"], v["result"]) for k, v in fin.items()}))
        _, txt = http("GET", f"/api/events/{et}/results")
        grp_ = {(g["category"], g["distance"]): g["count"] for g in json.loads(txt)["groups"]}
        check("3.1: общий зачёт по дисциплине считается по убыванию результата",
              grp_.get(("Юноши", "Прыжок в длину")) == 2, str(grp_))
        code, txt = http("POST", f"/api/events/{et}/results", json.dumps({"rows": [{"bib": "6", "result": "13:20"}]}).encode(), J)
        check("3.1: время в дисциплине с очками не принимается", json.loads(txt)["saved"] == 0 and len(json.loads(txt)["errors"]) == 1, txt[:200])
        # 3.2: три секундомера и попытки
        e5 = seed("Секундомеры и попытки", [
            (11, "Один Аа", 2008, M_, "СШОР", "1р", ["100 м"]), (12, "Два Бб", 2008, M_, "СШОР", "кмс", ["100 м"]),
            (13, "Три Вв", 2008, M_, "СШОР", "Б/р", ["100 м"]), (14, "Четыре Гг", 2008, M_, "СШОР", "Б/р", ["100 м"]),
            (15, "Пять Дд", 2008, M_, "СШОР", "Б/р", ["100 м"]), (21, "Шесть Ее", 2008, M_, "СШОР", "мс", ["Прыжок в длину"]),
            (22, "Семь Жж", 2008, M_, "СШОР", "Б/р", ["Прыжок в длину"]), (23, "Восемь Зз", 2008, M_, "СШОР", "Б/р", ["Прыжок в длину"]),
            (31, "Девять Ии", 2008, M_, "СШОР", "Б/р", ["Прыжок в высоту"]), (32, "Десять Кк", 2008, M_, "СШОР", "Б/р", ["Прыжок в высоту"])],
            ["100 м", "Прыжок в длину", "Прыжок в высоту"])
        code, txt = http("POST", f"/api/events/{e5}/results", json.dumps({"rows": [
            {"bib": "11", "t": ["12.31", "12.40", "12.33"], "auto": True},
            {"bib": "12", "t": ["13.0", "13.2", ""], "auto": True},
            {"bib": "13", "t": ["14.52", "", ""], "auto": True},
            {"bib": "14", "t": ["12.0", "12.0", "12.3"], "auto": True},
            {"bib": "15", "t": ["12.31", "abc", ""], "auto": True},
            {"bib": "21", "a": ["7.10", "X", "7.85", "-", "7,60"], "auto": True},
            {"bib": "22", "a": ["7.2", "x", "7.2"], "auto": True},
            {"bib": "23", "a": ["abc"], "auto": True},
            {"bib": "31", "a": ["1.80", "1.85", "X"], "auto": True},
            {"bib": "32", "a": ["X", "X", "X"], "auto": True}]}).encode(), J)
        rr = json.loads(txt)
        check("3.2: секундомеры и попытки сохранены, непонятные ячейки названы",
              rr["saved"] == 8 and len(rr["errors"]) == 2 and any("секундомер 2" in e for e in rr["errors"])
              and any("попытка 1" in e for e in rr["errors"]), txt[:400])
        _, txt = http("GET", f"/api/events/{e5}/results")
        fin = {x["bib"]: x for x in json.loads(txt)["finished"]}
        res_ = {b: fin[b]["result"] for b in fin}
        check("3.2: три секундомера — среднее (12.33 → 12.4), два — худшее (13.2), один — он сам, округление вверх до 0,1; два совпали — их время",
              res_.get("11") == "12.4" and res_.get("12") == "13.2" and res_.get("13") == "14.6" and res_.get("14") == "12.0", str(res_))
        check("3.2: показания секундомеров доходят до протокола", fin["11"]["sw"] == ["12.31", "12.40", "12.33"] and fin["11"]["rank"] == "1 р."
              and fin["12"]["rank"] == "КМС", str({k: (v.get("sw"), v.get("rank")) for k, v in fin.items()}))
        check("3.2: лучший результат из попыток (7.85), отметки X и «-» не мешают; высота — лучшая покорённая",
              res_.get("21") == "7.85" and res_.get("22") == "7.20" and res_.get("31") == "1.85" and "32" not in fin
              and fin["21"]["attempts"] == ["7.10", "X", "7.85", "-", "7.60"] and fin["21"]["rank"] == "МС", str(res_) + str(fin.get("21", {}).get("attempts")))
        check("3.2: места: бег 12.0 лучше 12.4, прыжок 7.85 лучше 7.20", fin["14"]["place"] == 1 and fin["11"]["place"] == 2
              and fin["21"]["place"] == 1 and fin["22"]["place"] == 2, str({k: v["place"] for k, v in fin.items()}))
        code, txt = http("POST", f"/api/events/{e5}/results", json.dumps({"rows": [{"bib": "11", "t": ["12.31", "12.40", "12.33"], "result": "12.9"}]}).encode(), J)
        _, txt = http("GET", f"/api/events/{e5}/results")
        f11 = [x for x in json.loads(txt)["finished"] if x["bib"] == "11"][0]
        check("3.2: ручной ввод главного результата сильнее автоматического, показания сохраняются",
              f11["result"] == "12.9" and f11["sw"] == ["12.31", "12.40", "12.33"], str(f11)[:200])
        code, txt = http("POST", f"/api/events/{e5}/results", json.dumps({"rows": [{"bib": "11", "t": ["", "", ""], "auto": True}]}).encode(), J)
        _, txt = http("GET", f"/api/events/{e5}/results")
        check("3.2: стёртые секундомеры снимают результат", all(x["bib"] != "11" for x in json.loads(txt)["finished"]), txt[:100])
        _, txt = http("GET", f"/api/events/{e5}/startlist")
        sl5 = [e for h in json.loads(txt)["heats"] for e in h["entries"]]
        check("3.2: разряд в стартовом списке", {e["bib"]: e["rank"] for e in sl5}.get("21") == "МС", str(sl5)[:200])
        # календарь: перенесённый старт обновляет прежнюю запись
        code, txt = http("POST", "/api/events", json.dumps({"name": "«Ночной забег»", "date": "2026-10-16"}).encode(), J)
        en = json.loads(txt)["id"]
        code, txt = http("POST", "/api/calendar", json.dumps({"import": True, "year": 2026}).encode(), J)
        _, txt2 = http("GET", f"/api/events/{en}")
        n8 = json.loads(txt2)
        check("2.8: календарь — «Ночной забег» перенесён на 23 октября, проводит ЦСП",
              json.loads(txt).get("updated") == 1 and n8["date"] == "2026-10-23" and n8["name"] == "«Ночной забег К-70»"
              and n8["ours"] is False and "myrace.info/events/2124" in (n8["links"] or ""), txt + str(n8)[:300])

        # 3.5: мастер протоколов — бег и техника, выборочная сетка, выгрузка в сеть
        code, txt = http("POST", "/api/events", json.dumps({"name": "Мастер протоколов", "date": "2026-10-20", "kind": "stadium",
                         "timing": "manual", "finish_device": "JUDGE"}).encode(), J)
        e9 = json.loads(txt)["id"]
        code, txt = http("POST", f"/api/events/{e9}", json.dumps({"reg_open": True, "reg_rules": "Юноши;М;2008;2014\nДевушки;Ж;2008;2014",
                         "reg_distances": "60 м\nПрыжок в длину"}).encode(), J)
        s9 = json.loads(txt)["reg_path"].rsplit("/", 1)[-1]

        def reg9(last, sex, dists, year="2011"):
            body = {"last_name": last, "first_name": "Тест", "birth_date": f"{year}-03-03", "sex": sex, "team": "СШОР", "consent": True, "policy": True,
                    "representative": "Родитель", "distances": dists, "rank": "1р"}
            c, t, _ = pub("POST", f"/r/{s9}", json.dumps(body).encode())
            return c
        codes = [reg9("Аргунов", "М", [{"distance": "60 м"}, {"distance": "Прыжок в длину"}]),
                 reg9("Бегунов", "М", [{"distance": "60 м"}, {"distance": "Прыжок в длину"}], "2010"),
                 reg9("Васильева", "Ж", [{"distance": "60 м"}, {"distance": "Прыжок в длину"}]),
                 reg9("Громова", "Ж", [{"distance": "Прыжок в длину"}])]
        http("POST", f"/api/events/{e9}/regs", json.dumps({"approve_all": True}).encode(), J)
        give_bibs(e9)
        code, txt = http("POST", f"/api/events/{e9}/heats", json.dumps({"distance": "Прыжок в длину", "sex": "Ж", "lanes": 8}).encode(), J)
        g1 = json.loads(txt)
        check("3.5: техника — только «Общий список», дорожки заблокированы, участницы не потеряны",
              code == 200 and g1["kind"] == "tech" and g1["mode"] == "list" and len(g1["heats"]) == 1
              and g1["heats"][0]["name"].startswith("Общий список") and g1["entries"] == 2, txt[:300])
        code, txt = http("POST", f"/api/events/{e9}/heats", json.dumps({"distance": "Прыжок в длину", "sex": "М"}).encode(), J)
        g2 = json.loads(txt)
        _, txt = http("GET", f"/api/events/{e9}/startlist")
        sl9 = json.loads(txt)
        jump = [e for h in sl9["heats"] for e in h["entries"] if e["distance"] == "Прыжок в длину"]
        check("3.5: после списка мальчиков девочки на месте: 2 списка, 4 прыгуна, у всех slots=6, дорожек нет",
              code == 200 and len(sl9["heats"]) == 2 and len(jump) == 4 and all(e["slots"] == 6 and e["lane"] is None for e in jump)
              and {sexo for sexo in (e["sex"] for e in jump)} == {"М", "Ж"}, txt[:400])
        code, txt = http("POST", f"/api/events/{e9}/heats", json.dumps({"distance": "Прыжок в длину"}).encode(), J)
        g4 = json.loads(txt)
        check("3.7: техника без фильтра пола — отдельный общий список на каждую категорию, категории не смешиваются",
              code == 200 and sorted(h["category"] for h in g4["heats"]) == ["Девушки", "Юноши"]
              and all(h["name"].startswith("Общий список · Прыжок в длину · ") for h in g4["heats"]) and g4["entries"] == 4, txt[:300])
        code, txt = http("POST", f"/api/events/{e9}/heats", json.dumps({"distance": "60 м", "lanes": 2}).encode(), J)
        g3 = json.loads(txt)
        _, txt = http("GET", f"/api/events/{e9}/startlist")
        sl9 = json.loads(txt)
        run = [h for h in sl9["heats"] if h["distance"] == "60 м"]
        check("3.5: бег — забеги с дорожками, выборочная сетка не тронула технику",
              code == 200 and g3["kind"] == "run" and g3["mode"] == "heats" and len(run) == 2
              and all(e["lane"] for h in run for e in h["entries"]) and len([h for h in sl9["heats"] if h["distance"] == "Прыжок в длину"]) == 2, txt[:300])
        code, txt = http("POST", f"/api/events/{e9}/heats", json.dumps({"distance": "60 м", "ages": ["u12"]}).encode(), J)
        check("3.5: фильтр по возрасту без подходящих участников — понятная ошибка", code == 400 and "нет подтверждённых" in txt, txt[:200])
        DJ, D60 = "Прыжок в длину", "60 м"
        j_bib = next(e["bib"] for e in jump if e["name"].startswith("Аргунов"))
        r_bib = next(e["bib"] for h in run for e in h["entries"] if e["name"].startswith("Аргунов"))
        code, txt = http("POST", f"/api/events/{e9}/results", json.dumps({"rows": [
            {"bib": j_bib, "distance": DJ, "a": ["7.10", "X", "7.85", "-", "7,60", "6.00"], "auto": True, "done_rank": "2р"},
            {"bib": r_bib, "distance": D60, "t": ["8.31", "8.40", "8.33"], "auto": True, "done_rank": "3 юн."}]}).encode(), J)
        _, txt = http("GET", f"/api/events/{e9}/results")
        rs9 = json.loads(txt)
        fj = next(x for x in rs9["finished"] if x["bib"] == j_bib and x["distance"] == DJ)
        fr = next(x for x in rs9["finished"] if x["bib"] == r_bib and x["distance"] == D60)
        c_nod, t_nod = http("POST", f"/api/events/{e9}/results", json.dumps({"rows": [{"bib": j_bib, "result": "7.00"}]}).encode(), J)
        check("7.0: номер стоит в нескольких дисциплинах (60 м и длина) — без «distance» результат не принят, ошибка названа строкой «номер: текст»",
              j_bib == r_bib and c_nod == 200 and json.loads(t_nod)["saved"] == 0
              and json.loads(t_nod)["errors"] == [f"{j_bib}: номер стоит в нескольких дисциплинах — укажите дисциплину"], t_nod[:300])
        check("7.0: результаты одного спортсмена по двум видам независимы (одинаковый bib, разный distance)",
              fj["bib"] == fr["bib"] and fj["result"] == "7.85" and fr["result"] == "8.4" and fj["place"] == 1 and fr["place"] == 1, str((fj, fr))[:300])
        check("3.5: техника — лучшая попытка 7.85 найдена сервером, шесть попыток и выполненный разряд в итогах",
              fj["result"] == "7.85" and fj["rt"] == "distance" and fj["attempts"] == ["7.10", "X", "7.85", "-", "7.60", "6.00"]
              and fj["done_rank"] == "2 р.", str(fj)[:300])
        check("3.5: бег — официальный результат по трём секундомерам (среднее 8.33 → 8.4 вверх), разряд сохранён",
              fr["result"] == "8.4" and fr["sw"] == ["8.31", "8.40", "8.33"] and fr["done_rank"] == "3 юн." and fr["rt"] == "time", str(fr)[:300])
        # 5.2: один секундомер — официальный результат
        r_one = next(e["bib"] for h in run for e in h["entries"] if e["bib"] != r_bib)
        http("POST", f"/api/events/{e9}/results", json.dumps({"rows": [{"bib": r_one, "distance": D60, "t": ["8.27", "", ""], "auto": True}]}).encode(), J)
        f1 = fin_by(e9)[(r_one, D60)]
        check("5.2: заполнен один секундомер — он и есть официальный результат (8.27 → 8.3 вверх до 0,1)", f1["result"] == "8.3", str(f1)[:200])
        # 5.2: правка номера после сетки и результатов — результат переезжает вместе с участником
        bvj = {r["name"]: r for r in json.loads(http("GET", f"/api/events/{e9}/bibs?distance=" + urllib.parse.quote("Прыжок в длину"))[1])["rows"]}
        arg = next(r for n_, r in bvj.items() if n_.startswith("Аргунов"))
        oth = next(r for n_, r in bvj.items() if not n_.startswith("Аргунов") and r["bib"])
        cs_, ts_ = http("POST", f"/api/events/{e9}/bibs", json.dumps({"rows": [{"ids": arg["ids"], "bib": oth["bib"]},
                                                                             {"ids": oth["ids"], "bib": arg["bib"]}]}).encode(), J)
        fj2 = next(x for x in json.loads(http("GET", f"/api/events/{e9}/results")[1])["finished"] if x["name"].startswith("Аргунов") and x["rt"] == "distance")
        cclr, tclr = http("POST", f"/api/events/{e9}/bibs", json.dumps({"rows": [{"ids": arg["ids"], "bib": ""}]}).encode(), J)
        _, lg9 = http("GET", f"/api/events/{e9}/log")
        check("5.2: номера двух участников меняются местами — попытки и результат остаются у своего спортсмена; стереть номер участника сетки нельзя; запись в журнале",
              cs_ == 200 and fj2["bib"] == oth["bib"] and fj2["result"] == "7.85" and cclr == 400 and "нельзя стереть" in tclr
              and "Нагрудные номера сохранены" in lg9, f"{ts_[:150]} {fj2.get('bib')} {tclr[:100]}")
        http("POST", f"/api/events/{e9}/bibs", json.dumps({"rows": [{"ids": arg["ids"], "bib": arg["bib"]},
                                                                    {"ids": oth["ids"], "bib": oth["bib"]}]}).encode(), J)
        # 5.2: стартовый протокол в Excel для судей с ручкой
        import zipfile as _zf

        def xl(dist):
            req = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e9}/startlist.xlsx?distance=" + urllib.parse.quote(dist),
                                         headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode()})
            with urllib.request.urlopen(req, timeout=10) as resp:
                blob, ct, cd = resp.read(), resp.headers.get("Content-Type", ""), resp.headers.get("Content-Disposition", "")
            z = _zf.ZipFile(io.BytesIO(blob))
            return z.read("xl/worksheets/sheet1.xml").decode("utf-8"), z.read("xl/workbook.xml").decode("utf-8"), ct, cd
        xr, wr, ctr, cdr = xl("60 м")
        xt, wt, _, _ = xl("Прыжок в длину")
        check("5.2: Excel бега — № п/п, номер, ФИО, год, разряд, команда, забег, дорожка и три пустые графы секундомеров; книжный лист",
              "spreadsheetml" in ctr and ".xlsx" in urllib.parse.unquote(cdr) and all(h in xr for h in ("№ п/п", "Забег №", "Дорожка", "Нагрудный номер",
              "Фамилия, Имя", "Год рождения", "Разряд", "Команда / Город", "Секундомер 1", "Секундомер 2", "Секундомер 3"))
              and "Аргунов" in xr and 'orientation="portrait"' in xr and "Print_Titles" in wr and "Попытка 1" not in xr, xr[:200])
        check("5.2: Excel техники — порядок выполнения, шесть пустых попыток и «Лучший результат»; альбомный лист",
              all(h in xt for h in ("Порядок выполнения", "Попытка 1", "Попытка 6", "Лучший результат", "Нагрудный номер"))
              and 'orientation="landscape"' in xt and "Секундомер" not in xt and "Общий список" in xt, xt[:200])
        # 5.2: экстренная отмена старта — время старта обнуляется, сетку снова можно пересобрать
        w60 = run[0]["name"]
        http("POST", f"/api/events/{e9}/start", json.dumps({"wave": w60}).encode(), J)
        cg1, _ = http("POST", f"/api/events/{e9}/heats", json.dumps({"distance": "60 м", "lanes": 2}).encode(), J)
        http("POST", f"/api/events/{e9}/reset", json.dumps({"wave": w60}).encode(), J)
        wv = next(w for w in json.loads(http("GET", f"/api/events/{e9}")[1])["waves"] if w["name"] == w60)
        cg2, tg2 = http("POST", f"/api/events/{e9}/heats", json.dumps({"distance": "60 м", "lanes": 2}).encode(), J)
        fr2 = fin_by(e9)[(r_bib, D60)]
        check("5.2: после старта пересобрать нельзя; «Отменить старт» обнуляет время — сетка пересобирается, введённые результаты целы",
              cg1 == 400 and not wv.get("start_time") and cg2 == 200 and fr2["result"] == "8.4", f"{cg1} {wv} {cg2} {tg2[:150]}")
        # 6.0: официальный результат считает только сервер (POST /api/calc); возрасты — из справочника; общее состояние Мастера и корзины
        def calc(dist, rows):
            c, t = http("POST", "/api/calc", json.dumps({"distance": dist, "rows": rows}).encode(), J)
            return c, (json.loads(t)["rows"] if c == 200 else t)
        c1, r1 = calc("60 м", [{"key": "a", "t": ["8.20", "8.40", "8.30"]}, {"key": "b", "t": ["8.2", "8.5"]}, {"key": "c", "t": ["8.27"]},
                              {"key": "d", "t": ["8.2", "ой"]}, {"key": "e", "t": []}])
        check("6.0: /api/calc — три секундомера → средний, два → худший, один → сам (вверх до 0,1), ошибка ввода → сообщение, пусто → пусто",
              c1 == 200 and [x["result"] for x in r1] == ["8.3", "8.5", "8.3", "", ""] and r1[3]["errors"] and not r1[0]["errors"], str(r1))
        c2, r2 = calc("Прыжок в длину", [{"key": "a", "a": ["5.10", "X", "5.40", "-", "5.25"]}, {"key": "b", "a": ["Ы"]}])
        check("6.0: /api/calc — попытки: лучшая; неверная ячейка — сообщение", c2 == 200 and r2[0]["result"] in ("5.40", "5.4") and r2[1]["errors"], str(r2))
        hubdir = os.path.dirname(os.path.abspath(args.hub))
        src = {n: open(os.path.join(hubdir, n), encoding="utf-8").read() for n in ("ui.html", "sector.html", "hub.py")}
        check("6.0: в браузере нет правила секундомеров (ни в админке, ни на планшете сектора) — только запрос к серверу",
              all(w not in src[n] for n in ("ui.html", "sector.html") for w in ("function swMain", "function attBest", "function parseT", "function fmtT"))
              and "/api/calc" in src["ui.html"] and "/api/calc" in src["sector.html"], "")
        check("6.0: возрастные границы не прописаны в коде — только в seed/disciplines.json; мёртвый экран ввода и localStorage Мастера/корзины удалены",
              "AGE_LIMITS" not in src["hub.py"] and "AGE_LIM " not in src["ui.html"] and "loadEntry" not in src["ui.html"] and "resEntry" not in src["ui.html"]
              and "ss.wzp" not in src["ui.html"] and "ss.cart" not in src["ui.html"] and "const STATUS_NAMES" in src["ui.html"], "")
        check("6.0: ни одного принудительного скролла наверх при смене шагов Мастера и после сохранения (scrollIntoView удалён)",
              "scrollIntoView" not in src["ui.html"] and src["ui.html"].count("window.scrollTo(") == 1, str(src["ui.html"].count("window.scrollTo(")))
        _, txt = http("GET", "/api/disciplines")
        ag = {a["id"]: (a.get("min"), a.get("max")) for a in json.loads(txt)["ages"]}
        check("6.0: возрастные группы отдаются справочником с границами min/max", ag.get("u12") == (0, 12) and ag.get("sen") == (19, 200), str(ag))
        _, txt = http("GET", f"/api/events/{e9}/ui")
        u0 = json.loads(txt)["state"]
        check("6.0: общее состояние: у нового соревнования Мастер и корзина пусты", u0["wizard"]["rev"] == 0 and u0["cart"]["value"] == [], txt[:200])
        cw, tw = http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "wizard", "cid": "A", "value": {"disc": "60 м", "step": 4, "sex": "Ж", "ages": ["u12", "нет-такой"]}}).encode(), J)
        _, txt = http("GET", f"/api/events/{e9}/ui")
        wz_ = json.loads(txt)["state"]["wizard"]
        check("6.0: дисциплина, шаг и фильтры Мастера хранятся в базе и видны другому экрану; неизвестная возрастная группа отброшена",
              cw == 200 and wz_["rev"] == 1 and wz_["cid"] == "A" and wz_["value"] == {"disc": "60 м", "step": 4, "sex": "Ж", "ages": ["u12"]}, txt[:300])
        item = {"type": "start", "dist": "60 м", "gk": "", "sf": "", "mode": "heats", "orient": "", "label": "Старт: 60 м — Все участники"}
        ca, ta = http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "cart", "op": "add", "cid": "A", "item": item}).encode(), J)
        cb, tb = http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "cart", "op": "add", "cid": "B", "item": dict(item, dist="Прыжок в длину", label="Старт: прыжок")}).encode(), J)
        cd, td = http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "cart", "op": "add", "cid": "B", "item": item}).encode(), J)
        cart = json.loads(td)["value"]
        check("6.0: корзина общая: два секретаря добавили разные листы — оба на месте, повтор того же листа не дублируется",
              ca == cb == cd == 200 and json.loads(ta)["added"] and not json.loads(td)["added"] and len(cart) == 2 and all(x["on"] and x["id"] for x in cart), td[:300])
        http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "cart", "op": "toggle", "id": cart[0]["id"], "on": False}).encode(), J)
        http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "cart", "op": "remove", "id": cart[1]["id"]}).encode(), J)
        _, txt = http("GET", f"/api/events/{e9}/ui")
        c3 = json.loads(txt)["state"]["cart"]["value"]
        cx, _ = http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "cart", "op": "взорвать"}).encode(), J)
        cy, _ = http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "что-то"}).encode(), J)
        http("POST", f"/api/events/{e9}/ui", json.dumps({"key": "cart", "op": "clear"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e9}/ui")
        check("6.0: корзина — отметка, удаление и очистка делаются на сервере; неизвестные операции и разделы отвергаются",
              len(c3) == 1 and c3[0]["on"] is False and cx == 400 and cy == 400 and json.loads(txt)["state"]["cart"]["value"] == [], txt[:200])
        # 4.0: судья на секторе / секретарь вида — только ввод результатов
        def spost(path, obj, cookie=None):
            h = {"Content-Type": "application/json", "X-Requested-With": "timing-hub", "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"}
            if cookie:
                h["Cookie"] = cookie
            req = urllib.request.Request(f"http://127.0.0.1:{p_web}{path}", data=json.dumps(obj).encode(), method="POST", headers=h)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, json.loads(resp.read() or b"{}"), resp.headers.get("Set-Cookie", "")
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}"), ""

        def sget(path, cookie):
            req = urllib.request.Request(f"http://127.0.0.1:{p_web}{path}", headers={"Cookie": cookie, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status
            except urllib.error.HTTPError as e:
                return e.code
        _, ad, adck = spost("/api/login", {"login": "admin", "password": "test-pass"})
        adm4 = adck.split(";")[0]
        # 4.5: две роли — администратор и судья; старые роли «секретарь» и «судья на секторе» сводятся к судье
        code, d, _ = spost("/api/users", {"login": "sector1", "name": "Судья сектора", "role": "sector", "password": "sector-pass-1"}, adm4)
        code_s, _, _ = spost("/api/users", {"login": "secr1", "name": "Секретарь", "role": "secretary", "password": "secr-pass-1"}, adm4)
        code_x, _, _ = spost("/api/users", {"login": "boss1", "role": "chief", "password": "boss-pass-1"}, adm4)
        ulst = {u["login"]: u["role"] for u in json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{p_web}/api/users", headers={"Cookie": adm4, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"}), timeout=10).read())["users"]}
        roles_ = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{p_web}/api/users", headers={"Cookie": adm4, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"}), timeout=10).read())["roles"]
        check("4.5: ролей ровно две — Администратор и Судья; «секретарь» и «судья на секторе» сохраняются как судья, неизвестная роль — отказ",
              roles_ == {"admin": "Администратор", "judge": "Судья"} and ulst.get("sector1") == "judge" and ulst.get("secr1") == "judge"
              and code_s == 200 and code_x == 400, f"{roles_} {ulst} {code_x}")
        code, d, ck = spost("/api/login", {"login": "sector1", "password": "sector-pass-1", "next": "/"})
        sck = ck.split(";")[0]
        se = e9
        check("4.5: судья после входа попадает в общую админку (Мастер протоколов)", code == 200 and d.get("next") == "/" and d["user"]["role"] == "judge", str(d))

        class _NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        page_ = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{p_web}/sector?event={e9}", headers={"Cookie": sck, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"}), timeout=10).read().decode()
        check("4.5: судье открыты админка, экраны финиша и сектора, табло, пульт, протокол, заявки",
              sget("/", sck) == 200 and sget("/judge", sck) == 200 and sget("/sector", sck) == 200 and "Судья на секторе" in page_
              and sget("/board", sck) == 200 and sget("/scoreboard", sck) == 200 and sget("/protocol", sck) == 200
              and sget(f"/api/events/{se}/regs", sck) == 200 and sget(f"/api/events/{se}/startlist", sck) == 200
              and sget(f"/api/events/{se}/results", sck) == 200 and sget("/api/disciplines", sck) == 200)
        check("4.5: судье жёстко закрыты «Система», обновления, пользователи; журнал открыт; чиповых адресов нет вовсе",
              sget("/api/system", sck) == 403 and sget("/api/system/update", sck) == 403 and sget("/api/users", sck) == 403
              and sget("/api/readers", sck) in (403, 404) and sget("/api/wiclax-ports", sck) in (403, 404) and sget("/api/log", sck) == 200)
        c1, _, _ = spost(f"/api/events/{se}/results", {"rows": []}, sck)
        c2, _, _ = spost(f"/api/events/{se}/heats", {"distance": "нет такой дистанции"}, sck)
        c3, _, _ = spost(f"/api/events/{se}/delete", {}, sck)
        c4, _, _ = spost(f"/api/events/{se}/clearresults", {"bibs": []}, sck)
        c5, _, _ = spost(f"/api/events/{se}", {"organizer": "СШОР"}, sck)
        c6, _, _ = spost("/api/system/update/install", {}, sck)
        c7, _, _ = spost("/api/users", {"login": "hack1", "role": "admin", "password": "hack-pass-1"}, sck)
        c8, _, _ = spost("/api/system/retention", {}, sck)
        check("4.5: судья вводит результаты, строит сетку, очищает протокол, правит соревнование — но не удаляет его и не трогает систему",
              c1 == 200 and c2 != 403 and c4 != 403 and c5 == 200 and c3 == 403 and c6 == 403 and c7 == 403 and c8 == 403,
              f"{c1} {c2} {c3} {c4} {c5} {c6} {c7} {c8}")
        # 4.4: пульт управления стадионным табло
        code, txt = http("GET", f"/api/scoreboard/state?event={se}")
        sb0 = json.loads(txt) if code == 200 else {}
        gk = {g["key"]: g for g in sb0.get("groups", [])}
        tk = next((k for k, g in gk.items() if g["tech"] and g["results"]), "")
        check("4.4: табло по умолчанию в режиме авто-трансляции, пульт видит группы дисциплин с результатами",
              code == 200 and sb0["mode"] == "auto" and tk and "server_ms" in sb0 and sb0["rotate"]["interval"] == 15, txt[:300])
        code, txt = http("POST", "/api/scoreboard/state", json.dumps({"event_id": se, "mode": "fixed", "wave_id": tk}).encode(), J)
        sb1 = json.loads(txt) if code == 200 else {}
        code2, txt2 = http("GET", f"/api/scoreboard/state?event={se}")
        check("4.4: фиксация дисциплины сохраняется и сразу отдаётся табло",
              code == 200 and sb1["mode"] == "fixed" and sb1["group"] == tk and json.loads(txt2)["group"] == tk, txt[:300])
        c1, _ = http("POST", "/api/scoreboard/state", json.dumps({"event_id": se, "mode": "kino"}).encode(), J)
        c2, _ = http("POST", "/api/scoreboard/state", json.dumps({"event_id": se, "mode": "fixed", "group": "нет|такой"}).encode(), J)
        c3, _ = http("POST", "/api/scoreboard/state", json.dumps({"event_id": 99999, "mode": "auto"}).encode(), J)
        check("4.4: неизвестный режим, чужая группа, несуществующее соревнование — ошибка", c1 == 400 and c2 == 400 and c3 in (400, 404), f"{c1} {c2} {c3}")
        code, txt = http("POST", "/api/scoreboard/state", json.dumps({"event_id": se, "mode": "rotate", "rotate": {"interval": 3, "groups": [tk, "нет|такой"]}}).encode(), J)
        sb2 = json.loads(txt) if code == 200 else {}
        check("4.4: ротация — интервал не меньше 5 с, в круг попадают только существующие группы",
              code == 200 and sb2["mode"] == "rotate" and sb2["rotate"]["interval"] == 5 and sb2["rotate"]["groups"] == [tk], txt[:300])
        cs1, sbj, _ = spost("/api/scoreboard/state", {"event_id": se, "mode": "fixed", "group": tk}, sck)
        rq = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/system/scoreboard/control?event={se}", headers={"Cookie": sck, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"})
        try:
            urllib.request.build_opener(_NoRedir).open(rq, timeout=10)
            locs = ""
        except urllib.error.HTTPError as e_:
            locs = e_.headers.get("Location", "")
        check("4.5: судья управляет пультом табло (фиксация лидеров), адрес /api/system/scoreboard/control ему открыт",
              cs1 == 200 and sbj.get("mode") == "fixed" and locs == f"/scoreboard?event={se}", f"{cs1} {locs}")
        http("POST", "/api/scoreboard/state", json.dumps({"event_id": se, "mode": "auto"}).encode(), J)
        pg = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{p_web}/scoreboard?event={se}", headers={"Cookie": adm4, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"}), timeout=10)
        pgt = pg.read().decode()
        rq = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/system/scoreboard/control?event={se}", headers={"Cookie": adm4, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"})
        try:
            urllib.request.build_opener(_NoRedir).open(rq, timeout=10)
            loc4 = ""
        except urllib.error.HTTPError as e_:
            loc4 = e_.headers.get("Location", "")
        bh = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{p_web}/board?event={se}", headers={"Cookie": adm4, "X-Forwarded-Proto": "https", "X-Real-IP": "198.51.100.7"}), timeout=10)
        check("4.4: страница пульта открывается, /api/system/scoreboard/control ведёт на неё, табло можно встроить в превью пульта",
              pg.status == 200 and "Пульт" in pgt and "/api/scoreboard/state" in pgt and loc4 == f"/scoreboard?event={se}"
              and bh.headers.get("X-Frame-Options") == "SAMEORIGIN", f"{loc4} {bh.headers.get('X-Frame-Options')}")
        # 4.5.2: «Завершить» по ошибке — «Возобновить» возвращает всё: статус, архив, регистрацию, сайт; журнал пишет оба шага
        code, txt = http("POST", "/api/events", json.dumps({"name": "Перенос 4.5.2", "date": "2030-05-20", "kind": "stadium",
                                                             "timing": "manual", "finish_device": "JUDGE"}).encode(), J)
        ef = json.loads(txt)["id"]
        code, txt = http("POST", f"/api/events/{ef}", json.dumps({"reg_open": True, "pub_site": True, "ours": True,
                                                                   "reg_distances": "60 м"}).encode(), J)

        def card_f():
            return next(c for c in json.loads(pub("GET", "/r/api/calendar")[1])["events"] if c["name"] == "Перенос 4.5.2")

        def ev_f():
            return json.loads(http("GET", f"/api/events/{ef}")[1])
        c0 = card_f()
        http("POST", f"/api/events/{ef}/start", b"{}", J)
        c1 = card_f()
        code, txt = http("POST", f"/api/events/{ef}/finish", b"{}", J)
        c2, e2_ = card_f(), ev_f()
        nfiles = len(json.loads(http("GET", f"/api/events/{ef}/files")[1])["files"])
        http("POST", f"/api/events/{ef}/finish", b"{}", J)
        nfiles2 = len(json.loads(http("GET", f"/api/events/{ef}/files")[1])["files"])
        check("4.5.2: «Завершить» — на сайте в прошедших, регистрация закрыта; повторное нажатие не плодит снимков",
              c0["status"] == "planned" and c0["reg"] and c1["status"] == "running" and c1["reg"]
              and c2["status"] == "finished" and c2["reg"] is None and e2_["finished_at"] and nfiles == nfiles2,
              f"{c0['status']} {c1['status']} {c2['status']} {c2['reg']} {nfiles}/{nfiles2}")
        http("POST", f"/api/events/{ef}/archive", b"{}", J)
        code, txt = http("POST", f"/api/events/{ef}/reopen", b"{}", J)
        c3, e3_ = card_f(), ev_f()
        check("4.5.2: «Возобновить» — снова идёт, из архива назад, регистрация открыта, на сайте текущее с онлайн-результатами",
              code == 200 and e3_["status"] == "running" and not e3_["archived"] and not e3_["finished_at"]
              and c3["status"] == "running" and c3["reg"] and c3["reg"]["open"], f"{e3_.get('status')} {e3_.get('archived')} {c3}"[:300])
        logf = [x for x in json.loads(http("GET", "/api/log")[1])["log"] if x.get("event_id") == ef]
        acts = [x.get("action") for x in logf]
        reo = next((x for x in logf if x.get("action") == "Соревнование возобновлено"), {})
        check("4.5.2: журнал: завершение (одно), архив, возобновление — с пояснением, что вернулось",
              acts.count("Соревнование завершено") == 1 and "Перенесено в архив" in acts and reo
              and "возвращено из архива" in (reo.get("details") or "") and "регистрация открыта" in (reo.get("details") or ""),
              str([(x.get("action"), x.get("details")) for x in logf])[:400])
        http("POST", f"/api/events/{ef}/reset", b"{}", J)
        http("POST", f"/api/events/{ef}/finish", b"{}", J)
        http("POST", f"/api/events/{ef}/reopen", b"{}", J)
        check("4.5.2: старт ещё не дан — после «Возобновить» соревнование ждёт старта", ev_f()["status"] == "planned")
        # 3.6: выполненный разряд по нормам ЕВСК (seed/rank_norms.json)
        vas = next(e["bib"] for h in run for e in h["entries"] if e["name"].startswith("Васильева"))
        beg = next(e["bib"] for e in jump if e["name"].startswith("Бегунов"))
        grm = next(e["bib"] for e in jump if e["name"].startswith("Громова"))
        http("POST", f"/api/events/{e9}/results", json.dumps({"rows": [
            {"bib": vas, "distance": D60, "t": ["9.1", "9.2", "9.15"], "auto": True},
            {"bib": beg, "distance": DJ, "a": ["6.10", "X", "5.90"], "auto": True},
            {"bib": grm, "distance": DJ, "a": ["5.75", "5.50"], "auto": True}]}).encode(), J)
        fin9 = fin_by(e9)
        check("4.3: у введённого вручную результата есть время ввода (табло показывает свежие сверху)",
              all(isinstance(fin9[b_].get("entered_epoch_ms"), int) and fin9[b_]["entered_epoch_ms"] > 1.7e12 for b_ in ((vas, D60), (beg, DJ), (grm, DJ))),
              str({k: v.get("entered_epoch_ms") for k, v in fin9.items()}))
        check("3.6: разряд считается сам — 60 м девочка 15 лет 9.2 (ручной) → 1 юн.; длина юноша 16 лет 6.10 → 2 р.",
              fin9[vas, D60]["done_rank"] == "1 юн." and fin9[vas, D60]["done_rank_src"] == "auto"
              and fin9[beg, DJ]["done_rank"] == "2 р.", str({k: (v["result"], v["done_rank"]) for k, v in fin9.items()}))
        check("3.6: на региональных соревнованиях потолок — I разряд (5.75 у девушки — норма КМС, засчитан 1 р.)",
              fin9[grm, DJ]["done_rank"] == "1 р.", str(fin9[grm, DJ])[:200])
        check("3.6: вписанный секретарём разряд главнее расчётного", fin9[j_bib, DJ]["done_rank"] == "2 р." and fin9[j_bib, DJ]["done_rank_src"] == "manual"
              and fin9[j_bib, DJ]["done_rank_auto"] == "1 р.", str(fin9[j_bib, DJ])[:300])
        http("POST", f"/api/events/{e9}/results", json.dumps({"rows": [{"bib": vas, "distance": D60, "done_rank": "—"}, {"bib": beg, "distance": DJ, "done_rank": "кмс"}]}).encode(), J)
        fin9 = fin_by(e9)
        check("3.8: секретарь вручную ставит «Не выполнен» (—) и свой разряд — они главнее расчёта ЕВСК, результат не стёрт",
              fin9[vas, D60]["done_rank"] == "" and fin9[vas, D60]["done_rank_src"] == "manual" and fin9[vas, D60]["done_rank_auto"] == "1 юн."
              and fin9[beg, DJ]["done_rank"] == "КМС" and fin9[beg, DJ]["done_rank_src"] == "manual" and fin9[beg, DJ]["result"] == "6.10"
              and fin9[vas, D60]["result"] == "9.2", str({k: (v["result"], v["done_rank"], v["done_rank_src"]) for k, v in fin9.items()}))
        http("POST", f"/api/events/{e9}/results", json.dumps({"rows": [{"bib": vas, "distance": D60, "done_rank": ""}, {"bib": beg, "distance": DJ, "done_rank": ""}]}).encode(), J)
        fin9 = fin_by(e9)
        check("3.8: «Авто» возвращает расчёт по нормам", fin9[vas, D60]["done_rank"] == "1 юн." and fin9[beg, DJ]["done_rank"] == "2 р."
              and fin9[vas, D60]["done_rank_src"] == "auto", str({k: (v["done_rank"], v["done_rank_src"]) for k, v in fin9.items()}))
        code, txt = http("POST", f"/api/events/{e9}/clearresults", json.dumps({"bibs": [vas], "distance": D60, "label": "60 м"}).encode(), J)
        fin9c = fin_by(e9)
        sl9c = {(e["bib"], e["distance"]): e for h in json.loads(http("GET", f"/api/events/{e9}/startlist")[1])["heats"] for e in h["entries"]}
        check("4.0: «Очистить протокол» стирает результат, секундомеры и ручной разряд только выбранных участников",
              code == 200 and json.loads(txt)["cleared"] == 1 and (vas, D60) not in fin9c and (beg, DJ) in fin9c
              and not sl9c[vas, D60].get("result") and not sl9c[vas, D60].get("detail") and not sl9c[vas, D60].get("done_rank"), txt[:200])
        http("POST", f"/api/events/{e9}/results", json.dumps({"rows": [{"bib": vas, "distance": D60, "t": ["9.1", "9.2", "9.15"], "auto": True}]}).encode(), J)
        http("POST", f"/api/events/{e9}", json.dumps({"level": "interregion"}).encode(), J)
        fin9 = fin_by(e9)
        check("3.6: на межрегиональных соревнованиях та же попытка 5.75 даёт КМС", fin9[grm, DJ]["done_rank"] == "КМС", str(fin9[grm, DJ])[:200])
        http("POST", f"/api/events/{e9}", json.dumps({"level": "region"}).encode(), J)
        _, dtxt = http("GET", "/api/disciplines")
        dd = {x["name"]: x for x in json.loads(dtxt)["disciplines"]}
        mb = dd.get("Метание мяча/снаряда")
        check("3.6: «Метание мяча/снаряда» есть в справочнике как техническая дисциплина (попытки, расстояние)",
              mb and mb["attempts"] and mb["result"] == "distance" and mb["group"] == "throws" and "Метание снаряда" in mb["aliases"], str(mb)[:200])
        # бег и техника в одном соревновании: техника не должна читаться как время
        code, txt = http("POST", "/api/events", json.dumps({"name": "Смешанный список", "kind": "stadium", "timing": "manual", "finish_device": "JUDGE"}).encode(), J)
        e10 = json.loads(txt)["id"]
        http("POST", f"/api/events/{e10}", json.dumps({"reg_open": True, "reg_distances": "60 м\nПрыжок в длину"}).encode(), J)
        sl10 = json.loads(http("GET", f"/api/events/{e10}")[1])["reg_path"].rsplit("/", 1)[-1]
        for ln, dd in (("Смешанов", "60 м"), ("Прыгунов", "Прыжок в длину")):
            pub("POST", f"/r/{sl10}", json.dumps({"last_name": ln, "first_name": "Тест", "birth_date": "2010-01-01", "sex": "М", "team": "К", "consent": True, "policy": True,
                 "representative": "Р", "distances": [{"distance": dd}], "rank": "Б/р"}).encode())
        http("POST", f"/api/events/{e10}/regs", json.dumps({"approve_all": True}).encode(), J)
        give_bibs(e10)
        c_mix, t_mix = http("POST", f"/api/events/{e10}/heats", json.dumps({"mode": "list"}).encode(), J)
        check("7.0: смешанный общий список без дисциплины больше не формируется — 400 «выберите дисциплину»",
              c_mix == 400 and "выберите дисциплину" in t_mix, t_mix)
        grid_all(e10, ["60 м", "Прыжок в длину"])
        sl = json.loads(http("GET", f"/api/events/{e10}/startlist")[1])
        jb = next(e["bib"] for h in sl["heats"] for e in h["entries"] if e["name"].startswith("Прыгунов"))
        http("POST", f"/api/events/{e10}/results", json.dumps({"rows": [{"bib": jb, "a": ["5.20", "5.45", "X"], "auto": True}]}).encode(), J)
        rs10 = json.loads(http("GET", f"/api/events/{e10}/results")[1])
        f10 = [x for x in rs10["finished"] if x["bib"] == jb]
        check("3.5: у соревнования с бегом и техникой прыжок читается как расстояние (5.45), а не как время",
              f10 and f10[0]["result"] == "5.45" and f10[0]["distance"] == "Прыжок в длину" and f10[0]["rt"] == "distance",
              str(f10)[:300])
        # публикация в общую сеть
        code, txt = http("POST", f"/api/events/{e9}/publish", json.dumps({"start": True, "results": True}).encode(), J)
        pb = json.loads(txt)
        cs, _, _ = pub("GET", f"/r/{s9}/startlist.json", cookie=TCK)
        cr, _, _ = pub("GET", f"/r/{s9}/results.json", cookie=TCK)
        check("3.5: «Выгрузить в общую сеть» открывает стартовый и итоговый протоколы на публичной странице",
              code == 200 and pb["pub_start"] and pb["pub_results"] and cs == 200 and cr == 200 and "/protocol" in pb["start_url"], txt[:300])
        code, txt = http("POST", f"/api/events/{e9}/publish", json.dumps({}).encode(), J)
        check("3.5: выгрузка без указания, что выгружать, отклоняется", code == 400, txt[:200])
        code, txt = http("POST", f"/api/events/{e9}/resetheats", json.dumps({"distance": "Прыжок в длину"}).encode(), J)
        sl9 = json.loads(http("GET", f"/api/events/{e9}/startlist")[1])
        check("3.5: сброс одной дисциплины убирает только её списки, забеги бега остаются",
              code == 200 and json.loads(txt)["waves"] == 2 and len([h for h in sl9["heats"] if h["distance"] == "60 м"]) == 2
              and not [h for h in sl9["heats"] if h["distance"] == "Прыжок в длину"], txt[:200])

        # ===================== 7.0: сквозной номер спортсмена на все его дисциплины =====================
        DM = "Метание мяча/снаряда"
        c_, e13v = api("POST", "/api/events", {"name": "Открытое первенство СШОР по метаниям", "date": "2026-10-17", "kind": "stadium",
                                                "timing": "manual", "finish_device": "JUDGE"})
        e13 = e13v["id"]
        c_, evr13 = api("POST", f"/api/events/{e13}", {
            "reg_open": True, "place": "Легкоатлетический манеж", "organizer": "ГАУ СШОР по лёгкой атлетике",
            "reg_rules": "Девочки до 14 лет;Ж;2012;2013\nМальчики до 14 лет;М;2012;2013", "reg_distances": f"{DM}\n60 м"})
        s13 = evr13["reg_path"].rsplit("/", 1)[-1]

        def reg13(last, first="Анна", year="2013", dists=(DM, D60)):
            body = {"last_name": last, "first_name": first, "birth_date": f"{year}-05-05", "sex": "Ж", "team": "СШОР ЛВС",
                    "coach": "Петрова П.В.", "consent": True, "policy": True, "representative": "Родитель", "rank": "3 юн.",
                    "distances": [{"distance": d_, "best": "25.5" if d_ == DM else "9.1"} for d_ in dists]}
            c__, t__, _ = pub("POST", f"/r/{s13}", json.dumps(body).encode())
            return c__
        letters = "абвгдежзиклмн"
        codes13 = [reg13("Фамилиева" + letters[i]) for i in range(13)]
        c_, rv13 = api("POST", f"/api/events/{e13}/regs", {"approve_all": True})
        check("7.0: 13 девочек заявлены через публичную форму на 60 м и метание (26 заявок), все подтверждены",
              codes13 == [201] * 13 and rv13["counts"] == {"pending": 0, "approved": 26, "rejected": 0}, f"{codes13} {rv13.get('counts')}")
        bv60 = json.loads(http("GET", f"/api/events/{e13}/bibs?distance=" + urllib.parse.quote(D60) + "&sex=" + urllib.parse.quote("Ж"))[1])
        check("7.0: шаг 2 по «60 м»: 13 человек, у каждого показана вторая дисциплина (метание) и пока без номера",
              bv60["total"] == 13 and bv60["with_bib"] == 0 and all(len(r["also"]) == 1 and r["also"][0]["distance"] == DM
                                                                     and not r["also"][0]["bib"] and not r["inherited"] for r in bv60["rows"]),
              str(bv60["rows"][:1]))
        rows13 = [{"ids": r["ids"], "bib": str(i + 1)} for i, r in enumerate(bv60["rows"])]
        c_, sv13 = api("POST", f"/api/events/{e13}/bibs", {"rows": rows13})
        check("7.0: номер вписан один раз на шаге «60 м» и «разъехался» на 2 дисциплины: saved=13, spread=13 (по числу людей)",
              c_ == 200 and sv13.get("ok") and sv13.get("saved") == 13 and sv13.get("spread") == 13, str(sv13))
        nm_bib = {r["name"]: str(i + 1) for i, r in enumerate(bv60["rows"])}
        dbq = _sql.connect(cfg["db_path"])
        rg = dbq.execute("SELECT last_name, distance, bib FROM registrations WHERE event_id = ? ORDER BY last_name, distance", (e13,)).fetchall()
        dbq.close()
        per = {}
        for ln_, d_, b_ in rg:
            per.setdefault(ln_, {})[d_] = b_
        check("7.0: в registrations.bib у каждой из 26 заявок стоит номер, а у каждой девочки в метании — тот же, что в беге",
              len(rg) == 26 and all(b_ for _, _, b_ in rg) and all(len(v) == 2 and v[D60] == v[DM] for v in per.values())
              and sorted(int(v[D60]) for v in per.values()) == list(range(1, 14)), str(rg[:4]))
        bvm = json.loads(http("GET", f"/api/events/{e13}/bibs?distance=" + urllib.parse.quote(DM))[1])
        check("7.0: шаг 2 по метанию: те же 13 человек с теми же номерами, повторно вписывать не нужно",
              bvm["total"] == 13 and bvm["with_bib"] == 13 and {r["name"]: r["bib"] for r in bvm["rows"]} == nm_bib
              and not any(r["mismatch"] for r in bvm["rows"]), str(bvm["rows"][:1]))
        # повтор номера у ДРУГОГО человека — 400
        r1_, r2_ = bvm["rows"][0], bvm["rows"][1]
        c_, dup = api("POST", f"/api/events/{e13}/bibs", {"rows": [{"ids": r2_["ids"], "bib": r1_["bib"]}]})
        check("7.0: номер другого человека дать нельзя — 400 с errors, в базе ничего не изменилось",
              c_ == 400 and dup.get("errors") and "уже у другого участника" in dup["errors"][0]["error"]
              and json.loads(http("GET", f"/api/events/{e13}/bibs?distance=" + urllib.parse.quote(DM))[1])["rows"][1]["bib"] == r2_["bib"], str(dup)[:300])
        c_, dup2 = api("POST", f"/api/events/{e13}/bibs", {"rows": [{"ids": r1_["ids"], "bib": r2_["bib"]}]})
        check("7.0: то же через шаг «метание» — 400 (проверка по людям, а не по дисциплинам)", c_ == 400 and dup2.get("errors"), str(dup2)[:200])
        # сетки обеих дисциплин
        g60 = api("POST", f"/api/events/{e13}/heats", {"distance": D60, "lanes": 8})
        gdm = api("POST", f"/api/events/{e13}/heats", {"distance": DM, "lanes": 8})
        ents13 = sl_entries(e13)
        by_bib = {}
        for e_ in ents13:
            by_bib.setdefault(e_["bib"], []).append(e_["distance"])
        check("7.0: после генерации обеих сеток в entries у каждой девочки две строки с одним номером (60 м и метание); всего 26",
              g60[0] == 200 and gdm[0] == 200 and g60[1]["entries"] == 13 and gdm[1]["entries"] == 13 and len(ents13) == 26
              and all(sorted(v) == sorted([D60, DM]) for v in by_bib.values()) and len(by_bib) == 13
              and all(isinstance(e_["id"], int) for e_ in ents13) and len({e_["id"] for e_ in ents13}) == 26,
              str(g60[1])[:150] + str(sorted(by_bib.items())[:2]))
        check("7.0: в стартовом списке и в entries нет поля chip", "chip" not in json.dumps(ents13).lower()
              and "chip" not in http("GET", f"/api/events/{e13}/results")[1].lower(), "")
        # результаты по обоим видам независимы
        bA = nm_bib[bvm["rows"][0]["name"]]
        bB = nm_bib[bvm["rows"][1]["name"]]
        c_, rs = api("POST", f"/api/events/{e13}/results", {"rows": [
            {"bib": bA, "distance": D60, "result": "9.1"}, {"bib": bA, "distance": DM, "a": ["25.5", "X", "27.1"], "auto": True},
            {"bib": bB, "distance": DM, "a": ["30.0"], "auto": True}, {"bib": bB, "distance": D60, "result": "8.8"}]})
        f13 = fin_by(e13)
        check("7.0: результаты вписаны по каждой дисциплине отдельно: один bib, разный distance — разные результаты и места",
              c_ == 200 and rs["saved"] == 4 and not rs["errors"] and f13[(bA, D60)]["result"] == "9.1"
              and f13[(bA, DM)]["result"].startswith("27.1") and f13[(bB, D60)]["result"] == "8.8"
              and f13[(bB, DM)]["result"].startswith("30.0") and f13[(bA, D60)]["place"] == 2 and f13[(bB, D60)]["place"] == 1
              and f13[(bA, DM)]["place"] == 2 and f13[(bB, DM)]["place"] == 1, str({k: (v["result"], v["place"]) for k, v in f13.items()}))
        c_, rs = api("POST", f"/api/events/{e13}/results", {"rows": [{"bib": bA, "result": "9.0"}]})
        check("7.0: без distance результат номера из двух дисциплин не принят — «номер стоит в нескольких дисциплинах — укажите дисциплину»",
              c_ == 200 and rs["saved"] == 0 and rs["errors"] == [f"{bA}: номер стоит в нескольких дисциплинах — укажите дисциплину"], str(rs))
        c_, rs = api("POST", f"/api/events/{e13}/results", {"rows": [{"bib": bA, "distance": "100 м", "result": "9.0"}]})
        check("7.0: дисциплина, в которой номера нет, — ошибка строкой «номер: текст»",
              c_ == 200 and rs["saved"] == 0 and len(rs["errors"]) == 1 and rs["errors"][0].startswith(f"{bA}:"), str(rs))
        c_, cl = api("POST", f"/api/events/{e13}/clearresults", {"bibs": [bA], "distance": DM, "label": DM})
        f13 = fin_by(e13)
        check("7.0: «Очистить протокол» с distance стирает результат только в этой дисциплине",
              c_ == 200 and cl["cleared"] == 1 and (bA, DM) not in f13 and (bA, D60) in f13 and (bB, DM) in f13, str(cl))
        # выдача номеров — по людям
        pk13 = json.loads(http("GET", f"/api/events/{e13}/pickup")[1])
        c_, pkp = api("POST", f"/api/events/{e13}/pickup", {"bib": bA})
        dbq = _sql.connect(cfg["db_path"])
        pk_rows = dbq.execute("SELECT COUNT(*), SUM(picked_at IS NOT NULL) FROM entries WHERE event_id = ? AND bib = ?", (e13, bA)).fetchone()
        dbq.close()
        pk13b = json.loads(http("GET", f"/api/events/{e13}/pickup")[1])
        check("7.0: выдача номеров — одна строка на человека (13, а не 26); отметка «выдан» ложится на обе строки номера",
              pk13["total"] == 13 and len(pk13["rows"]) == 13 and pk13["picked"] == 0 and c_ == 200 and pkp["total"] == 13 and pkp["picked"] == 1
              and tuple(pk_rows) == (2, 2) and pk13b["picked"] == 1
              and next(r for r in pk13b["rows"] if r["bib"] == bA)["distance"] in (f"{D60}, {DM}", f"{DM}, {D60}"), str((pk13["total"], pkp, pk_rows)))

        # тёзки в одной дисциплине — разные люди; выравнивание «разъехавшихся» номеров; номер подхватывается в новой дисциплине
        e12 = api("POST", "/api/events", {"name": "Тёзки и сквозные номера", "kind": "stadium", "timing": "manual", "finish_device": "JUDGE",
                                          "date": "2026-10-18"})[1]["id"]
        api("POST", f"/api/events/{e12}", {"reg_distances": f"{D60}\n{DM}", "reg_rules": "Девочки до 14 лет;Ж;2012;2013"})

        def man_reg(eid_, last, first, year, dists):
            return api("POST", f"/api/events/{eid_}/regs", {"last_name": last, "first_name": first, "birth_date": f"{year}-04-04", "sex": "Ж",
                       "team": "СШОР", "rank": "Б/р", "representative": "Р", "policy": True, "distances": [{"distance": d_} for d_ in dists]})
        t1 = man_reg(e12, "Петрова", "Анна", 2012, [D60, DM])
        t2 = man_reg(e12, "Петрова", "Анна", 2013, [D60])
        bt = json.loads(http("GET", f"/api/events/{e12}/bibs?distance=" + urllib.parse.quote(D60))[1])
        pe = {r["birth_year"]: r for r in bt["rows"]}
        check("7.0: тёзки (Петрова Анна 2012 и 2013) в одной дисциплине — две разные строки шага 2; у старшей видна вторая дисциплина",
              t1[0] == 201 and t2[0] == 201 and bt["total"] == 2 and pe["2012"]["ids"] != pe["2013"]["ids"]
              and len(pe["2012"]["also"]) == 1 and pe["2013"]["also"] == [], str(bt["rows"]))
        c_, sv = api("POST", f"/api/events/{e12}/bibs", {"rows": [{"ids": pe["2012"]["ids"], "bib": "1"}, {"ids": pe["2013"]["ids"], "bib": "2"}]})
        check("7.0: тёзкам можно дать разные номера (saved=2); spread=1 — только у той, что заявлена на две дисциплины",
              c_ == 200 and sv["saved"] == 2 and sv["spread"] == 1, str(sv))
        c_, sv = api("POST", f"/api/events/{e12}/bibs", {"rows": [{"ids": pe["2013"]["ids"], "bib": "1"}]})
        check("7.0: номер тёзки другому тёзке — 400", c_ == 400 and sv.get("errors"), str(sv))
        # старые разъехавшиеся номера (101 и 201 у одного человека) выравниваются сохранением
        dbq = _sql.connect(cfg["db_path"], isolation_level=None)
        dbq.execute("UPDATE registrations SET bib = '101' WHERE event_id = ? AND last_name = 'Петрова' AND birth_date LIKE '2012%' AND distance = ?", (e12, D60))
        dbq.execute("UPDATE registrations SET bib = '201' WHERE event_id = ? AND last_name = 'Петрова' AND birth_date LIKE '2012%' AND distance = ?", (e12, DM))
        dbq.close()
        bt = json.loads(http("GET", f"/api/events/{e12}/bibs?distance=" + urllib.parse.quote(D60))[1])
        pe = {r["birth_year"]: r for r in bt["rows"]}
        check("7.0: разъехавшиеся номера (101 в беге, 201 в метании у одного человека) видны на шаге 2 как расхождение",
              pe["2012"]["bib"] == "101" and pe["2012"]["mismatch"] is True and pe["2012"]["also"] == [{"distance": DM, "bib": "201"}]
              and pe["2013"]["mismatch"] is False, str(pe["2012"]))
        c_, sv = api("POST", f"/api/events/{e12}/bibs", {"rows": [{"ids": pe["2012"]["ids"], "bib": "101"}]})
        dbq = _sql.connect(cfg["db_path"])
        rg = dbq.execute("SELECT distance, bib FROM registrations WHERE event_id = ? AND last_name = 'Петрова' AND birth_date LIKE '2012%'", (e12,)).fetchall()
        dbq.close()
        bt = json.loads(http("GET", f"/api/events/{e12}/bibs?distance=" + urllib.parse.quote(D60))[1])
        check("7.0: сохранение выравнивает номера: 101 стоит в обеих дисциплинах, расхождения нет",
              c_ == 200 and sv["saved"] == 1 and sv["spread"] == 1 and sorted(rg) == sorted([(D60, "101"), (DM, "101")])
              and not {r["birth_year"]: r for r in bt["rows"]}["2012"]["mismatch"], f"{sv} {rg}")
        # новая дисциплина у человека с номером: заявка добавлена позже — номер подхватывается без повторного ввода
        t3 = man_reg(e12, "Петрова", "Анна", 2013, [DM])
        bm = json.loads(http("GET", f"/api/events/{e12}/bibs?distance=" + urllib.parse.quote(DM))[1])
        pm = {r["birth_year"]: r for r in bm["rows"]}
        check("7.0: у младшей Петровой заявка на метание добавлена позже — на шаге 2 уже стоит её номер 2 («inherited»), вписывать не нужно",
              t3[0] == 201 and pm["2013"]["bib"] == "2" and pm["2013"]["inherited"] is True and pm["2012"]["inherited"] is False
              and pm["2012"]["bib"] == "101", str(bm["rows"]))
        c_, ga = api("POST", f"/api/events/{e12}/heats", {"distance": D60, "lanes": 8})
        c2_, gb = api("POST", f"/api/events/{e12}/heats", {"distance": DM, "lanes": 8})
        ents12 = sl_entries(e12)
        sig = sorted((e_["bib"], e_["distance"]) for e_ in ents12)
        check("7.0: сетки двух дисциплин построены без повторного ввода: у младшей Петровой в метании тот же номер 2, у старшей — 101 в обеих",
              c_ == 200 and c2_ == 200 and sig == sorted([("101", D60), ("101", DM), ("2", D60), ("2", DM)]), str(sig))
        dbq = _sql.connect(cfg["db_path"])
        late_reg = dbq.execute("SELECT bib FROM registrations WHERE event_id = ? AND distance = ? AND birth_date LIKE '2013%'", (e12, DM)).fetchone()
        dbq.close()
        check("7.0: после генерации номер записан и в registrations.bib заявки, добавленной позже", late_reg and late_reg[0] == "2", str(late_reg))

        # ===================== 7.0: принудительный сброс сетки и пересборка 13 → 21 =====================
        def wave_names(eid_, dist_):
            return [w["name"] for w in json.loads(http("GET", f"/api/events/{eid_}")[1])["waves"] if w.get("distance") == dist_]

        def ev_state(eid_):
            v_ = json.loads(http("GET", f"/api/events/{eid_}")[1])
            return v_["status"], v_.get("start_time"), {w["name"]: w.get("start_time") for w in v_["waves"]}
        wm = wave_names(e13, DM)
        w60_ = wave_names(e13, D60)
        # время старта выставлено по ошибке в технической дисциплине
        c_, _ = api("POST", f"/api/events/{e13}/start", {"wave": wm[0]})
        stt, st_time, wst = ev_state(e13)
        check("7.0: старт «по ошибке» поставлен в технической дисциплине (метание): забег стартовал, соревнование идёт",
              c_ == 200 and len(wm) == 1 and wm[0].startswith("Общий список") and wst[wm[0]] and stt == "running", f"{wm} {stt} {wst}")
        nb = [reg13("Новикова" + letters[i]) for i in range(8)]
        c_, rv21 = api("POST", f"/api/events/{e13}/regs", {"approve_all": True})
        check("7.0: ещё 8 девочек подали заявки и подтверждены (теперь 21 человек, 42 заявки)",
              nb == [201] * 8 and rv21["counts"]["approved"] == 42, str(rv21.get("counts")))
        give_bibs(e13, 14)
        c_, rb = api("POST", f"/api/events/{e13}/heats", {"distance": DM, "lanes": 8})
        check("7.0: пересборка без сброса после старта — 400 «стоит время старта — нажмите «Сбросить сетку»»",
              c_ == 400 and "стоит время старта" in rb["error"] and "Сбросить сетку" in rb["error"], str(rb))
        keep = fin_by(e13)
        c_, rr = api("POST", f"/api/events/{e13}/resetheats", {"distance": DM})
        stt, st_time, wst = ev_state(e13)
        sl13 = json.loads(http("GET", f"/api/events/{e13}/startlist")[1])
        dm_rows = [e_ for e_ in sl13["no_heat"] if e_["distance"] == DM]
        check("7.0: сброс сетки метания НЕ блокируется стартом: ответ {waves:1, entries:13, stopped:[имя забега]}; время старта обнулено, "
              "часы события остановлены (planned, start_time пусто), участники в «нераспределённых»",
              c_ == 200 and rr == {"waves": 1, "entries": 13, "stopped": wm} and wm[0] not in wst and stt == "planned" and not st_time
              and len(dm_rows) == 13 and all(e_["wave"] is None and e_["lane"] is None for e_ in dm_rows), f"{rr} {stt} {st_time} {len(dm_rows)}")
        check("7.0: сброс одной дисциплины не тронул бег (2 забега с 13 участницами), номера и введённые результаты целы",
              sorted(wave_names(e13, D60)) == sorted(w60_) and len([e_ for h in sl13["heats"] for e_ in h["entries"]]) == 13
              and all(k in fin_by(e13) for k in keep), f"{wave_names(e13, D60)} {w60_}")
        c_, g21 = api("POST", f"/api/events/{e13}/heats", {"distance": DM, "lanes": 8})
        c2_, g21b = api("POST", f"/api/events/{e13}/heats", {"distance": D60, "lanes": 8})
        ents21 = sl_entries(e13)
        check("7.0: после сброса список формируется заново и подтягивает ВСЕХ подтверждённых: было 13 → стало 21 (метание и бег), всего 42 строки",
              c_ == 200 and g21["entries"] == 21 and c2_ == 200 and g21b["entries"] == 21 and len(ents21) == 42
              and len({e_["bib"] for e_ in ents21}) == 21, f"{g21.get('entries')} {g21b.get('entries')} {len(ents21)}")
        check("7.0: введённые результаты пережили сброс и пересборку", all(k in fin_by(e13) for k in keep), str(sorted(keep)))
        pk21 = json.loads(http("GET", f"/api/events/{e13}/pickup")[1])
        check("7.0: выдача номеров после пересборки: 21 человек, отметка «выдан» сохранилась", pk21["total"] == 21 and pk21["picked"] == 1, str((pk21["total"], pk21["picked"])))
        # ошибочный старт в беге и в технике одновременно: сброс одной дисциплины не останавливает часы, пока стоит старт другой
        w60_ = wave_names(e13, D60)
        wm = wave_names(e13, DM)
        api("POST", f"/api/events/{e13}/start", {"wave": w60_[0]})
        api("POST", f"/api/events/{e13}/start", {"wave": wm[0]})
        c_, rr1 = api("POST", f"/api/events/{e13}/resetheats", {"distance": DM})
        stt1, stm1, _ = ev_state(e13)
        c2_, rr2 = api("POST", f"/api/events/{e13}/resetheats", {"distance": D60})
        stt2, stm2, wst2 = ev_state(e13)
        check("7.0: два ошибочных старта: после сброса метания часы идут (стартовавший бег остался), после сброса бега — остановлены; "
              "ответ перечисляет стартовавшие забеги",
              c_ == 200 and rr1["stopped"] == wm and stt1 == "running" and stm1 and c2_ == 200 and rr2["stopped"] == [w60_[0]]
              and stt2 == "planned" and not stm2 and not wst2, f"{rr1} {stt1} {rr2} {stt2} {wst2}")
        api("POST", f"/api/events/{e13}/heats", {"distance": D60, "lanes": 8})
        api("POST", f"/api/events/{e13}/heats", {"distance": DM, "lanes": 8})
        w60_ = wave_names(e13, D60)
        api("POST", f"/api/events/{e13}/start", {"wave": w60_[0]})
        c_, rr3 = api("POST", f"/api/events/{e13}/reset", {})
        stt3, stm3, wst3 = ev_state(e13)
        check("7.0: «Сбросить старт» всего соревнования по-прежнему обнуляет время всех забегов",
              c_ == 200 and stt3 == "planned" and not stm3 and not any(wst3.values()), f"{stt3} {wst3}")
        c_, rr4 = api("POST", f"/api/events/{e13}/resetheats", {"distance": "Прыжок в высоту"})
        check("7.0: сброс несуществующей в сетке дисциплины безвреден: {waves:0, entries:0}", c_ == 200 and rr4["waves"] == 0 and rr4["entries"] == 0, str(rr4))

        # ===================== 7.1: открытый список «прошли регистрацию» и очистка номеров дисциплины =====================
        c_, e14v = api("POST", "/api/events", {"name": "Первенство для списков", "date": "2026-10-20", "kind": "stadium", "timing": "manual"})
        e14 = e14v["id"]
        c_, evr14 = api("POST", f"/api/events/{e14}", {"reg_open": True, "reg_rules": "Девочки до 14 лет;Ж;2012;2013", "reg_distances": f"{DM}\n60 м"})
        s14 = evr14["reg_path"].rsplit("/", 1)[-1]

        def reg14(last, first, year, dists):
            body = {"last_name": last, "first_name": first, "birth_date": f"{year}-04-04", "sex": "Ж", "team": "Секретная команда",
                    "coach": "Тренер Т.Т.", "contact": "+79140000000", "consent": True, "policy": True, "representative": "Родитель Р.Р.",
                    "rank": "3 юн.", "distances": [{"distance": d_, "best": "20" if d_ == DM else "9.5"} for d_ in dists]}
            return pub("POST", f"/r/{s14}", json.dumps(body).encode())[0]
        codes14 = [reg14("Петрова", "Мария", "2013", (DM, D60)), reg14("Сидорова", "Ольга", "2013", (D60,)), reg14("Ждущая", "Ирина", "2013", (D60,)),
                   reg14("Старшая", "Анна", "2002", (D60,))]
        regs14 = json.loads(http("GET", f"/api/events/{e14}/regs")[1])["regs"]
        for r_ in regs14:        # «Ждущая» остаётся на проверке: в списке её быть не должно
            if r_["last_name"] != "Ждущая":
                api("POST", f"/api/events/{e14}/regs/{r_['id']}", {"status": "approved"})
        c_, t_, _ = pub("GET", f"/r/{s14}/registered.json")
        check("7.1: открытый список не опубликован, пока секретарь не включил его (404)", codes14 == [201] * 4 and c_ == 404, f"{codes14} {c_} {t_[:80]}")
        c_, pb14 = api("POST", f"/api/events/{e14}/publish", {"regs": True})
        c_, t_, _ = pub("GET", f"/r/{s14}/registered.json")
        rl14 = json.loads(t_) if c_ == 200 else {}
        flat14 = {a["name"]: (g["group"], a["disciplines"]) for g in rl14.get("groups", []) for a in g["athletes"]}
        check("7.1: открытый список без входа: «Фамилия И.», возрастная группа из AGES и дисциплины одобренных заявок; неодобренные не видны",
              c_ == 200 and pb14.get("pub_regs") is True and rl14["total"] == 3
              and flat14.get("Петрова М.") == ("до 14 лет", [DM, D60]) and flat14.get("Сидорова О.") == ("до 14 лет", [D60])
              and flat14.get("Старшая А.", ("",))[0] == "взрослые" and "Ждущая И." not in flat14, t_[:300])
        leak = [w for w in ("Мария", "Ольга", "2013", "bib", "birth", "lane", "Секретная", "Тренер", "79140000000", "Родитель", "contact", "coach", "team", "rank")
                if w in t_]
        check("7.1: в открытом списке нет полных имён, дат рождения, номеров, дорожек, команд, тренеров и контактов", not leak, str(leak))
        c_, t_, _ = pub("GET", f"/r/{s14}/startlist.json")
        c2_, t2_, _ = pub("GET", f"/r/{s14}/results.json")
        c3_, t3_, _ = pub("GET", f"/r/{s14}/protocol")
        check("7.1: полные протоколы по-прежнему закрыты без входа: нужен личный кабинет", c_ == 401 and c2_ == 401 and c3_ in (302, 401), f"{c_} {c2_} {c3_}")
        c_, t_, _ = pub("GET", f"/r/{s14}/info")
        check("7.1: страница события знает, что список опубликован (regs_public)", c_ == 200 and json.loads(t_).get("regs_public") is True, t_[:120])
        api("POST", f"/api/events/{e14}/publish", {"regs": False})
        c_, t_, _ = pub("GET", f"/r/{s14}/registered.json")
        check("7.1: публикацию списка можно снять — снова 404", c_ == 404, str(c_))

        # очистка номеров дисциплины
        bv = json.loads(http("GET", f"/api/events/{e14}/bibs?distance=" + urllib.parse.quote(D60))[1])
        api("POST", f"/api/events/{e14}/bibs", {"rows": [{"ids": r["ids"], "bib": str(70 + i)} for i, r in enumerate(bv["rows"])]})
        api("POST", f"/api/events/{e14}/heats", {"distance": D60, "lanes": 8})
        api("POST", f"/api/events/{e14}/heats", {"distance": DM, "lanes": 8})
        c_, ce1 = api("POST", f"/api/events/{e14}/clear-bibs", {})
        check("7.1: очистка номеров без указания дисциплины отклоняется", c_ == 400, str(ce1))
        first_bib = bv["rows"][0]["bib"] or "70"
        c_, rs14 = api("POST", f"/api/events/{e14}/results", {"rows": [{"bib": "70", "distance": D60, "t": ["9.5"], "auto": True}]})
        c_, ce2 = api("POST", f"/api/events/{e14}/clear-bibs", {"distance": D60})
        bvk = json.loads(http("GET", f"/api/events/{e14}/bibs?distance=" + urllib.parse.quote(D60))[1])
        check("7.1: если у кого-то уже введён результат — очистка номеров отклоняется целиком, ничего не стёрто",
              c_ == 400 and "результат" in ce2.get("error", "") and bvk["with_bib"] == bvk["total"] > 0, str(ce2))
        api("POST", f"/api/events/{e14}/clearresults", {"bibs": ["70"], "distance": D60})
        c_, ce3 = api("POST", f"/api/events/{e14}/clear-bibs", {"distance": D60})
        bv60k = json.loads(http("GET", f"/api/events/{e14}/bibs?distance=" + urllib.parse.quote(D60))[1])
        bvmk = json.loads(http("GET", f"/api/events/{e14}/bibs?distance=" + urllib.parse.quote(DM))[1])
        sl14 = json.loads(http("GET", f"/api/events/{e14}/startlist")[1])
        dbq = _sql.connect(cfg["db_path"])
        nbib = dbq.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ? AND bib IS NOT NULL AND bib != ''", (e14,)).fetchone()[0]
        nent = dbq.execute("SELECT COUNT(*) FROM entries WHERE event_id = ?", (e14,)).fetchone()[0]
        dbq.close()
        check("7.1: «Очистить все номера дисциплины»: bib = NULL у всех участников дисциплины и у них же в метании, сетки убраны, поля пусты",
              c_ == 200 and ce3["people"] == 4 and ce3["entries"] == 4 and DM in ce3["also"] and bv60k["with_bib"] == 0 and bvmk["with_bib"] == 0
              and nbib == 0 and nent == 0 and not sl14["heats"], f"{ce3} {nbib} {nent}")
        c_, sv = api("POST", f"/api/events/{e14}/bibs", {"rows": [{"ids": r["ids"], "bib": str(90 + i)} for i, r in enumerate(bv60k["rows"])]})
        check("7.1: после очистки номера вписываются и сохраняются заново (кнопка сохранения не затронута)", c_ == 200 and sv.get("saved") == 3, str(sv))


    except Exception as e:  # noqa
        failed = True
        check("непредвиденная ошибка", False, repr(e))
        import traceback
        traceback.print_exc()
    finally:
        out = stop_server(proc)
        check("сервер корректно останавливается", proc.returncode == 0, f"код {proc.returncode}")
        if out.strip():
            print("--- журнал сервера ---")
            print(out.strip()[-3000:])

    bad = [r for r in RESULTS if not r[1]]
    print()
    print(f"Итого: {len(RESULTS) - len(bad)} из {len(RESULTS)} проверок пройдено.")
    if bad or failed:
        print("ЕСТЬ ОШИБКИ — см. FAIL выше.")
        return 1
    print("Всё работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
