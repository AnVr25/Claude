#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Имитатор Wiclax — подключается к серверу так же, как Wiclax, и печатает,
что сервер отдаёт. Удобно, чтобы проверить сервер без компьютера с Wiclax.

    python3 fake_wiclax.py 10.66.0.1 9854
    python3 fake_wiclax.py 10.66.0.1 9854 --rewind "06-10-2026 09:00:00" "06-10-2026 14:00:00"
"""
import argparse
import socket
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description="Имитатор Wiclax (generic acquisition)")
    ap.add_argument("host")
    ap.add_argument("port", type=int)
    ap.add_argument("--seconds", type=float, default=30, help="сколько секунд слушать")
    ap.add_argument("--rewind", nargs=2, metavar=("FROM", "TO"),
                    help='перезапросить отметки: "дд-мм-гггг чч:мм:сс" "дд-мм-гггг чч:мм:сс"')
    ap.add_argument("--show-heartbeat", action="store_true", help="печатать сигналы «на связи» (*)")
    args = ap.parse_args()

    with socket.create_connection((args.host, args.port), timeout=10) as s:
        s.settimeout(0.5)
        print(f"подключился к {args.host}:{args.port}")
        s.sendall(b"HELLO\r")
        s.sendall(b"CLOCK\r")
        if args.rewind:
            s.sendall(f"REWIND {args.rewind[0]} {args.rewind[1]}\r".encode())
        buf = b""
        end = time.time() + args.seconds
        passings = beats = 0
        while time.time() < end:
            try:
                data = s.recv(65536)
            except socket.timeout:
                continue
            if not data:
                print("сервер закрыл соединение")
                break
            buf += data
            *lines, buf = buf.replace(b"\r\n", b"\r").replace(b"\n", b"\r").split(b"\r")
            for ln in lines:
                t = ln.decode("utf-8", "replace")
                if t == "*":
                    beats += 1
                    if args.show_heartbeat:
                        print("*")
                    continue
                if ";" in t:
                    passings += 1
                print(t)
        print(f"итого: прохождений {passings}, сигналов «на связи» {beats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
