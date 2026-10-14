#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
timing-hub (SakhStart) — судейско-секретарский АРМ стадиона и манежа.

Что делает:
  1. Принимает онлайн-заявки (публичная форма /r/, кабинет тренера), ведёт соревнования, посев,
     нагрудные номера (вписываются вручную, один номер на все виды спортсмена), забеги и общие списки.
  2. Ввод результатов судьями вручную: 1–3 секундомера, попытки на секторе; официальный результат
     считает только сервер; места, разряды ЕВСК, командный зачёт.
  3. Протоколы (печать, Excel), табло, публикация результатов, личный кабинет тренера (152-ФЗ).

Чиповый хронометраж (IPICO) и обмен с Wiclax вынесены в отдельный проект и с версии 7.0.0 здесь не поддерживаются.
Только стандартная библиотека Python 3.10+. Внешних зависимостей нет.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import csv
import datetime as dt
import hmac
import html
import io
import json
import logging
import math
import os
import re
import signal
import socket
import sqlite3
import sys
import random
import time
from collections import deque
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

VERSION = "7.1.0"
BUILD_DATE = "2026-10-14"        # дата сборки: показывается в «Системе» и в /api/status
log = logging.getLogger("timing-hub")


# --------------------------------------------------------------------------- #
#  Время
# --------------------------------------------------------------------------- #
# Все времена хранятся как «наивное» местное время. Сервер работает в часовом поясе
# соревнований (install.sh ставит Asia/Sakhalin), поэтому время старта тоже местное.

def now_local() -> dt.datetime:
    return dt.datetime.now()




def frac_to_us(frac: Optional[str]) -> int:
    """Дробная часть секунд строкой («84», «5», «123») → микросекунды."""
    return int((frac or "0").ljust(6, "0")[:6])


def fmt_db(ts: dt.datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d}"


def parse_db(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")


# --------------------------------------------------------------------------- #
#  Excel (.xlsx) без сторонних библиотек: шаблон заявки и чтение файла тренера
# --------------------------------------------------------------------------- #
def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def xlsx_build(sheets: list, widths=None, header_row=None, title_row=None, validations=(), date_cols=(),
               hidden_sheets=(), group_rows=(), orientation="landscape", data_height=None, repeat_header=False) -> bytes:
    """sheets = [(имя, [[ячейки]])]. Оформление (ширины, заголовок, проверки) — только у первого листа.
    group_rows — номера строк-заголовков групп (забег, список) жирным на заливке; data_height — высота строк
    данных (место для записи ручкой); repeat_header — шапка таблицы на каждой печатной странице."""
    import zipfile
    from xml.sax.saxutils import escape

    def esc(v):
        return escape(str(v), {'"': "&quot;"})

    def sheet_xml(rows, first):
        ncol = max((len(r) for r in rows), default=1)
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">']
        if first:
            out.append('<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
        if first and header_row:
            out.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{header_row}" topLeftCell="A{header_row + 1}" '
                       'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
        if first and widths:
            out.append("<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                                          for i, w in enumerate(widths)) + "</cols>")
        out.append("<sheetData>")
        for ri, row in enumerate(rows, start=1):
            attrs = ""
            if first and title_row and ri == title_row + 1:
                attrs = ' ht="48" customHeight="1"'
            if first and header_row and ri == header_row:
                attrs = ' ht="32" customHeight="1"'
            elif first and data_height and header_row and ri > header_row and ri not in group_rows:
                attrs = f' ht="{data_height}" customHeight="1"'
            cells = []
            for ci in range(ncol if first else len(row)):
                v = row[ci] if ci < len(row) else ""
                st = 0
                if first and title_row and ri == title_row:
                    st = 2
                elif first and title_row and ri == title_row + 1:
                    st = 4
                elif first and header_row and ri == header_row:
                    st = 1
                elif first and ri in group_rows:
                    st = 6
                elif first and header_row and ri > header_row:
                    st = 3 if ci in date_cols else 5
                ref = f"{_col(ci)}{ri}"
                if v == "" or v is None:
                    if st:
                        cells.append(f'<c r="{ref}" s="{st}"/>')
                elif isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}" s="{st}"><v>{v}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">{esc(v)}</t></is></c>')
            out.append(f'<row r="{ri}"{attrs}>' + "".join(cells) + "</row>")
        out.append("</sheetData>")
        if first and title_row:
            last = _col(ncol - 1)
            out.append(f'<mergeCells count="2"><mergeCell ref="A{title_row}:{last}{title_row}"/>'
                       f'<mergeCell ref="A{title_row + 1}:{last}{title_row + 1}"/></mergeCells>')
        if first and validations:
            out.append(f'<dataValidations count="{len(validations)}">')
            for ref, formula in validations:
                out.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" '
                           f'errorTitle="Значение из списка" error="Выберите значение из списка" sqref="{ref}">'
                           f"<formula1>{esc(formula)}</formula1></dataValidation>")
            out.append("</dataValidations>")
        if first:
            out.append('<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
                       f'<pageSetup paperSize="9" orientation="{orientation}" fitToWidth="1" fitToHeight="0"/>')
        out.append("</worksheet>")
        return "".join(out)

    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd.mm.yyyy"/></numFmts>'
              '<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="14"/><name val="Calibri"/></font>'
              '<font><i/><sz val="10"/><color rgb="FF666666"/><name val="Calibri"/></font></fonts>'
              '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFF4E3DD"/><bgColor indexed="64"/></patternFill></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFE6ECF4"/><bgColor indexed="64"/></patternFill></fill></fills>'
              '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
              '<border><left style="thin"><color rgb="FFBBBBBB"/></left><right style="thin"><color rgb="FFBBBBBB"/></right>'
              '<top style="thin"><color rgb="FFBBBBBB"/></top><bottom style="thin"><color rgb="FFBBBBBB"/></bottom><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="7"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
              '<alignment wrapText="1" vertical="center"/></xf>'
              '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
              '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
              '<xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>'
              '<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        n = len(sheets)
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join('<sheet name="%s" sheetId="%d"%s r:id="rId%d"/>'
                             % (esc(nm), i + 1, ' state="hidden"' if i in hidden_sheets else "", i + 1)
                             for i, (nm, _) in enumerate(sheets))
                   + "</sheets>"
                   + (f'<definedNames><definedName name="_xlnm.Print_Titles" localSheetId="0">\'{esc(sheets[0][0])}\'!${header_row}:${header_row}</definedName></definedNames>'
                      if repeat_header and header_row else "")
                   + "</workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(n))
                   + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml", styles)
        for i, (_, rows) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", sheet_xml(rows, i == 0))
    return buf.getvalue()


def xlsx_read(blob: bytes, max_rows: int = 1000) -> list:
    """Первый видимый лист .xlsx → список строк (str или число)."""
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    z = zipfile.ZipFile(io.BytesIO(blob))
    if sum(i.file_size for i in z.infolist()) > 50 * 1024 * 1024:
        raise ValueError("слишком большой файл")
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheet = next((sh for sh in wb.find("m:sheets", ns) if sh.get("state") not in ("hidden", "veryHidden")), None)
    rid = sheet.get(f"{{{ns['r']}}}id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in rels if r.get("Id") == rid)
    path = target.lstrip("/") if target.startswith("/") else "xl/" + target
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    out = []
    for row in ET.fromstring(z.read(path)).iter(f"{{{ns['m']}}}row"):
        vals = {}
        for c in row.findall("m:c", ns):
            ref = re.match(r"([A-Z]+)", c.get("r") or "A")
            ci = 0
            for ch in ref.group(1):
                ci = ci * 26 + ord(ch) - 64
            t, v = c.get("t"), c.find("m:v", ns)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            elif v is None:
                continue
            elif t in ("str", "b", "e"):
                val = v.text or ""
            else:
                try:
                    f = float(v.text)
                    val = int(f) if f.is_integer() else f
                except (TypeError, ValueError):
                    val = v.text or ""
            vals[ci - 1] = val
        if vals:
            r = int(row.get("r") or len(out) + 1)
            while len(out) < r - 1:
                out.append([])
            out.append([vals.get(i, "") for i in range(max(vals) + 1)])
        if len(out) >= max_rows:
            break
    return out








# --------------------------------------------------------------------------- #
#  Конфигурация
# --------------------------------------------------------------------------- #
DEFAULTS: dict[str, Any] = {
    "db_path": "/var/lib/timing-hub/reads.db",
    "log_level": "INFO",
    "web": {
        "listen_host": "127.0.0.1",
        "listen_port": 8080,
        "user": "admin",
        "password": "",
        "api_key": "",
    },
    # публичная форма регистрации: слушаем только локально, наружу — через nginx (HTTPS)
    "public": {
        "enabled": True,
        "listen_host": "127.0.0.1",
        "listen_port": 8081,
        "url": "",                 # например https://reg.fla65.ru — для ссылки в админке
    },
}

VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class ConfigError(Exception):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"не найден файл настроек {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"ошибка в JSON {path}: строка {e.lineno}, позиция {e.colno}: {e.msg}")
    # 7.0: чиповых источников и Wiclax больше нет — ключи sources и wiclax в старых config.json молча игнорируются
    cfg = _merge(DEFAULTS, {k: v for k, v in raw.items() if k not in ("sources", "wiclax", "store_raw", "raw_memory_lines", "clock_warn_sec")})
    ports = [(cfg["web"]["listen_host"], int(cfg["web"]["listen_port"]), "web")]
    if (cfg.get("public") or {}).get("enabled"):
        ports.append((cfg["public"]["listen_host"], int(cfg["public"]["listen_port"]), "public"))
    used = {}
    for host, port, who in ports:
        if port in used:
            raise ConfigError(f"порт {port} занят дважды: {used[port]} и {who}")
        used[port] = who
    return cfg


# --------------------------------------------------------------------------- #
#  База данных
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self, path: str):
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self.con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript(
            """
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                date TEXT,
                place TEXT,
                finish_device TEXT,
                start_time TEXT,
                status TEXT NOT NULL DEFAULT 'planned',
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entries(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                bib TEXT NOT NULL
            );
            """
        )
        self._migrate()

    # ---- соревнования
    EVENT_FIELDS = ("name", "date", "place", "finish_device", "notes", "organizer", "chief_judge", "chief_secretary", "start_clock",
                    "heats_sequential", "reg_open", "reg_deadline", "reg_distances", "reg_rules", "reg_lanes",
                    "reg_info", "reg_consent",
                    "kind", "timing", "pub_site", "ours", "level", "adaptive", "date_end", "city", "note",
                    "live_url", "photo_url", "links", "pub_start", "pub_results", "pub_regs", "team_best",
                    "cover", "program", "contacts", "series")
    KINDS = ("stadium",)
    TIMINGS = ("judge", "manual", "lynx")
    LEVELS = ("russia", "dfo", "interregion", "region", "mass")

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

    ENTRY_KEEP = ("bib", "wave", "name", "birth_year", "team", "category", "lane", "coach", "seed", "reg_id", "sex", "result",
                  "status", "points", "picked_at", "members", "rank", "detail", "done_rank", "result_at")

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

    def get_scoreboard(self, eid: int) -> Optional[dict]:
        row = self.con.execute("SELECT state, updated_at FROM scoreboard WHERE event_id = ?", (eid,)).fetchone()
        if not row:
            return None
        try:
            st = json.loads(row[0])
        except ValueError:
            return None
        st["updated_at"] = row[1]
        return st

    def set_scoreboard(self, eid: int, state: dict) -> None:
        self.con.execute("INSERT OR REPLACE INTO scoreboard(event_id, state, updated_at) VALUES (?,?,?)",
                         (eid, json.dumps(state, ensure_ascii=False), fmt_db(now_local())))

    # ---- 6.0: общее состояние экранов секретарей (Мастер протоколов, корзина печати)
    def ui_states(self, eid: int) -> dict:
        out = {}
        for key, value, rev, who, cid, at in self.con.execute(
                "SELECT key, value, rev, who, cid, updated_at FROM ui_state WHERE event_id = ?", (eid,)):
            try:
                out[key] = {"value": json.loads(value), "rev": rev, "who": who or "", "cid": cid or "", "at": at}
            except ValueError:
                continue
        return out

    def ui_put(self, eid: int, key: str, value: Any, who: str, cid: str) -> int:
        """Записать значение целиком, rev увеличивается на 1; возвращает новый rev."""
        old = self.con.execute("SELECT rev FROM ui_state WHERE event_id = ? AND key = ?", (eid, key)).fetchone()
        rev = (old[0] if old else 0) + 1
        self.con.execute("INSERT OR REPLACE INTO ui_state(event_id, key, value, rev, who, cid, updated_at) VALUES (?,?,?,?,?,?,?)",
                         (eid, key, json.dumps(value, ensure_ascii=False), rev, who, cid, fmt_db(now_local())))
        return rev

    # ---- пользователи и сессии (вход через браузер)
    def users(self) -> list:
        return self._rows(self.con.execute(
            "SELECT login, name, role, note, active, created_at, last_login FROM users ORDER BY active DESC, login"))

    def get_user(self, login: str) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM users WHERE login = ?", (login,)))
        return rows[0] if rows else None

    def save_user(self, login: str, name: str, role: str, pwd: Optional[str], note: Optional[str] = None) -> None:
        if self.get_user(login):
            self.con.execute("UPDATE users SET name = ?, role = ? WHERE login = ?", (name, role, login))
            if note is not None:
                self.con.execute("UPDATE users SET note = ? WHERE login = ?", (note, login))
            if pwd:
                self.con.execute("UPDATE users SET pwd = ? WHERE login = ?", (pwd, login))
                self.con.execute("DELETE FROM sessions WHERE login = ?", (login,))
        else:
            self.con.execute("INSERT INTO users(login, name, role, pwd, created_at, note) VALUES (?,?,?,?,?,?)",
                             (login, name, role, pwd, fmt_db(now_local()), note or ""))

    def update_user(self, login: str, **f) -> None:
        """Частичное изменение: name, role, note, active, pwd. Смена пароля и блокировка закрывают сеансы."""
        for k in ("name", "role", "note", "active", "pwd"):
            if k in f:
                self.con.execute(f"UPDATE users SET {k} = ? WHERE login = ?", (f[k], login))
        if "pwd" in f or f.get("active") == 0:
            self.con.execute("DELETE FROM sessions WHERE login = ?", (login,))

    def delete_user(self, login: str) -> None:
        self.con.execute("DELETE FROM users WHERE login = ?", (login,))
        self.con.execute("DELETE FROM sessions WHERE login = ?", (login,))

    def add_session(self, token_hash: str, login: str, days: int, ip: str) -> None:
        now = now_local()
        self.con.execute("DELETE FROM sessions WHERE expires_at < ?", (fmt_db(now),))
        self.con.execute("INSERT INTO sessions(token, login, created_at, expires_at, ip) VALUES (?,?,?,?,?)",
                         (token_hash, login, fmt_db(now), fmt_db(now + dt.timedelta(days=days)), ip))
        self.con.execute("UPDATE users SET last_login = ? WHERE login = ?", (fmt_db(now), login))

    def get_session(self, token_hash: str) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM sessions WHERE token = ? AND expires_at > ?",
                                           (token_hash, fmt_db(now_local()))))
        return rows[0] if rows else None

    def delete_session(self, token_hash: str) -> None:
        self.con.execute("DELETE FROM sessions WHERE token = ?", (token_hash,))

    # ---- тренеры (личный кабинет): вход в сеанс — login «trainer:<id>», чтобы не путать с логинами судей
    def trainers(self) -> list:
        return self._rows(self.con.execute(
            "SELECT id, name, team, email, is_verified, active, created_at, last_login, verified_at, verified_by, "
            "consent_accepted, consent_at "
            "FROM trainers ORDER BY is_verified, created_at DESC"))

    def trainer_by_email(self, email: str) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM trainers WHERE email = ?", (email,)))
        return rows[0] if rows else None

    def trainer_by_id(self, tid: int) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM trainers WHERE id = ?", (tid,)))
        return rows[0] if rows else None

    def add_trainer(self, name: str, team: str, email: str, pwd_hash: str) -> int:
        cur = self.con.execute("INSERT INTO trainers(name, team, email, password_hash, created_at) VALUES (?,?,?,?,?)",
                               (name, team, email, pwd_hash, fmt_db(now_local())))
        return int(cur.lastrowid)

    def update_trainer(self, tid: int, **f) -> None:
        for k in ("name", "team", "password_hash", "is_verified", "verification_token", "token_expires", "token_attempts",
                  "token_sent_at", "active", "last_login", "verified_at", "verified_by", "consent_accepted", "consent_at",
                  "consent_hash", "policy_hash"):
            if k in f:
                self.con.execute(f"UPDATE trainers SET {k} = ? WHERE id = ?", (f[k], tid))
        if "password_hash" in f or f.get("active") == 0 or f.get("is_verified") == 0:
            self.con.execute("DELETE FROM sessions WHERE login = ?", (f"trainer:{tid}",))

    def save_consent_text(self, h: str, kind: str, text: str) -> None:
        self.con.execute("INSERT OR IGNORE INTO consent_texts(hash, kind, text, created_at) VALUES (?,?,?,?)",
                         (h, kind, text, fmt_db(now_local())))

    def consent_texts(self) -> list:
        rows = self._rows(self.con.execute("SELECT hash, kind, text, created_at FROM consent_texts ORDER BY created_at DESC"))
        for r in rows:
            r["used"] = (self.con.execute("SELECT COUNT(*) FROM registrations WHERE consent_hash = ?", (r["hash"],)).fetchone()[0]
                         + self.con.execute("SELECT COUNT(*) FROM trainers WHERE consent_hash = ?", (r["hash"],)).fetchone()[0])
        return rows

    def delete_trainer(self, tid: int) -> None:
        self.con.execute("DELETE FROM trainers WHERE id = ?", (tid,))
        self.con.execute("DELETE FROM sessions WHERE login = ?", (f"trainer:{tid}",))












    def _rows(self, cur) -> list:
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    _EV_SELECT = ("SELECT e.*, (SELECT COUNT(*) FROM entries n WHERE n.event_id = e.id) AS entries_count,"
                  " (SELECT COUNT(*) FROM files f WHERE f.event_id = e.id) AS files_count,"
                  " (SELECT COUNT(*) FROM registrations g WHERE g.event_id = e.id) AS regs_count,"
                  " (SELECT COUNT(*) FROM registrations g WHERE g.event_id = e.id AND g.status = 'pending')"
                  " AS regs_pending"
                  " FROM events e")

    def list_events(self) -> list:
        return self._rows(self.con.execute(self._EV_SELECT + " ORDER BY COALESCE(e.date, '') DESC, e.id DESC"))

    def get_event(self, eid: int) -> Optional[dict]:
        rows = self._rows(self.con.execute(self._EV_SELECT + " WHERE e.id = ?", (eid,)))
        return rows[0] if rows else None

    def add_event(self, d: dict) -> int:
        cur = self.con.execute(
            "INSERT INTO events(name, date, place, finish_device, notes, organizer, chief_judge, chief_secretary,"
            " start_clock, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (d["name"], d.get("date"), d.get("place"), d.get("finish_device"), d.get("notes"), d.get("organizer"),
             d.get("chief_judge"), d.get("chief_secretary"), d.get("start_clock"), fmt_db(now_local())))
        eid = int(cur.lastrowid)
        if "heats_sequential" in d:
            self.update_event(eid, {"heats_sequential": d["heats_sequential"]})
        return eid

    def update_event(self, eid: int, d: dict) -> None:
        sets, args = [], []
        for k in self.EVENT_FIELDS:
            if k in d:
                v = d[k]
                if k == "heats_sequential":
                    v = None if v is None or v == "" else (1 if v else 0)
                if k in ("reg_open", "pub_site", "ours", "adaptive", "pub_start", "pub_results", "pub_regs"):
                    v = 1 if v else 0
                if k == "kind":
                    v = v if v in self.KINDS else "stadium"
                if k == "timing":
                    v = v if v in self.TIMINGS else None
                if k == "level":
                    v = v if v in self.LEVELS else None
                if k in ("date_end", "city", "note", "live_url", "photo_url", "links") and v is not None:
                    v = str(v).strip()[:4000 if k == "links" else 500] or None
                if k == "reg_lanes":
                    v = max(1, min(int(v or 8), 50))
                if k == "team_best":
                    try:
                        v = max(1, min(int(v), 20)) if v not in (None, "", 0, "0") else None
                    except (TypeError, ValueError):
                        v = None
                if k == "cover" and v is not None:
                    v = str(v).strip()
                    v = v if re.fullmatch(r"file:\d{1,9}", v) or re.fullmatch(r"https?://[^\s<>\"']{3,490}", v) else None
                if k in ("program", "contacts") and v is not None:
                    v = str(v).strip()[:2000] or None
                if k == "series" and v is not None:
                    v = re.sub(r"\s+", " ", str(v)).strip()[:80] or None
                if k in ("reg_distances", "reg_rules", "reg_info", "reg_consent", "reg_deadline") and v is not None:
                    v = str(v)[:4000] or None
                sets.append(f"{k} = ?")
                args.append(v)
        if sets:
            self.con.execute(f"UPDATE events SET {', '.join(sets)} WHERE id = ?", (*args, eid))

    def set_event_field(self, eid: int, **kw) -> None:
        for k, v in kw.items():
            if k not in ("start_time", "status", "archived", "finished_at", "reg_slug", "pub_site", "ours",
                         "level", "adaptive", "date_end", "city", "note", "kind", "links"):
                raise ValueError(k)
            self.con.execute(f"UPDATE events SET {k} = ? WHERE id = ?", (v, eid))

    def delete_event(self, eid: int) -> None:
        for t in ("entries", "waves", "manual", "files", "registrations", "ui_state", "scoreboard"):
            self.con.execute(f"DELETE FROM {t} WHERE event_id = ?", (eid,))
        self.con.execute("DELETE FROM events WHERE id = ?", (eid,))

    # участники: строка = спортсмен в одной дисциплине. Ключ — id; один и тот же нагрудный номер bib может стоять в нескольких
    # строках (спортсмен заявлен на несколько видов), но у разных людей номера не повторяются
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

    def entries_rows(self, eid: int) -> list:
        rows = self._rows(self.con.execute(
            "SELECT id, bib, wave, name, birth_year, team, category, lane, coach, seed, reg_id, sex, result, status, points,"
            " picked_at, members, rank, detail, done_rank, result_at FROM entries"
            " WHERE event_id = ? ORDER BY CAST(bib AS INTEGER), bib, id", (eid,)))
        for r in rows:
            try:
                r["detail"] = json.loads(r["detail"]) if r.get("detail") else None
            except ValueError:
                r["detail"] = None
        return rows

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

    def set_picked(self, eid: int, bib: str, ts: Optional[str]) -> int:
        """Выдача номера на руки — одна на человека: отмечаются все его строки (все дисциплины)."""
        return self.con.execute("UPDATE entries SET picked_at = ? WHERE event_id = ? AND bib = ?",
                                (ts, eid, bib)).rowcount

    def set_file_public(self, fid: int, public: bool) -> None:
        self.con.execute("UPDATE files SET public = ? WHERE id = ?", (1 if public else 0, fid))

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

    def rename_bib(self, eid: int, old: str, new: str) -> None:
        """Сменить нагрудный номер везде: во всех строках участника (дисциплинах), заявках и ручных отметках судей."""
        self.con.execute("UPDATE entries SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
        self.con.execute("UPDATE registrations SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))
        self.con.execute("UPDATE manual SET bib = ? WHERE event_id = ? AND bib = ?", (new, eid, old))

    def delete_entry(self, eid: int, entry_id: int) -> None:
        self.con.execute("DELETE FROM entries WHERE event_id = ? AND id = ?", (eid, entry_id))

    # заявки с публичной формы
    REG_FIELDS = ("last_name", "first_name", "middle_name", "birth_date", "sex", "team", "coach", "distance",
                  "best", "best_sec", "category", "representative", "contact", "status", "note", "bib", "relay", "leg", "rank")

    def add_registration(self, eid: int, d: dict) -> int:
        cols = [k for k in self.REG_FIELDS if k in d] + ["consent_at", "consent_hash", "policy_hash", "created_at", "event_id"]
        vals = [d[k] for k in self.REG_FIELDS if k in d] + [d["consent_at"], d.get("consent_hash"), d.get("policy_hash"),
                                                             fmt_db(now_local()), eid]
        cur = self.con.execute(f"INSERT INTO registrations({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               vals)
        return int(cur.lastrowid)

    def registrations(self, eid: int) -> list:
        return self._rows(self.con.execute("SELECT * FROM registrations WHERE event_id = ? ORDER BY id", (eid,)))

    def get_registration(self, rid: int) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM registrations WHERE id = ?", (rid,)))
        return rows[0] if rows else None

    def update_registration(self, rid: int, **kw) -> None:
        for k, v in kw.items():
            if k not in self.REG_FIELDS:
                raise ValueError(k)
            self.con.execute(f"UPDATE registrations SET {k} = ?, updated_at = ? WHERE id = ?",
                             (v, fmt_db(now_local()), rid))

    def event_by_slug(self, slug: str) -> Optional[dict]:
        rows = self._rows(self.con.execute(self._EV_SELECT + " WHERE e.reg_slug = ?", (slug,)))
        return rows[0] if rows else None

    def entries(self, eid: int) -> dict:
        return {c: b for b, c, _ in self.entries_full(eid)}

    # забеги (в базе — waves): свой старт, финиш, категория, дистанция
    def waves(self, eid: int) -> list:
        return self._rows(self.con.execute(
            "SELECT w.*, (SELECT COUNT(*) FROM entries n WHERE n.event_id = w.event_id AND n.wave = w.name)"
            " AS entries_count FROM waves w WHERE event_id = ? ORDER BY id", (eid,)))

    def get_wave(self, eid: int, name: str) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM waves WHERE event_id = ? AND name = ?", (eid, name)))
        return rows[0] if rows else None

    def add_wave(self, eid: int, name: str, category: Optional[str] = None, distance: Optional[str] = None) -> None:
        self.con.execute("INSERT OR IGNORE INTO waves(event_id, name, category, distance) VALUES (?,?,?,?)",
                         (eid, name, category, distance))

    def update_wave(self, eid: int, name: str, **kw) -> None:
        for k, v in kw.items():
            if k not in ("category", "distance", "start_time", "finished_at", "name"):
                raise ValueError(k)
            self.con.execute(f"UPDATE waves SET {k} = ? WHERE event_id = ? AND name = ?", (v, eid, name))

    def rename_wave(self, eid: int, old: str, new: str) -> None:
        self.con.execute("UPDATE waves SET name = ? WHERE event_id = ? AND name = ?", (new, eid, old))
        self.con.execute("UPDATE entries SET wave = ? WHERE event_id = ? AND wave = ?", (new, eid, old))
        self.con.execute("UPDATE manual SET wave = ? WHERE event_id = ? AND wave = ?", (new, eid, old))

    def delete_wave(self, eid: int, name: str) -> None:
        self.con.execute("DELETE FROM waves WHERE event_id = ? AND name = ?", (eid, name))
        self.con.execute("UPDATE entries SET wave = NULL WHERE event_id = ? AND wave = ?", (eid, name))
        self.con.execute("UPDATE manual SET wave = NULL WHERE event_id = ? AND wave = ?", (eid, name))

    def set_wave_start(self, eid: int, name: str, start: Optional[str]) -> None:
        self.con.execute("UPDATE waves SET start_time = ?, finished_at = NULL WHERE event_id = ? AND name = ?",
                         (start, eid, name))

    # ручные отметки (судья, кнопка, ввод номера)
    def add_manual(self, eid: int, device: str, ts: dt.datetime, bib: str, judge: str,
                   client_id: Optional[str], wave: Optional[str] = None) -> Optional[int]:
        cur = self.con.execute(
            "INSERT OR IGNORE INTO manual(event_id, device, ts, bib, judge, client_id, created_at, wave)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (eid, device, fmt_db(ts), bib, judge, client_id, fmt_db(now_local()), wave))
        if cur.rowcount:
            return int(cur.lastrowid)
        row = self.con.execute("SELECT id FROM manual WHERE client_id = ?", (client_id,)).fetchone()
        return int(row[0]) if row else None

    def manual_list(self, eid: int, include_deleted: bool = False) -> list:
        q = "SELECT * FROM manual WHERE event_id = ?" + ("" if include_deleted else " AND deleted = 0")
        return self._rows(self.con.execute(q + " ORDER BY ts, id", (eid,)))

    def get_manual(self, mid: int) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM manual WHERE id = ?", (mid,)))
        return rows[0] if rows else None

    def update_manual(self, mid: int, **kw) -> None:
        for k, v in kw.items():
            if k not in ("bib", "deleted", "ts", "device", "wave"):
                raise ValueError(k)
            self.con.execute(f"UPDATE manual SET {k} = ? WHERE id = ?", (v, mid))

    # файлы соревнования (протоколы, снимки результатов)
    FOLDERS = ("Положение и документы", "Заявки", "Для судей", "Протоколы", "Результаты", "Фото и прочее")

    @classmethod
    def folder_of(cls, f: dict) -> str:
        if f.get("folder") in cls.FOLDERS:
            return f["folder"]
        return "Результаты" if f.get("kind") == "snapshot" else "Протоколы"

    def add_file(self, eid: int, name: str, stored: str, size: int, kind: str, author: str,
                 folder: Optional[str] = None) -> int:
        cur = self.con.execute(
            "INSERT INTO files(event_id, name, stored, size, kind, created_at, author, folder) VALUES (?,?,?,?,?,?,?,?)",
            (eid, name, stored, size, kind, fmt_db(now_local()), author, folder if folder in self.FOLDERS else None))
        return int(cur.lastrowid)

    def files(self, eid: int) -> list:
        rows = self._rows(self.con.execute(
            "SELECT id, event_id, name, size, kind, created_at, author, folder, public FROM files WHERE event_id = ? ORDER BY id",
            (eid,)))
        for r in rows:
            r["folder"] = self.folder_of(r)
        return rows

    def move_file(self, fid: int, folder: str) -> None:
        self.con.execute("UPDATE files SET folder = ? WHERE id = ?", (folder, fid))

    def get_file(self, fid: int) -> Optional[dict]:
        rows = self._rows(self.con.execute("SELECT * FROM files WHERE id = ?", (fid,)))
        return rows[0] if rows else None

    def delete_file_row(self, fid: int) -> None:
        self.con.execute("DELETE FROM files WHERE id = ?", (fid,))

    # журнал действий
    def audit(self, actor: str, event_id: Optional[int], action: str, details: str = "") -> None:
        self.con.execute("INSERT INTO audit(ts, actor, event_id, action, details) VALUES (?,?,?,?,?)",
                         (fmt_db(now_local()), actor, event_id, action, details))

    def audit_list(self, event_id: Optional[int], limit: int = 300) -> list:
        if event_id:
            cur = self.con.execute("SELECT * FROM audit WHERE event_id = ? ORDER BY id DESC LIMIT ?",
                                   (event_id, limit))
        else:
            cur = self.con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return self._rows(cur)











# --------------------------------------------------------------------------- #
#  Хаб
# --------------------------------------------------------------------------- #
class Hub:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = Store(cfg["db_path"])
        self.servers: list = []
        self.tasks: list = []
        self._rate: dict = {}
        self._clients: dict = {}       # кто открывал страницы сервера: IP → последнее обращение
        self.started_at = now_local()
        self.stopping = asyncio.Event()

    # ----------------------------------------------------------------------- #
    #  Соревнования: API для веб-интерфейса
    # ----------------------------------------------------------------------- #
    @staticmethod
    def _epoch_ms(ts: Optional[dt.datetime]) -> Optional[int]:
        return None if ts is None else int(ts.timestamp() * 1000)

    @staticmethod
    def fmt_elapsed(sec: float) -> str:
        if sec < 0:
            return "-" + Hub.fmt_elapsed(-sec)
        tenths = int(sec * 10 + 1e-6)
        h, rem = divmod(tenths, 36000)
        m, rem = divmod(rem, 600)
        s, t = divmod(rem, 10)
        return f"{h}:{m:02d}:{s:02d}.{t}"

    def _event_view(self, ev: dict) -> dict:
        out = dict(ev)
        st = parse_db(ev["start_time"]) if ev.get("start_time") else None
        out["start_epoch_ms"] = self._epoch_ms(st)
        seq = ev.get("heats_sequential")
        out["heats_sequential"] = bool(seq) if seq is not None else (ev.get("finish_device") or "").upper() == "JUDGE"
        waves = self.store.waves(ev["id"])
        for w in waves:
            w["start_epoch_ms"] = self._epoch_ms(parse_db(w["start_time"])) if w.get("start_time") else None
            w["finish_epoch_ms"] = self._epoch_ms(parse_db(w["finished_at"])) if w.get("finished_at") else None
            w["state"] = "finished" if w.get("finished_at") else ("running" if w.get("start_time") else "planned")
        out["waves"] = waves
        out["reg_open"] = bool(ev.get("reg_open"))
        base = (self.cfg.get("public", {}).get("url") or "").rstrip("/")
        out["reg_url"] = f"{base}/r/{ev['reg_slug']}" if ev.get("reg_slug") else ""
        out["reg_path"] = f"/r/{ev['reg_slug']}" if ev.get("reg_slug") else ""
        out["reg_lanes"] = ev.get("reg_lanes") or 8
        out["kind"] = ev.get("kind") or "stadium"
        out["timing"] = ev.get("timing") if ev.get("timing") in Store.TIMINGS else "judge"
        for k in ("pub_site", "ours", "adaptive", "pub_start", "pub_results", "pub_regs"):
            out[k] = bool(ev.get(k)) if ev.get(k) is not None else (k == "ours")
        out["page_url"] = f"{base}/r/{ev['reg_slug']}" if ev.get("reg_slug") and base else out["reg_path"]
        return out

    # ---- публикация на сайте fla65.ru: календарь и страница события
    URL_RE = re.compile(r"https?://[^\s<>\"']{3,490}")

    @classmethod
    def clean_url(cls, v) -> Optional[str]:
        v = str(v or "").strip()
        return v if cls.URL_RE.fullmatch(v) else None

    @classmethod
    def parse_links(cls, text) -> list:
        """Строки «Название | https://…» → [{title, url}] (только http/https)."""
        out = []
        for ln in str(text or "").splitlines():
            title, _, url = ln.rpartition("|") if "|" in ln else ("", "", ln)
            url = cls.clean_url(url)
            if url:
                out.append({"title": (title.strip() or "Ссылка")[:80], "url": url})
        return out[:12]

    def ensure_slug(self, eid: int) -> str:
        ev = self.store.get_event(eid)
        if ev.get("reg_slug"):
            return ev["reg_slug"]
        import secrets
        while True:
            slug = secrets.token_urlsafe(6).replace("-", "x").replace("_", "z")
            if slug.lower() not in ("assets", "api", "series") and not self.store.event_by_slug(slug):
                break
        self.store.set_event_field(eid, reg_slug=slug)
        return slug

    def public_base(self) -> str:
        return (self.cfg.get("public", {}).get("url") or "").rstrip("/")

    # Площадки федерации: адрес и ссылка на карту для календаря fla65.ru и страницы события
    VENUES = (
        {"key": "manezh", "name": "Легкоатлетический манеж", "address": "Южно-Сахалинск, ул. Горького, 39",
         "match": ("манеж",), "q": "Легкоатлетический манеж, Южно-Сахалинск, улица Горького, 39"},
        {"key": "spartak", "name": "Стадион «Спартак»", "address": "Южно-Сахалинск, ул. Горького, 7",
         "match": ("спартак",), "q": "Стадион Спартак, Южно-Сахалинск, улица Горького, 7"},
        {"key": "triumf", "name": "ЛБК «Триумф»", "address": "Южно-Сахалинск, ул. Горького, 25А",
         "match": ("триумф",), "map": "https://yandex.ru/maps/org/biatlonny_kompleks_triumf/227359721489/"},
    )

    def venue_for(self, ev: dict) -> Optional[dict]:
        """Где проходит старт: указанное место или (если не указано) правило федерации для Южно-Сахалинска:
        кросс — ЛБК «Триумф»; апрель–октябрь — стадион «Спартак»; остальное и «в помещении» — манеж.
        Массовые забеги по улицам и старты в других городах не угадываем."""
        from urllib.parse import quote
        ymap = lambda q: "https://yandex.ru/maps/?text=" + quote(q)
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
            return {"name": pick["name"], "address": pick["address"], "map": pick.get("map") or ymap(pick["q"])}
        if place:
            return {"name": place, "address": city, "map": ymap(", ".join(x for x in (place, city) if x))}
        return None

    def event_card(self, ev: dict) -> dict:
        """Элемент календаря для сайта (см. docs/public-api.md)."""
        from urllib.parse import quote
        v = self._event_view(ev)
        base, slug = self.public_base(), ev.get("reg_slug")
        page = f"{base}/r/{slug}" if slug and v["ours"] else None
        open_, _ = self.reg_state(ev) if slug else (False, "")
        files = []
        if page:
            for f in self.store.files(ev["id"]):
                if f.get("public"):
                    ext = os.path.splitext(f["name"])[1].lstrip(".").lower()[:6]
                    files.append({"title": f["name"], "url": f"{page}/files/{f['id']}", "size": f["size"], "ext": ext})
        status = v.get("status") or "planned"
        return {"slug": slug if page else None, "name": ev["name"], "date": ev.get("date"), "date_end": ev.get("date_end"),
                "place": ev.get("place") or "", "city": ev.get("city") or "", "venue": self.venue_for(ev),
                "level": ev.get("level") or "region",
                "adaptive": v["adaptive"], "note": ev.get("note") or "", "ours": v["ours"], "kind": v["kind"],
                "status": status, "page": page,
                "reg": {"open": True, "deadline": ev.get("reg_deadline"), "url": page} if page and open_ else None,
                "start_list": f"{page}/protocol?kind=start" if page and v["pub_start"] else None,
                "results": f"{page}/protocol" if page and v["pub_results"] else None,
                "teams": f"{page}/protocol?kind=teams" if page and v["pub_results"] and ev.get("team_best") else None,
                "results_live": bool(page and v["pub_results"] and status == "running"),
                "live": self.clean_url(ev.get("live_url")), "photo": self.clean_url(ev.get("photo_url")),
                "links": self.parse_links(ev.get("links")), "files": files,
                "cover": self.cover_url(ev, page), "program": self.parse_program(ev.get("program")),
                "contacts": self.parse_contacts(ev.get("contacts")),
                "series": {"name": ev["series"], "url": f"{base}/r/series?name={quote(ev['series'])}"}
                if ev.get("series") and base else None,
                "places": [{"distance": d["name"], "limit": d["limit"], "left": d["left"]}
                           for d in self.dist_info(ev) if d["limit"]] if page and open_ else []}

    def cover_url(self, ev: dict, page: Optional[str]) -> Optional[str]:
        """Обложка страницы события: ссылка на картинку или фото из «Документов» с галочкой «на сайте»."""
        c = (ev.get("cover") or "").strip()
        m = re.fullmatch(r"file:(\d+)", c)
        if m:
            f = self.store.get_file(int(m.group(1)))
            ok = f and f["event_id"] == ev["id"] and f.get("public") and page
            return f"{page}/files/{f['id']}" if ok else None
        return self.clean_url(c)

    @staticmethod
    def parse_program(text) -> list:
        """Программа дня: строки «18:30 | Выдача номеров» или «18:30 Выдача номеров» → [{time, title}]."""
        out = []
        for ln in str(text or "").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            t, sep, title = ln.partition("|")
            if not sep:
                m = re.match(r"(\d{1,2}[:.]\d{2}(?:\s*[–—-]\s*\d{1,2}[:.]\d{2})?)\s+(.+)", ln)
                t, title = (m.group(1), m.group(2)) if m else ("", ln)
            out.append({"time": t.strip()[:20], "title": title.strip()[:200]})
        return out[:30]

    @staticmethod
    def parse_contacts(text) -> list:
        """Контакты организатора: телефон → tel:, почта → mailto:, ссылка → как есть. → [{text, href}]"""
        out = []
        for ln in str(text or "").splitlines():
            ln = ln.strip()[:200]
            if not ln:
                continue
            href = None
            mail = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", ln)
            url = re.search(r"https?://[^\s<>\"']{3,300}", ln)
            phone = re.search(r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}", ln)
            if url:
                href = url.group()
            elif mail:
                href = "mailto:" + mail.group()
            elif phone:
                href = "tel:+7" + re.sub(r"\D", "", phone.group())[1:]
            out.append({"text": ln, "href": href})
        return out[:8]

    def copy_event(self, ev: dict, who: str) -> int:
        """Копия события на следующий год: настройки, дистанции, правила, забеги — без участников и заявок."""
        def next_year(v):
            v = str(v or "")
            if not re.match(r"\d{4}-\d\d-\d\d", v):
                return v or None
            y, rest = int(v[:4]) + 1, v[4:]
            return f"{y}{'-02-28' + rest[6:] if rest.startswith('-02-29') else rest}"
        view = self._event_view(ev)
        data = {k: ev.get(k) for k in self.store.EVENT_FIELDS}
        data.update(name=re.sub(r"\b(20\d\d)\b", lambda m: str(int(m.group(1)) + 1), ev["name"]),
                    date=next_year(ev.get("date")), date_end=next_year(ev.get("date_end")),
                    reg_deadline=next_year(ev.get("reg_deadline")), reg_open=0, pub_site=0, pub_start=0,
                    pub_results=0, pub_regs=0, live_url=None, photo_url=None, kind=view["kind"], timing=view["timing"],
                    cover=None if str(ev.get("cover") or "").startswith("file:") else ev.get("cover"))
        eid = self.store.add_event(data)
        self.store.update_event(eid, data)
        for w in self.store.waves(ev["id"]):
            self.store.add_wave(eid, w["name"], w.get("category"), w.get("distance"))
        self.store.audit(who, eid, "Скопировано соревнование", f"из «{ev['name']}» ({ev.get('date') or 'без даты'})")
        return eid

    # ---- серии и кубки: сумма очков за этапы
    def series_names(self) -> list:
        seen: dict = {}
        for e in self.store.list_events():
            n = (e.get("series") or "").strip()
            if n and (e.get("pub_site") or e.get("reg_slug")):
                seen.setdefault(n.lower(), {"name": n, "events": 0})["events"] += 1
        return sorted(seen.values(), key=lambda x: x["name"])

    def series_standings(self, name: str) -> dict:
        """Зачёт серии: очки участника за каждый этап (из протокола или по месту в категории: 20, 17, 15 … 1),
        сумма — по всем этапам. Участник — фамилия и имя + год рождения."""
        key = re.sub(r"\s+", " ", name or "").strip().lower()
        evs = sorted([e for e in self.store.list_events() if (e.get("series") or "").strip().lower() == key],
                     key=lambda e: (e.get("date") or "9999", e["id"]))
        base = self.public_base()
        stages, people = [], {}
        for e in evs:
            v = self._event_view(e)
            page = f"{base}/r/{e['reg_slug']}" if e.get("reg_slug") and v["ours"] else None
            st = {"id": e["id"], "name": e["name"], "date": e.get("date"), "page": page,
                  "results": f"{page}/protocol" if page and v["pub_results"] else None, "done": False}
            stages.append(st)
            if not (v["ours"] and v["pub_results"]):
                continue
            fin = self.compute(e)["finished"]
            st["done"] = bool(fin) and e.get("status") == "finished"
            grp: dict = {}
            for x in fin:
                grp.setdefault((x["category"], x["distance"]), []).append(x)
            for (cat, dist), lst in grp.items():
                imported = any(x.get("points") is not None for x in lst) and not e.get("team_best")
                for x in lst:
                    po = x.get("place_overall") or x.get("place") or 99
                    pts = float(x["points"]) if imported and x.get("points") is not None else \
                        (self.TEAM_POINTS[po - 1] if po <= len(self.TEAM_POINTS) else 1)
                    who = re.sub(r"\s+", " ", x["name"] or "").strip()
                    if not who:
                        continue
                    group = cat or dist or "Общий зачёт"
                    p = people.setdefault((group, who.lower(), x.get("birth_year") or ""), {
                        "group": group, "name": who, "birth_year": x.get("birth_year") or "", "team": "", "by": {}})
                    p["team"] = x.get("team") or p["team"]
                    p["by"][str(e["id"])] = max(p["by"].get(str(e["id"]), 0), pts)
        groups: dict = {}
        for p in people.values():
            tot = sum(p["by"].values())
            p["total"] = int(tot) if float(tot).is_integer() else round(tot, 1)
            p["starts"] = len(p["by"])
            p["by"] = {k: int(v) if float(v).is_integer() else v for k, v in p["by"].items()}
            groups.setdefault(p["group"], []).append(p)
        out = []
        for g in sorted(groups):
            rows = sorted(groups[g], key=lambda p: (-p["total"], p["name"]))
            for i, p in enumerate(rows):
                p["place"] = rows[i - 1]["place"] if i and rows[i - 1]["total"] == p["total"] else i + 1
                p.pop("group")
            out.append({"group": g, "rows": rows})
        return {"name": evs[0]["series"].strip() if evs else name, "stages": stages, "groups": out,
                "updated": fmt_db(now_local())[:19].replace(" ", "T")}

    def pickup_view(self, ev: dict) -> dict:
        """Выдача стартовых пакетов: кто получил номер, кто ещё не пришёл."""
        dist = {w["name"]: w.get("distance") or "" for w in self.store.waves(ev["id"])}
        rd = {r["id"]: r.get("distance") or "" for r in self.store.registrations(ev["id"])}
        people: dict = {}          # номер выдаётся один на человека, даже если он заявлен на несколько видов
        for r in self.store.entries_rows(ev["id"]):
            d = dist.get(r["wave"] or "", "") or rd.get(r.get("reg_id"), "")
            p = people.setdefault(r["bib"], {"bib": r["bib"], "name": r["name"] or "", "team": r["team"] or "",
                                             "category": r["category"] or "", "birth_year": r["birth_year"] or "",
                                             "wave": r["wave"] or "", "distances": [], "members": r.get("members") or "",
                                             "picked_at": r.get("picked_at")})
            if d and d not in p["distances"]:
                p["distances"].append(d)
            p["picked_at"] = p["picked_at"] or r.get("picked_at")
        rows = [dict(p, distance=", ".join(p["distances"])) for p in people.values()]
        picked = sum(1 for r in rows if r["picked_at"])
        return {"rows": rows, "total": len(rows), "picked": picked, "left": len(rows) - picked}

    def registered_list(self, ev: dict) -> dict:
        """7.1: открытый «Список прохождения регистрации» для тренеров — БЕЗ авторизации, поэтому строго минимальный набор:
        «Фамилия И.», возрастная группа из справочника AGES и дисциплины, на которые заявка одобрена секретарём.
        Ни номеров, ни дорожек, ни дат рождения, ни команд, ни контактов; у эстафет — только название команды."""
        regs = [r for r in self.store.registrations(ev["id"]) if r["status"] == "approved"]
        year = int(ev["date"][:4]) if ev.get("date") else dt.date.today().year
        ages = [a for a in (self.disciplines()["data"].get("ages") or []) if a.get("id")]
        ordered = sorted([a for a in ages if a["id"] != "sen"], key=lambda a: int(a.get("max", 200))) + [a for a in ages if a["id"] == "sen"]

        def group_of(birth) -> str:
            try:
                age = year - int(str(birth)[:4])
            except ValueError:
                return "Без возрастной группы"
            for a in ordered:
                if int(a.get("min", 0)) <= age <= int(a.get("max", 200)):
                    return a["name"]
            return "Без возрастной группы"
        order = {d: i for i, d in enumerate(self.reg_distances(ev))}
        key_of = self._people(regs)
        people: dict = {}
        relays: dict = {}
        for r in sorted(regs, key=lambda r: r["id"]):
            if r.get("relay"):
                relays.setdefault((r["relay"], r["distance"]), None)
                continue
            first = str(r.get("first_name") or "").strip()
            p = people.setdefault(key_of[r["id"]], {
                "name": f"{str(r['last_name']).strip().capitalize()} {first[:1].upper()}." if first else str(r["last_name"]).strip().capitalize(),
                "group": group_of(r.get("birth_date")), "disciplines": []})
            if r["distance"] not in p["disciplines"]:
                p["disciplines"].append(r["distance"])
        groups: dict = {}
        for p in people.values():
            p["disciplines"].sort(key=lambda d: order.get(d, 99))
            groups.setdefault(p["group"], []).append({"name": p["name"], "disciplines": p["disciplines"]})
        rank = {a["name"]: i for i, a in enumerate(ordered)}
        out = [{"group": g, "athletes": sorted(lst, key=lambda x: x["name"].lower())}
               for g, lst in sorted(groups.items(), key=lambda kv: (rank.get(kv[0], 99), kv[0]))]
        return {"event": {"name": ev["name"], "date": ev.get("date"), "place": ev.get("place") or ""},
                "updated": fmt_db(now_local())[:16], "total": len(people), "groups": out,
                "relays": [{"team": t, "discipline": d} for (t, d) in sorted(relays)]}

    def calendar(self, year: Optional[int]) -> dict:
        evs = [e for e in self.store.list_events() if e.get("pub_site")]
        if year:
            evs = [e for e in evs if (e.get("date") or "").startswith(str(year))]
        evs.sort(key=lambda e: (e.get("date") or "9999", e["id"]))
        return {"year": year, "updated": fmt_db(now_local())[:19].replace(" ", "T"),
                "events": [self.event_card(e) for e in evs]}

    PUBLIC_EVENT_KEYS = ("id", "name", "date", "date_end", "place", "city", "organizer", "start_clock", "chief_judge",
                         "chief_secretary", "status", "start_time", "finished_at", "finish_device", "kind")

    def _public_event(self, ev: dict) -> dict:
        v = self._event_view(ev)
        out = {k: v.get(k) for k in self.PUBLIC_EVENT_KEYS}
        out["waves"] = [{k: w.get(k) for k in ("name", "category", "distance", "state", "start_time")} for w in v["waves"]]
        return out

    @staticmethod
    def _public_rows(rows: list) -> list:
        return [{k: val for k, val in r.items() if k not in ("id", "reg_id", "picked_at", "detail")} for r in rows]

    def public_results(self, ev: dict) -> dict:
        r = self.compute(ev)
        return {"event": self._public_event(ev), "started": r["started"],
                "finished": self._public_rows(r["finished"]), "not_seen": self._public_rows(r["not_seen"]), "groups": r["groups"], "teams": r.get("teams") or [],
                "final": (ev.get("status") == "finished")}

    def public_startlist(self, ev: dict) -> dict:
        sl = self.startlist(ev)
        for h in sl["heats"]:
            h["entries"] = self._public_rows(h["entries"])
        return {"event": self._public_event(ev), "heats": sl["heats"], "no_heat": self._public_rows(sl["no_heat"])}

    def import_calendar(self, year: int, who: str) -> dict:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed", f"calendar-{int(year)}.json")
        try:
            with open(p, encoding="utf-8") as f:
                items = json.load(f)["events"]
        except (OSError, ValueError, KeyError):
            return {"error": f"нет календаря на {year} год"}
        evs = self.store.list_events()
        have = {(e["name"].strip().lower(), e.get("date")) for e in evs}
        added = updated = 0
        for it in items:
            if (it["name"].strip().lower(), it.get("date")) in have:
                continue
            # старт перенесли или уточнили (название, дата, место) — обновляем прежнюю запись, а не плодим вторую
            rp = it.get("replaces") or {}
            old = next((e for e in evs if rp and e["name"].strip().lower() == str(rp.get("name", "")).strip().lower()
                        and e.get("date") == rp.get("date")), None)
            if old:
                eid = old["id"]
                self.store.update_event(eid, {"name": it["name"], "date": it.get("date"), "place": it.get("place") or None})
                updated += 1
            else:
                eid = self.store.add_event({"name": it["name"], "date": it.get("date"), "place": it.get("place") or None})
            self.store.update_event(eid, {"kind": it.get("kind") or "stadium", "pub_site": True,
                                          "ours": it.get("ours", it.get("level") in ("region", "mass")), "level": it.get("level"),
                                          "adaptive": bool(it.get("adaptive")), "date_end": it.get("date_end"),
                                          "city": it.get("city"), "note": it.get("note"),
                                          "links": "\n".join(f"{l['title']} | {l['url']}" for l in it.get("links") or [])})
            if (it.get("date_end") or it.get("date") or "9999") < now_local().strftime("%Y-%m-%d"):
                self.store.set_event_field(eid, status="finished", archived=1)   # прошедшие — сразу в архив
            self.ensure_slug(eid)
            added += 0 if old else 1
        self.store.audit(who, None, "Импорт календаря", f"{year}: добавлено {added}" + (f", обновлено {updated}" if updated else ""))
        return {"added": added, "updated": updated, "total": len(items)}



    def _refresh_event_start(self, eid: int) -> None:
        """Общее время старта соревнования = самый ранний старт забега."""
        starts = [w["start_time"] for w in self.store.waves(eid) if w.get("start_time")]
        ev = self.store.get_event(eid)
        if starts:
            self.store.set_event_field(eid, start_time=min(starts),
                                       status="finished" if ev["status"] == "finished" else "running")
        elif self.store.waves(eid):
            self.store.set_event_field(eid, start_time=None, status="planned")

    # ---- расчёт результатов и предупреждений
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

    # ---- разряд / звание (обязательное поле карточки участника)
    RANKS = ("Б/р", "3 юн.", "2 юн.", "1 юн.", "3 р.", "2 р.", "1 р.", "КМС", "МС", "МСМК", "ЗМС")
    _RANK_ALIAS = {"бр": "Б/р", "безразряда": "Б/р", "нет": "Б/р", "кмс": "КМС", "мс": "МС", "мсмк": "МСМК", "змс": "ЗМС",
                   "3юн": "3 юн.", "2юн": "2 юн.", "1юн": "1 юн.", "3р": "3 р.", "2р": "2 р.", "1р": "1 р.",
                   "3юношеский": "3 юн.", "2юношеский": "2 юн.", "1юношеский": "1 юн.",
                   "3разряд": "3 р.", "2разряд": "2 р.", "1разряд": "1 р.", "iii": "3 р.", "ii": "2 р.", "i": "1 р.",
                   "3спортивный": "3 р.", "2спортивный": "2 р.", "1спортивный": "1 р."}

    @classmethod
    def norm_rank(cls, v) -> str:
        """Разряд как в протоколах: «1р», «1 разряд», «кмс» → «1 р.», «КМС». Пустое — пустая строка."""
        t = re.sub(r"\s+", " ", str(v or "")).strip()[:20]
        key = re.sub(r"[\s./]+", "", t.lower()).replace("первый", "1").replace("второй", "2").replace("третий", "3")
        return cls._RANK_ALIAS.get(key) or cls._RANK_ALIAS.get(key.rstrip("."), "") or t

    # ---- ручной хронометраж: три секундомера; попытки в прыжках и метаниях
    @staticmethod
    def round_up_tenth(x: float) -> float:
        return math.ceil(round(x * 10, 6)) / 10.0

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

    ATTEMPT_MARKS = {"X": "X", "Х": "X", "x": "X", "х": "X", "-": "-", "–": "-", "—": "-", "R": "r", "r": "r", "Р": "r"}

    @classmethod
    def attempt_slots(cls, name) -> int:
        """Сколько ячеек попыток: 6 в прыжках и метаниях; в высоте и шесте — до 12 покорённых высот."""
        d = cls.discipline(name)
        if not d or not d.get("attempts"):
            return 0
        return 12 if d.get("result") == "height" else 6

    CART_KEYS = ("type", "dist", "gk", "sf", "mode", "orient")     # что считается одним и тем же листом корзины

    def ui_view(self, eid: int) -> dict:
        st = self.store.ui_states(eid)
        st.setdefault("wizard", {"value": {}, "rev": 0, "who": "", "cid": "", "at": ""})
        st.setdefault("cart", {"value": [], "rev": 0, "who": "", "cid": "", "at": ""})
        return {"state": st}

    def ui_write(self, ev: dict, data: dict, who: str) -> tuple:
        """POST …/ui. wizard: {value:{disc,step,sex,ages}} — последний записавший выигрывает.
        cart: {op: add|remove|toggle|clear} — операции складываются на сервере, поэтому два секретаря,
        одновременно добавляющие листы, не затирают друг друга."""
        eid, key, cid = ev["id"], str(data.get("key") or ""), str(data.get("cid") or "")[:40]
        if key == "wizard":
            v = data.get("value") if isinstance(data.get("value"), dict) else {}
            lim = self.age_limits()
            try:
                step = int(v.get("step") or 1)
            except (TypeError, ValueError):
                step = 1
            sex = str(v.get("sex") or "")
            val = {"disc": str(v.get("disc") or "")[:120], "step": max(1, min(5, step)), "sex": sex if sex in ("М", "Ж") else "",
                   "ages": [a for a in (v.get("ages") if isinstance(v.get("ages"), list) else []) if a in lim]}
            rev = self.store.ui_put(eid, "wizard", val, who, cid)
            return 200, {"key": key, "rev": rev, "value": val}
        if key == "cart":
            op = str(data.get("op") or "")
            items = self.store.ui_states(eid).get("cart", {}).get("value") or []
            items = items if isinstance(items, list) else []
            added = False
            if op == "add" and isinstance(data.get("item"), dict):
                it = {str(k)[:20]: (v if isinstance(v, (int, float, bool)) else str(v)[:200])
                      for k, v in list(data["item"].items())[:14] if isinstance(v, (str, int, float, bool))}
                if any(all((x.get(k) or "") == (it.get(k) or "") for k in self.CART_KEYS) for x in items):
                    pass
                elif len(items) >= 200:
                    return 400, {"error": "в корзине слишком много листов — очистите её"}
                else:
                    it.update({"id": f"{int(time.time() * 1000):x}{random.randrange(36 ** 3):03x}", "on": True})
                    items.append(it)
                    added = True
            elif op == "remove":
                items = [x for x in items if x.get("id") != data.get("id")]
            elif op == "toggle":
                for x in items:
                    if x.get("id") == data.get("id"):
                        x["on"] = bool(data.get("on"))
            elif op == "clear":
                items = []
            else:
                return 400, {"error": "неизвестная операция с корзиной"}
            rev = self.store.ui_put(eid, "cart", items, who, cid)
            return 200, {"key": key, "rev": rev, "value": items, "added": added}
        return 400, {"error": "неизвестный раздел состояния"}

    def _entry_of(self, bib: str, cands: list, distance, ed: dict) -> tuple:
        """Строка участника по номеру. Номер многоборца стоит в нескольких дисциплинах — тогда нужно название дисциплины."""
        if not cands:
            return None, "нет такого номера"
        dist = str(distance or "").strip()
        if dist:
            hit = [c for c in cands if self._dkey(ed.get(c["id"]) or "") == self._dkey(dist)]
            return (hit[0], None) if hit else (None, f"номер {bib} не заявлен на «{dist}»")
        if len(cands) == 1:
            return cands[0], None
        return None, "номер стоит в нескольких дисциплинах — укажите дисциплину"

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

    RESULT_RE = re.compile(r"(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,5})(?:[.,](\d{1,3}))?")
    STATUSES = ("DNS", "DNF", "DQ", "NM")

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

    # ---- справочник дисциплин лёгкой атлетики (seed/disciplines.json) и типы результата
    _DISC: Optional[dict] = None

    @staticmethod
    def _dkey(name) -> str:
        t = re.sub(r"(?<=\d)[xх*](?=\d)", "×", str(name or "").lower())
        return re.sub(r"[\s.\-]+", "", t).replace("ё", "е")

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

    @classmethod
    def discipline(cls, name) -> Optional[dict]:
        return cls.disciplines()["index"].get(cls._dkey(name)) if name else None

    # ---- выполненные разряды по нормам ЕВСК (seed/rank_norms.json, из приложения к приказу Минспорта)
    NO_RANK = "—"                         # ручная отметка «разряд не выполнен»
    RANK_ORDER = ("МСМК", "МС", "КМС", "1 р.", "2 р.", "3 р.", "1 юн.", "2 юн.", "3 юн.")
    RANK_MIN_AGE = {"МСМК": 16, "МС": 15, "КМС": 14}          # остальные разряды — с 10 лет
    # статус соревнований (поле «уровень» события) → высший разряд, который на них можно выполнить
    RANK_CAP = {"russia": "МС", "dfo": "МС", "interregion": "КМС", "region": "1 р.", "mass": "2 р."}
    _NORMS = None
    _MULTI = {"десяти": "10", "восьми": "8", "семи": "7", "шести": "6", "пяти": "5", "четырех": "4", "трое": "3", "тре": "3"}

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

    @staticmethod
    def age_group(age: int) -> str:
        for lim in (12, 14, 16, 18, 20, 23):
            if age < lim:
                return f"u{lim}"
        return "sen"

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

    @classmethod
    def discipline_kind(cls, name) -> str:
        """run — бег (время), tech — техника (попытки: прыжки, метания), other — очки и прочее."""
        d = cls.discipline(name)
        if not d:
            return "run"
        if d.get("attempts") or d.get("result") in ("distance", "height"):
            return "tech"
        return "run" if d.get("result") == "time" else "other"

    def entry_dists(self, eid: int, erows: Optional[list] = None) -> dict:
        """id строки участника → её дисциплина: дистанция забега, а у смешанного «общего списка» — из заявки."""
        erows = erows if erows is not None else self.store.entries_rows(eid)
        wd = {w["name"]: w.get("distance") for w in self.store.waves(eid)}
        rd = {r["id"]: r.get("distance") for r in self.store.registrations(eid)}
        return {e["id"]: (wd.get(e["wave"] or "") or rd.get(e.get("reg_id")) or None) for e in erows}

    @classmethod
    def result_type(cls, name) -> str:
        """time · distance · height · points. Неизвестная дисциплина — время, как раньше."""
        d = cls.discipline(name)
        return d["result"] if d else "time"

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

    @classmethod
    def result_hint(cls, rtype: str) -> str:
        return (cls.disciplines()["data"].get("result_types", {}).get(rtype) or {}).get("hint") or "12.84 или 4:05.32"

    TEAM_POINTS = (20, 17, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
    GENDER_WORDS = ("мальчики", "юноши", "юниоры", "мужчины", "девочки", "девушки", "юниорки", "женщины")

    def team_standings(self, finished: list, best: int) -> list:
        """Командный зачёт: в каждой категории команде идут очки её `best` лучших участников;
        категории одной возрастной группы (мальчики и девочки 2017–2018 г.р.) — колонки одной таблицы.
        Очки — из протокола (колонка «Очки»), а если их нет — по месту: 20, 17, 15, 14, 13 … 1, дальше по 1."""
        by_cat: dict = {}
        for r in finished:
            by_cat.setdefault((r["category"], r["distance"]), []).append(r)
        groups: dict = {}
        for (cat, dist), lst in by_cat.items():
            lst.sort(key=lambda r: r.get("place_overall") or 0)
            imported = any(r.get("points") is not None for r in lst)
            if not imported:
                for i, r in enumerate(lst):
                    r["points"] = self.TEAM_POINTS[i] if i < len(self.TEAM_POINTS) else 1
            low = (cat or "").strip().lower()
            word = next((w for w in self.GENDER_WORDS if low.startswith(w)), None)
            if word:
                grp, col = (cat or "").strip()[len(word):].strip(" ,·-") or dist or "Общий зачёт", word.capitalize()
            else:
                grp, col = cat or dist or "Общий зачёт", "Очки"
            g = groups.setdefault(grp, {"cols": [], "teams": {}})
            if col not in g["cols"]:
                g["cols"].append(col)
            per_team: dict = {}
            for r in lst:
                if r.get("team") and r.get("points") is not None:
                    per_team.setdefault(r["team"], []).append(float(r["points"]))
            for team, pts in per_team.items():
                t = g["teams"].setdefault(team, {})
                t[col] = t.get(col, 0) + sum(sorted(pts, reverse=True)[:best])
        out = []
        for grp in sorted(groups, reverse=True):
            g = groups[grp]
            cols = sorted(g["cols"], key=lambda c: (self.GENDER_WORDS.index(c.lower()) if c.lower() in self.GENDER_WORDS else 99))
            rows = [{"team": t, "by": {c: (int(v) if float(v).is_integer() else v) for c, v in by.items()},
                     "total": sum(by.values())} for t, by in g["teams"].items()]
            rows.sort(key=lambda r: (-r["total"], r["team"]))
            for i, r in enumerate(rows):
                r["place"] = rows[i - 1]["place"] if i and rows[i - 1]["total"] == r["total"] else i + 1
                r["total"] = int(r["total"]) if float(r["total"]).is_integer() else r["total"]
            out.append({"group": grp, "columns": cols, "best": best, "rows": rows})
        return out

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

    def event_results(self, ev: dict) -> dict:
        return self.compute(ev)

    # ---- старт
    def _parse_clock(self, ev: dict, when: str) -> dt.datetime:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,3}))?)?", when.strip())
        if not m:
            raise ValueError("время: ЧЧ:ММ:СС или ЧЧ:ММ:СС.ммм")
        h, mi, s, frac = m.groups()
        base = now_local()
        if ev.get("date"):
            try:
                base = dt.datetime.strptime(ev["date"], "%Y-%m-%d")
            except ValueError:
                pass
        return base.replace(hour=int(h), minute=int(mi), second=int(s or 0), microsecond=frac_to_us(frac))

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
        return self._event_view(self.store.get_event(ev["id"]))

    # ---- API
    def _api(self, method: str, path: str, qs: dict, body: bytes, actor: str = "", headers: Optional[dict] = None):
        J = "application/json; charset=utf-8"
        headers = headers or {}

        def ok(obj, code=200):
            return code, J, json.dumps(obj, ensure_ascii=False), None

        def err(msg, code=400):
            return code, J, json.dumps({"error": msg}, ensure_ascii=False), None

        mi = re.fullmatch(r"/api/events/(\d+)/import", path)
        if mi and method == "POST":
            ev = self.store.get_event(int(mi.group(1)))
            if ev is None:
                return err("соревнование не найдено", 404)
            if not self.reg_distances(ev):
                return err("сначала задайте дистанции во вкладке «Регистрация»")
            rows, e = self.parse_team_file(ev, body)
            if e:
                return err(e)
            ev = {**ev, "_no_limit": True}          # секретарь может внести сверх лимита мест
            info = {"team": qs.get("team", ""), "coach": qs.get("coach", "")}
            if qs.get("check"):
                out = self._strip_check(self.check_team(ev, info, rows))
                return ok(out)
            code, out = self.submit_team(ev, info, rows, status="approved", actor=actor)
            return code, J, json.dumps(out, ensure_ascii=False), None

        if path == "/api/system/update" and method == "POST":
            code, out = self.receive_update(body, actor)
            return code, J, json.dumps(out, ensure_ascii=False), None

        mf = re.fullmatch(r"/api/events/(\d+)/files", path)
        if mf and method == "POST" and "json" not in headers.get("content-type", ""):
            ev = self.store.get_event(int(mf.group(1)))
            if ev is None:
                return err("соревнование не найдено", 404)
            from urllib.parse import unquote
            name = unquote(headers.get("x-file-name", "")) or "file"
            if not body:
                return err("пустой файл")
            folder = unquote(headers.get("x-folder", "")) or None
            f = self.save_file(ev["id"], name, body, "protocol", actor, folder)
            self.store.audit(actor, ev["id"], "Загружен файл", f"{f['folder']} / {f['name']} ({f['size'] // 1024} КБ)")
            return ok({"file": f}, 201)

        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return err("неверный JSON")
        if not isinstance(data, dict):
            return err("ожидается JSON-объект")
        judge = str(data.get("judge") or "").strip()[:40]
        who = f"{actor} / {judge}" if judge else actor

        if path == "/api/clock":
            return ok({"server_epoch_ms": int(time.time() * 1000), "server_time": fmt_db(now_local())})
        if path == "/api/system":
            return ok(self.system_view())
        if path == "/api/system/update":
            return ok(self.update_state())
        if path == "/api/system/update/install" and method == "POST":
            code, out = self.confirm_update_install(actor)
            return code, J, json.dumps(out, ensure_ascii=False), None
        if path == "/api/log":
            return ok({"log": self.store.audit_list(None)})
        if path == "/api/system/scoreboard/control":
            return 302, "text/plain; charset=utf-8", "", {"Location": "/scoreboard" + (f"?event={int(qs['event'])}" if str(qs.get("event", "")).isdigit() else "")}
        if path == "/api/scoreboard/state":
            # пульт табло: GET — что сейчас показывать (табло спрашивает раз в 1,5 с), POST — секретарь/визуализатор меняет режим
            if method == "GET":
                eid_ = int(qs["event"]) if str(qs.get("event", "")).isdigit() else 0
                ev_ = self.store.get_event(eid_) if eid_ else None
                if ev_ is None:
                    return err("соревнование не найдено", 404)
                return ok(self.scoreboard_view(ev_))
            try:
                d = json.loads(body.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return err("неверные данные")
            ev_ = self.store.get_event(int(d.get("event_id") or 0)) if str(d.get("event_id") or "").isdigit() else None
            if ev_ is None:
                return err("соревнование не найдено", 404)
            mode = d.get("mode")
            if mode not in self.SB_MODES:
                return err("режим табло: auto, fixed или rotate")
            keys = {g["key"] for g in self.scoreboard_groups(ev_)}
            group = str(d.get("group") or d.get("wave_id") or "")
            if mode == "fixed" and group not in keys:
                return err("выберите вид программы для фиксации")
            rot = d.get("rotate") if isinstance(d.get("rotate"), dict) else {}
            interval = max(5, min(int(rot.get("interval") or 15), 120))
            rgroups = [k for k in (rot.get("groups") or []) if k in keys][:40]
            state = {"mode": mode, "group": group if mode == "fixed" else "", "rotate": {"interval": interval, "groups": rgroups},
                     "by": actor}
            self.store.set_scoreboard(ev_["id"], state)
            self.store.audit(actor, ev_["id"], "Табло: " + self.SB_MODES[mode], group if mode == "fixed" else
                             (f"каждые {interval} с" if mode == "rotate" else ""))
            return ok(self.scoreboard_view(ev_))
        if path == "/api/disciplines" and method == "GET":
            data = self.disciplines()["data"]
            return ok({k: data.get(k) for k in ("version", "updated", "sources", "groups", "result_types", "ages", "disciplines", "presets")})
        if path == "/api/calc" and method == "POST":      # 6.0: официальный результат по сырым цифрам — считает только сервер
            return ok(self.calc_official(str(data.get("distance") or ""), data.get("rows") if isinstance(data.get("rows"), list) else []))
        if path == "/api/default-rules" and method == "GET":
            # возрастные группы по образцу положений ВФЛА для года соревнований (для мастера создания)
            y = str(qs.get("year", ""))
            ev0 = {"date": f"{y}-06-01"} if y.isdigit() and 1990 <= int(y) <= 2100 else None
            return ok({"rules": self.default_rules(ev0), "year": int(y) if ev0 else now_local().year})
        if path == "/api/calendar":
            if method == "POST" and data.get("import"):
                out = self.import_calendar(int(data.get("year") or now_local().year), who)
                return (err(out["error"], 404) if "error" in out else ok(out))
            return ok(self.calendar(int(qs["year"]) if str(qs.get("year", "")).isdigit() else None))
        if path == "/api/events":
            if method == "GET":
                return ok({"events": [self._event_view(e) for e in self.store.list_events()]})
            if method == "POST":
                name = str(data.get("name", "")).strip()
                if not name:
                    return err("укажите название")
                eid = self.store.add_event({**data, "name": name})
                extra = {k: data[k] for k in ("kind", "timing", "pub_site", "ours", "level", "adaptive", "date_end",
                                              "city", "note", "team_best") if k in data}
                if extra:
                    self.store.update_event(eid, extra)
                if data.get("pub_site"):
                    self.ensure_slug(eid)
                self.store.audit(who, eid, "Создано соревнование", name)
                return ok(self._event_view(self.store.get_event(eid)), 201)
            return err("метод не поддерживается", 405)

        m = re.fullmatch(r"/api/events/(\d+)(?:/([a-z.-]+))?(?:/(\d+))?", path)
        if not m:
            return err("нет такого адреса", 404)
        ev = self.store.get_event(int(m.group(1)))
        if ev is None:
            return err("соревнование не найдено", 404)
        eid = ev["id"]
        action = m.group(2) or ""
        sub_id = int(m.group(3)) if m.group(3) else None

        if method == "GET":
            if action == "":
                return ok(self._event_view(ev))
            if action == "results":
                return ok(self.compute(ev))
            if action == "results.csv":
                return self._results_csv(ev)
            if action == "entries":
                rows = self.store.entries_rows(eid)
                lines = []
                for r in rows:
                    pts = r.get("points")
                    vals = [r["bib"], r["wave"] or "",
                            r["name"] or "", r["birth_year"] or "", r["team"] or "", r["category"] or "",
                            str(r["lane"] or ""), r["coach"] or "", r["seed"] or "",
                            r.get("status") or r.get("result") or "",
                            "" if pts is None else (str(int(pts)) if float(pts).is_integer() else str(pts)),
                            r.get("rank") or ""]
                    while len(vals) > 2 and not vals[-1]:
                        vals.pop()
                    lines.append(";".join(vals))
                return ok({"text": "\n".join(lines), "count": len(rows)})
            if action == "manual":
                marks = self.store.manual_list(eid)
                for mk in marks:
                    mk["epoch_ms"] = self._epoch_ms(parse_db(mk["ts"]))
                return ok({"marks": marks})
            if action == "log":
                return ok({"log": self.store.audit_list(eid)})
            if action == "files":
                fl = self.store.files(eid)
                if qs.get("folder"):
                    fl = [f for f in fl if f["folder"] == qs["folder"]]
                return ok({"files": fl, "folders": list(self.store.FOLDERS)})
            if action == "regs":
                out = self.regs_view(ev)
                out["consent"] = self.consent_text(ev)
                out["default_rules"] = self.default_rules(ev)
                out["dist_info"] = self.dist_info(ev)
                return ok(out)
            if action == "regs.csv":
                return self._regs_csv(ev)
            if action == "startlist":
                return ok(self.startlist(ev))
            if action == "ui":              # 6.0: общее состояние Мастера и корзины печати
                return ok(self.ui_view(eid))
            if action == "bibs":            # 5.2: шаг 2 Мастера — ручные нагрудные номера
                ages = [a for a in str(qs.get("ages") or "").split(",") if a]
                return ok(self.bibs_view(ev, {"distance": qs.get("distance"), "sex": qs.get("sex"), "ages": ages}))
            if action == "startlist.xlsx":  # 5.2: стартовый протокол для судей с ручкой
                return self.startlist_xlsx(ev, qs)
            if action == "pickup":
                return ok(self.pickup_view(ev))
            if action == "template.xlsx":
                return self._template_response(ev)
            if action == "qr.png":
                base = (self.cfg.get("public", {}).get("url") or "").rstrip("/")
                if not (base and ev.get("reg_slug")):
                    return err("нет публичного адреса", 404)
                import shutil
                import subprocess
                if not shutil.which("qrencode"):
                    return err("не установлен qrencode", 404)
                png = subprocess.run(["qrencode", "-t", "PNG", "-s", "12", "-m", "2", "-o", "-",
                                      f"{base}/r/{ev['reg_slug']}"], capture_output=True, timeout=10).stdout
                return 200, "image/png", png, {"Content-Disposition": 'inline; filename="qr-registraciya.png"'}
            return err("нет такого адреса", 404)
        if method != "POST":
            return err("метод не поддерживается", 405)

        if action == "":
            if "name" in data and not str(data["name"]).strip():
                return err("название не может быть пустым")
            for k in ("live_url", "photo_url"):
                if data.get(k) and not self.clean_url(data[k]):
                    return err("ссылка должна начинаться с https://")
            self.store.update_event(eid, data)
            if data.get("reg_open") or data.get("pub_site"):
                self.ensure_slug(eid)
            self.store.audit(who, eid, "Изменены настройки", ", ".join(k for k in data if k != "judge"))
            return ok(self._event_view(self.store.get_event(eid)))
        if action == "copy":
            new = self.copy_event(ev, who)
            return ok(self._event_view(self.store.get_event(new)), 201)
        if action == "pickup":
            # выдача стартового пакета: по номеру; undo — отменить отметку
            bib = str(data.get("bib") or "").strip()
            ts = None if data.get("undo") else fmt_db(now_local())[:19]
            if not self.store.set_picked(eid, bib, ts):
                return err("нет участника с таким номером", 404)
            if data.get("undo"):
                self.store.audit(who, eid, "Выдача номера отменена", f"№{bib}")
            v = self.pickup_view(ev)
            return ok({"bib": bib, "picked_at": ts, "picked": v["picked"], "total": v["total"]})
        if action == "relay":
            # эстафета вручную (секретарь): сразу подтверждена, сверх лимита можно
            code, out = self.submit_relay({**ev, "_no_limit": True}, data, status="approved", actor=who)
            return code, J, json.dumps(out, ensure_ascii=False), None
        if action == "delete":
            self.store.delete_event(eid)
            self.store.audit(who, None, "Удалено соревнование", ev["name"])
            return ok({"deleted": eid})
        if action == "start":
            wave = str(data.get("wave") or "").strip() or None
            try:
                out = self.start_event(ev, data.get("time"), wave, data.get("epoch_ms"))
            except (ValueError, TypeError, OverflowError, OSError) as e:
                return err(str(e))
            st = next((w["start_time"] for w in out["waves"] if w["name"] == wave), None) if wave else out["start_time"]
            self.store.audit(who, eid, "СТАРТ" + (f" «{wave}»" if wave else ""), st or "")
            return ok(out)
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
        if action == "finish":
            if ev.get("status") == "finished":          # повторное нажатие — без второго снимка и записи в журнале
                return ok(self._event_view(ev))
            self.store.set_event_field(eid, status="finished", finished_at=fmt_db(now_local()))
            snap = self.snapshot_results(ev, who)
            self.store.audit(who, eid, "Соревнование завершено",
                             "регистрация закрыта, на сайте — в прошедших, протокол итоговый"
                             + (f"; снимок результатов: {snap['name']}" if snap else ""))
            return ok(self._event_view(self.store.get_event(eid)))
        if action == "snapshot":
            snap = self.snapshot_results(ev, who)
            self.store.audit(who, eid, "Сохранён снимок результатов", snap["name"] if snap else "")
            return ok({"file": snap})
        if action == "archive":
            flag = 0 if data.get("restore") else 1
            self.store.set_event_field(eid, archived=flag)
            self.store.audit(who, eid, "Перенесено в архив" if flag else "Возвращено из архива")
            return ok(self._event_view(self.store.get_event(eid)))
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
        if action == "files" and sub_id is not None and "public" in data:
            f = self.store.get_file(sub_id)
            if f is None or f["event_id"] != eid:
                return err("файл не найден", 404)
            self.store.set_file_public(sub_id, bool(data["public"]))
            self.store.audit(who, eid, "Файл на сайте" if data["public"] else "Файл убран с сайта", f["name"])
            return ok({"public": bool(data["public"])})
        if action == "files" and sub_id is not None and data.get("folder"):
            f = self.store.get_file(sub_id)
            if f is None or f["event_id"] != eid:
                return err("файл не найден", 404)
            if data["folder"] not in self.store.FOLDERS:
                return err("нет такой папки")
            self.store.move_file(sub_id, data["folder"])
            self.store.audit(who, eid, "Файл перенесён", f"{f['name']} → {data['folder']}")
            return ok({"moved": sub_id})
        if action == "files" and sub_id is not None and data.get("delete"):
            f = self.store.get_file(sub_id)
            if f is None or f["event_id"] != eid:
                return err("файл не найден", 404)
            try:
                os.remove(os.path.join(self.files_dir, f["stored"]))
            except OSError:
                pass
            self.store.delete_file_row(sub_id)
            self.store.audit(who, eid, "Удалён файл", f["name"])
            return ok({"deleted": sub_id})
        if action == "reopen":
            # «Возобновить»: всё как до «Завершить» — статус по старту, из архива назад, регистрация снова
            # подчиняется своим настройкам (галочка и срок приёма), на сайте — снова в предстоящих / идущих.
            # Результаты, сетка и снимки протоколов не трогаются.
            new = "running" if ev.get("start_time") else "planned"
            self.store.set_event_field(eid, status=new, finished_at=None, archived=0)
            nv_ = self.store.get_event(eid)
            reg_ok, why = self.reg_state(nv_)
            self.store.audit(who, eid, "Соревнование возобновлено",
                             "; ".join(x for x in (
                                 f"было завершено {str(ev['finished_at'])[:16]}" if ev.get("finished_at") else "",
                                 "возвращено из архива" if ev.get("archived") else "",
                                 "идёт" if new == "running" else "ждёт старта",
                                 "регистрация открыта" if reg_ok else f"регистрация: {why.lower()}") if x))
            return ok(self._event_view(nv_))
        if action == "waves":
            waves = self.store.waves(eid)
            cat = str(data.get("category") or "").strip()[:40] or None
            dist = str(data.get("distance") or "").strip()[:20] or None
            if data.get("next"):
                # следующий забег: «Забег N+1», категория и дистанция — как у последнего, если не заданы
                last = waves[-1] if waves else {}
                nums = [int(m.group(1)) for w in waves for m in [re.fullmatch(r"Забег (\d+)", w["name"])] if m]
                name = f"Забег {max(nums + [len(waves)]) + 1}"
                self.store.add_wave(eid, name, cat if "category" in data else last.get("category"),
                                    dist if "distance" in data else last.get("distance"))
                self.store.audit(who, eid, "Добавлен забег", name)
                out = self._event_view(self.store.get_event(eid))
                out["created"] = name
                return ok(out)
            name = str(data.get("name", "")).strip()[:40]
            if not name:
                return err("укажите название забега")
            if data.get("delete"):
                self.store.delete_wave(eid, name)
                self._refresh_event_start(eid)
                self.store.audit(who, eid, "Удалён забег", name)
            elif data.get("finish"):
                w = self.store.get_wave(eid, name)
                if not w or not w.get("start_time"):
                    return err("забег ещё не стартовал")
                fin = now_local()
                if data.get("epoch_ms"):
                    fin = dt.datetime.fromtimestamp(float(data["epoch_ms"]) / 1000.0)
                self.store.update_wave(eid, name, finished_at=fmt_db(fin))
                self.store.audit(who, eid, "ФИНИШ забега", f"{name} · {fmt_db(fin)[11:]}")
            elif data.get("reopen"):
                self.store.update_wave(eid, name, finished_at=None)
                self.store.audit(who, eid, "Забег открыт снова", name)
            elif self.store.get_wave(eid, name):
                upd = {}
                if "category" in data:
                    upd["category"] = cat
                if "distance" in data:
                    upd["distance"] = dist
                new_name = str(data.get("new_name") or "").strip()[:40]
                if upd:
                    self.store.update_wave(eid, name, **upd)
                if new_name and new_name != name:
                    if self.store.get_wave(eid, new_name):
                        return err(f"забег «{new_name}» уже есть")
                    self.store.rename_wave(eid, name, new_name)
                self.store.audit(who, eid, "Изменён забег", f"{name}: {cat or '—'}, {dist or '—'}")
            else:
                self.store.add_wave(eid, name, cat, dist)
                self.store.audit(who, eid, "Добавлен забег", f"{name}: {cat or '—'}, {dist or '—'}")
            return ok(self._event_view(self.store.get_event(eid)))
        if action == "regs":
            if sub_id is None:
                if data.get("approve_all"):
                    n = 0
                    for r in self.store.registrations(eid):
                        if r["status"] == "pending":
                            self.store.update_registration(r["id"], status="approved")
                            n += 1
                    self.store.audit(who, eid, "Заявки подтверждены все", str(n))
                    return ok(self.regs_view(self.store.get_event(eid)))
                if data.get("recategorize"):
                    for r in self.store.registrations(eid):
                        cat = self.category_for(ev.get("reg_rules") or "", r["sex"], int(r["birth_date"][:4]))
                        self.store.update_registration(r["id"], category=cat or None)
                    self.store.audit(who, eid, "Категории пересчитаны по правилам")
                    return ok(self.regs_view(self.store.get_event(eid)))
                # заявка вручную (секретарь), без публичной формы
                code, out = self.submit_registration({**ev, "reg_open": 1, "reg_deadline": None, "status": "planned",
                                                      "archived": 0, "_no_limit": True}, {**data, "consent": True})
                if code == 201:
                    for rid in out["ids"]:
                        self.store.update_registration(rid, status="approved", note="внесена секретарём")
                    self.store.audit(who, eid, "Заявка внесена вручную", out.get("name", ""))
                return code, J, json.dumps(out, ensure_ascii=False), None
            r = self.store.get_registration(sub_id)
            if r is None or r["event_id"] != eid:
                return err("заявка не найдена", 404)
            upd = {}
            if data.get("status") in ("pending", "approved", "rejected"):
                upd["status"] = data["status"]
            for k in ("last_name", "first_name", "middle_name", "team", "coach", "category", "distance", "note",
                      "representative", "contact"):
                if k in data:
                    upd[k] = str(data[k] or "").strip()[:80] or None
            if "rank" in data:
                upd["rank"] = self.norm_rank(data["rank"]) or None
            # карточка участника не сохраняется без разряда (смена одного статуса заявки — не правка карточки)
            if set(data) - {"status", "note"} and not (upd["rank"] if "rank" in upd else r.get("rank")):
                return err("Укажите разряд или звание участника; если разряда нет — «Б/р»")
            if "best" in data:
                b = str(data["best"] or "").strip()[:12]
                if b and self.parse_best(b) is None:
                    return err("результат пишите как 12.5 или 4:05.2")
                upd["best"], upd["best_sec"] = b or None, self.parse_best(b)
            if "birth_date" in data or "sex" in data:
                bd = str(data.get("birth_date") or r["birth_date"])[:10]
                sx = str(data.get("sex") or r["sex"])[:1].upper()
                try:
                    dt.date.fromisoformat(bd)
                except ValueError:
                    return err("дата рождения: ГГГГ-ММ-ДД")
                if sx not in ("М", "Ж"):
                    return err("пол: М или Ж")
                upd["birth_date"], upd["sex"] = bd, sx
                if "category" not in data:
                    upd["category"] = self.category_for(ev.get("reg_rules") or "", sx, int(bd[:4])) or None
            if upd.get("last_name") is None and "last_name" in upd or upd.get("first_name") is None and "first_name" in upd:
                return err("фамилия и имя обязательны")
            self.store.update_registration(sub_id, **upd)
            # участник уже в забеге — обновляем и стартовый список (эстафета — запись команды, её не трогаем)
            if not r.get("relay"):
                e = {"name": " ".join(x for x in (upd.get("last_name", r["last_name"]), upd.get("first_name", r["first_name"])) if x),
                     "team": upd.get("team", r["team"]), "coach": upd.get("coach", r["coach"]),
                     "category": upd.get("category", r["category"]), "seed": upd.get("best", r["best"]),
                     "birth_year": upd.get("birth_date", r["birth_date"])[:4], "rank": upd.get("rank", r.get("rank"))}
                for en in [x for x in self.store.entries_rows(eid) if x.get("reg_id") == sub_id]:
                    self.store.update_entry(eid, en["id"], **e)
                    if upd.get("status") == "rejected":
                        self.store.delete_entry(eid, en["id"])
                if upd.get("status") == "rejected":
                    self.store.update_registration(sub_id, bib=None)
            what = {"approved": "Заявка подтверждена", "rejected": "Заявка отклонена", "pending": "Заявка возвращена"}
            self.store.audit(who, eid, what.get(upd.get("status"), "Заявка изменена"),
                             f"{r['last_name']} {r['first_name']} · {r['distance']}")
            return ok({"reg": self.store.get_registration(sub_id)})
        if action == "clearresults":
            # «Очистить протокол»: результаты, отметки, секундомеры, попытки и ручные разряды выбранных участников
            bibs = {str(b) for b in (data.get("bibs") or []) if str(b).strip()}
            if not bibs:
                return err("не указано, чьи результаты очистить")
            dist = str(data.get("distance") or "").strip()
            rows_ = self.store.entries_rows(eid)
            ed_ = self.entry_dists(eid, rows_)
            n = 0
            for e_ in rows_:                    # номер многоборца стоит в нескольких дисциплинах — чистим только указанную
                if e_["bib"] not in bibs or (dist and self._dkey(ed_.get(e_["id"]) or "") != self._dkey(dist)):
                    continue
                self.store.set_entry_result(eid, e_["id"], None, None, None, True)
                self.store.update_entry(eid, e_["id"], done_rank=None)
                n += 1
            self.store.audit(who, eid, "Очищены результаты", f"{data.get('label') or ''} участников: {n}".strip())
            return ok({"cleared": n})
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
                       "registered_url": f"{self.public_base()}/r/{slug}#registered",
                       "start_url": f"{self.public_base()}/r/{slug}/protocol?kind=start",
                       "results_url": f"{self.public_base()}/r/{slug}/protocol?kind=results"})
        if action == "resetheats":
            try:
                out = self.reset_heats(ev, data.get("distance"))
            except ValueError as e:
                return err(str(e))
            self.store.audit(who, eid, "Сброшена сетка забегов", f"забегов удалено: {out['waves']}, участников возвращено в нераспределённые: {out['entries']}"
                             + (f"; сброшено время старта: {', '.join(out['stopped'])}" if out["stopped"] else ""))
            return ok(out)
        if action == "ui":
            code, out = self.ui_write(ev, data, who)
            return code, J, json.dumps(out, ensure_ascii=False), None
        if action == "clear-bibs":
            try:
                return ok(self.clear_bibs(ev, data.get("distance"), who))
            except ValueError as e:
                return err(str(e))
        if action == "bibs":
            code, out = self.save_bibs(ev, data.get("rows") if isinstance(data.get("rows"), list) else [], who)
            return code, J, json.dumps(out, ensure_ascii=False), None
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
        if action == "manual":
            if sub_id is None:
                device = str(data.get("device") or ev.get("finish_device") or "").strip()
                if not device:
                    return err("не выбрана точка (финиш)")
                bib = re.sub(r"[^0-9A-Za-z-]", "", str(data.get("bib") or ""))[:12]
                if data.get("time"):
                    try:
                        ts = self._parse_clock(ev, str(data["time"]))
                    except ValueError as e:
                        return err(str(e))
                elif data.get("epoch_ms"):
                    try:
                        ts = dt.datetime.fromtimestamp(float(data["epoch_ms"]) / 1000.0)
                    except (ValueError, OverflowError, OSError):
                        return err("неверное epoch_ms")
                else:
                    ts = now_local()
                cid = str(data.get("client_id") or "")[:64] or None
                wave = str(data.get("wave") or "").strip()[:40] or None
                if wave and not self.store.get_wave(eid, wave):
                    wave = None
                mid = self.store.add_manual(eid, device, ts, bib, judge, cid, wave)
                self.store.audit(who, eid, "Ручная отметка", f"{bib or 'без номера'} · {device} · {fmt_db(ts)[11:]}")
                return ok({"mark": self.store.get_manual(mid)}, 201)
            mk = self.store.get_manual(sub_id)
            if mk is None or mk["event_id"] != eid:
                return err("отметка не найдена", 404)
            if data.get("delete"):
                self.store.update_manual(sub_id, deleted=1)
                self.store.audit(who, eid, "Удалена ручная отметка", f"{mk['bib'] or 'без номера'} · {mk['ts'][11:]}")
            elif "bib" in data:
                bib = re.sub(r"[^0-9A-Za-z-]", "", str(data.get("bib") or ""))[:12]
                self.store.update_manual(sub_id, bib=bib)
                self.store.audit(who, eid, "Номер в ручной отметке", f"{mk['bib'] or '—'} → {bib or '—'} · {mk['ts'][11:]}")
            return ok({"mark": self.store.get_manual(sub_id)})
        return err("неизвестное действие", 404)

    # ----------------------------------------------------------------------- #
    #  Регистрация: публичная форма, категории, посев по забегам
    # ----------------------------------------------------------------------- #
    AGE_GROUPS = (("Мальчики до 12 лет", "Девочки до 12 лет", None, 11), ("Мальчики до 14 лет", "Девочки до 14 лет", 13, 12),
                  ("Юноши до 16 лет", "Девушки до 16 лет", 15, 14), ("Юноши до 18 лет", "Девушки до 18 лет", 17, 16),
                  ("Юниоры до 20 лет", "Юниорки до 20 лет", 19, 18), ("Мужчины до 23 лет", "Женщины до 23 лет", 22, 20),
                  ("Мужчины", "Женщины", None, 23))

    @classmethod
    def default_rules(cls, ev: Optional[dict] = None) -> str:
        """Возрастные группы по годам рождения относительно года соревнований (как в положениях ВФЛА):
        «до 16 лет» = в год соревнований исполняется 14–15 лет."""
        y = int(str((ev or {}).get("date") or dt.date.today().isoformat())[:4])
        lines = []
        for m, f, older, younger in cls.AGE_GROUPS:
            if m == "Мужчины":                       # взрослые: 23 года и старше
                lo, hi = "", str(y - younger)
            else:
                lo = str(y - older) if older is not None else ""
                hi = str(y - younger)
                if older is None:                    # младшая группа: открыта снизу по возрасту
                    lo, hi = str(y - younger), ""
            lines.append(f"{m};М;{lo};{hi}")
            lines.append(f"{f};Ж;{lo};{hi}")
        return "\n".join(lines)


    @staticmethod
    def parse_rules(text: str) -> list:
        """Строки «Название;пол;год_с;год_по» → правила. Пустой год — без ограничения."""
        out = []
        for ln in (text or "").splitlines():
            parts = [p.strip() for p in re.split(r"[;\t]", ln)]
            if not parts or not parts[0] or parts[0].startswith("#"):
                continue
            parts += [""] * 4
            sex = parts[1][:1].upper().replace("M", "М").replace("F", "Ж").replace("W", "Ж")
            y1 = int(parts[2]) if parts[2].isdigit() else None
            y2 = int(parts[3]) if parts[3].isdigit() else None
            out.append({"name": parts[0][:40], "sex": sex if sex in ("М", "Ж") else "", "from": y1, "to": y2})
        return out

    @classmethod
    def category_for(cls, rules_text: str, sex: str, birth_year: Optional[int]) -> str:
        rules = cls.parse_rules(rules_text)
        if not rules:
            return {"М": "Мужчины", "Ж": "Женщины"}.get(sex, "")
        for r in rules:
            if r["sex"] and r["sex"] != sex:
                continue
            if birth_year is not None:
                if r["from"] is not None and birth_year < r["from"]:
                    continue
                if r["to"] is not None and birth_year > r["to"]:
                    continue
            elif r["from"] is not None or r["to"] is not None:
                continue
            return r["name"]
        return ""

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

    @staticmethod
    def dist_specs(ev: dict) -> list:
        """Строки дистанций «5 км | лимит 300 | номера с 1», «4×100 м | эстафета 4 | лимит 12».
        Числа без слов — по порядку: лимит, первый номер. → [{name, limit, bib_from, legs}]"""
        out = []
        for ln in (ev.get("reg_distances") or "").splitlines():
            parts = [p.strip() for p in ln.split("|")]
            name = parts[0][:20].strip()
            if not name or name in [x["name"] for x in out]:
                continue
            sp = {"name": name, "limit": None, "bib_from": None, "legs": None}
            loose = []
            for part in parts[1:]:
                low = part.lower()
                m = re.search(r"\d+", low)
                if not m:
                    continue
                n = int(m.group())
                if low.startswith(("эстаф", "relay")):
                    sp["legs"] = max(2, min(n, 10))
                elif low.startswith(("лимит", "мест", "limit", "до ")):
                    sp["limit"] = n or None
                elif low.startswith(("номер", "bib", "с ", "№")):
                    sp["bib_from"] = n or None
                else:
                    loose.append(n)
            for key in [k for k in ("limit", "bib_from") if sp[k] is None]:
                if loose:
                    sp[key] = loose.pop(0) or None
            out.append(sp)
        return out

    @classmethod
    def reg_distances(cls, ev: dict) -> list:
        return [d["name"] for d in cls.dist_specs(ev)]

    @classmethod
    def solo_distances(cls, ev: dict) -> list:
        """Дистанции для личной заявки и шаблона Excel — без эстафет."""
        return [d["name"] for d in cls.dist_specs(ev) if not d["legs"]]

    def dist_info(self, ev: dict) -> list:
        """Сколько заявлено и сколько мест осталось на каждой дистанции (эстафета — по командам)."""
        taken: dict = {}
        for r in self.store.registrations(ev["id"]):
            if r["status"] != "rejected":
                taken.setdefault(r["distance"], set()).add(
                    ("relay", (r.get("relay") or "").lower()) if r.get("relay") else r["id"])
        out = []
        for d in self.dist_specs(ev):
            n = len(taken.get(d["name"], ()))
            out.append({**d, "taken": n, "left": max(0, d["limit"] - n) if d["limit"] else None})
        return out

    # ---- нагрудные номера: вписываются вручную (шаг 2 Мастера), один номер на человека на все его дисциплины (7.0)
    BIB_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё\-]{1,10}")

    @staticmethod
    def _norm_name(v) -> str:
        return re.sub(r"\s+", " ", str(v or "").strip().lower().replace("ё", "е"))

    def _people(self, regs: list) -> dict:
        """id заявки → ключ человека. Один человек = фамилия + имя + год рождения: заявленный на несколько дисциплин
        получает один ключ и один номер. Эстафетная команда — по названию. Тёзки одного года рождения в одной и той же
        дисциплине — разные люди."""
        key_of: dict = {}
        seen: dict = {}
        for r in sorted(regs, key=lambda r: r["id"]):
            if r.get("relay"):
                key_of[r["id"]] = "relay:" + self._norm_name(r["relay"])
                continue
            k = "p:" + "|".join(self._norm_name(r.get(x)) for x in ("last_name", "first_name")) + "|" + str(r.get("birth_date") or "")[:4]
            used = seen.setdefault(k, set())
            if r.get("distance") in used:
                k += f"#{r['id']}"
            used.add(r.get("distance"))
            key_of[r["id"]] = k
        return key_of

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

    @staticmethod
    def _own_bib(r: dict, e: Optional[dict]) -> str:
        return str(r.get("bib") or (e or {}).get("bib") or "").strip()

    def _reg_bib(self, r: dict, st: dict) -> str:
        """Номер участника для сетки: свой (вписан в заявку или уже стоит в сетке), иначе — номер того же человека
        из другой его дисциплины (вписывать второй раз не нужно)."""
        return self._own_bib(r, st["ent_by_reg"].get(r["id"])) or st["person_bib"].get(st["key_of"].get(r["id"], ""), "")

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

    def bibs_view(self, ev: dict, scope: dict) -> dict:
        """Шаг 2: подтверждённые участники дисциплины (с фильтром шага 1) и их нагрудные номера.
        also — другие дисциплины этого же человека: номер у него один на все виды."""
        eid, dist = ev["id"], str(scope.get("distance") or "").strip()
        sex = str(scope.get("sex") or "").strip().upper()[:1]
        ages = [a for a in (scope.get("ages") or []) if a in self.age_limits()]
        year = int(ev["date"][:4]) if ev.get("date") else dt.date.today().year
        st = self._bib_state(eid)

        def ok_(r):
            if r["status"] != "approved" or (dist and r["distance"] != dist):
                return False
            if sex in ("М", "Ж") and str(r.get("sex") or "").upper() != sex:
                return False
            return self.age_ok(year, r["birth_date"], ages)
        regs = self.collapse_relays(ev, [r for r in st["regs"].values() if ok_(r)])
        cat_order = {r["name"]: i for i, r in enumerate(self.parse_rules(ev.get("reg_rules") or ""))}
        rows = []
        for r in sorted(regs, key=lambda r: (cat_order.get(r.get("category") or "", 99), r.get("category") or "",
                                             r["last_name"].lower(), r["first_name"].lower())):
            e = st["ent_by_reg"].get(r["id"])
            own = self._own_bib(r, e)
            bib = own or self._reg_bib(r, st)
            also = []
            if not r.get("relay"):
                for i in st["members"].get(st["key_of"].get(r["id"]), []):
                    x = st["regs"][i]
                    if x["id"] != r["id"] and x.get("distance") != r.get("distance"):
                        also.append({"distance": x.get("distance") or "", "bib": self._own_bib(x, st["ent_by_reg"].get(i))})
            rows.append({"ids": r.get("_ids") or [r["id"]], "bib": bib, "also": also,
                         "inherited": bool(bib and not own), "mismatch": any(a["bib"] and bib and a["bib"] != bib for a in also),
                         "name": " ".join(x for x in (r["last_name"], r["first_name"]) if x),
                         "birth_year": str(r["birth_date"])[:4].strip(), "sex": r.get("sex") or "",
                         "category": r.get("category") or "", "team": r.get("team") or "", "rank": r.get("rank") or "",
                         "members": r.get("members") or "", "in_grid": bool(e and e.get("wave")),
                         "has_result": bool(e and (e.get("result") or e.get("detail") or e.get("status")))})
        return {"distance": dist, "rows": rows, "total": len(rows), "with_bib": sum(1 for x in rows if x["bib"])}

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

    def save_bibs(self, ev: dict, items: list, who: str) -> tuple:
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

    def consent_text(self, ev: dict) -> str:
        if ev.get("reg_consent"):
            return ev["reg_consent"]
        op = self.operator_info()
        days = self.retention_days()
        return (f"Я, действуя свободно, своей волей и в своём интересе (а если участнику нет 18 лет — как его родитель "
                f"или иной законный представитель), даю согласие оператору — {op['name']} (ИНН {op['inn']}, "
                f"адрес: {op['address']}) — на обработку персональных данных участника: фамилия, имя, отчество, "
                f"дата рождения, пол, команда (спортивная школа, клуб), тренер, спортивный разряд, дистанции и заявочный "
                f"результат, стартовый номер, результаты соревнований (время, попытки, место, выполненный разряд), "
                f"контактный телефон или e-mail, ФИО законного представителя.\n\n"
                f"Цели: регистрация и участие в соревнованиях «{ev['name']}»; формирование стартовых и итоговых "
                f"протоколов; расчёт выполненных спортивных разрядов по ЕВСК и подготовка документов для их присвоения; "
                f"работа судей, хронометраж; отображение фамилии, имени, стартового номера и результата на табло "
                f"и их объявление диктором на месте соревнований.\n\n"
                f"Действия: сбор, запись, систематизация, накопление, хранение, уточнение, извлечение, использование, "
                f"предоставление доступа судьям, организаторам и тренерам с подтверждённой учётной записью, передача "
                f"в органы, присваивающие спортивные разряды, обезличивание, блокирование, удаление, уничтожение — "
                f"с использованием средств автоматизации и без них.\n\n"
                f"Дата рождения, контакты и ФИО законного представителя обезличиваются через {days} дней после "
                f"окончания соревнований; итоговые протоколы хранятся как документы, подтверждающие спортивные "
                f"результаты. Согласие действует до достижения целей обработки и может быть отозвано письменным "
                f"заявлением оператору (e-mail {op['email']}).")

    def retention_days(self) -> int:
        """Через сколько дней после окончания соревнований обезличивать заявки (config.json → retention)."""
        try:
            return max(1, int((self.cfg.get("retention") or {}).get("applications_days") or 180))
        except (TypeError, ValueError):
            return 180

    def trainer_consent_text(self) -> str:
        op = self.operator_info()
        return (f"Я, действуя свободно, своей волей и в своём интересе, даю согласие оператору — {op['name']} "
                f"(ИНН {op['inn']}, адрес: {op['address']}) — на обработку моих персональных данных: фамилия, имя, "
                f"отчество, спортивная школа или клуб, адрес электронной почты, дата и время входов в личный кабинет.\n\n"
                f"Цели: регистрация и работа личного кабинета тренера, доступ к стартовым и итоговым протоколам "
                f"соревнований, связь по вопросам соревнований.\n\n"
                f"Действия: сбор, запись, хранение, уточнение, использование, блокирование, удаление и уничтожение — "
                f"с использованием средств автоматизации. Учётная запись без входа в течение 3 лет удаляется "
                f"автоматически. Согласие действует до удаления учётной записи и может быть отозвано письменным "
                f"заявлением оператору (e-mail {op['email']}).")

    def reg_state(self, ev: dict) -> tuple:
        """(открыта ли регистрация, причина)"""
        if not ev.get("reg_open"):
            return False, "Регистрация закрыта"
        if ev.get("archived") or ev.get("status") == "finished":
            return False, "Соревнование завершено"
        dl = self.parse_deadline(ev.get("reg_deadline"))
        if dl and now_local() > dl:
            return False, "Приём заявок окончен"
        return True, ""

    @staticmethod
    def parse_deadline(v) -> Optional[dt.datetime]:
        """Срок приёма заявок из формы: 2026-10-08T17:16 · 2026-10-08 17:16:00 · 2026-10-08 (до конца дня)."""
        t = str(v or "").strip().replace("T", " ")
        for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return dt.datetime.strptime(t, f)
            except ValueError:
                pass
        try:
            return dt.datetime.strptime(t, "%Y-%m-%d") + dt.timedelta(days=1)
        except ValueError:
            return None

    def _public_info(self, ev: dict) -> dict:
        open_, why = self.reg_state(ev)
        return {"name": ev["name"], "date": ev.get("date"), "place": ev.get("place"),
                "organizer": ev.get("organizer"), "start_clock": ev.get("start_clock"),
                "deadline": ev.get("reg_deadline"), "open": open_, "reason": why, "regs_public": bool(ev.get("pub_regs")),
                "distances": self.solo_distances(ev), "info": ev.get("reg_info") or "",
                "dist_info": [{k: d[k] for k in ("name", "limit", "left", "legs")} for d in self.dist_info(ev)],
                "consent": self.consent_text(ev)}

    NAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё' .-]{0,49}")

    @staticmethod
    def _clean(v, n=60) -> str:
        return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:n]

    @staticmethod
    def parse_birth(v) -> Optional[dt.date]:
        """Дата рождения из формы/Excel: 2011-05-14 · 14.05.2011 · 14/05/2011 · число-дата Excel."""
        if isinstance(v, (int, float)) and 3000 < v < 80000:
            return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
        t = str(v or "").strip()
        if re.fullmatch(r"\d{4,5}(\.0+)?", t) and 3000 < float(t) < 80000:
            return dt.date(1899, 12, 30) + dt.timedelta(days=int(float(t)))
        t = t.split(" ")[0]
        for f in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"):
            try:
                return dt.datetime.strptime(t, f).date()
            except ValueError:
                pass
        return None

    @staticmethod
    def parse_sex(v) -> str:
        t = str(v or "").strip().lower()[:3]
        if t[:1] in ("м", "m") or t.startswith("муж"):
            return "М"
        if t[:1] in ("ж", "f", "w") or t.startswith("жен"):
            return "Ж"
        return ""

    def _left_map(self, ev: dict) -> dict:
        """{дистанция: осталось мест} — только для дистанций с лимитом. Секретарь вносит заявки сверх лимита."""
        if ev.get("_no_limit"):
            return {}
        if ev.get("_left") is not None:
            return ev["_left"]
        return {d["name"]: d["left"] for d in self.dist_info(ev) if d["left"] is not None}

    def check_person(self, ev: dict, d: dict, team_mode: bool = False, relay: bool = False) -> tuple:
        """Проверка одного участника. → (ошибки {поле: текст}, чистые данные, [(дистанция, результат)])"""
        c = self._clean
        errs = {}
        last, first, middle = c(d.get("last_name")), c(d.get("first_name")), c(d.get("middle_name"))
        for k, v in (("last_name", last), ("first_name", first)):
            if not v:
                errs[k] = "обязательное поле"
            elif not self.NAME_RE.fullmatch(v):
                errs[k] = "только буквы, дефис, пробел"
        if middle and not self.NAME_RE.fullmatch(middle):
            errs["middle_name"] = "только буквы, дефис, пробел"
        bdate = self.parse_birth(d.get("birth_date"))
        if not bdate or not (1920 <= bdate.year <= dt.date.today().year - 3):
            bdate = None
            errs["birth_date"] = "укажите дату рождения (ДД.ММ.ГГГГ)"
        sex = self.parse_sex(d.get("sex"))
        if sex not in ("М", "Ж"):
            errs["sex"] = "пол: М или Ж"
        team, coach, contact = c(d.get("team"), 80), c(d.get("coach"), 80), c(d.get("contact"), 80)
        if not team:
            errs["team"] = "обязательное поле"
        rank = self.norm_rank(d.get("rank"))
        if not rank:
            errs["rank"] = "укажите разряд или звание; если разряда нет — «Б/р»"
        allowed = self.reg_distances(ev) if relay else self.solo_distances(ev)
        relays = [x for x in self.reg_distances(ev) if x not in allowed]
        low = {a.lower().replace(" ", ""): a for a in allowed}
        dists = d.get("distances")
        if not isinstance(dists, list):
            dists = [{"distance": d.get("distance"), "best": d.get("best")}] if d.get("distance") else []
        picks, bad = [], []
        for x in dists[:10]:
            if isinstance(x, dict):
                name, best = c(x.get("distance"), 20), c(x.get("best"), 12)
            else:
                name, best = c(x, 20), ""
            if allowed:
                key = name.lower().replace(" ", "")
                name = low.get(key) or low.get(key + "м") or ""
                if not name:
                    raw = c(x.get("distance") if isinstance(x, dict) else x, 20)
                    if any(raw.lower().replace(" ", "") == r.lower().replace(" ", "") for r in relays):
                        errs["distances"] = f"«{raw}» — эстафета: заявка командой в разделе «Эстафета»"
                        continue
                    bad.append(raw)
                    continue
            if name and name not in [p[0] for p in picks]:
                picks.append((name, best))
        if not relay:
            left = self._left_map(ev)
            full = [n for n, _ in picks if left.get(n) is not None and left[n] <= 0]
            if full:
                errs["distances"] = "мест больше нет: " + ", ".join(full)
        if not picks and "distances" not in errs:
            errs["distances"] = ("нет такой дистанции: " + ", ".join(b for b in bad if b) + ". Есть: " + ", ".join(allowed)) \
                if any(bad) else "выберите дистанцию"
        for name, best in picks:
            if best and self.parse_best(best) is None:
                errs["distances"] = f"результат «{best}»: пишите как 12.5 или 4:05.2"
        rep = c(d.get("representative"), 80)
        minor = False
        if bdate:
            ref = dt.date.fromisoformat(ev["date"]) if ev.get("date") else dt.date.today()
            age = ref.year - bdate.year - ((ref.month, ref.day) < (bdate.month, bdate.day))
            minor = age < 18
            if minor and not rep and not team_mode:
                errs["representative"] = "участнику нет 18 лет — укажите ФИО родителя (законного представителя)"
        clean = {"last_name": last, "first_name": first, "middle_name": middle or None, "rank": rank or None,
                 "birth_date": bdate.isoformat() if bdate else "", "sex": sex, "team": team, "coach": coach or None,
                 "contact": contact or None, "representative": (rep or None) if minor else None,
                 "category": (self.category_for(ev.get("reg_rules") or "", sex, bdate.year) or None) if bdate else None}
        return errs, clean, picks

    def _store_person(self, ev: dict, clean: dict, picks: list, chash: str, status: str = "pending",
                      note: Optional[str] = None) -> tuple:
        """Сохраняет заявки человека на выбранные дистанции, пропуская повторы. → (ids, повторы)"""
        same = [r for r in self.store.registrations(ev["id"])
                if r["last_name"].lower() == clean["last_name"].lower() and r["first_name"].lower() == clean["first_name"].lower()
                and r["birth_date"] == clean["birth_date"] and r["status"] != "rejected"]
        have = {r["distance"] for r in same}
        ids, dup = [], []
        for name, best in picks:
            if name in have:
                dup.append(name)
                continue
            ids.append(self.store.add_registration(ev["id"], {
                **clean, "distance": name, "best": best or None, "best_sec": self.parse_best(best),
                "status": status, "note": note, "consent_at": fmt_db(now_local()), "consent_hash": chash,
                "policy_hash": self.privacy_hash()}))
        return ids, dup

    def _consent_hash(self, ev: dict) -> str:
        """Отпечаток текста согласия; сам текст кладётся в архив редакций (consent_texts) — чтобы при проверке
        показать, с каким именно текстом согласился человек."""
        text = self.consent_text(ev)
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        self.store.save_consent_text(h, f"Участник · {ev['name']}", text)
        return h

    def submit_registration(self, ev: dict, data: dict) -> tuple:
        """Заявка одного участника с публичной формы. → (код, ответ)"""
        open_, why = self.reg_state(ev)
        if not open_:
            return 403, {"error": why}
        if str(data.get("website") or "").strip():          # ловушка для ботов
            return 200, {"ok": True, "ids": []}
        errs, clean, picks = self.check_person(ev, data)
        if not data.get("consent"):
            errs["consent"] = "нужно согласие на обработку персональных данных"
        if not data.get("policy"):
            errs["policy"] = "подтвердите, что ознакомились с Политикой конфиденциальности"
        if errs:
            return 400, {"error": "Проверьте поля формы", "fields": errs}
        ids, dup = self._store_person(ev, clean, picks, self._consent_hash(ev))
        if not ids:
            return 409, {"error": "Вы уже зарегистрированы на " + ", ".join(dup)}
        self.store.audit("форма", ev["id"], "Заявка с сайта",
                         f"{clean['last_name']} {clean['first_name']}, {clean['birth_date'][:4]} · "
                         + ", ".join(n for n, _ in picks if n not in dup))
        return 201, {"ok": True, "ids": ids, "category": clean["category"] or "",
                     "distances": [n for n, _ in picks if n not in dup], "already": dup,
                     "name": f"{clean['last_name']} {clean['first_name']}"}

    # ---- командная заявка: шаблон Excel → файл → проверка → отправка
    TEAM_COLS = (("last_name", "Фамилия*", ("фамил",)), ("first_name", "Имя*", ("имя",)),
                 ("middle_name", "Отчество", ("отчеств",)),
                 ("birth_date", "Дата рождения*", ("дата рожд", "д.р", "др", "рожд")),
                 ("sex", "Пол* (М/Ж)", ("пол",)), ("distance", "Дистанция*", ("дистанц", "вид")),
                 ("best", "Лучший результат", ("лучш", "результ", "заявл")),
                 ("team", "Команда", ("команд", "клуб", "школ", "организ")),
                 ("coach", "Тренер", ("тренер",)),
                 ("representative", "Родитель / представитель (до 18 лет)", ("родит", "представ")),
                 ("rank", "Разряд / звание*", ("разряд", "звани")))

    def team_template(self, ev: dict) -> bytes:
        dists = self.solo_distances(ev) or ["60 м"]
        title = f"Заявка команды — {ev['name']}" + (f", {'.'.join(reversed(ev['date'].split('-')))}" if ev.get("date") else "")
        rows = [[title], ["Одна строка — один участник на одну дистанцию. Несколько дистанций — несколько строк. "
                          "Обязательны поля со звёздочкой, в том числе разряд (если разряда нет — «Б/р»). Команду и тренера можно не заполнять, если они указаны в форме."],
                [h for _, h, _ in self.TEAM_COLS]]
        rows += [[""] * len(self.TEAM_COLS) for _ in range(60)]
        return xlsx_build(
            sheets=[("Заявка", rows), ("Справочник", [["Дистанции"]] + [[d] for d in dists] + [[""], ["Пол"], ["М"], ["Ж"]])],
            widths=[18, 14, 16, 15, 10, 12, 14, 24, 22, 30, 16], header_row=3, title_row=1,
            validations=[("E4:E63", "\"М,Ж\""), ("F4:F63", f"Справочник!$A$2:$A${len(dists) + 1}"),
                         ("K4:K63", "\"" + ",".join(self.RANKS) + "\"")],
            date_cols=[3], hidden_sheets=[1])

    def parse_team_file(self, ev: dict, blob: bytes, name: str = "") -> tuple:
        """Excel/CSV тренера → (строки-участники [{поля..., _row}], общая ошибка)"""
        try:
            if blob[:2] == b"PK":
                table = xlsx_read(blob)
            else:
                text = blob.decode("utf-8-sig", errors="strict") if not blob[:3] == b"\xef\xbb\xbf" else blob[3:].decode("utf-8")
                sep = ";" if text.count(";") >= text.count(",") else ","
                table = list(csv.reader(io.StringIO(text), delimiter=sep))
        except UnicodeDecodeError:
            text = blob.decode("cp1251", errors="replace")
            sep = ";" if text.count(";") >= text.count(",") else ","
            table = list(csv.reader(io.StringIO(text), delimiter=sep))
        except Exception:
            return [], "Не удалось прочитать файл. Сохраните его как Excel (.xlsx) или CSV и попробуйте снова."
        head_i, cols = None, {}
        for i, row in enumerate(table[:15]):
            m = {}
            for j, cell in enumerate(row):
                low = str(cell or "").strip().lower()
                for key, _, words in self.TEAM_COLS:
                    if key not in m and low and any(low.startswith(w) or w in low for w in words):
                        if key == "first_name" and ("фамил" in low or "отчеств" in low):
                            continue
                        if key == "birth_date" and "год" in low and "дата" not in low:
                            pass
                        m[key] = j
                        break
            if "last_name" in m and "first_name" in m:
                head_i, cols = i, m
                break
        if head_i is None:
            return [], "В файле не найдена строка заголовков (Фамилия, Имя, Дата рождения…). Используйте шаблон."
        out = []
        for i, row in enumerate(table[head_i + 1:], start=head_i + 2):
            def g(k):
                j = cols.get(k)
                return row[j] if j is not None and j < len(row) else ""
            if not any(str(g(k) or "").strip() for k, _, _ in self.TEAM_COLS):
                continue
            rec = {k: g(k) for k, _, _ in self.TEAM_COLS}
            rec["_row"] = i
            out.append(rec)
            if len(out) >= 300:
                break
        if not out:
            return [], "В файле нет участников — заполните строки под заголовком."
        return out, ""

    def check_team(self, ev: dict, data: dict, rows: list) -> dict:
        """Проверяет список участников команды. Ничего не сохраняет."""
        team = self._clean(data.get("team"), 80)
        coach = self._clean(data.get("coach"), 80)
        res = []
        ev = {**ev, "_left": dict(self._left_map(ev))}     # места убывают по ходу списка
        for r in rows:
            d = {**r, "team": self._clean(r.get("team"), 80) or team, "coach": self._clean(r.get("coach"), 80) or coach,
                 "contact": data.get("contact"), "distances": [{"distance": r.get("distance"), "best": r.get("best")}]}
            errs, clean, picks = self.check_person(ev, d, team_mode=True)
            if not errs and picks and picks[0][0] in ev["_left"]:
                ev["_left"][picks[0][0]] -= 1
            res.append({"row": r.get("_row"), "name": f"{clean['last_name']} {clean['first_name']}".strip(),
                        "birth_date": clean["birth_date"], "sex": clean["sex"], "category": clean["category"] or "",
                        "rank": clean.get("rank") or "",
                        "distance": picks[0][0] if picks else self._clean(r.get("distance"), 20),
                        "best": picks[0][1] if picks else self._clean(r.get("best"), 12),
                        "team": clean["team"], "coach": clean["coach"] or "", "minor": bool(clean.get("representative")) or (
                            bool(clean["birth_date"]) and self._age(ev, clean["birth_date"]) < 18),
                        "errors": errs, "_clean": clean, "_picks": picks})
        return {"rows": res, "ok": sum(1 for x in res if not x["errors"]), "bad": sum(1 for x in res if x["errors"])}

    @staticmethod
    def _age(ev: dict, bd: str) -> int:
        b = dt.date.fromisoformat(bd)
        ref = dt.date.fromisoformat(ev["date"]) if ev.get("date") else dt.date.today()
        return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))

    def submit_team(self, ev: dict, data: dict, rows: list, status: str = "pending", actor: str = "форма") -> tuple:
        if not self._clean(data.get("team"), 80) and any(not self._clean(r.get("team")) for r in rows):
            return 400, {"error": "Укажите команду", "fields": {"team": "обязательное поле"}}
        if actor == "форма":
            fe = {}
            if not self._clean(data.get("coach")):
                fe["coach"] = "укажите ФИО тренера / представителя команды"
            if not self._clean(data.get("contact")):
                fe["contact"] = "укажите телефон или e-mail для связи"
            if not data.get("consent"):
                fe["consent"] = "нужно подтвердить наличие согласий"
            if not data.get("policy"):
                fe["policy"] = "подтвердите, что ознакомились с Политикой конфиденциальности"
            if fe:
                return 400, {"error": "Проверьте поля формы", "fields": fe}
        chk = self.check_team(ev, data, rows)
        if chk["bad"]:
            return 400, {"error": f"Исправьте строки с ошибками: {chk['bad']}", "check": self._strip_check(chk)}
        chash = self._consent_hash(ev)
        note = (f"командная заявка: {self._clean(data.get('coach'), 80)}" if actor == "форма"
                else "импорт секретарём")
        added, dups = 0, []
        for x in chk["rows"]:
            ids, dup = self._store_person(ev, x["_clean"], x["_picks"], chash, status, note)
            added += len(ids)
            if dup:
                dups.append(f"{x['name']} ({', '.join(dup)})")
        self.store.audit(actor, ev["id"], "Командная заявка" if actor == "форма" else "Импорт заявок",
                         f"{self._clean(data.get('team'), 80) or '—'}: {added} заявок" + (f", повторов {len(dups)}" if dups else ""))
        return 201, {"ok": True, "added": added, "duplicates": dups, "team": self._clean(data.get("team"), 80)}

    def submit_relay(self, ev: dict, data: dict, status: str = "pending", actor: str = "форма") -> tuple:
        """Заявка эстафетной команды: название, дистанция-эстафета и участники по этапам. → (код, ответ)"""
        c = self._clean
        spec = next((d for d in self.dist_info(ev) if d["legs"] and d["name"] == c(data.get("distance"), 20)), None)
        if not spec:
            return 400, {"error": "Выберите эстафету", "fields": {"distance": "выберите эстафету"}}
        team, coach, contact = c(data.get("team"), 80), c(data.get("coach"), 80), c(data.get("contact"), 80)
        relay = c(data.get("relay"), 60) or team
        fe = {}
        if not team:
            fe["team"] = "обязательное поле"
        if actor == "форма":
            if not coach:
                fe["coach"] = "укажите ФИО тренера / представителя команды"
            if not contact:
                fe["contact"] = "укажите телефон или e-mail для связи"
            if not data.get("consent"):
                fe["consent"] = "нужно подтвердить наличие согласий"
            if not data.get("policy"):
                fe["policy"] = "подтвердите, что ознакомились с Политикой конфиденциальности"
        regs = [r for r in self.store.registrations(ev["id"]) if r["status"] != "rejected" and r["distance"] == spec["name"]]
        if relay and any((r.get("relay") or "").lower() == relay.lower() for r in regs):
            fe["relay"] = f"команда «{relay}» уже заявлена — добавьте номер, например «{relay}-2»"
        if spec["left"] is not None and spec["left"] <= 0 and not ev.get("_no_limit"):
            return 409, {"error": f"На «{spec['name']}» мест больше нет"}
        members = [m for m in (data.get("members") or [])[:10] if isinstance(m, dict)]
        merrs, clean = {}, []
        for i in range(spec["legs"]):
            m = members[i] if i < len(members) else {}
            errs, cl, _ = self.check_person(ev, {**m, "team": team or "—", "coach": coach, "contact": contact,
                                                 "distances": [spec["name"]]}, team_mode=True, relay=True)
            errs.pop("team", None)
            if any((r["last_name"].lower(), r["first_name"].lower(), r["birth_date"]) ==
                   (cl["last_name"].lower(), cl["first_name"].lower(), cl["birth_date"]) for r in regs):
                errs["last_name"] = "уже заявлен(а) в другой команде на эту эстафету"
            if errs:
                merrs[str(i + 1)] = errs
            clean.append(cl)
        if len({(x["last_name"].lower(), x["first_name"].lower(), x["birth_date"]) for x in clean}) < len(clean):
            fe["members"] = "один и тот же участник указан на двух этапах"
        if fe or merrs:
            return 400, {"error": "Проверьте поля формы", "fields": fe, "members": merrs}
        chash = self._consent_hash(ev)
        ids = []
        for i, cl in enumerate(clean, 1):
            ids.append(self.store.add_registration(ev["id"], {
                **cl, "team": team, "distance": spec["name"], "relay": relay, "leg": i, "status": status,
                "note": f"эстафета «{relay}», этап {i}" + (f" · {coach}" if coach and actor == "форма" else ""),
                "consent_at": fmt_db(now_local()), "consent_hash": chash, "policy_hash": self.privacy_hash()}))
        self.store.audit(actor, ev["id"], "Заявка эстафеты", f"{relay} · {spec['name']}: "
                         + ", ".join(f"{x['last_name']} {x['first_name']}" for x in clean))
        return 201, {"ok": True, "ids": ids, "relay": relay, "distance": spec["name"],
                     "members": [f"{x['last_name']} {x['first_name']}" for x in clean]}

    @staticmethod
    def relay_members(members: list) -> str:
        """Состав эстафеты для протокола: «1. Иванов Иван (2010); 2. …»"""
        return "; ".join(f"{m.get('leg') or i}. {m['last_name']} {m['first_name']} ({m['birth_date'][:4]})"
                         for i, m in enumerate(members, 1))

    def relay_entry(self, members: list) -> dict:
        """Заявки участников одной эстафетной команды → одна «заявка-команда» для забега."""
        members = sorted(members, key=lambda r: (r.get("leg") or 0, r["id"]))
        r0 = members[0]
        cats = {m.get("category") or "" for m in members}
        return {**r0, "last_name": r0["relay"], "first_name": "", "birth_date": "    ", "best_sec": None, "best": None,
                "category": cats.pop() if len(cats) == 1 else (r0.get("category") or None),
                "members": self.relay_members(members), "_ids": [m["id"] for m in members]}

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

    @staticmethod
    def _strip_check(chk: dict) -> dict:
        return {**chk, "rows": [{k: v for k, v in x.items() if not k.startswith("_")} for x in chk["rows"]]}

    def regs_view(self, ev: dict) -> dict:
        regs = self.store.registrations(ev["id"])
        erows = self.store.entries_rows(ev["id"])
        bibs = {r["reg_id"]: r for r in erows if r.get("reg_id")}
        by_bib = {r["bib"]: r for r in erows}
        seen: dict = {}
        for r in regs:
            key = (r["last_name"].lower(), r["first_name"].lower(), r["birth_date"], r["distance"])
            r["dup_of"] = seen.get(key) if r["status"] != "rejected" else None
            if r["status"] != "rejected":
                seen.setdefault(key, r["id"])
            e = bibs.get(r["id"]) or (by_bib.get(r["bib"]) if r.get("relay") and r.get("bib") else None)
            r["entry_bib"], r["entry_wave"], r["entry_lane"] = (e["bib"], e["wave"], e["lane"]) if e else ("", "", None)
            r["birth_year"] = r["birth_date"][:4]
        counts = {k: sum(1 for r in regs if r["status"] == k) for k in ("pending", "approved", "rejected")}
        no_cat = sum(1 for r in regs if r["status"] != "rejected" and not r.get("category"))
        return {"regs": regs, "counts": counts, "no_category": no_cat,
                "unassigned": sum(1 for r in regs if r["status"] == "approved" and not r["entry_bib"])}

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

    # возрастные группы мастера: допустимый возраст на год соревнований (возраст = год старта − год рождения)
    @classmethod
    def age_limits(cls) -> dict:
        """Возрастные группы шага 1 Мастера: границы берутся ТОЛЬКО из seed/disciplines.json (ages[].min/max)."""
        return {a["id"]: (int(a.get("min", 0)), int(a.get("max", 200)))
                for a in (cls.disciplines()["data"].get("ages") or []) if a.get("id")}

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

    # ---- стадионное табло: режимы и активные группы (вид программы × категория)
    SB_MODES = {"auto": "авто-трансляция", "fixed": "фиксация дисциплины", "rotate": "ротация"}

    def scoreboard_groups(self, ev: dict, res: Optional[dict] = None) -> list:
        """Группы стартового протокола (дисциплина × категория): сколько участников, сколько результатов, когда последний."""
        sl = self.startlist(ev)
        res = res or self.compute(ev)
        groups: dict = {}
        for h in sl["heats"] + [{"distance": "", "category": "", "entries": sl["no_heat"]}]:
            for e in h["entries"]:
                d = e.get("distance") or h.get("distance") or ""
                c = h.get("category") or e.get("category") or ""
                if not d:
                    continue
                g = groups.setdefault(d + "|" + c, {"key": d + "|" + c, "distance": d, "category": c, "total": 0, "results": 0,
                                                    "last_ms": None, "tech": self.discipline_kind(d) == "tech"})
                g["total"] += 1
        for x in res["finished"]:
            g = groups.get((x.get("distance") or "") + "|" + (x.get("category") or ""))
            if g:
                g["results"] += 1
                t = x.get("finish_epoch_ms") or x.get("entered_epoch_ms")
                if t and (g["last_ms"] is None or t > g["last_ms"]):
                    g["last_ms"] = t
        return sorted(groups.values(), key=lambda g: (not g["tech"], g["distance"], g["category"]))

    def scoreboard_view(self, ev: dict) -> dict:
        res = self.compute(ev)
        groups = self.scoreboard_groups(ev, res)
        st = self.store.get_scoreboard(ev["id"]) or {"mode": "auto", "group": "", "rotate": {"interval": 15, "groups": []}}
        keys = [g["key"] for g in groups]
        rot = [k for k in (st.get("rotate") or {}).get("groups") or [] if k in keys] or \
              [g["key"] for g in groups if g["tech"] and g["results"]] or [g["key"] for g in groups if g["results"]]
        return {"event_id": ev["id"], "mode": st.get("mode", "auto"), "group": st.get("group", ""),
                "rotate": {"interval": (st.get("rotate") or {}).get("interval", 15), "groups": rot,
                           "chosen": (st.get("rotate") or {}).get("groups") or []},
                "updated_at": st.get("updated_at"), "by": st.get("by", ""), "groups": groups, "server_ms": self._epoch_ms(now_local())}

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

    # ---- «Оборудование»: сервер, службы, VPN, кто подключён
    PAGES = {"/": "Админка", "/judge": "Судья", "/sector": "Судья на секторе", "/scoreboard": "Пульт табло", "/announcer": "Диктор", "/board": "Табло", "/protocol": "Протокол"}

    def _note_client(self, writer, headers: dict, path: str) -> None:
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "?"
        c = self._clients.setdefault(ip, {"ip": ip, "first": time.time(), "page": ""})
        c["last"] = time.time()
        c["ua"] = headers.get("user-agent", "")[:200]
        c["user"] = self._auth_user(headers)
        if path in self.PAGES:
            c["page"] = self.PAGES[path]
        elif path.startswith("/api/events/") and "/manual" in path and not c["page"]:
            c["page"] = "Судья"
        if len(self._clients) > 300:
            for k in sorted(self._clients, key=lambda k: self._clients[k]["last"])[:100]:
                self._clients.pop(k, None)

    @staticmethod
    def _ua_short(ua: str) -> str:
        os_ = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
                                    ("Mac OS", "Mac"), ("Linux", "Linux")) if k in ua), "")
        br = next((n for k, n in (("YaBrowser", "Яндекс Браузер"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox", "Firefox"),
                                   ("Chrome", "Chrome"), ("Safari", "Safari"), ("curl", "curl"), ("python", "скрипт")) if k in ua), "")
        return " · ".join(x for x in (os_, br) if x) or (ua[:40] or "—")

    def _sys_file(self, name: str) -> str:
        p = os.path.join(os.path.dirname(os.path.abspath(self.cfg["db_path"])), "system", name)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    @staticmethod
    def _dir_size(path: str) -> int:
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    def system_view(self) -> dict:
        import shutil
        data_dir = os.path.dirname(os.path.abspath(self.cfg["db_path"]))
        out: dict = {"server": {}, "services": [], "vpn": [], "wireguard": [], "clients": [], "certs": []}
        sv = out["server"]
        sv["hostname"] = socket.gethostname()
        sv["version"] = VERSION
        sv["build_date"] = BUILD_DATE
        sv["python"] = sys.version.split()[0]
        sv["time"] = fmt_db(now_local())[:19]
        off = -time.altzone if time.localtime().tm_isdst > 0 else -time.timezone
        sv["timezone"] = f"UTC{'+' if off >= 0 else '-'}{abs(off) // 3600:02d}:{abs(off) % 3600 // 60:02d}" + \
            (f" · {os.path.realpath('/etc/localtime').split('zoneinfo/')[-1]}" if os.path.exists("/etc/localtime") else "")
        sv["hub_started"] = fmt_db(self.started_at)[:19] if self.started_at else None
        try:
            with open("/proc/uptime") as fh:
                sv["uptime_sec"] = int(float(fh.read().split()[0]))
        except OSError:
            pass
        try:
            sv["load"] = [round(x, 2) for x in os.getloadavg()]
            sv["cpus"] = os.cpu_count()
        except OSError:
            pass
        try:
            mem = {}
            with open("/proc/meminfo") as fh:
                for ln in fh:
                    k, v = ln.split(":", 1)
                    mem[k] = int(v.split()[0]) * 1024
            sv["mem_total"], sv["mem_avail"] = mem.get("MemTotal"), mem.get("MemAvailable")
        except (OSError, ValueError):
            pass
        du = shutil.disk_usage(data_dir)
        sv["disk_total"], sv["disk_free"] = du.total, du.free
        db = self.cfg["db_path"]
        sv["db_size"] = sum(os.path.getsize(db + x) for x in ("", "-wal", "-shm") if os.path.exists(db + x))
        sv["files_size"] = self._dir_size(self.files_dir)
        bdir = os.path.join(data_dir, "backups")
        bk = sorted((f for f in os.listdir(bdir) if f.endswith(".db")), reverse=True) if os.path.isdir(bdir) else []
        sv["backups"] = len(bk)
        if bk:
            fp = os.path.join(bdir, bk[0])
            sv["backup_last"] = {"name": bk[0], "size": os.path.getsize(fp),
                                 "at": dt.datetime.fromtimestamp(os.path.getmtime(fp)).strftime("%Y-%m-%d %H:%M")}
        sv["public_url"] = (self.cfg.get("public", {}).get("url") or "")
        ntp = self._sys_file("ntp.txt").strip()
        sv["ntp_synced"] = {"yes": True, "no": False}.get(ntp)
        upd = self._sys_file("updated.txt").strip()
        sv["collector_age_sec"] = int(time.time() - int(upd)) if upd.isdigit() else None
        sv["firewall"] = self._sys_file("ufw.txt").strip() or None
        names = {"timing-hub": "Сервер хронометража", "openvpn-server@timing": "OpenVPN (TCP 443)", "nginx": "Форма регистрации (nginx)",
                 "cron": "Расписание (резервные копии)", "chrony": "Синхронизация времени"}
        for ln in self._sys_file("services.txt").splitlines():
            parts = ln.split()
            if len(parts) != 2:
                continue
            optional = parts[0] in ("chrony",) or (parts[0] == "nginx" and not sv["public_url"])
            if not (optional and parts[1] != "active"):
                nm = names.get(parts[0]) or ("WireGuard (UDP)" if parts[0].startswith("wg-quick") else parts[0])
                out["services"].append({"id": parts[0], "name": nm, "state": parts[1]})
        for ln in self._sys_file("cert.txt").splitlines():
            dom, _, end = ln.partition(" ")
            try:
                d = dt.datetime.strptime(end.strip(), "%b %d %H:%M:%S %Y %Z")
                out["certs"].append({"domain": dom, "until": d.strftime("%Y-%m-%d"), "days": (d - dt.datetime.utcnow()).days})
            except ValueError:
                pass
        # OpenVPN: все профили (ccd) + кто сейчас на связи (status v1)
        prof = {}
        for ln in self._sys_file("ovpn-profiles.txt").splitlines():
            n, _, ip = ln.partition(" ")
            if n:
                prof[n] = {"name": n, "vpn_ip": ip.strip(), "online": False}
        sect = ""
        for ln in self._sys_file("ovpn-status.txt").splitlines():
            if ln.startswith(("OpenVPN CLIENT LIST", "ROUTING TABLE", "GLOBAL STATS")):
                sect = ln
                continue
            f = ln.split(",")
            if f[0] == "CLIENT_LIST" and len(f) >= 8:          # status-version 2 (так пишет systemd-юнит Ubuntu)
                p = prof.setdefault(f[1], {"name": f[1], "vpn_ip": ""})
                p.update(online=True, real=f[2].rsplit(":", 1)[0], rx=int(f[5] or 0), tx=int(f[6] or 0), since=f[7])
                p["vpn_ip"] = p.get("vpn_ip") or f[3]
                continue
            if f[0] == "ROUTING_TABLE" and len(f) >= 5:
                p = prof.setdefault(f[2], {"name": f[2]})
                p["vpn_ip"] = p.get("vpn_ip") or f[1]
                p["last_ref"] = f[4]
                continue
            if sect.startswith("OpenVPN CLIENT") and len(f) >= 5 and f[0] not in ("Common Name", "Updated"):
                p = prof.setdefault(f[0], {"name": f[0], "vpn_ip": ""})
                p.update(online=True, real=f[1].rsplit(":", 1)[0], rx=int(f[2] or 0), tx=int(f[3] or 0), since=f[4])
            elif sect.startswith("ROUTING") and len(f) >= 4 and f[0] != "Virtual Address":
                p = prof.setdefault(f[1], {"name": f[1]})
                p["vpn_ip"] = p.get("vpn_ip") or f[0]
                p["last_ref"] = f[3]
        out["vpn"] = sorted(prof.values(), key=lambda p: (not p.get("online"), p["name"]))
        try:
            out["ovpn_revoked"] = int(self._sys_file("ovpn-revoked.txt").strip() or 0)
        except ValueError:
            out["ovpn_revoked"] = 0
        # WireGuard
        wnames = dict(ln.split(" ", 1) for ln in self._sys_file("wg-names.txt").splitlines() if " " in ln)
        dump = self._sys_file("wg-dump.txt").splitlines()
        for ln in dump[1:]:
            f = ln.split("\t")
            if len(f) >= 7:
                hs = int(f[4] or 0)
                out["wireguard"].append({"name": wnames.get(f[0], f[0][:10] + "…"), "endpoint": f[2] if f[2] != "(none)" else "",
                                         "vpn_ip": f[3].split("/")[0], "handshake_ago": int(time.time() - hs) if hs else None,
                                         "rx": int(f[5] or 0), "tx": int(f[6] or 0)})
        # кто открывал страницы сервера за последний час
        by_ip = {p.get("vpn_ip"): p["name"] for p in out["vpn"] if p.get("vpn_ip")}
        by_ip.update({w["vpn_ip"]: w["name"] for w in out["wireguard"]})
        now = time.time()
        for c in sorted(self._clients.values(), key=lambda c: -c["last"]):
            if now - c["last"] > 3600:
                continue
            out["clients"].append({"ip": c["ip"], "profile": by_ip.get(c["ip"], "сервер" if c["ip"] in ("127.0.0.1", "::1") else ""),
                                   "device": self._ua_short(c.get("ua", "")), "page": c.get("page") or "",
                                   "ago": int(now - c["last"]), "user": c.get("user", "")})
        out["offsite"] = self.offsite_state()
        return out

    # ---- 5.1: внешние зашифрованные копии (tools/offsite-backup.sh из cron), проверка восстановления
    @property
    def offsite_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(self.cfg["db_path"])), "offsite")

    def offsite_state(self) -> dict:
        st: dict = {}
        try:
            st = json.load(open(os.path.join(self.offsite_dir, "status.json"), encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            files = sorted(f for f in os.listdir(self.offsite_dir) if f.startswith("sakhstart-") and f.endswith(".db.gz.enc"))
        except OSError:
            files = []
        st["copies"] = len(files)
        st["latest"] = files[-1] if files else ""
        st["installed"] = os.path.isdir(self.offsite_dir)
        return st

    def offsite_latest(self) -> Optional[tuple]:
        st = self.offsite_state()
        if not st["latest"]:
            return None
        p = os.path.join(self.offsite_dir, st["latest"])
        try:
            with open(p, "rb") as fh:
                return st["latest"], fh.read()
        except OSError:
            return None


    @staticmethod
    def split_parcours(name: str, meters: Optional[str]) -> tuple:
        """«4000 м Женщины» → («4000 м», «Женщины»)."""
        m = re.match(r"\s*(\d+(?:[.,]\d+)?\s*(?:м|км|m|km)\b\.?)\s*(.*)", name or "", re.I)
        if m:
            return m.group(1).strip(), m.group(2).strip() or ""
        return (f"{meters} м" if meters and meters != "0" else ""), (name or "").strip()


    def _startlist_csv(self, ev: dict) -> str:
        sl = self.startlist(ev)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["Забег", "Дистанция", "Категория", "Дорожка", "Номер", "Участник", "Год", "Команда", "Тренер", "Заявл. результат"])
        for h in sl["heats"]:
            for e in h["entries"]:
                w.writerow([h["name"], h["distance"], h["category"], e["lane"] or "", e["bib"], e["name"] or "",
                            e["birth_year"] or "", e["team"] or "", e["coach"] or "", e["seed"] or ""])
        return "\ufeff" + buf.getvalue()


    # ---- обновление сервера из браузера (ставит root-служба timing-update, с автооткатом)
    @property
    def update_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(self.cfg["db_path"])), "update")

    def update_state(self) -> dict:
        d = self.update_dir
        st, log_tail = {}, ""
        try:
            st = json.load(open(os.path.join(d, "status.json"), encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:
            log_tail = open(os.path.join(d, "last.log"), encoding="utf-8", errors="replace").read()[-4000:]
        except OSError:
            pass

        # Проверяем наличие готового обновления (не pending, а ready для установки)
        ready_zip = os.path.join(d, "ready.zip")
        ready_info = {}
        if os.path.exists(ready_zip):
            try:
                info_file = os.path.join(d, "ready-info.json")
                if os.path.exists(info_file):
                    ready_info = json.load(open(info_file, encoding="utf-8"))
            except (OSError, ValueError):
                pass
            # 4.5: архив той же или более старой версии — остаток прошлой установки, а не «доступное обновление»
            if self._vtuple(ready_info.get("version", "")) <= self._vtuple(VERSION):
                self._drop_ready()
                ready_info = {}

        return {
            "version": VERSION,
            "build_date": BUILD_DATE,
            "pending": os.path.exists(os.path.join(d, "incoming.zip")),
            "ready": os.path.exists(ready_zip) and bool(ready_info),
            "ready_info": ready_info,
            "helper": os.path.isdir(d),
            "status": st,
            "log": log_tail
        }

    def receive_update(self, body: bytes, actor: str) -> tuple:
        import hashlib
        import zipfile
        if not os.path.isdir(self.update_dir):
            return 400, {"error": "обновление из браузера ещё не включено — один раз поставьте эту версию через WinSCP"}
        if os.path.exists(os.path.join(self.update_dir, "incoming.zip")):
            return 409, {"error": "предыдущее обновление ещё устанавливается — подождите минуту"}
        if not body or len(body) > 20 * 1024 * 1024:
            return 400, {"error": "нужен архив timing-hub.zip (до 20 МБ)"}
        try:
            z = zipfile.ZipFile(io.BytesIO(body))
            names = set(z.namelist())
            bad = z.testzip()
        except zipfile.BadZipFile:
            return 400, {"error": "это не zip-архив"}
        if bad or "timing-hub/install.sh" not in names or "timing-hub/hub/hub.py" not in names:
            return 400, {"error": "это не архив сервера хронометража (нужен timing-hub.zip)"}
        if any(n.startswith("/") or ".." in n.split("/") for n in names):
            return 400, {"error": "в архиве недопустимые пути"}
        src = z.read("timing-hub/hub/hub.py").decode("utf-8", "replace")
        m = re.search(r'VERSION = "([^"]+)"', src)
        newv = m.group(1) if m else "?"

        # Извлекаем BUILD_DATE если есть
        build_date_match = re.search(r'BUILD_DATE = "([^"]+)"', src)
        build_date = build_date_match.group(1) if build_date_match else "unknown"

        sha = hashlib.sha256(body).hexdigest()

        # Сохраняем как ready.zip (НЕ incoming.zip) - установка только по команде пользователя
        ready_path = os.path.join(self.update_dir, "ready.zip")
        part = os.path.join(self.update_dir, "ready.part")
        with open(part, "wb") as fh:
            fh.write(body)
        os.replace(part, ready_path)

        # Сохраняем метаданные обновления
        info = {
            "version": newv,
            "build_date": build_date,
            "uploaded_at": fmt_db(now_local()),
            "sha256": sha,
            "size": len(body)
        }
        with open(os.path.join(self.update_dir, "ready-info.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        self.store.audit(actor, None, "Обновление загружено и готово к установке",
                        f"{VERSION} → {newv} (дата сборки: {build_date}), sha256 {sha[:16]}…")
        return 200, {"ok": True, "from": VERSION, "to": newv, "build_date": build_date, "sha256": sha,
                    "message": "Обновление загружено. Для установки нажмите кнопку в интерфейсе."}

    def _drop_ready(self) -> None:
        for n in ("ready.zip", "ready-info.json"):
            try:
                os.remove(os.path.join(self.update_dir, n))
            except OSError:
                pass

    def confirm_update_install(self, actor: str) -> tuple:
        """Подтверждение установки: переносит ready.zip -> incoming.zip, запуская установку."""
        d = self.update_dir
        ready_zip = os.path.join(d, "ready.zip")
        ready_info_file = os.path.join(d, "ready-info.json")

        if os.path.exists(os.path.join(d, "incoming.zip")):
            return 409, {"error": "Обновление уже устанавливается — подождите минуту"}

        if not os.path.exists(ready_zip):
            return 404, {"error": "Нет загруженного обновления — нажмите «Проверить обновления»"}

        # Читаем информацию об обновлении
        info = {}
        try:
            if os.path.exists(ready_info_file):
                info = json.load(open(ready_info_file, encoding="utf-8"))
        except (OSError, ValueError):
            pass

        # Переносим ready.zip -> incoming.zip (это запускает timing-update.path); после установки в папке
        # не остаётся «готового» архива, и страница не предлагает поставить ту же версию ещё раз
        try:
            os.replace(ready_zip, os.path.join(d, "incoming.zip"))
        except OSError as e:
            return 500, {"error": f"Не удалось запустить установку: {e}"}
        try:
            os.remove(ready_info_file)
        except OSError:
            pass

        new_version = info.get("version", "?")
        self.store.audit(actor, None, "Запущена установка обновления",
                        f"{VERSION} → {new_version} (пользователь подтвердил установку)")

        return 200, {
            "ok": True,
            "message": "Установка запущена. Сервер перезапустится через ~1 минуту.",
            "from": VERSION,
            "to": new_version,
            "info": info
        }

    # ---- обновление с GitHub: сервер сам скачивает официальную версию и отдаёт её
    # в ту же цепочку, что и загрузку архива (receive_update → timing-update с автооткатом).
    GH_DEFAULT = {"repo": "AnVr25/Claude", "branch": "claude/greeting-d2g8ji", "dir": "timing-hub"}

    def _gh_cfg(self) -> dict:
        c = dict(self.GH_DEFAULT)
        c.update({k: v for k, v in (self.cfg.get("update") or {}).items() if k in c and v})
        return c

    @staticmethod
    def _gh_get(url: str, limit: int = 2 * 1024 * 1024, accept: str = "application/vnd.github+json") -> bytes:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "timing-hub-updater", "Accept": accept})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(limit + 1)
        if len(data) > limit:
            raise ValueError("ответ GitHub слишком большой")
        return data

    def _gh_head(self) -> dict:
        from urllib.parse import quote
        c = self._gh_cfg()
        j = json.loads(self._gh_get(f"https://api.github.com/repos/{c['repo']}/commits/{quote(c['branch'], safe='')}"))
        return {"sha": j["sha"], "date": (j.get("commit") or {}).get("committer", {}).get("date", "")}

    def github_check(self) -> tuple:
        """Выполняется в отдельном потоке: только сеть, без базы."""
        from urllib.parse import quote
        c = self._gh_cfg()
        try:
            head = self._gh_head()
            src = self._gh_get(f"https://raw.githubusercontent.com/{c['repo']}/{head['sha']}/{c['dir']}/hub/hub.py",
                               limit=5 * 1024 * 1024, accept="*/*").decode("utf-8", "replace")
            hist = json.loads(self._gh_get(
                f"https://api.github.com/repos/{c['repo']}/commits?sha={quote(c['branch'], safe='')}&path={quote(c['dir'])}&per_page=10"))
        except Exception as e:  # сеть, GitHub, разбор ответа
            return 502, {"error": f"не удалось проверить обновления на GitHub: {e}"}
        m = re.search(r'VERSION = "([^"]+)"', src)
        latest = m.group(1) if m else "?"
        changes = [{"sha": x["sha"][:7], "date": (x.get("commit") or {}).get("committer", {}).get("date", ""),
                    "message": ((x.get("commit") or {}).get("message") or "").split("\n")[0]} for x in hist]
        # новее — только бóльшая версия (откат на старую не предлагаем) или та же версия, но свежий коммит,
        # если известно, какой коммит стоит сейчас (его записывает установка с GitHub)
        mine = self._gh_installed()
        same_newer = latest == VERSION and mine.get("version") == VERSION and mine.get("sha") not in ("", None, head["sha"])
        return 200, {"current": VERSION, "latest": latest, "sha": head["sha"], "date": head["date"],
                     "newer": self._vtuple(latest) > self._vtuple(VERSION) or same_newer, "changes": changes}

    @staticmethod
    def _vtuple(v: str) -> tuple:
        return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)

    def _gh_installed(self) -> dict:
        try:
            return json.load(open(os.path.join(self.update_dir, "github-installed.json"), encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def github_fetch(self, sha: str) -> tuple:
        """Выполняется в отдельном потоке: скачивает вершину ветки и собирает такой же timing-hub.zip,
        какой загружают вручную. Возвращает (код, ответ, zip-байты или None)."""
        import zipfile
        c = self._gh_cfg()
        try:
            head = self._gh_head()
            if not re.fullmatch(r"[0-9a-f]{40}", sha or "") or sha != head["sha"]:
                return 409, {"error": "на GitHub уже другая версия — нажмите «Проверить» ещё раз"}, None
            raw = self._gh_get(f"https://codeload.github.com/{c['repo']}/zip/{sha}", limit=60 * 1024 * 1024, accept="*/*")
            src = zipfile.ZipFile(io.BytesIO(raw))
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
                for info in src.infolist():
                    parts = info.filename.split("/")
                    # Claude-<sha>/timing-hub/... → timing-hub/...
                    if len(parts) < 3 or parts[1] != c["dir"] or info.is_dir():
                        continue
                    zi = zipfile.ZipInfo("timing-hub/" + "/".join(parts[2:]), date_time=info.date_time)
                    zi.external_attr = info.external_attr
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    dst.writestr(zi, src.read(info))
        except Exception as e:
            return 502, {"error": f"не удалось скачать обновление с GitHub: {e}"}, None
        return 200, {"sha": sha}, out.getvalue()




    def startlist_xlsx(self, ev: dict, qs: dict):
        """5.2: стартовый протокол дисциплины в Excel для судей с ручкой. Бег — забег, дорожка и три графы
        секундомеров; техника — порядок выполнения, шесть попыток и «Лучший результат». Фильтр — как на шаге 1."""
        from urllib.parse import quote
        dist = str(qs.get("distance") or qs.get("dist") or "").strip()
        sex = str(qs.get("sex") or "").strip().upper()[:1]
        ages = [a for a in str(qs.get("ages") or "").split(",") if a in self.age_limits()]
        year = int(ev["date"][:4]) if ev.get("date") else dt.date.today().year
        tech = self.discipline_kind(dist) == "tech"

        def keep(e):
            if sex in ("М", "Ж") and str(e.get("sex") or "").upper() != sex:
                return False
            return self.age_ok(year, e.get("birth_year") or "", ages)
        sl = self.startlist(ev)
        groups = []
        for h in sl["heats"]:
            es = [e for e in h["entries"] if (e.get("distance") or h.get("distance") or "") == dist and keep(e)]
            if es:
                groups.append((h, es))
        head = (["№ п/п", "Порядок выполнения", "Нагрудный номер", "Фамилия, Имя", "Год рождения", "Разряд", "Команда / Город"]
                + [f"Попытка {i}" for i in range(1, 7)] + ["Лучший результат"]) if tech else \
               ["№ п/п", "Забег №", "Дорожка", "Нагрудный номер", "Фамилия, Имя", "Год рождения", "Разряд", "Команда / Город",
                "Секундомер 1", "Секундомер 2", "Секундомер 3"]
        when = ".".join(reversed((ev.get("date") or "").split("-")))
        sub = " · ".join(x for x in ("Стартовый протокол", dist, {"М": "мальчики / юноши", "Ж": "девочки / девушки"}.get(sex, ""),
                                       when, ev.get("place") or "") if x)
        rows = [[ev["name"]], [sub], head]
        group_rows = []
        for h, es in groups:
            label = h["name"] if h["name"].startswith("Общий список") else " · ".join(x for x in (h["name"], h.get("category")) if x)
            rows.append([label] + [""] * (len(head) - 1))
            group_rows.append(len(rows))
            heat_no = (re.fullmatch(r"Забег (\d+)", h["name"]) or [None, ""])[1]
            es = sorted(es, key=lambda e: (e.get("lane") is None, e.get("lane") or 0)) if not tech else es
            for i, e in enumerate(es, 1):
                base = [str(e.get("bib") or ""), e.get("name") or "", str(e.get("birth_year") or ""), e.get("rank") or "",
                        e.get("team") or ""]
                if tech:
                    rows.append([i, ""] + base + [""] * 7)
                else:
                    rows.append([i, heat_no or h["name"], e.get("lane") or ""] + base + ["", "", ""])
        if not groups:
            rows.append(["Сетки по этой дисциплине ещё нет — сформируйте её на шаге 3 Мастера"] + [""] * (len(head) - 1))
        widths = ([6, 11, 10, 28, 8, 8, 22] + [10] * 6 + [12]) if tech else [6, 9, 9, 10, 28, 8, 8, 22, 12, 12, 12]
        blob = xlsx_build([("Стартовый протокол", rows)], widths=widths, header_row=3, title_row=1,
                          group_rows=tuple(group_rows), orientation="landscape" if tech else "portrait",
                          data_height=24, repeat_header=True)
        fname = re.sub(r'[\\/:*?"<>|]+', " ", f"Стартовый протокол — {dist or ev['name']}.xlsx")
        return 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", blob, {
            "Content-Disposition": f"attachment; filename=\"startlist.xlsx\"; filename*=UTF-8''{quote(fname)}"}

    def _template_response(self, ev: dict):
        from urllib.parse import quote
        fname = re.sub(r'[\\/:*?"<>|]+', " ", f"Заявка команды — {ev['name']}.xlsx")
        return 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", self.team_template(ev), {
            "Content-Disposition": f"attachment; filename=\"zayavka.xlsx\"; filename*=UTF-8''{quote(fname)}"}

    def _regs_csv(self, ev: dict):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["№ заявки", "Статус", "Фамилия", "Имя", "Отчество", "Дата рождения", "Пол", "Категория",
                    "Дистанция", "Лучший результат", "Разряд", "Команда", "Тренер", "Представитель", "Контакт", "Нагр. №",
                    "Подана"])
        st = {"pending": "на рассмотрении", "approved": "подтверждена", "rejected": "отклонена"}
        for r in self.store.registrations(ev["id"]):
            w.writerow([r["id"], st.get(r["status"], r["status"]), r["last_name"], r["first_name"], r["middle_name"] or "",
                        r["birth_date"], r["sex"], r["category"] or "", r["distance"], r["best"] or "", r.get("rank") or "", r["team"] or "",
                        r["coach"] or "", r["representative"] or "", r["contact"] or "", r["bib"] or "", r["created_at"]])
        from urllib.parse import quote
        return 200, "text/csv; charset=utf-8", "\ufeff" + buf.getvalue(), {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote('Заявки ' + ev['name'] + '.csv')}"}

    def _results_csv(self, ev: dict):
        r = self.compute(ev)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["Дистанция", "Категория", "Место общее", "Забег", "Место в забеге", "Номер", "ФИО", "Год",
                    "Команда", "Результат", "Выполненный разряд"])
        for x in sorted(r["finished"], key=lambda x: (x["distance"], x["category"], x["place_overall"])):
            w.writerow([x["distance"], x["category"], x["place_overall"], x["wave"], x["place"], x["bib"], x["name"],
                        x["birth_year"], x["team"], x["result"], x.get("done_rank") or ""])
        for x in r["not_seen"]:
            w.writerow([x["distance"], x["category"], "", x["wave"], "", x["bib"], x["name"], x["birth_year"], x["team"],
                        x.get("status") or "нет результата", ""])
        fname = f"results-{ev['id']}"
        return (200, "text/csv; charset=utf-8", "\ufeff" + buf.getvalue(),
                {"Content-Disposition": f'attachment; filename="{fname}.csv"'})

    @property
    def files_dir(self) -> str:
        d = os.path.join(os.path.dirname(os.path.abspath(self.cfg["db_path"])), "files")
        os.makedirs(d, exist_ok=True)
        return d

    def save_file(self, eid: int, name: str, data: bytes, kind: str, author: str, folder: Optional[str] = None) -> dict:
        safe = re.sub(r"[^0-9A-Za-zА-Яа-яЁё._ ()«»№,+-]+", "_", os.path.basename(name)).strip(" .")[:120] or "file"
        sub = os.path.join(self.files_dir, str(eid))
        os.makedirs(sub, exist_ok=True)
        stored = f"{eid}/{int(time.time() * 1000)}_{safe}"
        with open(os.path.join(self.files_dir, stored), "wb") as fh:
            fh.write(data)
        fid = self.store.add_file(eid, safe, stored, len(data), kind, author, folder)
        f = {k: v for k, v in self.store.get_file(fid).items() if k != "stored"}
        f["folder"] = self.store.folder_of(f)
        return f

    def snapshot_results(self, ev: dict, author: str) -> Optional[dict]:
        ev = self.store.get_event(ev["id"])
        if not ev.get("start_time") and not any(w.get("start_time") for w in self.store.waves(ev["id"])):
            return None
        _, _, data, _ = self._results_csv(ev)
        name = f"Результаты (снимок) {now_local():%Y-%m-%d %H-%M}.csv"
        return self.save_file(ev["id"], name, data.encode("utf-8"), "snapshot", author)

    ASSET_TYPES = {".woff2": "font/woff2", ".png": "image/png", ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8",
                   ".js": "text/javascript; charset=utf-8"}

    def _asset(self, name: str):
        """Шрифты, логотипы и общий стиль из папки assets рядом с hub.py (только известные типы, без подкаталогов)."""
        ext = os.path.splitext(name)[1].lower()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name) or name.startswith(".") or ext not in self.ASSET_TYPES:
            return None
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)
        try:
            with open(p, "rb") as f:
                return self.ASSET_TYPES[ext], f.read()
        except OSError:
            return None

    def _ui_file(self, name: str) -> Optional[str]:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    # ---- сроки хранения ПДн (раздел 5 Политики конфиденциальности /privacy)
    RETENTION = {"unverified_days": 7, "trainer_idle_days": 3 * 365, "audit_days": 3 * 365}

    def apply_retention(self) -> dict:
        """Неподтверждённые регистрации тренеров — 7 дней; тренер без входа 3 года — удаляется;
        истёкшие сеансы; журнал действий старше 3 лет."""
        now = now_local()
        cut_unv = fmt_db(now - dt.timedelta(days=self.RETENTION["unverified_days"]))
        cut_idle = fmt_db(now - dt.timedelta(days=self.RETENTION["trainer_idle_days"]))
        cut_aud = fmt_db(now - dt.timedelta(days=self.RETENTION["audit_days"]))
        con = self.store.con
        gone = [r[0] for r in con.execute(
            "SELECT id FROM trainers WHERE (is_verified = 0 AND created_at < ?) "
            "OR (is_verified = 1 AND COALESCE(last_login, verified_at, created_at) < ?)", (cut_unv, cut_idle))]
        for tid in gone:
            self.store.delete_trainer(tid)
        ses = con.execute("DELETE FROM sessions WHERE expires_at < ?", (fmt_db(now),)).rowcount
        aud = con.execute("DELETE FROM audit WHERE ts < ?", (cut_aud,)).rowcount
        # заявки: через N дней после окончания соревнований — без контактов, представителя и полной даты рождения
        # (год остаётся: он нужен протоколам и разрядам)
        cut_ev = (now - dt.timedelta(days=self.retention_days())).strftime("%Y-%m-%d")
        anon = 0
        for e in self.store.list_events():
            end = e.get("date_end") or e.get("date")
            if not end or str(end)[:10] >= cut_ev:
                continue
            anon += con.execute(
                "UPDATE registrations SET contact = NULL, representative = NULL, "
                "birth_date = CASE WHEN birth_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*' "
                "THEN substr(birth_date, 1, 4) || '-01-01' ELSE birth_date END, anonymized_at = ? "
                "WHERE event_id = ? AND anonymized_at IS NULL", (fmt_db(now), e["id"])).rowcount
        if gone:
            self.store.audit("система", None, "Сроки хранения ПДн", f"удалено учётных записей тренеров: {len(gone)}")
        if anon:
            self.store.audit("система", None, "Сроки хранения ПДн",
                             f"обезличено заявок: {anon} (контакты, представитель, дата рождения → год)")
        return {"trainers": len(gone), "sessions": ses, "audit": aud, "applications": anon}

    async def _retention_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                self.apply_retention()
            except Exception:
                log.exception("Сроки хранения ПДн: ошибка очистки")
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=3600)
            except asyncio.TimeoutError:
                pass

    # ---- запуск
    async def start(self) -> None:
        self.tasks.append(asyncio.ensure_future(self._retention_loop()))
        web = self.cfg["web"]
        srv = await asyncio.start_server(self._http, web["listen_host"], int(web["listen_port"]))
        self.servers.append(srv)
        log.info("Страница состояния: http://%s:%s/", web["listen_host"], web["listen_port"])
        pub = self.cfg.get("public") or {}
        if pub.get("enabled"):
            try:
                srv = await asyncio.start_server(self._http_public, pub["listen_host"], int(pub["listen_port"]))
                self.servers.append(srv)
                log.info("Форма регистрации: http://%s:%s/r/ (наружу — через nginx)", pub["listen_host"], pub["listen_port"])
            except OSError as e:
                log.warning("Форма регистрации не запущена: %s", e)
        if not web.get("password"):
            log.warning("В настройках web.password пусто — страница состояния без пароля")

    async def stop(self) -> None:
        self.stopping.set()
        for srv in self.servers:
            srv.close()
        for t in self.tasks:
            t.cancel()

    # ----------------------------------------------------------------------- #
    #  HTTP: страница состояния, выгрузка, приём POST
    # ----------------------------------------------------------------------- #
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

    # Две роли: администратор — всё; судья — вся спортивная работа (мастер протоколов, ввод результатов, печать, табло)
    ROLES = {"admin": "Администратор", "judge": "Судья"}
    LEGACY_ROLES = {"secretary": "judge", "sector": "judge"}     # роли до 4.5.0 — сводятся к судье
    SESSION_COOKIE = "ss_session"
    SESSION_DAYS = 30

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

    @staticmethod
    def _cookie(headers: dict, name: str) -> str:
        for part in headers.get("cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def session_user(self, headers: dict) -> Optional[dict]:
        tok = self._cookie(headers, self.SESSION_COOKIE)
        if not tok or len(tok) > 100:
            return None
        sess = self.store.get_session(hashlib.sha256(tok.encode()).hexdigest())
        return self._user_by_login(sess["login"]) if sess else None

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

    # только администратор: сервер и обновления, VPN, учётные записи, сырые отметки
    ADMIN_ONLY = re.compile(r"/api/(system|users|trainers|consents)(/.*)?|/simple")
    JUDGE_OPEN = ("/api/system/scoreboard/control",)                 # пульт табло — судейский, хоть и под /api/system
    JUDGE_DENY_POST = re.compile(r"/api/events/\d+/delete")          # удалить соревнование целиком

    def _role(self, role: str) -> str:
        role = self.LEGACY_ROLES.get(role, role)
        return role if role in self.ROLES else "judge"

    # тренер в панели: только кто я / выход и /protocol (его сервер переадресует на закрытый протокол в /r/)
    TRAINER_PANEL = ("/api/me", "/api/logout", "/protocol")

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

    @staticmethod
    def _auth_user(headers: dict) -> str:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                return base64.b64decode(auth[6:].strip()).decode("utf-8").partition(":")[0] or "?"
            except Exception:
                return "?"
        return "-"

    def _trusted_proxies(self) -> set:
        return {"127.0.0.1", "::1", "::ffff:127.0.0.1", str(self.cfg["web"].get("listen_host") or "")}

    @staticmethod
    def _safe_next(nxt: str) -> str:
        nxt = str(nxt or "")
        return nxt if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt and len(nxt) < 300 else "/"

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

    # ---- 5.0: личный кабинет тренера — регистрация, подтверждение почты кодом, вход, закрытые протоколы
    EMAIL_RE = re.compile(r"[^@\s<>\"',;]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")
    CODE_TTL_MIN = 30          # код из письма действует 30 минут
    CODE_TRIES = 5             # после 5 неверных вводов — только новый код

    def mail_mode(self) -> str:
        """smtp — настоящая почта; outbox — письма складываются файлами (проверка, сервер без почты); '' — не настроено."""
        m = self.cfg.get("mail") or {}
        return "smtp" if m.get("host") else "outbox" if m.get("outbox_dir") else ""

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

    @staticmethod
    def _code_hash(email: str, code: str) -> str:
        return hashlib.sha256(f"{email}|{code}".encode()).hexdigest()

    def _issue_code(self, t: dict) -> bool:
        import secrets
        code = f"{secrets.randbelow(10 ** 6):06d}"
        now = now_local()
        self.store.update_trainer(t["id"], verification_token=self._code_hash(t["email"], code), token_attempts=0,
                                  token_expires=fmt_db(now + dt.timedelta(minutes=self.CODE_TTL_MIN)),
                                  token_sent_at=fmt_db(now))
        base = self.public_base()
        return self.send_mail(
            t["email"], f"Код подтверждения: {code} — SakhStart",
            f"Здравствуйте, {t['name']}!\n\n"
            f"Код подтверждения почты для личного кабинета тренера SakhStart:\n\n    {code}\n\n"
            f"Код действует {self.CODE_TTL_MIN} минут. Введите его на странице входа"
            + (f": {base}/r/trainer" if base else "") + ".\n\n"
            "Если вы не регистрировались — просто удалите это письмо, без кода учётная запись не откроется.\n\n"
            "Федерация лёгкой атлетики Сахалинской области · SakhStart")

    # Реквизиты оператора ПДн — из карточки организации РСОО «ФЛАСО»; любое поле можно заменить в config.json → "operator"
    OPERATOR_DEFAULT = {
        "name": "Региональная спортивная общественная организация «Федерация легкой атлетики Сахалинской области»",
        "short": "РСОО «ФЛАСО»",
        "inn": "6501159635",
        "ogrn": "1056500009521",
        "address": "Сахалинская область, г. Южно-Сахалинск, ул. М. Горького, д. 7а",
        "responsible": "Шаронов Виталий Александрович",
        "email": "sakhathletics@bk.ru",
        "phone": "+7 (4242) 55-95-55",
    }

    def operator_info(self) -> dict:
        op = self.cfg.get("operator") or {}
        return {k: str(op.get(k) or v) for k, v in self.OPERATOR_DEFAULT.items()}

    def privacy_page(self) -> str:
        """Политика обработки ПДн: hub/privacy.html + реквизиты оператора (OPERATOR_DEFAULT / config.json → "operator")."""
        tpl = self._ui_file("privacy.html") or "нет privacy.html"
        op, e = self.operator_info(), html.escape
        rows = [("Полное наименование", op["name"]), ("Краткое наименование", op["short"]), ("ИНН", op["inn"]),
                ("ОГРН", op["ogrn"]), ("Адрес", op["address"]),
                ("Ответственный за организацию обработки персональных данных", op["responsible"]),
                ("Электронная почта", f'<a href="mailto:{e(op["email"])}">{e(op["email"])}</a>' if op["email"] else ""),
                ("Телефон", e(op["phone"]))]
        table = "".join(f"<tr><th scope=\"row\">{k}</th><td>{v if k in ('Электронная почта', 'Телефон') else e(v)}</td></tr>"
                        for k, v in rows if v)
        base = self.public_base() or ""
        mail = f'<a href="mailto:{e(op["email"])}">{e(op["email"])}</a>' if op["email"] else "адрес Оператора"
        return (tpl.replace("{{OP_TABLE}}", table).replace("{{OP_SHORT}}", e(op["short"]))
                .replace("{{OP_FULL}}", e(op["name"])).replace("{{OP_EMAIL}}", mail)
                .replace("{{OP_ADDRESS}}", e(op["address"])).replace("{{OP_RESPONSIBLE}}", e(op["responsible"]))
                .replace("{{APP_DAYS}}", str(self.retention_days()))
                .replace("{{SITE}}", e(base.replace("https://", "").replace("http://", "") or "reg.fla65.ru")))

    def privacy_hash(self) -> str:
        """Отпечаток редакции политики — записывается вместе с согласием, чтобы знать, с какой редакцией согласились."""
        return hashlib.sha256(self.privacy_page().encode("utf-8")).hexdigest()[:16]

    def protocol_viewer(self, headers: dict) -> Optional[dict]:
        """Кто может смотреть протоколы: администратор, судья или тренер с подтверждённой почтой."""
        u = self.session_user(headers)
        if not u:
            return None
        return u if u["role"] == "trainer" or self._role(u["role"]) in ("admin", "judge") else None

    def _trainer_cookie(self, tok: str, headers: dict) -> str:
        sec = headers.get("x-forwarded-proto") == "https"
        return (f"{self.SESSION_COOKIE}={tok}; Path=/; Max-Age={self.SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax"
                + ("; Secure" if sec else ""))

    def _trainer_session(self, t: dict, headers: dict, ip: str) -> dict:
        import secrets
        tok = secrets.token_urlsafe(32)
        self.store.add_session(hashlib.sha256(tok.encode()).hexdigest(), f"trainer:{t['id']}", self.SESSION_DAYS, ip)
        self.store.update_trainer(t["id"], last_login=fmt_db(now_local()))
        return {"Set-Cookie": self._trainer_cookie(tok, headers)}

    def trainer_events(self) -> list:
        """Закрытый список для кабинета: наши соревнования, у которых выложен стартовый или итоговый протокол."""
        out = []
        for e in self.store.list_events():
            v = self._event_view(e)
            if not (e.get("reg_slug") and v["ours"] and (v["pub_start"] or v["pub_results"])):
                continue
            out.append({"name": e["name"], "date": e.get("date"), "date_end": e.get("date_end"),
                        "place": e.get("place") or "", "city": e.get("city") or "", "status": v.get("status") or "planned",
                        "start": bool(v["pub_start"]), "results": bool(v["pub_results"]),
                        "protocol": f"/r/{e['reg_slug']}/protocol"})
        run =[x for x in out if x["status"] == "running"]
        rest = sorted([x for x in out if x["status"] != "running"], key=lambda x: x["date"] or "0000", reverse=True)
        return run + rest

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

    def trainers_admin(self, method: str, path: str, actor: str) -> tuple:
        """Администратор: список тренеров, ручное подтверждение (когда почта сервера не настроена), блокировка, удаление."""
        if path == "/api/trainers" and method == "GET":
            return 200, {"trainers": self.store.trainers(), "mail": self.mail_mode()}
        m = re.fullmatch(r"/api/trainers/(\d+)/(verify|block|unblock|delete)", path)
        if not m or method != "POST":
            return 404, {"error": "нет такого адреса"}
        t = self.store.trainer_by_id(int(m.group(1)))
        if not t:
            return 404, {"error": "тренер не найден"}
        act = m.group(2)
        if act == "verify":
            self.store.update_trainer(t["id"], is_verified=1, verification_token=None, token_expires=None,
                                      verified_at=fmt_db(now_local()), verified_by=actor.split("@")[0])
        elif act in ("block", "unblock"):
            self.store.update_trainer(t["id"], active=0 if act == "block" else 1)
        else:
            self.store.delete_trainer(t["id"])
        names = {"verify": "почта подтверждена вручную", "block": "заблокирован", "unblock": "разблокирован", "delete": "удалён"}
        self.store.audit(actor, None, "Тренер: " + names[act], f"{t['name']} · {t['email']}")
        return 200, {"ok": True}

    LOGIN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{1,31}")

    def users_api(self, method: str, path: str, body: bytes, me: dict, actor: str) -> tuple:
        try:
            data = json.loads(body.decode("utf-8") or "{}") if method == "POST" else {}
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return 400, {"error": "неверные данные"}
        if path == "/api/me":
            return 200, {**me, "role_name": "Тренер" if me["role"] == "trainer" else self.ROLES.get(me["role"], me["role"])}
        if path == "/api/me/password" and method == "POST":
            old, new = str(data.get("old") or ""), str(data.get("new") or "")
            if not self.check_login(me["login"], old):
                return 400, {"error": "текущий пароль неверный"}
            if len(new) < 8:
                return 400, {"error": "новый пароль — не короче 8 символов"}
            self.store.save_user(me["login"], me.get("name") or me["login"], me["role"], self.hash_password(new))
            self.store.audit(actor, None, "Смена пароля")
            return 200, {"ok": True}
        if me["role"] != "admin":
            return 403, {"error": "недостаточно прав"}
        if path == "/api/users" and method == "GET":
            have = {u["login"] for u in self.store.users()}
            cfg_admin = self.cfg["web"].get("user", "admin")
            lst = self.store.users()
            if cfg_admin not in have:
                lst.insert(0, {"login": cfg_admin, "name": "Администратор (из настроек сервера)", "role": "admin",
                               "created_at": None, "last_login": None, "note": "", "active": 1, "builtin": True})
            for u in lst:
                u["role"] = self._role(u["role"])
            return 200, {"users": lst, "roles": self.ROLES, "me": me["login"]}
        m = re.fullmatch(r"/api/users(?:/([a-z0-9._-]{1,32})/(delete|update))?", path)
        if not m or method != "POST":
            return 404, {"error": "нет такого адреса"}
        if m.group(2) == "delete":
            if m.group(1) == me["login"]:
                return 400, {"error": "нельзя удалить самого себя"}
            self.store.delete_user(m.group(1))
            self.store.audit(actor, None, "Удалён пользователь", m.group(1))
            return 200, {"deleted": m.group(1)}
        if m.group(2) == "update":
            target = m.group(1)
            if not self.store.get_user(target):
                return 404, {"error": "пользователь не найден"}
            f, what = {}, []
            if "role" in data:
                data["role"] = self.LEGACY_ROLES.get(str(data["role"]), data["role"])
                if data["role"] not in self.ROLES:
                    return 400, {"error": "неизвестная роль"}
                if target == me["login"] and data["role"] != "admin":
                    return 400, {"error": "нельзя снять права администратора с самого себя"}
                f["role"] = data["role"]; what.append(f"роль: {self.ROLES[data['role']]}")
            if "name" in data:
                f["name"] = re.sub(r"\s+", " ", str(data["name"] or "")).strip()[:80] or target; what.append("имя")
            if "note" in data:
                f["note"] = re.sub(r"\s+", " ", str(data["note"] or "")).strip()[:200]; what.append("примечание")
            if "active" in data:
                if target == me["login"] and not data["active"]:
                    return 400, {"error": "нельзя заблокировать самого себя"}
                f["active"] = 1 if data["active"] else 0; what.append("разблокирован" if data["active"] else "заблокирован")
            if data.get("password"):
                if len(str(data["password"])) < 8:
                    return 400, {"error": "пароль — не короче 8 символов"}
                f["pwd"] = self.hash_password(str(data["password"])); what.append("новый пароль")
            if not f:
                return 400, {"error": "нечего менять"}
            self.store.update_user(target, **f)
            self.store.audit(actor, None, "Пользователь изменён", f"{target} · {', '.join(what)}")
            return 200, {"ok": True}
        login = str(data.get("login") or "").strip().lower()
        role = str(data.get("role") or "")
        role = self.LEGACY_ROLES.get(role, role)
        name = re.sub(r"\s+", " ", str(data.get("name") or "")).strip()[:80]
        pwd = str(data.get("password") or "")
        note = re.sub(r"\s+", " ", str(data["note"] or "")).strip()[:200] if "note" in data else None
        if not self.LOGIN_RE.fullmatch(login):
            return 400, {"error": "логин: латиница, цифры, точка, дефис; 2–32 символа"}
        if role not in self.ROLES:
            return 400, {"error": "неизвестная роль"}
        if login == me["login"] and role != "admin":
            return 400, {"error": "нельзя снять права администратора с самого себя"}
        exists = self.store.get_user(login) is not None
        if exists and data.get("create"):
            return 409, {"error": "такой логин уже есть"}
        if (not exists or pwd) and len(pwd) < 8:
            return 400, {"error": "пароль — не короче 8 символов"}
        if not exists and login == self.cfg["web"].get("user", "admin") and login != me["login"]:
            return 400, {"error": "этот логин занят встроенным администратором"}
        self.store.save_user(login, name or login, role, self.hash_password(pwd) if pwd else None, note)
        self.store.audit(actor, None, "Пользователь сохранён" if exists else "Добавлен пользователь",
                         f"{login} · {self.ROLES[role]}")
        return 200, {"ok": True, "login": login}

    async def _http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = (lines[0].split(" ") + ["", "", ""])[:3]
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            body = b""
            n = int(headers.get("content-length", "0") or 0)
            if n > 30 * 1024 * 1024:
                await self._send(writer, 413, "text/plain", "слишком большой запрос")
                return
            if n:
                body = await asyncio.wait_for(reader.readexactly(n), timeout=30)
            url = urlsplit(target)
            qs = {k: v[-1] for k, v in parse_qs(url.query).items()}
            path = url.path
            peer = writer.get_extra_info("peername")
            peer_ip = peer[0] if peer else "?"
            # через nginx (вход из интернета по https://reg.fla65.ru) — доверяем его заголовкам
            proxied = peer_ip in self._trusted_proxies() and "x-forwarded-proto" in headers
            client_ip = (headers.get("x-real-ip") or peer_ip) if proxied else peer_ip
            secure = proxied and headers.get("x-forwarded-proto") == "https"
            J = "application/json; charset=utf-8"
            # без входа: страница входа, вход/выход, шрифты и логотипы, публичная часть
            if path == "/privacy" and method == "GET":     # политика конфиденциальности — без входа
                await self._send(writer, 200, "text/html; charset=utf-8", self.privacy_page(),
                                 extra={**self.PUBLIC_HEADERS, "Cache-Control": "public, max-age=300"})
                return
            if path == "/login" and method == "GET":
                await self._send(writer, 200, "text/html; charset=utf-8", self._ui_file("login.html") or "нет login.html")
                return
            if path == "/api/login" and method == "POST":
                code, res, extra = self.do_login(body, headers, client_ip, secure)
                await self._send(writer, code, J, json.dumps(res, ensure_ascii=False), extra=extra)
                return
            if path == "/api/logout" and method == "POST":
                tok = self._cookie(headers, self.SESSION_COOKIE)
                if tok:
                    self.store.delete_session(hashlib.sha256(tok.encode()).hexdigest())
                await self._send(writer, 200, J, '{"ok":true}',
                                 extra={"Set-Cookie": f"{self.SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})
                return
            mt = re.fullmatch(r"/api/auth/trainer/(consent|register|verify|resend|login|logout|me)", path)
            if mt:
                code, res, extra = self.trainer_api(method, mt.group(1), headers, body, client_ip)
                await self._send(writer, code, J, json.dumps(res, ensure_ascii=False), extra=extra)
                return
            if path.startswith("/assets/") and method == "GET":
                a = self._asset(path[8:])
                if a is None:
                    await self._send(writer, 404, "text/plain", "нет такого файла")
                else:
                    await self._send(writer, 200, a[0], a[1], extra={"Cache-Control": "public, max-age=86400"})
                return
            if (path == "/r" or path.startswith("/r/")) and method in ("GET", "POST"):
                code, ctype, data, extra = self._public_route(method, path, headers, body, client_ip, qs)
                await self._send(writer, code, ctype, data, extra={**self.PUBLIC_HEADERS, **(extra or {})})
                return
            user = self.request_user(headers, proxied)
            if user is None:
                if path.startswith("/api/") or method != "GET":
                    await self._send(writer, 401, J, json.dumps({"error": "нужно войти", "login": "/login"}, ensure_ascii=False))
                elif path == "/" and proxied:
                    await self._send(writer, 302, "text/plain", "", extra={"Location": "/r/"})
                elif path == "/protocol":
                    # 5.0: гость на протоколе — на вход тренера (там же ссылка «Вход для судей и организаторов»)
                    from urllib.parse import quote
                    await self._send(writer, 302, "text/plain", "", extra={"Location": "/r/trainer?next=" + quote(target, safe="")})
                else:
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
                else:
                    await self._send(writer, 403, J, json.dumps({"error": "недостаточно прав"}, ensure_ascii=False))
                return
            self._note_client(writer, headers, path)
            if path.startswith("/api/") and path not in ("/api/status",):
                if method == "POST" and headers.get("x-requested-with") != "timing-hub":
                    await self._send(writer, 403, "text/plain", "нужен заголовок X-Requested-With")
                    return
                actor = f"{user['login']}@{client_ip}"
                if path == "/api/me" or path.startswith("/api/users") or path == "/api/me/password":
                    code, res = self.users_api(method, path, body, user, actor)
                    await self._send(writer, code, J, json.dumps(res, ensure_ascii=False))
                    return
                if path == "/api/system/backup/latest" and method == "GET":    # только администратор (ADMIN_ONLY)
                    got = self.offsite_latest()
                    if not got:
                        await self._send(writer, 404, J, json.dumps({"error": "внешних копий пока нет"}, ensure_ascii=False))
                    else:
                        self.store.audit(actor, None, "Скачана зашифрованная копия базы", got[0])
                        await self._send(writer, 200, "application/octet-stream", got[1],
                                         extra={"Content-Disposition": f'attachment; filename="{got[0]}"'})
                    return
                if path == "/api/system/retention" and method == "POST":       # применить сроки хранения сейчас
                    res = self.apply_retention()
                    self.store.audit(actor, None, "Сроки хранения ПДн применены вручную", json.dumps(res, ensure_ascii=False))
                    await self._send(writer, 200, J, json.dumps(res, ensure_ascii=False))
                    return
                if path == "/api/consents" and method == "GET":
                    await self._send(writer, 200, J, json.dumps({"consents": self.store.consent_texts(),
                                                                 "policy_hash": self.privacy_hash(),
                                                                 "retention_days": self.retention_days()}, ensure_ascii=False))
                    return
                if path == "/api/trainers" or path.startswith("/api/trainers/"):
                    code, res = self.trainers_admin(method, path, actor)
                    await self._send(writer, code, J, json.dumps(res, ensure_ascii=False))
                    return
                # Обновление с GitHub: сеть — в отдельном потоке, чтобы не задерживать приём отметок
                if path == "/api/system/update/github/check" and method == "GET":
                    code, res = await asyncio.to_thread(self.github_check)
                    await self._send(writer, code, "application/json; charset=utf-8", json.dumps(res, ensure_ascii=False))
                    return
                if path == "/api/system/update/github" and method == "POST":
                    try:
                        gd = json.loads(body.decode("utf-8") or "{}")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        gd = {}
                    sha = str(gd.get("sha") or "") if isinstance(gd, dict) else ""
                    code, res, blob = await asyncio.to_thread(self.github_fetch, sha)
                    if blob is not None:
                        code, res = self.receive_update(blob, actor)
                        if code == 200:
                            # два клика: «Проверить» → «Установить» — скачанная версия сразу уходит в установку
                            self.store.audit(actor, None, "Обновление с GitHub", f"коммит {sha[:7]}")
                            newv = res.get("to", "")
                            code, res = self.confirm_update_install(actor)
                            if code == 200:
                                try:
                                    with open(os.path.join(self.update_dir, "github-installed.json"), "w", encoding="utf-8") as fh:
                                        json.dump({"sha": sha, "version": newv}, fh)
                                except OSError:
                                    pass
                    await self._send(writer, code, "application/json; charset=utf-8", json.dumps(res, ensure_ascii=False))
                    return
                if path == "/api/readers/scan" and method == "POST":
                    try:
                        sd = json.loads(body.decode("utf-8") or "{}")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        sd = {}
                    code, res = await self.scan_readers(sd if isinstance(sd, dict) else {}, actor)
                    await self._send(writer, code, "application/json; charset=utf-8", json.dumps(res, ensure_ascii=False))
                    return
                code, ctype, data, extra = self._api(method, path, qs, body, actor, headers)
                await self._send(writer, code, ctype, data, extra=extra)
                return
            if path == "/r" or path.startswith("/r/"):
                peer = writer.get_extra_info("peername")
                code, ctype, data, extra = self._public_route(method, path, headers, body, peer[0] if peer else "?", qs)
                await self._send(writer, code, ctype, data, extra=extra)
            elif method != "GET":
                await self._send(writer, 405, "text/plain", "метод не поддерживается")
            elif path in ("/", "/board", "/judge", "/announcer", "/protocol", "/sector", "/scoreboard"):
                name = {"/": "ui.html", "/board": "board.html", "/judge": "judge.html", "/sector": "sector.html", "/scoreboard": "scoreboard.html",
                        "/announcer": "announcer.html", "/protocol": "protocol.html"}[path]
                page = self._ui_file(name)
                if page is None:
                    await self._send(writer, 200, "text/html; charset=utf-8", self._page_status())
                else:
                    # протокол показывается во встроенном предпросмотре мастера — только со страниц этого же сервера
                    await self._send(writer, 200, "text/html; charset=utf-8", page,
                                     extra={"X-Frame-Options": "SAMEORIGIN", "X-Content-Type-Options": "nosniff",
                                            "Referrer-Policy": "same-origin"} if path in ("/protocol", "/board") else None)
            elif path.startswith("/assets/"):
                a = self._asset(path[8:])
                if a is None:
                    await self._send(writer, 404, "text/plain", "нет такого файла")
                else:
                    await self._send(writer, 200, a[0], a[1], extra={"Cache-Control": "public, max-age=86400"})
            elif re.fullmatch(r"/files/\d+", path):
                f = self.store.get_file(int(path.rsplit("/", 1)[1]))
                fp = os.path.join(self.files_dir, f["stored"]) if f else None
                if not f or not os.path.isfile(fp):
                    await self._send(writer, 404, "text/plain; charset=utf-8", "файл не найден")
                else:
                    import mimetypes
                    from urllib.parse import quote
                    with open(fp, "rb") as fh:
                        blob = fh.read()
                    ctype = mimetypes.guess_type(f["name"])[0] or "application/octet-stream"
                    disp = "inline" if ctype in ("application/pdf", "text/csv") and qs.get("dl") != "1" else "attachment"
                    await self._send(writer, 200, ctype, blob,
                                     extra={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(f['name'])}"})
            elif path == "/simple":
                await self._send(writer, 200, "text/html; charset=utf-8", self._page_status())
            elif path == "/api/status":
                await self._send(writer, 200, "application/json; charset=utf-8",
                                 json.dumps(self.status(), ensure_ascii=False, indent=1))
            else:
                await self._send(writer, 404, "text/plain", "нет такой страницы")
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ConnectionError, ValueError):
            pass
        except Exception as e:
            log.exception("HTTP: ошибка обработки запроса")
            try:
                if str(locals().get("path", "")).startswith("/api/"):
                    await self._send(writer, 500, "application/json; charset=utf-8", json.dumps(
                        {"error": f"внутренняя ошибка сервера: {type(e).__name__}: {str(e)[:200]}"}, ensure_ascii=False))
                    return
                await self._send(writer, 500, "text/plain", "внутренняя ошибка")
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    # ---- публичная часть: только форма регистрации
    PUBLIC_HEADERS = {
        "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                   "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    }

    def _rate_ok(self, key: str, limit: int, per_sec: int) -> bool:
        now = time.monotonic()
        q = self._rate.setdefault(key, deque())
        while q and now - q[0] > per_sec:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def _public_route(self, method: str, path: str, headers: dict, body: bytes, client: str, qs: Optional[dict] = None):
        J = "application/json; charset=utf-8"

        def js(obj, code=200):
            return code, J, json.dumps(obj, ensure_ascii=False), None

        if method == "GET" and path in ("/r/privacy", "/privacy"):
            return 200, "text/html; charset=utf-8", self.privacy_page(), {"Cache-Control": "public, max-age=300"}
        if method == "GET" and path in ("/r", "/r/", "/r/trainer", "/r/trainer/"):
            page = self._ui_file("reg.html")
            return 200, "text/html; charset=utf-8", page or "нет reg.html", None
        # 5.0: личный кабинет тренера (тот же обработчик доступен в панели как /api/auth/trainer/…)
        mt = re.fullmatch(r"/r/api/(?:auth/trainer/(consent|register|verify|resend|login|logout|me)|trainer/(events))", path)
        if mt:
            code, out, extra = self.trainer_api(method, mt.group(1) or mt.group(2), headers, body, client)
            return code, J, json.dumps(out, ensure_ascii=False), extra
        if method == "GET" and path.startswith("/r/assets/"):
            a = self._asset(path[10:])
            if a is None:
                return 404, "text/plain; charset=utf-8", "нет такого файла", None
            # виджет календаря и шрифты подключаются на fla65.ru — разрешаем чужому сайту их читать
            return 200, a[0], a[1], {"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*",
                                     "Cross-Origin-Resource-Policy": "cross-origin"}
        if method == "GET" and path == "/r/api/calendar":
            y = str((qs or {}).get("year", ""))
            data = self.calendar(int(y) if y.isdigit() else None)
            return 200, J, json.dumps(data, ensure_ascii=False), {"Access-Control-Allow-Origin": "*",
                                                                  "Cache-Control": "public, max-age=60"}
        if method == "GET" and path == "/r/api/series":
            n = str((qs or {}).get("name", "")).strip()
            data = self.series_standings(n) if n else {"series": self.series_names()}
            if n and not data["stages"]:
                return js({"error": "серия не найдена"}, 404)
            return 200, J, json.dumps(data, ensure_ascii=False), {"Access-Control-Allow-Origin": "*",
                                                                  "Cache-Control": "public, max-age=60"}
        if method == "GET" and path in ("/r/series", "/r/series/"):
            page = self._ui_file("series.html")
            return 200, "text/html; charset=utf-8", page or "нет series.html", None
        if method == "GET" and path == "/r/api/open":
            out = []
            for e in self.store.list_events():
                if e.get("reg_slug") and self.reg_state(e)[0]:
                    out.append({"name": e["name"], "date": e.get("date"), "place": e.get("place"),
                                "deadline": e.get("reg_deadline"), "slug": e["reg_slug"]})
            return js({"events": out})
        m = re.fullmatch(r"/r/([A-Za-z0-9]{4,20})(/info|/template\.xlsx|/team-check|/team|/relay|/results\.json|/startlist\.json"
                         r"|/protocol|/registered\.json|/files/\d+)?/?", path)
        if not m:
            return 404, "text/plain; charset=utf-8", "нет такой страницы", None
        ev = self.store.event_by_slug(m.group(1))
        if ev is None:
            return (js({"error": "регистрация не найдена"}, 404) if m.group(2) or method == "POST"
                    else (404, "text/plain; charset=utf-8", "Регистрация не найдена. Проверьте ссылку.", None))
        sub = m.group(2) or ""
        if method == "GET" and sub == "/template.xlsx":
            return self._template_response(ev)
        if method == "GET" and sub == "/info":
            info = self._public_info(ev)
            info["card"] = self.event_card(ev)
            return js(info)
        if method == "GET" and sub == "/registered.json":
            # открыто без входа, но только если секретарь включил публикацию; данные минимальны (см. registered_list)
            if not self._rate_ok("rl:" + client, 120, 600):
                return js({"error": "Слишком много запросов, попробуйте через минуту"}, 429)
            if not self._event_view(ev)["pub_regs"]:
                return js({"error": "Список прошедших регистрацию пока не опубликован"}, 404)
            code, ctype, data_, _ = js(self.registered_list(ev))
            return code, ctype, data_, {"Cache-Control": "public, max-age=30"}
        if method == "GET" and sub in ("/results.json", "/startlist.json", "/protocol"):
            # 5.0: протоколы закрыты — только администратор, судья и тренер с подтверждённой почтой
            if not self.protocol_viewer(headers):
                if sub == "/protocol":
                    from urllib.parse import quote
                    nxt = f"/r/{m.group(1)}/protocol" + (f"?kind={quote(str((qs or {}).get('kind', '')))}" if (qs or {}).get("kind") else "")
                    return 302, "text/plain; charset=utf-8", "", {"Location": "/r/trainer?next=" + quote(nxt, safe="")}
                return js({"error": "Протоколы доступны тренерам, судьям и организаторам — войдите", "login": "/r/trainer"}, 401)
            v = self._event_view(ev)
            if sub == "/protocol":
                page = self._ui_file("protocol.html")
                return 200, "text/html; charset=utf-8", page or "нет protocol.html", None
            if not v["ours"] or not (v["pub_results"] if sub == "/results.json" else v["pub_start"]):
                return js({"error": "протокол ещё не опубликован"}, 404)
            return js(self.public_results(ev) if sub == "/results.json" else self.public_startlist(ev))
        if method == "GET" and sub.startswith("/files/"):
            f = self.store.get_file(int(sub.rsplit("/", 1)[1]))
            fp = os.path.join(self.files_dir, f["stored"]) if f else None
            if not f or f["event_id"] != ev["id"] or not f.get("public") or not os.path.isfile(fp):
                return 404, "text/plain; charset=utf-8", "файл не найден", None
            import mimetypes
            from urllib.parse import quote
            with open(fp, "rb") as fh:
                blob = fh.read()
            ctype = mimetypes.guess_type(f["name"])[0] or "application/octet-stream"
            disp = "inline" if ctype in ("application/pdf",) or ctype.startswith("image/") else "attachment"
            return 200, ctype, blob, {"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(f['name'])}",
                                      "Cache-Control": "public, max-age=300"}
        if method == "POST" and sub == "/relay":
            open_, why = self.reg_state(ev)
            if not open_:
                return js({"error": why}, 403)
            ip_ok = client in ("127.0.0.1", "::1", "?") or self._rate_ok("ip:" + client, 40, 600)
            if not (ip_ok and self._rate_ok("ev:" + m.group(1), 300, 600) and self._rate_ok("all", 600, 600)):
                return js({"error": "Слишком много заявок подряд, попробуйте через несколько минут"}, 429)
            try:
                data = json.loads(body.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return js({"error": "неверные данные"}, 400)
            if str(data.get("website") or "").strip():
                return js({"ok": True, "ids": []}, 201)
            code, out = self.submit_relay(ev, data)
            return js(out, code)
        if method == "POST" and sub in ("/team-check", "/team"):
            open_, why = self.reg_state(ev)
            if not open_:
                return js({"error": why}, 403)
            if not (self._rate_ok("ev:" + m.group(1), 300, 600) and self._rate_ok("all", 600, 600)):
                return js({"error": "Слишком много запросов, попробуйте через несколько минут"}, 429)
            if sub == "/team-check":
                from urllib.parse import unquote
                rows, e = self.parse_team_file(ev, body)
                if e:
                    return js({"error": e}, 400)
                chk = self.check_team(ev, {"team": unquote(headers.get("x-team", "")),
                                           "coach": unquote(headers.get("x-coach", ""))}, rows)
                out = self._strip_check(chk)
                for x, raw in zip(out["rows"], rows):
                    x["raw"] = {k: raw.get(k, "") for k, _, _ in self.TEAM_COLS}
                return js(out)
            try:
                data = json.loads(body.decode("utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return js({"error": "неверные данные"}, 400)
            if str(data.get("website") or "").strip():
                return js({"ok": True, "added": 0}, 201)
            rows = [r for r in data["rows"][:300] if isinstance(r, dict)]
            code, out = self.submit_team(ev, data, rows)
            return js(out, code)
        if method == "GET":
            page = self._ui_file("reg.html")
            return 200, "text/html; charset=utf-8", page or "нет reg.html", None
        if method == "POST" and not sub:
            if "json" not in headers.get("content-type", ""):
                return js({"error": "ожидается JSON"}, 415)
            # за OpenVPN port-share все приходят с 127.0.0.1 — тогда лимит по адресу не работает, только общий
            ip_ok = client in ("127.0.0.1", "::1", "?") or self._rate_ok("ip:" + client, 40, 600)
            if not (ip_ok and self._rate_ok("ev:" + m.group(1), 300, 600) and self._rate_ok("all", 600, 600)):
                return js({"error": "Слишком много заявок подряд, попробуйте через несколько минут"}, 429)
            try:
                data = json.loads(body.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return js({"error": "неверные данные"}, 400)
            code, out = self.submit_registration(ev, data)
            return js(out, code)
        return 405, "text/plain; charset=utf-8", "метод не поддерживается", None

    async def _http_public(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            if len(head) > 8192:
                return
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = (lines[0].split(" ") + ["", "", ""])[:3]
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            n = int(headers.get("content-length", "0") or 0)
            limit = 3 * 1024 * 1024 if target.split("?")[0].endswith(("/team-check", "/team")) else 16384
            if n > limit:
                await self._send(writer, 413, "text/plain", "слишком большой запрос", extra=self.PUBLIC_HEADERS)
                return
            body = await asyncio.wait_for(reader.readexactly(n), timeout=15) if n else b""
            peer = writer.get_extra_info("peername")
            client = headers.get("x-real-ip") or (peer[0] if peer else "?")
            u = urlsplit(target)
            code, ctype, data, extra = self._public_route(method, u.path, headers, body, client,
                                                          {k: v[-1] for k, v in parse_qs(u.query).items()})
            await self._send(writer, code, ctype, data, extra={**self.PUBLIC_HEADERS, **(extra or {})})
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ConnectionError, ValueError):
            pass
        except Exception:
            log.exception("Форма регистрации: ошибка обработки запроса")
            try:
                await self._send(writer, 500, "text/plain", "внутренняя ошибка")
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    @staticmethod
    async def _send(writer, code: int, ctype: str, body, extra: Optional[dict] = None) -> None:
        reasons = {200: "OK", 201: "Created", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                   404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
                   415: "Unsupported Media Type", 429: "Too Many Requests", 500: "Internal Server Error"}
        data = body.encode("utf-8") if isinstance(body, str) else body
        hdr = [f"HTTP/1.1 {code} {reasons.get(code, 'OK')}",
               f"Content-Type: {ctype}",
               f"Content-Length: {len(data)}",
               "Connection: close"]
        if "Cache-Control" not in (extra or {}):
            hdr.append("Cache-Control: no-store")
        if "X-Frame-Options" not in (extra or {}):
            hdr += ["X-Frame-Options: DENY", "X-Content-Type-Options: nosniff", "Referrer-Policy: same-origin"]
        for k, v in (extra or {}).items():
            hdr.append(f"{k}: {v}")
        writer.write(("\r\n".join(hdr) + "\r\n\r\n").encode("utf-8") + data)
        await writer.drain()




    # ---- состояние
    def status(self) -> dict:
        def t(x):
            return fmt_db(x) if x else None
        return {"version": VERSION, "build_date": BUILD_DATE, "server_time": t(now_local()),
                "server_epoch_ms": int(time.time() * 1000), "timezone": time.strftime("%Z %z"),
                "started_at": t(self.started_at)}

    def _page_status(self) -> str:
        st = self.status()
        e = html.escape
        return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="10">
<title>SakhStart — сервер</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:16px;color:#1b1f24;background:#f6f7f9}}
h1{{font-size:20px;margin:0 0 4px}} small{{color:#5b6570}} a{{color:#175cd3}}
</style></head><body>
<h1>SakhStart — судейско-секретарский АРМ</h1>
<small>Время сервера: <b>{e(st['server_time'])}</b> ({e(st['timezone'])}) · версия {VERSION} · сборка {BUILD_DATE}</small>
<p><a href="/">Открыть АРМ секретаря</a> · <a href="/api/status">JSON</a></p>
</body></html>"""


# --------------------------------------------------------------------------- #
#  Запуск
# --------------------------------------------------------------------------- #
async def amain(cfg: dict) -> None:
    hub = Hub(cfg)
    await hub.start()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, hub.stopping.set)
        except NotImplementedError:
            pass
    await hub.stopping.wait()
    log.info("Останавливаюсь…")
    await hub.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description="SakhStart: судейско-секретарский АРМ стадиона и манежа")
    ap.add_argument("--config", default="/etc/timing-hub/config.json")
    ap.add_argument("--check", action="store_true", help="проверить настройки и выйти")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"ОШИБКА НАСТРОЕК: {e}", file=sys.stderr)
        return 2

    logging.basicConfig(level=getattr(logging, str(cfg["log_level"]).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.check:
        print(f"Настройки в порядке: {args.config}")
        print(f"  база: {cfg['db_path']}")
        print(f"  страница: http://{cfg['web']['listen_host']}:{cfg['web']['listen_port']}/")
        return 0

    try:
        asyncio.run(amain(cfg))
    except OSError as e:
        log.error("Не удалось запуститься: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
