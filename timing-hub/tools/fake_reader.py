#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Имитатор ридера — для проверки сервера без настоящего оборудования.

Ридер сам подключается к серверу и шлёт отметки (как mode=listen):
    python3 fake_reader.py push 10.66.0.1 7001

Ридер ждёт, пока сервер подключится к нему (как mode=connect):
    python3 fake_reader.py serve 10000

Параметры:
    --chips 50        сколько участников бежит
    --laps 1          сколько раз каждый пересекает коврик
    --interval 0.5    пауза между участниками, секунд
    --format csv      csv | wiclax | spaces
    --clock-offset 0  на сколько секунд «врут» часы ридера (для проверки предупреждения)
"""
import argparse
import datetime as dt
import random
import socket
import sys
import time


def chip_id(n: int) -> str:
    return f"E2801160600002{n:010X}"


def fmt(fmt_name: str, chip: str, ts: dt.datetime, ant: int, rssi: int) -> str:
    ms = f"{ts.microsecond // 1000:03d}"
    if fmt_name == "wiclax":
        return f"{chip};{ts:%d-%m-%Y %H:%M:%S}.{ms};{ant};;;0"
    if fmt_name == "spaces":
        return f"TAG {chip} ANT {ant} RSSI {rssi} TIME {ts:%H:%M:%S}.{ms}"
    return f"{chip},{ts:%Y-%m-%d %H:%M:%S}.{ms},{ant},{rssi}"


def race(sock: socket.socket, args) -> int:
    sent = 0
    order = list(range(1, args.chips + 1))
    for lap in range(args.laps):
        random.shuffle(order)
        for n in order:
            chip = chip_id(n)
            base = dt.datetime.now() + dt.timedelta(seconds=args.clock_offset)
            # одно прохождение = несколько считываний за полсекунды
            for k in range(random.randint(3, 8)):
                ts = base + dt.timedelta(milliseconds=70 * k + random.randint(0, 40))
                line = fmt(args.format, chip, ts, random.choice([1, 2, 3, 4]), -random.randint(40, 70))
                sock.sendall((line + "\r\n").encode())
                sent += 1
            print(f"круг {lap + 1}: прошёл чип {chip}")
            time.sleep(args.interval)
    return sent


def main() -> int:
    ap = argparse.ArgumentParser(description="Имитатор ридера")
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("push", help="подключиться к серверу и слать отметки")
    p.add_argument("host")
    p.add_argument("port", type=int)
    s = sub.add_parser("serve", help="ждать подключения сервера")
    s.add_argument("port", type=int)
    s.add_argument("--bind", default="0.0.0.0")
    for x in (p, s):
        x.add_argument("--chips", type=int, default=20)
        x.add_argument("--laps", type=int, default=1)
        x.add_argument("--interval", type=float, default=0.5)
        x.add_argument("--format", choices=["csv", "wiclax", "spaces"], default="csv")
        x.add_argument("--clock-offset", type=float, default=0.0)
    args = ap.parse_args()

    if args.mode == "push":
        with socket.create_connection((args.host, args.port), timeout=10) as sock:
            print(f"подключился к {args.host}:{args.port}")
            n = race(sock, args)
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((args.bind, args.port))
            srv.listen(1)
            print(f"жду подключения сервера на порту {args.port}…")
            conn, addr = srv.accept()
            with conn:
                print(f"сервер подключился: {addr[0]}")
                n = race(conn, args)
    print(f"готово, отправлено строк: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
