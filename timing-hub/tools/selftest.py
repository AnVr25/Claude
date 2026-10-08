#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Самопроверка сервера хронометража.

Запускает отдельную копию сервера на 127.0.0.1 со своей временной базой
(рабочий сервер не трогает), имитирует ридеры и Wiclax и проверяет всю цепочку.

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
import threading
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


class WiclaxSim:
    """Подключается как Wiclax и собирает всё, что пришло."""

    def __init__(self, port: int):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.sock.settimeout(0.2)
        self.lines: list = []
        self.buf = b""
        self.lock = threading.Lock()
        self.alive = True
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self):
        while self.alive:
            try:
                d = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not d:
                break
            self.buf += d
            *ls, self.buf = self.buf.split(b"\r")
            with self.lock:
                self.lines.extend(x.decode() for x in ls if x)

    def send(self, cmd: str):
        self.sock.sendall((cmd + "\r").encode())

    def snapshot(self) -> list:
        with self.lock:
            return list(self.lines)

    def wait_for(self, pred, timeout=5.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if pred(self.snapshot()):
                return True
            time.sleep(0.05)
        return False

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=os.path.join(HERE, "..", "hub", "hub.py"))
    args = ap.parse_args()
    hub_path = os.path.abspath(args.hub)
    if not os.path.exists(hub_path):
        print(f"не найден {hub_path}")
        return 2

    tmp = tempfile.mkdtemp(prefix="timing-hub-selftest-")
    p_push, p_pull, p_wic, p_web, p_pub = free_port(), free_port(), free_port(), free_port(), free_port()
    cfg = {
        "db_path": os.path.join(tmp, "reads.db"),
        "log_level": "WARNING",
        "wiclax": {"listen_host": "127.0.0.1", "listen_port": p_wic, "heartbeat_sec": 1,
                   "forward_filter_sec": 3},
        "web": {"listen_host": "127.0.0.1", "listen_port": p_web, "user": "admin",
                "password": "test-pass", "api_key": "test-key"},
        "public": {"enabled": True, "listen_host": "127.0.0.1", "listen_port": p_pub, "url": "https://reg.example.ru"},
        "sources": [
            {"id": "FINISH", "name": "Финиш (push)", "mode": "listen", "listen_host": "127.0.0.1",
             "listen_port": p_push, "parser": "auto"},
            {"id": "KM5", "name": "5 км (connect)", "mode": "connect", "host": "127.0.0.1", "port": p_pull,
             "parser": "regex",
             "pattern": r"^(?P<chip>[0-9A-F]+),(?P<datetime>[0-9-]+ [0-9:.]+),(?P<antenna>\d+)",
             "datetime_format": "%Y-%m-%d %H:%M:%S.%f"},
            {"id": "HTTP", "name": "Через HTTP", "mode": "http", "parser": "auto"},
        ],
    }
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)

    # 0. проверка настроек
    r = subprocess.run([sys.executable, hub_path, "--config", cfg_path, "--check"],
                       capture_output=True, text=True)
    check("настройки читаются (--check)", r.returncode == 0, r.stderr.strip())
    r = subprocess.run([sys.executable, hub_path, "--config", cfg_path, "--test-parse", "KM5",
                        "E2801160600002000000AA01,2026-10-06 10:00:00.250,2,-50"], capture_output=True, text=True)
    check("проверка разбора строки (--test-parse)", r.returncode == 0 and "E2801160600002000000AA01" in r.stdout,
          r.stdout + r.stderr)

    # ридер в режиме «сервер ждёт подключения» (для mode=connect)
    pull_srv = socket.socket()
    pull_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    pull_srv.bind(("127.0.0.1", p_pull))
    pull_srv.listen(1)
    pull_srv.settimeout(15)

    proc = subprocess.Popen([sys.executable, hub_path, "--config", cfg_path],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    failed = False
    try:
        check("сервер запустился", wait_port(p_wic) and wait_port(p_web) and wait_port(p_push))

        wic = WiclaxSim(p_wic)
        wic.send("HELLO")
        wic.send("CLOCK")
        check("ответ на CLOCK", wic.wait_for(lambda L: any(x.startswith("CLOCK ") for x in L)))
        check("сигнал «на связи» (*)", wic.wait_for(lambda L: "*" in L, timeout=3))

        now = dt.datetime.now().replace(microsecond=0)
        t0 = now - dt.timedelta(seconds=30)

        def ts(sec, ms=0):
            x = t0 + dt.timedelta(seconds=sec, milliseconds=ms)
            return x

        # 1. ридер сам подключается (push), по 5 считываний на прохождение
        push = socket.create_connection(("127.0.0.1", p_push))
        lines = []
        for chip, sec in (("E2801160600002000000AA01", 0), ("E2801160600002000000AA02", 2)):
            for k in range(5):
                x = ts(sec, 80 * k)
                lines.append(f"{chip},{x:%Y-%m-%d %H:%M:%S}.{x.microsecond // 1000:03d},1,-55")
        push.sendall(("\r\n".join(lines) + "\r\n").encode())
        ok = wic.wait_for(lambda L: sum(1 for x in L if ";FINISH;" in x) >= 2)
        got = [x for x in wic.snapshot() if ";FINISH;" in x]
        check("push: отметки дошли до Wiclax", ok, str(got))
        time.sleep(0.5)
        got = [x for x in wic.snapshot() if ";FINISH;" in x]
        check("push: повторы склеены (2 прохождения из 10 считываний)", len(got) == 2, str(got))
        exp = f"E2801160600002000000AA01;{ts(0):%d-%m-%Y %H:%M:%S}.000;FINISH;;;0"
        check("формат строки для Wiclax", exp in got, f"ждали {exp}, пришло {got}")

        # 2. ридер повторно выгрузил всю память после обрыва связи
        push.sendall(("\r\n".join(lines) + "\r\n").encode())
        time.sleep(0.7)
        got2 = [x for x in wic.snapshot() if ";FINISH;" in x]
        check("повторная выгрузка памяти не дублирует отметки", len(got2) == 2, str(got2))
        push.close()

        # 3. сервер сам подключается к ридеру (connect)
        conn, _ = pull_srv.accept()
        x = ts(5, 250)
        conn.sendall(f"E2801160600002000000AA03,{x:%Y-%m-%d %H:%M:%S}.250,3,-60\n".encode())
        ok = wic.wait_for(lambda L: any("AA03" in y and ";KM5;" in y for y in L))
        check("connect: сервер подключился к ридеру и получил отметку", ok)

        # 4. обрыв связи с ридером и переподключение
        conn.close()
        conn, _ = pull_srv.accept()
        x = ts(9, 0)
        conn.sendall(f"E2801160600002000000AA04,{x:%Y-%m-%d %H:%M:%S}.000,1,-60\n".encode())
        ok = wic.wait_for(lambda L: any("AA04" in y for y in L))
        check("connect: переподключение после обрыва", ok)
        conn.close()

        # 5. приём по HTTP (JSON и текст)
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

        x = ts(12, 500)
        body = json.dumps([{"chip": "AA05", "time": f"{x:%Y-%m-%d %H:%M:%S}.500", "antenna": 1},
                           {"chip": "AA06", "time": x.timestamp()},
                           {"chip": "", "time": "bad"}]).encode()
        code, txt = http("POST", "/api/reads?source=HTTP", body,
                         {"Content-Type": "application/json", "X-Api-Key": "test-key"}, auth=False)
        check("HTTP JSON: принято 2, отклонено 1", code == 200 and json.loads(txt) == {"accepted": 2, "rejected": 1},
              f"{code} {txt}")
        code, txt = http("POST", "/api/reads?source=HTTP", b"AA07 " + f"{x:%H:%M:%S}".encode() + b".900\n",
                         {"Content-Type": "text/plain", "X-Api-Key": "wrong"}, auth=False)
        check("HTTP: неверный ключ отклонён", code == 401, f"{code}")
        code, txt = http("POST", "/api/reads?source=HTTP", b"AA07 " + f"{x:%H:%M:%S}".encode() + b".900\n",
                         {"Content-Type": "text/plain", "X-Api-Key": "test-key"}, auth=False)
        check("HTTP текст: строка принята", code == 200 and '"accepted": 1' in txt, f"{code} {txt}")
        ok = wic.wait_for(lambda L: all(any(c in y for y in L) for c in ("AA05", "AA06", "AA07")))
        check("HTTP: отметки дошли до Wiclax", ok)

        # 6. STOPREAD / STARTREAD
        wic.send("STOPREAD")
        check("STOPREAD -> READOK", wic.wait_for(lambda L: L.count("READOK") >= 1))
        push = socket.create_connection(("127.0.0.1", p_push))
        x = ts(15)
        push.sendall(f"AA08 {x:%Y-%m-%d %H:%M:%S}.000\n".encode())
        time.sleep(0.7)
        check("на паузе отметки в Wiclax не идут", not any("AA08" in y for y in wic.snapshot()))
        wic.send("STARTREAD")
        check("STARTREAD -> READOK", wic.wait_for(lambda L: L.count("READOK") >= 2))
        push.close()

        # 7. REWIND — перезапрос отметок за период
        a = (t0 - dt.timedelta(seconds=1)).strftime("%d-%m-%Y %H:%M:%S")
        b = (t0 + dt.timedelta(seconds=20)).strftime("%d-%m-%Y %H:%M:%S")
        wic.send(f"REWIND {a} {b}")
        ok = wic.wait_for(lambda L: any("AA08" in y and y.endswith(";1") for y in L))
        rew = [y for y in wic.snapshot() if y.endswith(";1")]
        check("REWIND: пропущенная на паузе отметка пришла с флагом 1", ok, str(rew))
        chips = sorted({y.split(";")[0] for y in rew})
        exp_chips = sorted(["E2801160600002000000AA01", "E2801160600002000000AA02", "E2801160600002000000AA03",
                            "E2801160600002000000AA04", "AA05", "AA06", "AA07", "AA08"])
        check("REWIND: все 8 участников, без повторов", chips == exp_chips and len(rew) == 8, str(rew))

        # 8. установка часов из Wiclax
        wic.send(f"CLOCK {dt.datetime.now():%d-%m-%Y %H:%M:%S}")
        check("CLOCK <время> -> CLOCKOK", wic.wait_for(lambda L: "CLOCKOK" in L))

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
        check("судья после входа попадает на экран судьи", code == 200 and d.get("next") == "/judge", str(d))
        check("судья: соревнования и ручные отметки доступны, система — нет",
              cget("/api/events", jck) == 200 and cget("/api/system", jck) == 403 and cget("/api/users", jck) == 403)
        code, _, _ = jpost(f"/api/events/1/delete", {}, jck, True)
        check("судья не может удалить соревнование", code == 403, str(code))
        jpost("/api/logout", {}, jck, True)
        check("после выхода сессия не действует", cget("/api/events", jck) == 401)
        code, txt = http("GET", "/")
        check("страница состояния открывается", code == 200 and "Сервер хронометража" in txt, str(code))
        code, txt = http("GET", "/api/status")
        st = json.loads(txt) if code == 200 else {}
        check("JSON-статус: 16 уникальных считываний в базе", st.get("totals", {}).get("reads") == 16, txt[:300])
        fin = next((s for s in st.get("sources", []) if s["id"] == "FINISH"), {})
        check("JSON-статус: повторы посчитаны", fin.get("duplicates") == 10, str(fin))
        code, txt = http("GET", "/export.csv")
        check("CSV: все считывания (16 строк + заголовок)", code == 200 and len(txt.strip().splitlines()) == 17,
              f"{code} {len(txt.strip().splitlines())}")
        code, txt = http("GET", "/export.csv?filtered=1")
        check("CSV: только прохождения (8 + заголовок)", code == 200 and len(txt.strip().splitlines()) == 9,
              f"{code} {len(txt.strip().splitlines())}")
        code, txt = http("GET", "/raw?source=FINISH")
        check("сырые строки видны", code == 200 and "AA01" in txt)

        # 9b. соревнования: создание, номера, старт, результаты
        J = {"Content-Type": "application/json", "X-Requested-With": "timing-hub"}
        code, _ = http("POST", "/api/events", json.dumps({"name": "x"}).encode(), {"Content-Type": "application/json"})
        check("API: POST без X-Requested-With отклонён", code == 403, str(code))
        code, txt = http("POST", "/api/events", json.dumps({"name": "Тестовый забег", "date": t0.strftime("%Y-%m-%d"),
                         "finish_device": "FINISH", "push_wiclax": True}).encode(), J)
        ev = json.loads(txt) if code == 201 else {}
        check("API: соревнование создано", code == 201 and ev.get("id"), f"{code} {txt}")
        eid = ev.get("id")
        code, txt = http("POST", f"/api/events/{eid}/entries", json.dumps({"text":
                         "1;E2801160600002000000AA01\n2 e2801160600002000000aa02\nплохая строка\n9;ZZ99"}).encode(), J)
        check("API: список номеров (3 принято, 1 строка пропущена)",
              code == 200 and json.loads(txt) == {"count": 3, "bad_lines": [3]}, txt)
        st_t = t0 - dt.timedelta(seconds=1)
        code, txt = http("POST", f"/api/events/{eid}/start", json.dumps({"time": st_t.strftime("%H:%M:%S") + ".000"}).encode(), J)
        check("API: старт дан", code == 200 and json.loads(txt).get("status") == "running", txt)
        exp_rs = f"RACESTART {st_t:%H:%M:%S},000"
        check("старт отправлен в Wiclax (RACESTART)", wic.wait_for(lambda L: exp_rs in L), str(wic.snapshot()[-5:]))
        code, txt = http("GET", f"/api/events/{eid}/results")
        r = json.loads(txt) if code == 200 else {}
        fin = [(x["place"], x["bib"], x["time"]) for x in r.get("finished", [])]
        check("результаты: финиш по порядку с номерами",
              fin[:2] == [(1, "1", "0:00:01.0"), (2, "2", "0:00:03.0")] and len(fin) == 3, str(fin))
        check("результаты: на трассе и не отмеченные",
              len(r.get("on_course", [])) == 5 and [x["bib"] for x in r.get("not_seen", [])] == ["9"], txt[:400])
        code, txt = http("GET", f"/api/events/{eid}/results.csv")
        check("результаты: CSV", code == 200 and "Результат;Чип" in txt, str(code))
        code, txt = http("GET", f"/api/live?since=0&limit=50&event={eid}")
        lv = json.loads(txt) if code == 200 else {}
        check("лента: номер и время с начала", any(x.get("bib") == "1" and x.get("elapsed") for x in lv.get("reads", [])), txt[:300])
        code, txt = http("GET", "/board?event=" + str(eid))
        check("табло открывается", code == 200 and "Табло" in txt, str(code))
        code, txt = http("GET", "/api/events")
        check("список соревнований", code == 200 and len(json.loads(txt)["events"]) == 1, txt[:200])

        # 9c. волны, ручные отметки, предупреждения, проверка чипов, журнал
        code, txt = http("POST", "/api/events", json.dumps({"name": "Волны", "date": t0.strftime("%Y-%m-%d"),
                         "finish_device": "FINISH"}).encode(), J)
        e2 = json.loads(txt)["id"]
        code, txt = http("POST", f"/api/events/{e2}/entries", json.dumps({"text":
                         "1;E2801160600002000000AA01;A\n2;E2801160600002000000AA02;B\n50;;B"}).encode(), J)
        check("забеги: участники с волнами и без чипа", code == 200 and json.loads(txt)["count"] == 3, txt)
        _, txt = http("GET", f"/api/events/{e2}")
        check("забеги созданы из списка", sorted(w["name"] for w in json.loads(txt)["waves"]) == ["A", "B"], txt[:300])
        tA = (t0 - dt.timedelta(seconds=1)).strftime("%H:%M:%S")
        tB = (t0 + dt.timedelta(seconds=1)).strftime("%H:%M:%S")
        http("POST", f"/api/events/{e2}/start", json.dumps({"wave": "A", "time": tA}).encode(), J)
        code, txt = http("POST", f"/api/events/{e2}/start", json.dumps({"wave": "B", "time": tB}).encode(), J)
        check("забеги: старт каждой волны", code == 200 and all(w["start_time"] for w in json.loads(txt)["waves"]), txt[:300])
        tm = (t0 + dt.timedelta(seconds=10)).strftime("%H:%M:%S")
        code, txt = http("POST", f"/api/events/{e2}/manual", json.dumps({"bib": "50", "time": tm, "judge": "Иванов",
                         "client_id": "c1"}).encode(), J)
        check("ручная отметка с номером", code == 201, txt)
        http("POST", f"/api/events/{e2}/manual", json.dumps({"bib": "50", "time": tm, "client_id": "c1"}).encode(), J)
        code, txt = http("POST", f"/api/events/{e2}/manual", json.dumps({"epoch_ms": int(t0.timestamp() * 1000) + 20000,
                         "client_id": "c2"}).encode(), J)
        pend_id = json.loads(txt)["mark"]["id"] if code == 201 else None
        _, txt = http("GET", f"/api/events/{e2}/manual")
        check("повторная отправка с тем же client_id не дублирует", len(json.loads(txt)["marks"]) == 2, txt[:300])
        _, txt = http("GET", f"/api/events/{e2}/results")
        r2 = json.loads(txt)
        got = sorted((x["wave"], x["place"], x["bib"], x["time"], tuple(x["manual"])) for x in r2["finished"] if x["bib"])
        check("забеги: места и время считаются от старта своей волны",
              got == [("A", 1, "1", "0:00:01.0", ()), ("B", 1, "2", "0:00:01.0", ()), ("B", 2, "50", "0:00:09.0", ("FINISH",))],
              str(got))
        texts = " | ".join(a["text"] for a in r2["alerts"])
        check("предупреждения: отсечка без номера и чужие чипы",
              r2["manual_pending"] == 1 and "без номера" in texts and "не из списка" in texts, texts)
        code, txt = http("POST", f"/api/events/{e2}/manual/{pend_id}", json.dumps({"bib": "77"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e2}/results")
        r2 = json.loads(txt)
        check("номер вписан в отсечку позже", r2["manual_pending"] == 0 and any(x["bib"] == "77" for x in r2["finished"]),
              str(r2["finished"]))
        code, txt = http("POST", f"/api/events/{e2}/check", b"{}", J)
        check("проверка чипов: старт", code == 200 and json.loads(txt)["since"], txt)
        push = socket.create_connection(("127.0.0.1", p_push))
        x = dt.datetime.now()
        push.sendall(f"E2801160600002000000AA01,{x:%Y-%m-%d %H:%M:%S}.{x.microsecond // 1000:03d}\n".encode())
        push.close()
        time.sleep(0.6)
        _, txt = http("GET", f"/api/events/{e2}/check")
        ck = json.loads(txt)
        check("проверка чипов: проверен 1 из 2, номер 2 в списке непроверенных",
              ck["checked"] == 1 and ck["total"] == 2 and ck["unchecked"] == ["2"] and ck["last"][0]["bib"] == "1", txt[:300])
        _, txt = http("GET", f"/api/events/{e2}/log")
        acts = [a["action"] for a in json.loads(txt)["log"]]
        check("журнал действий", "СТАРТ «A»" in acts and "Ручная отметка" in acts and "Номер в ручной отметке" in acts,
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
        check("при завершении сохраняется снимок результатов", kinds == ["protocol", "snapshot"], str(kinds))
        snap = [f for f in json.loads(txt)["files"] if f["kind"] == "snapshot"][0]
        code, txt = http("GET", f"/files/{snap['id']}")
        check("снимок результатов читается", code == 200 and "Результат;Чип" in txt, txt[:120])
        code, txt = http("POST", f"/api/events/{e2}/archive", b"{}", J)
        check("перенос в архив", code == 200 and json.loads(txt)["archived"] == 1 and json.loads(txt)["files_count"] == 2, txt[:200])
        code, txt = http("POST", f"/api/events/{e2}/files/{fid}", json.dumps({"delete": True}).encode(), J)
        code2, _ = http("GET", f"/files/{fid}")
        check("удаление файла", code == 200 and code2 == 404, f"{code} {code2}")

        # 9e. стадион: судья, забеги по очереди, финиш забега, общий протокол
        code, txt = http("POST", "/api/events", json.dumps({"name": "Первенство города", "finish_device": "JUDGE",
                         "push_wiclax": False, "organizer": "РСОО ФЛАСО", "chief_judge": "Иванов И. И.",
                         "chief_secretary": "Петрова А. А.", "place": "Стадион «Спартак»"}).encode(), J)
        e3 = json.loads(txt)["id"]
        check("забеги: судейское соревнование — забеги по очереди", json.loads(txt).get("heats_sequential") is True, txt[:300])
        code, txt = http("POST", f"/api/events/{e3}/entries", json.dumps({"text":
                         "ФИО;Номер;Год;Забег;Команда\nИванов Иван;11;2008;Забег 1;СШОР\nПетров Пётр;12;2008;Забег 1;СШОР\n"
                         "Сидоров Олег;21;2009;Забег 2;Холмск\nКозлов Илья;31;2008;;Корсаков"}).encode(), J)
        check("участники по заголовкам колонок", code == 200 and json.loads(txt)["count"] == 4, txt)
        for wn in ("Забег 1", "Забег 2"):
            http("POST", f"/api/events/{e3}/waves", json.dumps({"name": wn, "category": "Юноши", "distance": "100 м"}).encode(), J)
        base = int(time.time() * 1000) - 120000
        def jpost(path, body):
            return http("POST", f"/api/events/{e3}/{path}", json.dumps(body).encode(), J)
        jpost("start", {"wave": "Забег 1", "epoch_ms": base})
        jpost("manual", {"bib": "11", "epoch_ms": base + 12310, "wave": "Забег 1", "client_id": "h1"})
        jpost("manual", {"bib": "12", "epoch_ms": base + 13000, "wave": "Забег 1", "client_id": "h2"})
        code, txt = jpost("start", {"wave": "Забег 2", "epoch_ms": base + 20000})
        w = {x["name"]: x for x in json.loads(txt)["waves"]}
        check("старт следующего забега завершает предыдущий",
              w["Забег 1"]["state"] == "finished" and w["Забег 1"]["finish_epoch_ms"] == base + 20000 and w["Забег 2"]["state"] == "running",
              str(w)[:300])
        jpost("manual", {"bib": "21", "epoch_ms": base + 32050, "wave": "Забег 2", "client_id": "h3"})
        code, txt = jpost("waves", {"name": "Забег 2", "finish": True, "epoch_ms": base + 34000})
        jpost("manual", {"bib": "99", "epoch_ms": base + 37000, "wave": "Забег 2", "client_id": "h4"})
        code, txt = jpost("waves", {"next": True})
        w3 = [x for x in json.loads(txt)["waves"] if x["name"] == json.loads(txt).get("created")]
        check("«Следующий забег»: Забег 3 с категорией и дистанцией предыдущего",
              w3 and w3[0]["name"] == "Забег 3" and w3[0]["category"] == "Юноши" and w3[0]["distance"] == "100 м", txt[-300:])
        jpost("start", {"wave": "Забег 3", "epoch_ms": base + 40000})
        jpost("manual", {"bib": "31", "epoch_ms": base + 51900, "wave": "Забег 3", "client_id": "h5"})
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

        def pub(method, path, body=None, ctype="application/json"):
            req = urllib.request.Request(f"http://127.0.0.1:{p_pub}{path}", data=body, method=method,
                                         headers={"Content-Type": ctype} if body is not None else {})
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode("utf-8"), dict(e.headers)

        code, txt, hd = pub("GET", f"/r/{slug}")
        check("форма открывается без пароля, с защитными заголовками",
              code == 200 and "Отправить заявку" in txt and "frame-ancestors" in hd.get("Content-Security-Policy", ""), str(code))
        for bad in ("/api/events", "/judge", "/", f"/api/events/{e4}/regs", "/r/../api/events", "/files/1"):
            code, _, _ = pub("GET", bad)
            check(f"публичный порт не отдаёт {bad}", code == 404, str(code))
        # стадион: результаты вписывает секретарь; публикация на сайте fla65.ru
        code, txt = http("POST", "/api/events", json.dumps({"name": "Стадион 60 м", "kind": "stadium", "timing": "manual",
                         "finish_device": "JUDGE", "pub_site": True}).encode(), J)
        es = json.loads(txt)
        check("стадион: событие создано с форматом и ручным хронометражем",
              es.get("kind") == "stadium" and es.get("timing") == "manual" and es.get("pub_site") and es.get("reg_slug"), txt[:200])
        http("POST", f"/api/events/{es['id']}/entries",
             json.dumps({"text": "Номер;Чип;Забег;ФИО\n11;;;Иванов Иван\n12;;;Петров Пётр\n13;;;Сидоров Сидор"}).encode(), J)
        code, txt = http("POST", f"/api/events/{es['id']}/results", json.dumps({"rows": [
            {"bib": "11", "result": "8,15"}, {"bib": "12", "result": "7.94"}, {"bib": "13", "status": "dnf"},
            {"bib": "99", "result": "9"}, {"bib": "11x", "result": "abc"}]}).encode(), J)
        rr = json.loads(txt)
        check("стадион: результаты сохранены, ошибки названы", rr["saved"] == 3 and len(rr["errors"]) == 2, txt[:300])
        _, txt = http("GET", f"/api/events/{es['id']}/results")
        rs = json.loads(txt)
        check("стадион: места по введённым результатам, DNF отдельно",
              [(x["bib"], x["place"], x["result"]) for x in rs["finished"]] == [("12", 1, "7.94"), ("11", 2, "8.15")]
              and any(x["bib"] == "13" and x.get("status") == "DNF" for x in rs["not_seen"]), txt[:300])
        code, txt, hd = pub("GET", "/r/api/calendar")
        cal = json.loads(txt)
        card = next((c for c in cal["events"] if c["name"] == "Стадион 60 м"), None)
        check("календарь для fla65.ru: событие видно, CORS открыт, страница есть",
              card and card["page"] and hd.get("Access-Control-Allow-Origin") == "*" and card["results"] is None, txt[:300])
        sslug = es["reg_slug"]
        code, _, _ = pub("GET", f"/r/{sslug}/results.json")
        check("результаты не опубликованы — на сайте не видны", code == 404, str(code))
        http("POST", f"/api/events/{es['id']}", json.dumps({"pub_results": True, "live_url": "https://vk.com/video1",
             "links": "Итоги | https://fla65.ru/news/1\nПлохая | javascript:alert(1)"}).encode(), J)
        code, txt, _ = pub("GET", f"/r/{sslug}/results.json")
        check("результаты опубликованы — на сайте без чипов, с результатом", code == 200 and '"chip"' not in txt and "Петров" in txt
              and any(x.get("result") == "7.94" for x in json.loads(txt)["finished"]), txt[:300])
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
                    "consent": True, "representative": "Родитель", "distances": dists, **kw}
            c, t, _ = pub("POST", f"/r/{slug}", json.dumps(body).encode())
            return c, json.loads(t)

        runners = [("Быстров", "Иван", "7.5"), ("Скоров", "Пётр", "7.9"), ("Ветров", "Олег", "8.4"),
                   ("Лётов", "Илья", ""), ("Ходов", "Глеб", "8.1"), ("Шагов", "Лев", "7.7")]
        for i, (ln, fn, best) in enumerate(runners):
            code, out = reg(ln, fn, f"2010-0{i + 1}-15", "М", [{"distance": "60 м", "best": best}])
        check("заявка принята, категория определена по году и полу", code == 201 and out["category"] == "Юноши", str(out))
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
        code, txt = http("POST", f"/api/events/{e4}/heats", json.dumps({"lanes": 4}).encode(), J)
        hs = json.loads(txt)
        check("забеги сформированы: 60 м Юноши ×2, 60 м Девушки, 300 м Девушки",
              code == 200 and [(h["distance"], h["category"], h["count"]) for h in hs["heats"]] ==
              [("60 м", "Юноши", 2), ("60 м", "Юноши", 3), ("60 м", "Девушки", 1), ("300 м", "Девушки", 1)], txt)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        sl = json.loads(txt)
        h2 = {e["name"].split()[0]: e["lane"] for e in sl["heats"][1]["entries"]}
        h1 = [e["name"].split()[0] for e in sl["heats"][0]["entries"]]
        check("посев: сильнейшие в последнем забеге, лучший — на центральной дорожке",
              h2 == {"Быстров": 2, "Шагов": 3, "Скоров": 1} and sorted(h1) == ["Ветров", "Лётов"], f"{h1} {h2}")
        bibs = sorted(int(e["bib"]) for h in sl["heats"] for e in h["entries"])
        check("стартовые номера присвоены по порядку", bibs == list(range(1, 8)), str(bibs))
        anna = [e for e in sl["heats"][2]["entries"]][0]
        code, txt = http("POST", f"/api/events/{e4}/entry", json.dumps({"bib": [e["bib"] for e in sl["heats"][0]["entries"]
                         if e["name"].startswith("Лётов")][0], "wave": "Забег 2"}).encode(), J)
        _, txt = http("GET", f"/api/events/{e4}/startlist")
        sl = json.loads(txt)
        check("перенос участника в другой забег", len(sl["heats"][1]["entries"]) == 4 and len(sl["heats"][0]["entries"]) == 1
              and sorted(e["lane"] for e in sl["heats"][1]["entries"]) == [1, 2, 3, 4], str(sl["heats"][1]["entries"])[:300])
        # поздняя заявка после формирования забегов — добавляется вручную
        code, out = reg("Поздняков", "Яков", "2010-09-09", "М", [{"distance": "60 м", "best": "8.0"}])
        late = out["ids"][0]
        http("POST", f"/api/events/{e4}/regs/{late}", json.dumps({"status": "approved"}).encode(), J)
        code, txt = http("POST", f"/api/events/{e4}/entry", json.dumps({"reg_id": late, "wave": "Забег 1"}).encode(), J)
        check("поздняя заявка добавлена в забег с новым номером", code == 200 and json.loads(txt)["bib"] == "8", txt)
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
        code, txt = http("POST", f"/api/events/{e4}/heats", json.dumps({"lanes": 4}).encode(), J)
        check("после старта пересобрать забеги нельзя", code == 400, txt)
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
                  ["Командов", "Пётр", "", 40365, "м", "60м", "8,1", "", "", ""],
                  ["Командова", "Анна", "", "03.03.2011", "Ж", "300 м", "52.4", "", "", ""],
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
                            "consent": True, "rows": rows}).encode(), {"Content-Type": "application/json"})
        check("команда с ошибками в файле не принимается", code == 400 and out.get("check", {}).get("bad") == 1, str(out)[:200])
        code, out = pub_raw(f"/r/{slug}/team", json.dumps({"team": "Корсаков", "coach": "", "contact": "", "consent": False,
                            "rows": rows[:2]}).encode(), {"Content-Type": "application/json"})
        check("без тренера, контакта и согласия — ошибка", code == 400 and set(out.get("fields", {})) == {"coach", "contact", "consent"}, str(out))
        code, out = pub_raw(f"/r/{slug}/team", json.dumps({"team": "Корсаков", "coach": "Тренеров Т.Т.", "contact": "8-900",
                            "consent": True, "rows": rows[:2]}).encode(), {"Content-Type": "application/json"})
        check("командная заявка принята: 2 участника", code == 201 and out["added"] == 2, str(out))
        code, out = pub_raw(f"/r/{slug}/team", json.dumps({"team": "Корсаков", "coach": "Тренеров Т.Т.", "contact": "8-900",
                            "consent": True, "rows": rows[:2]}).encode(), {"Content-Type": "application/json"})
        check("повторная отправка той же команды — повторы пропущены", code == 201 and out["added"] == 0 and len(out["duplicates"]) == 2, str(out))
        _, txt = http("GET", f"/api/events/{e4}/regs")
        kr = [r for r in json.loads(txt)["regs"] if r["team"] == "Корсаков"]
        check("заявки команды: статус «на рассмотрении», тренер и категория", len(kr) == 2 and all(
            r["status"] == "pending" and r["coach"] == "Тренеров Т.Т." for r in kr) and {r["category"] for r in kr} == {"Юноши", "Девушки"},
              str(kr)[:300])
        # секретарь: импорт файла в админке — сразу подтверждено
        csvb = "Фамилия;Имя;Дата рождения;Пол;Дистанция;Лучший результат;Команда\nИмпортов;Иван;01.01.2010;М;60 м;7,9;Анива\n".encode("cp1251")
        r = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e4}/import?team=", data=csvb, method="POST",
                                   headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode(),
                                            "X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(r, timeout=5) as resp:
            out = json.loads(resp.read())
        _, txt = http("GET", f"/api/events/{e4}/regs")
        imp = [x for x in json.loads(txt)["regs"] if x["last_name"] == "Импортов"]
        check("импорт CSV (windows-1251) секретарём — сразу подтверждено", out["added"] == 1 and imp and imp[0]["status"] == "approved", str(out))
        r = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e4}/template.xlsx",
                                   headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode()})
        with urllib.request.urlopen(r, timeout=5) as resp:
            check("шаблон Excel в админке", resp.status == 200 and resp.read()[:2] == b"PK", str(resp.status))
        _, txt = http("GET", f"/api/events/{e4}/regs")
        dr = json.loads(txt)["default_rules"]
        check("образец категорий: до 12/14/16/18/20/23 и взрослые от года соревнований",
              "Мальчики до 12 лет;М;2015;" in dr and "Юноши до 16 лет;М;2011;2012" in dr and "Мужчины до 23 лет;М;2004;2006" in dr
              and "Женщины;Ж;;2003" in dr, dr)

        # обмен с Wiclax: импорт .clax (участники, дистанции, чипы из прохождений) и экспорт CSV
        clax = ('<?xml version="1.0" encoding="utf-8"?><Epreuve nom="TEST" dates="1 октября 2026 г."><Etapes><Etape><Engages>'
                '<E d="7" n="ТЕСТОВ ТЕСТ Тестович" a="2010" x="M" p="4000 м юноши" />'
                '<E d="8" n="ПРОБОВА ПРОБА" c="ЛИН" a="2011" x="F" p="2000 м Девочки" />'
                '<E d="9" n="БЕЗЧИПОВ ИВАН" a="1990" x="M" p="4000 м юноши" /></Engages>'
                '<Pass_Arr><P>*7*101343910*1*58003a9f837*0*0</P><P>*8*101703400*1*58003aa5d0f*0*0</P></Pass_Arr></Etape></Etapes>'
                '<Parcours><Pcs nom="2000 м Девочки" distance="2000" /><Pcs nom="4000 м юноши" distance="4000" /></Parcours></Epreuve>').encode()
        code, txt = http("POST", "/api/events", json.dumps({"name": "Импорт Wiclax", "finish_device": "FINISH"}).encode(), J)
        e5 = json.loads(txt)["id"]
        r = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e5}/clax", data=clax, method="POST",
                                   headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode(),
                                            "X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(r, timeout=5) as resp:
            out = json.loads(resp.read())
        _, txt = http("GET", f"/api/events/{e5}")
        evw = json.loads(txt)
        check("импорт .clax: участники, чипы, дистанции → забеги",
              out["entries"] == 3 and out["with_chip"] == 2 and
              {(w["name"], w["category"], w["distance"]) for w in evw["waves"]} == {("2000 м Девочки", "Девочки", "2000 м"), ("4000 м юноши", "юноши", "4000 м")},
              str(out) + str(evw["waves"])[:200])
        code, txt = http("GET", f"/api/events/{e5}/wiclax.csv")
        check("экспорт для Wiclax: номер, ФИО, пол, дистанция, чип", code == 200 and "7;Тестов;Тест;;M;2010;;;4000 м юноши;юноши;;58003A9F837" in txt
              and "9;Безчипов;Иван;;M;1990" in txt, txt[:300])
        req = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e5}/event.clax",
                                     headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode()})
        with urllib.request.urlopen(req, timeout=5) as resp:
            cl = resp.read()
        import xml.etree.ElementTree as ET
        cr = ET.fromstring(cl.split(b"?>", 1)[1])
        pucs = sorted(p_.text for p_ in cr.find("PucesDos"))
        check("файл .clax для Wiclax: дистанции, участники, чипы", cr.tag == "Epreuve" and cr.get("nom") == "Импорт Wiclax"
              and len(cr.find("Parcours")) == 2 and len(cr.find("Etapes/Etape/Engages")) == 3
              and pucs == ["58003a9f837.7", "58003aa5d0f.8"], cl[:300])
        r = urllib.request.Request(f"http://127.0.0.1:{p_web}/api/events/{e5}/clax?check=1", data=cl, method="POST",
                                   headers={"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode(),
                                            "X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(r, timeout=5) as resp:
            back = json.loads(resp.read())
        check("свой .clax читается обратно (чипы из PucesDos)", back.get("entries") == 3 and back.get("with_chip") == 2, str(back)[:200])

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
        check("обновление: архив принят и передан на установку", code == 200 and json.loads(txt).get("to") == "9.9.9"
              and os.path.exists(os.path.join(upd, "incoming.zip")), txt)
        code, txt = http("POST", "/api/system/update", zb.getvalue(), {"X-Requested-With": "timing-hub", "Content-Type": "application/octet-stream"})
        check("обновление: второе, пока идёт первое — отказ", code == 409, txt)
        _, txt = http("GET", "/api/system/update")
        check("обновление: статус для страницы", json.loads(txt).get("pending") is True, txt[:200])
        os.remove(os.path.join(upd, "incoming.zip"))

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
        check("вкладка «Оборудование»: сервер, ридеры, кто подключён", code == 200 and sy["server"]["disk_total"] > 0
              and len(sy["readers"]) == 3 and any(c["ip"] == "127.0.0.1" for c in sy["clients"]), txt[:300])

        http("POST", f"/api/events/{e4}", json.dumps({"reg_open": False}).encode(), J)
        code, out = reg("Опоздал", "Совсем", "2010-09-09", "М", ["60 м"])
        check("регистрация закрыта — заявки не принимаются", code == 403, str(out))

        # 9b. ридеры из браузера: добавить, подключить, порт Wiclax по точке, отключить, удалить
        ip_srv = socket.socket(); ip_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ip_srv.bind(("127.0.0.1", 0)); ip_srv.listen(5); ip_srv.settimeout(10)
        p_ip = ip_srv.getsockname()[1]
        code, txt = http("POST", "/api/readers", json.dumps({"id": "FINISH", "host": "127.0.0.1", "port": p_ip}).encode(), J)
        check("ридеры: имя из файла настроек не занять", code == 400 and "файле настроек" in txt, txt)
        code, txt = http("POST", "/api/readers", json.dumps({"id": "IP1", "host": "10.0.0.999", "port": 10000}).encode(), J)
        check("ридеры: неверный адрес отклонён", code == 400, txt)
        code, txt = http("POST", "/api/readers", json.dumps({"id": "IP1", "host": "127.0.0.1", "port": p_ip,
                                                              "device": "km10", "box": "Ящик 2", "enabled": True}).encode(), J)
        check("ридеры: добавлен и включён из браузера", code == 200, txt)
        code, txt = http("GET", "/api/readers")
        rd1 = next((r for r in json.loads(txt)["readers"] if r["id"] == "IP1"), {})
        rport = (rd1.get("wiclax") or {}).get("port")
        check("ридеру закреплён личный порт Wiclax (9861+)", bool(rport) and 9861 <= rport <= 9899, txt[:300])
        wic_rd = WiclaxSim(rport) if rport and wait_port(rport, 5) else None
        check("личный порт ридера открыт", wic_rd is not None)
        code, txt = http("POST", "/api/readers/scan", json.dumps({"subnet": "8.8.8"}).encode(), J)
        check("поиск ридеров: внешние сети запрещены", code == 400, txt)
        code, txt = http("POST", "/api/readers/scan", json.dumps({"subnet": "10.255.255", "port": 1}).encode(), J)
        check("поиск ридеров: внутренняя сеть проверяется", code == 200 and "found" in json.loads(txt), txt[:200])
        p_wx2 = free_port()
        while not 9855 <= p_wx2 <= 9860:
            p_wx2 = 9855 + (p_wx2 % 6)
            try:
                t_ = socket.socket(); t_.bind(("127.0.0.1", p_wx2)); t_.close()
            except OSError:
                p_wx2 = 0
        code, txt = http("POST", "/api/wiclax-ports", json.dumps({"port": p_wx2, "devices": "KM10", "name": "10 км"}).encode(), J)
        check("порт Wiclax для точки добавлен", code == 200, txt)
        ok_port = wait_port(p_wx2, 5)
        check("порт Wiclax для точки открыт", ok_port)
        wic_km = WiclaxSim(p_wx2) if ok_port else None
        conn_ip, _ = ip_srv.accept()
        now = dt.datetime.now()
        line = "aa00" + "058003a9f837" + "0100" + now.strftime("%y%m%d%H%M%S") + "%02x" % (now.microsecond // 10000) + "7e"
        conn_ip.sendall((line + "\r\n").encode())
        ok = wic.wait_for(lambda L: any(y.startswith("58003a9f837;") and ";KM10;" in y for y in L))
        check("IPICO из браузера: отметка ушла в Wiclax строчными, точка KM10", ok, str(wic.snapshot()[-3:]))
        if wic_rd:
            check("личный порт ридера получил отметку", wic_rd.wait_for(lambda L: any(y.startswith("58003a9f837;") for y in L)),
                  str(wic_rd.snapshot()[-3:]))
        if wic_km:
            check("порт точки KM10 получил отметку", wic_km.wait_for(lambda L: any(";KM10;" in y for y in L)))
            push = socket.create_connection(("127.0.0.1", p_push)); x = dt.datetime.now()
            push.sendall(f"AA77,{x:%Y-%m-%d %H:%M:%S}.{x.microsecond // 1000:03d}\n".encode())
            wic.wait_for(lambda L: any("AA77" in y for y in L)); push.close(); time.sleep(0.3)
            check("порт точки KM10 не получает финиш", not any("AA77" in y for y in wic_km.snapshot()))
        code, txt = http("GET", "/api/readers")
        rv = json.loads(txt) if code == 200 else {}
        r1 = next((r for r in rv.get("readers", []) if r["id"] == "IP1"), {})
        check("ридеры: список со статусом «на связи»", bool(r1.get("live", {}).get("connected")) and r1.get("box") == "Ящик 2", txt[:400])
        code, txt = http("POST", "/api/readers/IP1/point", json.dumps({"device": "km5"}).encode(), J)
        now = dt.datetime.now()
        line = "aa00" + "058003a9f999" + "0100" + now.strftime("%y%m%d%H%M%S") + "%02x" % (now.microsecond // 10000) + "7e"
        conn_ip.sendall((line + "\r\n").encode())
        ok = wic.wait_for(lambda L: any(y.startswith("58003a9f999;") and ";KM5;" in y for y in L))
        _, txt2 = http("GET", "/api/readers")
        r1 = next((r for r in json.loads(txt2)["readers"] if r["id"] == "IP1"), {})
        check("ридеры: переставлен на другую точку без переподключения", code == 200 and ok and r1.get("device") == "KM5"
              and bool(r1.get("live", {}).get("connected")), str(wic.snapshot()[-3:]))
        code, txt = http("POST", "/api/readers/IP1/disconnect", b"{}", J)
        time.sleep(0.5)
        code, txt = http("GET", "/api/readers")
        r1 = next((r for r in json.loads(txt)["readers"] if r["id"] == "IP1"), {})
        check("ридеры: отключён из браузера", r1.get("enabled") is False and r1.get("live") is None, txt[:300])
        try:
            conn_ip.settimeout(3)
            gone = conn_ip.recv(10) == b""
        except OSError:
            gone = True
        check("ридеры: соединение с ридером закрыто", gone)
        code, txt = http("POST", "/api/readers/bulk", json.dumps({"text": "название;IP;порт;точка;ящик\nIP2;10.19.1.62;10000;FINISH;Ящик 1\nIP3;10.19.1.63;;FINISH;Ящик 1"}).encode(), J)
        check("ридеры: список загружен (2 новых)", code == 200 and json.loads(txt).get("added") == 2, txt)
        code, txt = http("POST", "/api/readers", json.dumps({"id": "SIM", "parser": "sim", "device": "FINISH", "enabled": True}).encode(), J)
        check("симулятор: виртуальный ридер добавлен", code == 200, txt)
        code, txt = http("POST", "/api/readers/SIM/simulate", json.dumps({"count": 5, "minutes": 0.2}).encode(), J)
        check("симулятор: гонка запущена", code == 200 and json.loads(txt).get("total") == 5, txt)
        time.sleep(14)
        code, txt = http("GET", "/api/readers")
        sim = next((r for r in json.loads(txt)["readers"] if r["id"] == "SIM"), {})
        check("симулятор: все 5 «финишировали», отметки на сервере", (sim.get("sim") or {}).get("sent") == 5
              and (sim.get("live") or {}).get("reads", 0) >= 5, txt[:400])
        code, txt = http("POST", "/api/readers/SIM/clear-reads", b"{}", J)
        check("симулятор: отметки стёрты", code == 200 and json.loads(txt).get("deleted", 0) >= 5, txt)
        code, txt = http("POST", "/api/readers/IP2/clear-reads", b"{}", J)
        check("стереть отметки настоящего ридера нельзя", code == 400, txt)
        for rid in ("IP1", "IP2", "IP3", "SIM"):
            http("POST", f"/api/readers/{rid}/delete", b"{}", J)
        code, txt = http("GET", "/api/readers")
        check("ридеры: удалены", code == 200 and not json.loads(txt)["readers"], txt[:200])
        http("POST", f"/api/wiclax-ports/{p_wx2}/delete", b"{}", J)
        if wic_km:
            wic_km.close()
        conn_ip.close(); ip_srv.close()

        wic.close()
        # 10. второй Wiclax подключается и получает новые отметки
        wic2 = WiclaxSim(p_wic)
        push = socket.create_connection(("127.0.0.1", p_push))
        x = dt.datetime.now()
        push.sendall(f"AA09,{x:%Y-%m-%d %H:%M:%S}.{x.microsecond // 1000:03d}\n".encode())
        check("переподключение Wiclax", wic2.wait_for(lambda L: any("AA09" in y for y in L)))
        push.close()
        wic2.close()
    except Exception as e:  # noqa
        failed = True
        check("непредвиденная ошибка", False, repr(e))
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        pull_srv.close()
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
