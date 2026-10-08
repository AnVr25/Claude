#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
timing-hub — сервер хронометража.

Что делает:
  1. Принимает отметки от ридеров (F800 и любых других) тремя способами:
       listen  — ридер сам подключается к серверу и шлёт строки;
       connect — сервер сам подключается к ридеру (через VPN) и читает строки;
       http    — любая программа присылает отметки POST-запросом.
  2. Складывает ВСЕ сырые строки и распознанные отметки в базу SQLite (архив).
  3. Отдаёт отметки в Wiclax по протоколу «generic acquisition»
     (Wiclax подключается к серверу как к обычному ридеру).
  4. Показывает страницу состояния и выгрузку в CSV.

Только стандартная библиотека Python 3.10+. Внешних зависимостей нет.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
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
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

VERSION = "1.4.0"
log = logging.getLogger("timing-hub")


# --------------------------------------------------------------------------- #
#  Время
# --------------------------------------------------------------------------- #
# Все времена отметок хранятся как «наивное» местное время (время ридера,
# как его показывает ридер). Сервер работает в часовом поясе соревнований
# (install.sh ставит Asia/Sakhalin), поэтому время приёма тоже местное.

def now_local() -> dt.datetime:
    return dt.datetime.now()


def frac_to_us(frac: Optional[str]) -> int:
    """'5' -> 500000, '123' -> 123000, '123456' -> 123456."""
    if not frac:
        return 0
    return int((frac + "000000")[:6])


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
               hidden_sheets=()) -> bytes:
    """sheets = [(имя, [[ячейки]])]. Оформление (ширины, заголовок, проверки) — только у первого листа."""
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
                       '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>')
        out.append("</worksheet>")
        return "".join(out)

    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd.mm.yyyy"/></numFmts>'
              '<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="11"/><name val="Calibri"/></font>'
              '<font><b/><sz val="14"/><name val="Calibri"/></font>'
              '<font><i/><sz val="10"/><color rgb="FF666666"/><name val="Calibri"/></font></fonts>'
              '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FFF4E3DD"/><bgColor indexed="64"/></patternFill></fill></fills>'
              '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
              '<border><left style="thin"><color rgb="FFBBBBBB"/></left><right style="thin"><color rgb="FFBBBBBB"/></right>'
              '<top style="thin"><color rgb="FFBBBBBB"/></top><bottom style="thin"><color rgb="FFBBBBBB"/></bottom><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
              '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
              '<alignment wrapText="1" vertical="center"/></xf>'
              '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
              '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>'
              '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
              '<xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/></cellXfs>'
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
                   + "</sheets></workbook>")
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


def fmt_wiclax(ts: dt.datetime) -> str:
    return ts.strftime("%d-%m-%Y %H:%M:%S.") + f"{ts.microsecond // 1000:03d}"


def from_unix(value: float, tz_offset_hours: Optional[float]) -> dt.datetime:
    if tz_offset_hours is None:
        return dt.datetime.fromtimestamp(value)
    utc = dt.datetime.fromtimestamp(value, dt.timezone.utc)
    return (utc + dt.timedelta(hours=tz_offset_hours)).replace(tzinfo=None)


def fix_midnight(ts: dt.datetime, rx: dt.datetime) -> dt.datetime:
    """Если у строки было только время суток — подставили дату приёма.
    Переход через полночь: отметка 23:59 принята в 00:01 -> вчерашняя дата."""
    if ts - rx > dt.timedelta(hours=12):
        return ts - dt.timedelta(days=1)
    if rx - ts > dt.timedelta(hours=12):
        return ts + dt.timedelta(days=1)
    return ts


# --------------------------------------------------------------------------- #
#  Конфигурация
# --------------------------------------------------------------------------- #
DEFAULTS: dict[str, Any] = {
    "db_path": "/var/lib/timing-hub/reads.db",
    "log_level": "INFO",
    "store_raw": True,
    "raw_memory_lines": 200,
    "clock_warn_sec": 2.0,
    "wiclax": {
        "listen_host": "127.0.0.1",
        "listen_port": 9854,
        "heartbeat_sec": 5,
        "line_end": "\r",
        "forward_filter_sec": 3.0,
        "live_on_connect": True,
        "devices": None,
        "chip_lower": False,
    },
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
    "sources": [],
}

SOURCE_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "name": "",
    "mode": "listen",              # listen | connect | http
    "listen_host": "127.0.0.1",
    "listen_port": None,
    "host": None,
    "port": None,
    "init_commands": [],
    "parser": "auto",              # auto | regex | wiclax | ipico
    "pattern": None,
    "datetime_format": "%Y-%m-%d %H:%M:%S.%f",
    "date_format": "%Y-%m-%d",
    "time_format": "%H:%M:%S.%f",
    "unix_tz_offset_hours": None,
    "device": None,                # код точки для Wiclax; по умолчанию = id
    "device_per_antenna": False,   # True: код точки = device + номер антенны
    "allow_receive_time": False,   # True: если в строке нет времени — брать время приёма
    "chip_upper": True,
    "chip_strip_leading_zeros": False,
    "chip_take_last": 0,
    "min_chip_len": 4,
    "ipico_hundredths_hex": True,  # IPICO: сотые секунды в строке записаны шестнадцатерично
    "chip_lower": None,            # чип в Wiclax строчными (None — как в wiclax.chip_lower)
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
    cfg = _merge(DEFAULTS, raw)
    sources = []
    seen = set()
    for i, s in enumerate(raw.get("sources", [])):
        src = _merge(SOURCE_DEFAULTS, s)
        sid = src.get("id")
        if not sid or not VALID_ID.match(str(sid)):
            raise ConfigError(f"источник №{i + 1}: id обязателен, только латиница/цифры/_/- (до 32 символов)")
        if sid in seen:
            raise ConfigError(f"источник {sid}: id повторяется")
        seen.add(sid)
        if src["mode"] not in ("listen", "connect", "http"):
            raise ConfigError(f"источник {sid}: mode должен быть listen, connect или http")
        if src["mode"] == "listen" and not src["listen_port"]:
            raise ConfigError(f"источник {sid}: для mode=listen нужен listen_port")
        if src["mode"] == "connect" and (not src["host"] or not src["port"]):
            raise ConfigError(f"источник {sid}: для mode=connect нужны host и port")
        if src["parser"] not in ("auto", "regex", "wiclax", "ipico"):
            raise ConfigError(f"источник {sid}: parser должен быть auto, regex, wiclax или ipico")
        if src["parser"] == "regex":
            if not src["pattern"]:
                raise ConfigError(f"источник {sid}: для parser=regex нужен pattern")
            try:
                rx = re.compile(src["pattern"])
            except re.error as e:
                raise ConfigError(f"источник {sid}: ошибка в pattern: {e}")
            if "chip" not in rx.groupindex:
                raise ConfigError(f"источник {sid}: в pattern нужна группа (?P<chip>...)")
            time_groups = {"datetime", "unix", "unix_ms", "time"}
            if not (time_groups & set(rx.groupindex)) and not src["allow_receive_time"]:
                raise ConfigError(
                    f"источник {sid}: в pattern нужна группа времени "
                    "(?P<datetime>...), (?P<time>...), (?P<unix>...) или (?P<unix_ms>...)")
        if not src["device"]:
            src["device"] = sid
        if ";" in str(src["device"]):
            raise ConfigError(f"источник {sid}: в device нельзя использовать ';'")
        sources.append(src)
    cfg["sources"] = sources
    ports = []
    for s in sources:
        if s["enabled"] and s["mode"] == "listen":
            ports.append((s["listen_host"], int(s["listen_port"]), s["id"]))
    ports.append((cfg["wiclax"]["listen_host"], int(cfg["wiclax"]["listen_port"]), "wiclax"))
    ports.append((cfg["web"]["listen_host"], int(cfg["web"]["listen_port"]), "web"))
    used = {}
    for host, port, who in ports:
        if port in used:
            raise ConfigError(f"порт {port} занят дважды: {used[port]} и {who}")
        used[port] = who
    return cfg


# --------------------------------------------------------------------------- #
#  Разбор строк от ридеров
# --------------------------------------------------------------------------- #
@dataclass
class ParsedRead:
    chip: str
    ts: dt.datetime
    antenna: Optional[str] = None
    rssi: Optional[str] = None
    from_rx: bool = False   # время взято из момента приёма, а не из строки


_DT_YMD = re.compile(
    r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T_](\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?(?!\d)")
_DT_DMY = re.compile(
    r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})[ T_](\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?(?!\d)")
_TIME_ONLY = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?(?![\d:])")
_UNIX = re.compile(r"(?<![0-9A-Fa-f.])(\d{13}|\d{10}(?:\.\d{1,6})?)(?![0-9A-Fa-f])")
_TOKEN = re.compile(r"[0-9A-Za-z]+")
_HEX = re.compile(r"^[0-9A-Fa-f]+$")
_WICLAX_LINE = re.compile(
    r"^\s*([^;]+);(\d{1,2})-(\d{1,2})-(\d{4}) (\d{1,2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?(?:;([^;]*))?")


def _mk(y, mo, d, h, mi, s, frac) -> Optional[dt.datetime]:
    try:
        return dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), frac_to_us(frac))
    except ValueError:
        return None


def parse_any_time(value: Any, rx: dt.datetime, tz_offset_hours: Optional[float]) -> Optional[dt.datetime]:
    """Время из JSON: число (unix, секунды или миллисекунды) или строка
    '2026-10-06 10:15:30.123', '06-10-2026 10:15:30.123', '10:15:30.123'."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        try:
            return from_unix(v / 1000.0 if v > 1e12 else v, tz_offset_hours)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    m = _DT_YMD.fullmatch(s)
    if m:
        g = m.groups()
        return _mk(g[0], g[1], g[2], g[3], g[4], g[5], g[6])
    m = _DT_DMY.fullmatch(s)
    if m:
        g = m.groups()
        return _mk(g[2], g[1], g[0], g[3], g[4], g[5], g[6])
    m = _TIME_ONLY.fullmatch(s)
    if m:
        g = m.groups()
        t = _mk(rx.year, rx.month, rx.day, g[0], g[1], g[2], g[3])
        return fix_midnight(t, rx) if t else None
    return None


class LineParser:
    def __init__(self, src: dict):
        self.src = src
        self.kind = src["parser"]
        self.rx = re.compile(src["pattern"]) if self.kind == "regex" else None

    # --- нормализация номера чипа
    def norm_chip(self, chip: Optional[str]) -> Optional[str]:
        if chip is None:
            return None
        c = chip.strip()
        if self.src["chip_upper"]:
            c = c.upper()
        if self.src["chip_strip_leading_zeros"]:
            c = c.lstrip("0") or "0"
        n = int(self.src["chip_take_last"] or 0)
        if n > 0:
            c = c[-n:]
        if not c or ";" in c:
            return None
        return c

    def parse(self, line: str, rx_time: dt.datetime) -> Optional[ParsedRead]:
        if not line or line.startswith("HEX:"):
            return None
        if self.kind == "wiclax":
            rec = self._parse_wiclax(line)
        elif self.kind == "ipico":
            rec = self._parse_ipico(line)
        elif self.kind == "regex":
            rec = self._parse_regex(line, rx_time)
        else:
            rec = self._parse_auto(line, rx_time)
        if rec is None:
            return None
        rec.chip = self.norm_chip(rec.chip)
        if not rec.chip:
            return None
        return rec

    def _parse_wiclax(self, line: str) -> Optional[ParsedRead]:
        m = _WICLAX_LINE.match(line)
        if not m:
            return None
        g = m.groups()
        ts = _mk(g[3], g[2], g[1], g[4], g[5], g[6], g[7])
        if ts is None:
            return None
        ant = (g[8] or "").strip() or None
        return ParsedRead(chip=g[0], ts=ts, antenna=ant)

    _IPICO = re.compile(r"aa([0-9a-fA-F]{2})([0-9a-fA-F]{12})([0-9a-fA-F]{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})([0-9a-fA-F]{2})")

    def _parse_ipico(self, line: str) -> Optional[ParsedRead]:
        """IPICO (Lite/Elite), строка чтения:
        aa · ID ридера (2) · чип (12 hex) · I/Q (4) · ГГММДД · ЧЧММСС · сотые (2) · контрольная сумма…"""
        m = self._IPICO.search(line.strip())
        if not m:
            return None
        rid, tag, _, yy, mo, dd, hh, mi, ss, cs = m.groups()
        try:
            hund = int(cs, 16) if self.src.get("ipico_hundredths_hex", True) else int(cs)
        except ValueError:
            return None
        if hund > 99:
            return None
        ts = _mk(2000 + int(yy), mo, dd, hh, mi, ss, f"{hund:02d}")
        if ts is None:
            return None
        return ParsedRead(chip=tag, ts=ts, antenna=rid)

    def _parse_regex(self, line: str, rx_time: dt.datetime) -> Optional[ParsedRead]:
        m = self.rx.search(line)
        if not m:
            return None
        g = m.groupdict()
        ts = None
        from_rx = False
        try:
            if g.get("datetime"):
                ts = dt.datetime.strptime(g["datetime"].strip(), self.src["datetime_format"])
            elif g.get("unix_ms"):
                ts = from_unix(float(g["unix_ms"]) / 1000.0, self.src["unix_tz_offset_hours"])
            elif g.get("unix"):
                ts = from_unix(float(g["unix"]), self.src["unix_tz_offset_hours"])
            elif g.get("time"):
                t = dt.datetime.strptime(g["time"].strip(), self.src["time_format"]).time()
                if g.get("date"):
                    d = dt.datetime.strptime(g["date"].strip(), self.src["date_format"]).date()
                    ts = dt.datetime.combine(d, t)
                else:
                    ts = fix_midnight(dt.datetime.combine(rx_time.date(), t), rx_time)
        except (ValueError, OverflowError, OSError):
            return None
        if ts is None:
            if not self.src["allow_receive_time"]:
                return None
            ts, from_rx = rx_time, True
        return ParsedRead(chip=g.get("chip") or "", ts=ts, antenna=g.get("antenna"),
                          rssi=g.get("rssi"), from_rx=from_rx)

    def _parse_auto(self, line: str, rx_time: dt.datetime) -> Optional[ParsedRead]:
        ts = None
        span = None
        m = _DT_YMD.search(line)
        if m:
            g = m.groups()
            ts = _mk(g[0], g[1], g[2], g[3], g[4], g[5], g[6])
            span = m.span()
        if ts is None:
            m = _DT_DMY.search(line)
            if m:
                g = m.groups()
                ts = _mk(g[2], g[1], g[0], g[3], g[4], g[5], g[6])
                span = m.span()
        if ts is None:
            m = _TIME_ONLY.search(line)
            if m:
                g = m.groups()
                t = _mk(rx_time.year, rx_time.month, rx_time.day, g[0], g[1], g[2], g[3])
                if t is not None:
                    ts = fix_midnight(t, rx_time)
                    span = m.span()
        if ts is None:
            for um in _UNIX.finditer(line):
                v = um.group(1)
                val = float(v) / 1000.0 if (len(v) == 13 and "." not in v) else float(v)
                if abs(val - time.time()) < 7 * 86400:
                    ts = from_unix(val, self.src["unix_tz_offset_hours"])
                    span = um.span()
                    break
        rest = line if span is None else (line[:span[0]] + " " + line[span[1]:])
        tokens = _TOKEN.findall(rest)
        min_len = int(self.src["min_chip_len"])
        hex_tokens = [t for t in tokens if _HEX.match(t) and len(t) >= min_len]
        chip = max(hex_tokens, key=len) if hex_tokens else None
        if chip is None:
            return None
        from_rx = False
        if ts is None:
            if not self.src["allow_receive_time"]:
                return None
            ts, from_rx = rx_time, True
        return ParsedRead(chip=chip, ts=ts, from_rx=from_rx)


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
            CREATE TABLE IF NOT EXISTS reads(
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
            CREATE INDEX IF NOT EXISTS idx_reads_ts ON reads(ts);
            CREATE INDEX IF NOT EXISTS idx_reads_chip ON reads(chip);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_reads ON reads(source, device, chip, ts);
            CREATE TABLE IF NOT EXISTS raw(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                line TEXT NOT NULL,
                parsed INTEGER NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_raw_received ON raw(received_at);
            CREATE TABLE IF NOT EXISTS events(
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
            );
            CREATE TABLE IF NOT EXISTS entries(
                event_id INTEGER NOT NULL,
                bib TEXT NOT NULL,
                chip TEXT NOT NULL,
                PRIMARY KEY(event_id, chip)
            );
            """
        )
        self._migrate()

    # ---- соревнования
    EVENT_FIELDS = ("name", "date", "place", "finish_device", "min_time_sec", "push_wiclax", "notes",
                    "alert_silence_min", "organizer", "chief_judge", "chief_secretary", "start_clock",
                    "heats_sequential", "reg_open", "reg_deadline", "reg_distances", "reg_rules", "reg_lanes",
                    "reg_info", "reg_consent")

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
            """)

    # ---- ридеры, заведённые через браузер
    def readers(self) -> list:
        return self._rows(self.con.execute("SELECT * FROM readers ORDER BY COALESCE(box,''), id"))

    def get_reader(self, rid: str) -> Optional[dict]:
        r = self._rows(self.con.execute("SELECT * FROM readers WHERE id = ?", (rid,)))
        return r[0] if r else None

    def save_reader(self, d: dict, orig_id: Optional[str] = None) -> None:
        now = fmt_db(now_local())
        with self.con:
            if orig_id and orig_id != d["id"]:
                self.con.execute("DELETE FROM readers WHERE id = ?", (orig_id,))
            self.con.execute(
                "INSERT INTO readers(id, name, box, host, port, device, parser, enabled, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, box=excluded.box,"
                " host=excluded.host, port=excluded.port, device=excluded.device, parser=excluded.parser,"
                " enabled=excluded.enabled, updated_at=excluded.updated_at",
                (d["id"], d.get("name") or "", d.get("box") or "", d["host"], int(d["port"]), d["device"],
                 d.get("parser") or "ipico", 1 if d.get("enabled") else 0, now, now))

    def set_reader_wiclax_port(self, rid: str, port: Optional[int]) -> None:
        with self.con:
            self.con.execute("UPDATE readers SET wiclax_port = ? WHERE id = ?", (port, rid))

    def set_reader_device(self, rid: str, device: str) -> None:
        with self.con:
            self.con.execute("UPDATE readers SET device = ?, updated_at = ? WHERE id = ?",
                             (device, fmt_db(now_local()), rid))

    def set_reader_enabled(self, rid: str, on: bool) -> None:
        with self.con:
            self.con.execute("UPDATE readers SET enabled = ?, updated_at = ? WHERE id = ?",
                             (1 if on else 0, fmt_db(now_local()), rid))

    def delete_source_reads(self, source: str) -> int:
        with self.con:
            n = self.con.execute("DELETE FROM reads WHERE source = ?", (source,)).rowcount
            self.con.execute("DELETE FROM raw WHERE source = ?", (source,))
        return n

    def delete_reader(self, rid: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM readers WHERE id = ?", (rid,))

    def wiclax_ports(self) -> list:
        return self._rows(self.con.execute("SELECT * FROM wiclax_ports ORDER BY port"))

    def save_wiclax_port(self, port: int, devices: str, name: str) -> None:
        with self.con:
            self.con.execute("INSERT INTO wiclax_ports(port, devices, name) VALUES(?,?,?) ON CONFLICT(port) DO UPDATE"
                             " SET devices=excluded.devices, name=excluded.name", (port, devices, name))

    def delete_wiclax_port(self, port: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM wiclax_ports WHERE port = ?", (port,))

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
            "INSERT INTO events(name, date, place, finish_device, min_time_sec, push_wiclax, notes,"
            " alert_silence_min, organizer, chief_judge, chief_secretary, start_clock, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d["name"], d.get("date"), d.get("place"), d.get("finish_device"),
             float(d.get("min_time_sec") or 0), 1 if d.get("push_wiclax", True) else 0,
             d.get("notes"), float(d.get("alert_silence_min") or 10), d.get("organizer"),
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
                if k in ("min_time_sec", "alert_silence_min"):
                    v = float(v or 0)
                if k == "push_wiclax":
                    v = 1 if v else 0
                if k == "heats_sequential":
                    v = None if v is None or v == "" else (1 if v else 0)
                if k == "reg_open":
                    v = 1 if v else 0
                if k == "reg_lanes":
                    v = max(1, min(int(v or 8), 50))
                if k in ("reg_distances", "reg_rules", "reg_info", "reg_consent", "reg_deadline") and v is not None:
                    v = str(v)[:4000] or None
                sets.append(f"{k} = ?")
                args.append(v)
        if sets:
            self.con.execute(f"UPDATE events SET {', '.join(sets)} WHERE id = ?", (*args, eid))

    def set_event_field(self, eid: int, **kw) -> None:
        for k, v in kw.items():
            if k not in ("start_time", "status", "check_since", "archived", "finished_at", "reg_slug"):
                raise ValueError(k)
            self.con.execute(f"UPDATE events SET {k} = ? WHERE id = ?", (v, eid))

    def delete_event(self, eid: int) -> None:
        for t in ("entries", "waves", "manual", "files", "registrations"):
            self.con.execute(f"DELETE FROM {t} WHERE event_id = ?", (eid,))
        self.con.execute("DELETE FROM events WHERE id = ?", (eid,))

    # участники: номер, чип, забег, ФИО, год, команда, категория
    def set_entries(self, eid: int, rows: list) -> None:
        self.con.execute("BEGIN")
        try:
            self.con.execute("DELETE FROM entries WHERE event_id = ?", (eid,))
            self.con.executemany(
                "INSERT OR REPLACE INTO entries(event_id, bib, chip, wave, name, birth_year, team, category,"
                " lane, coach, seed, reg_id, sex) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(eid, r["bib"], r["chip"], r.get("wave"), r.get("name"), r.get("birth_year"), r.get("team"),
                  r.get("category"), r.get("lane"), r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex"))
                 for r in rows])
            for w in dict.fromkeys(r["wave"] for r in rows if r.get("wave")):
                self.con.execute("INSERT OR IGNORE INTO waves(event_id, name) VALUES (?,?)", (eid, w))
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise

    def entries_full(self, eid: int) -> list:
        return self.con.execute(
            "SELECT bib, chip, wave FROM entries WHERE event_id = ? ORDER BY CAST(bib AS INTEGER), bib",
            (eid,)).fetchall()

    def entries_rows(self, eid: int) -> list:
        return self._rows(self.con.execute(
            "SELECT bib, chip, wave, name, birth_year, team, category, lane, coach, seed, reg_id, sex FROM entries"
            " WHERE event_id = ? ORDER BY CAST(bib AS INTEGER), bib", (eid,)))

    def update_entry(self, eid: int, bib: str, **kw) -> int:
        sets, args = [], []
        for k, v in kw.items():
            if k not in ("wave", "lane", "name", "birth_year", "team", "category", "coach", "seed"):
                raise ValueError(k)
            sets.append(f"{k} = ?")
            args.append(v)
        if not sets:
            return 0
        return self.con.execute(f"UPDATE entries SET {', '.join(sets)} WHERE event_id = ? AND bib = ?",
                                (*args, eid, bib)).rowcount

    def add_entry(self, eid: int, r: dict) -> None:
        self.con.execute(
            "INSERT INTO entries(event_id, bib, chip, wave, name, birth_year, team, category, lane, coach, seed,"
            " reg_id, sex) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, r["bib"], r["chip"], r.get("wave"), r.get("name"), r.get("birth_year"), r.get("team"),
             r.get("category"), r.get("lane"), r.get("coach"), r.get("seed"), r.get("reg_id"), r.get("sex")))

    def delete_entry(self, eid: int, bib: str) -> None:
        self.con.execute("DELETE FROM entries WHERE event_id = ? AND bib = ?", (eid, bib))

    # заявки с публичной формы
    REG_FIELDS = ("last_name", "first_name", "middle_name", "birth_date", "sex", "team", "coach", "distance",
                  "best", "best_sec", "category", "representative", "contact", "status", "note", "bib")

    def add_registration(self, eid: int, d: dict) -> int:
        cols = [k for k in self.REG_FIELDS if k in d] + ["consent_at", "consent_hash", "created_at", "event_id"]
        vals = [d[k] for k in self.REG_FIELDS if k in d] + [d["consent_at"], d.get("consent_hash"),
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
            "SELECT id, event_id, name, size, kind, created_at, author, folder FROM files WHERE event_id = ? ORDER BY id",
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

    def reads_since(self, since_id: int, limit: int) -> list:
        rows = self.con.execute(
            "SELECT id, source, device, chip, ts FROM reads WHERE id > ? ORDER BY id DESC LIMIT ?",
            (since_id, limit)).fetchall()
        return list(reversed(rows))

    def reads_after_time(self, since: dt.datetime, limit: int) -> list:
        return self.con.execute(
            "SELECT id, source, device, chip, ts FROM reads WHERE ts >= ? ORDER BY id DESC LIMIT ?",
            (fmt_db(since), limit)).fetchall()

    def chips_after_time(self, since: dt.datetime) -> dict:
        return {c: (d, t) for c, d, t in self.con.execute(
            "SELECT chip, device, MAX(ts) FROM reads WHERE ts >= ? GROUP BY chip", (fmt_db(since),))}

    def last_id(self) -> int:
        return int(self.con.execute("SELECT COALESCE(MAX(id), 0) FROM reads").fetchone()[0])

    def reads_window(self, start: dt.datetime, end: dt.datetime) -> list:
        return self.con.execute(
            "SELECT device, chip, ts FROM reads WHERE ts >= ? AND ts <= ? ORDER BY ts, id",
            (fmt_db(start), fmt_db(end))).fetchall()

    def devices(self) -> list:
        return [r[0] for r in self.con.execute("SELECT DISTINCT device FROM reads ORDER BY device LIMIT 100")]

    def add_read(self, source: str, device: str, r: ParsedRead, rx: dt.datetime) -> bool:
        """True — новая отметка; False — точный повтор уже сохранённой
        (например, ридер после обрыва связи заново выгрузил память)."""
        cur = self.con.execute(
            "INSERT OR IGNORE INTO reads(source, device, chip, ts, antenna, rssi, time_from_receive, received_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (source, device, r.chip, fmt_db(r.ts), r.antenna, r.rssi, 1 if r.from_rx else 0, fmt_db(rx)),
        )
        return cur.rowcount > 0

    def add_raw(self, source: str, line: str, parsed: bool, rx: dt.datetime) -> None:
        self.con.execute(
            "INSERT INTO raw(source, line, parsed, received_at) VALUES (?,?,?,?)",
            (source, line[:2000], 1 if parsed else 0, fmt_db(rx)),
        )

    def query_reads(self, start: Optional[dt.datetime], end: Optional[dt.datetime],
                    devices: Optional[list] = None, source: Optional[str] = None) -> list:
        q = "SELECT source, device, chip, ts, antenna, rssi, time_from_receive, received_at FROM reads WHERE 1=1"
        args: list = []
        if start is not None:
            q += " AND ts >= ?"
            args.append(fmt_db(start))
        if end is not None:
            q += " AND ts <= ?"
            args.append(fmt_db(end))
        if devices:
            q += " AND device IN (%s)" % ",".join("?" * len(devices))
            args.extend(devices)
        if source:
            q += " AND source = ?"
            args.append(source)
        q += " ORDER BY ts, id"
        return self.con.execute(q, args).fetchall()

    def last_reads(self, n: int) -> list:
        return self.con.execute(
            "SELECT source, device, chip, ts, antenna, time_from_receive, received_at"
            " FROM reads ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def totals(self) -> dict:
        reads = self.con.execute("SELECT COUNT(*) FROM reads").fetchone()[0]
        raw = self.con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
        return {"reads": reads, "raw_lines": raw}


# --------------------------------------------------------------------------- #
#  Фильтр повторов для Wiclax
# --------------------------------------------------------------------------- #
class PassingFilter:
    """Ридер видит чип 5–20 раз за одно прохождение. В Wiclax отправляем первую
    отметку прохождения; следующие отметки того же чипа на той же точке,
    идущие с интервалом меньше gap секунд, считаются тем же прохождением.
    В базе при этом хранятся ВСЕ отметки."""

    MAX_WINDOWS = 64

    def __init__(self, gap_sec: float):
        self.gap = dt.timedelta(seconds=float(gap_sec or 0))
        self.windows: dict[tuple, list] = {}

    def accept(self, device: str, chip: str, ts: dt.datetime) -> bool:
        if self.gap.total_seconds() <= 0:
            return True
        wins = self.windows.setdefault((device, chip), [])
        for w in wins:
            # отметка попадает в уже известное прохождение (с запасом gap) —
            # расширяем его и в Wiclax повторно не отправляем
            if w[0] - self.gap <= ts <= w[1] + self.gap:
                if ts < w[0]:
                    w[0] = ts
                if ts > w[1]:
                    w[1] = ts
                return False
        wins.append([ts, ts])
        if len(wins) > self.MAX_WINDOWS:
            wins.pop(0)
        return True


# --------------------------------------------------------------------------- #
#  Состояние источника
# --------------------------------------------------------------------------- #
class SourceState:
    def __init__(self, cfg: dict, memory_lines: int):
        self.cfg = cfg
        self.id: str = cfg["id"]
        self.parser = LineParser(cfg)
        self.connected = 0
        self.peer: Optional[str] = None
        self.lines = 0
        self.reads = 0
        self.duplicates = 0
        self.parse_errors = 0
        self.last_line: Optional[str] = None
        self.last_line_at: Optional[dt.datetime] = None
        self.last_read_at: Optional[dt.datetime] = None
        self.last_offset: Optional[float] = None
        self.last_error: Optional[str] = None
        self.tail: deque = deque(maxlen=memory_lines)

    def device_for(self, antenna: Optional[str]) -> str:
        dev = str(self.cfg["device"])
        if self.cfg["device_per_antenna"] and antenna:
            dev = f"{dev}{antenna}"
        return dev


def set_keepalive(sock: Optional[socket.socket]) -> None:
    """Быстро замечаем «мёртвое» 4G-соединение."""
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except OSError:
        pass


def _is_binary(b: bytes) -> bool:
    if not b:
        return False
    bad = sum(1 for c in b if (c < 32 and c not in (9,)) or c == 127)
    return bad / len(b) > 0.1


class LineSplitter:
    """Режет поток на строки по \\r, \\n или \\r\\n. Двоичные данные
    сохраняет как 'HEX:...' — чтобы потом разобраться в формате."""
    MAX = 4096

    _SEP = re.compile(rb"[\r\n]")

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes) -> list:
        self.buf += data
        parts = self._SEP.split(self.buf)
        self.buf = parts.pop()  # хвост без конца строки ждёт следующих данных
        out = [self._decode(p) for p in parts if p]
        out = [x for x in out if x]
        if len(self.buf) > self.MAX:
            out.append("HEX:" + self.buf.hex())
            self.buf = b""
        return out

    @staticmethod
    def _decode(chunk: bytes) -> str:
        if _is_binary(chunk):
            return "HEX:" + chunk.hex()
        return chunk.decode("utf-8", errors="replace").strip()


# --------------------------------------------------------------------------- #
#  Клиент Wiclax
# --------------------------------------------------------------------------- #
class WiclaxClient:
    def __init__(self, hub: "Hub", reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 devices: Optional[set] = None, port: Optional[int] = None, sources: Optional[set] = None):
        self.hub = hub
        self.devices = devices          # None — все точки; иначе только эти коды точек
        self.sources = sources          # личный порт ридера: только отметки этих ридеров
        self.port = port
        self.reader = reader
        self.writer = writer
        wc = hub.cfg["wiclax"]
        self.line_end = wc["line_end"]
        self.heartbeat = float(wc["heartbeat_sec"] or 0)
        self.live = bool(wc["live_on_connect"])
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=500000)
        peer = writer.get_extra_info("peername")
        self.peer = f"{peer[0]}:{peer[1]}" if peer else "?"
        self.since = now_local()
        self.sent = 0
        self.commands: deque = deque(maxlen=20)

    def offer(self, line: str, rewind: bool = False) -> None:
        if not self.live and not rewind:
            return
        try:
            self.queue.put_nowait(line)
        except asyncio.QueueFull:
            log.warning("Wiclax %s: очередь переполнена, отметка пропущена (есть в базе)", self.peer)

    def command(self, line: str) -> None:
        """Служебная команда для Wiclax (например RACESTART) — уходит всегда, даже на паузе."""
        try:
            self.queue.put_nowait(line)
        except asyncio.QueueFull:
            log.warning("Wiclax %s: очередь переполнена, команда не отправлена", self.peer)

    def _write(self, text: str) -> None:
        self.writer.write((text + self.line_end).encode("utf-8"))

    async def run(self) -> None:
        log.info("Wiclax подключился: %s", self.peer)
        set_keepalive(self.writer.get_extra_info("socket"))
        self.hub.wiclax_clients.add(self)
        tasks = [asyncio.ensure_future(self._reader_loop()), asyncio.ensure_future(self._writer_loop())]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, (ConnectionError, asyncio.IncompleteReadError)):
                    log.warning("Wiclax %s: %r", self.peer, exc)
        finally:
            self.hub.wiclax_clients.discard(self)
            try:
                self.writer.close()
            except Exception:
                pass
            log.info("Wiclax отключился: %s", self.peer)

    async def _writer_loop(self) -> None:
        while True:
            try:
                if self.heartbeat > 0:
                    line = await asyncio.wait_for(self.queue.get(), timeout=self.heartbeat)
                else:
                    line = await self.queue.get()
                self._write(line)
                self.sent += 1
                # пачкой выгребаем всё, что накопилось
                while not self.queue.empty() and self.writer.transport.get_write_buffer_size() < 1 << 20:
                    self._write(self.queue.get_nowait())
                    self.sent += 1
            except asyncio.TimeoutError:
                self._write("*")
            await self.writer.drain()

    async def _reader_loop(self) -> None:
        splitter = LineSplitter()
        while True:
            data = await self.reader.read(4096)
            if not data:
                return
            for cmd in splitter.feed(data):
                await self._handle(cmd)

    async def _handle(self, cmd: str) -> None:
        c = cmd.strip()
        if not c:
            return
        up = c.upper()
        self.commands.append(f"{now_local():%H:%M:%S} {c}")
        log.debug("Wiclax %s -> %s", self.peer, c)
        if up.startswith("HELLO"):
            return
        if up == "CLOCK":
            self._write(f"CLOCK {now_local():%d-%m-%Y %H:%M:%S}")
        elif up.startswith("CLOCK "):
            # Wiclax хочет «установить время устройства». Сервер своё время
            # не сдвигает: время отметок задают сами ридеры. Запоминаем
            # расхождение и показываем на странице состояния.
            try:
                wt = dt.datetime.strptime(c[6:].strip(), "%d-%m-%Y %H:%M:%S")
                diff = (wt - now_local()).total_seconds()
                self.hub.wiclax_clock_diff = (now_local(), diff)
                if abs(diff) > float(self.hub.cfg["clock_warn_sec"]):
                    log.warning("Часы компьютера Wiclax расходятся с сервером на %.1f с", diff)
            except ValueError:
                pass
            self._write("CLOCKOK")
        elif up == "STARTREAD":
            self.live = True
            self._write("READOK")
        elif up == "STOPREAD":
            self.live = False
            self._write("READOK")
        elif up.startswith("REWIND"):
            parts = c.split()
            try:
                start = dt.datetime.strptime(f"{parts[1]} {parts[2]}", "%d-%m-%Y %H:%M:%S")
                end = dt.datetime.strptime(f"{parts[3]} {parts[4]}", "%d-%m-%Y %H:%M:%S")
                end = end.replace(microsecond=999999)
            except (IndexError, ValueError):
                log.warning("Wiclax %s: непонятная команда REWIND: %s", self.peer, c)
                return
            n = 0
            for line in self.hub.rewind_lines(start, end, self.devices, self.sources):
                self.offer(line, rewind=True)
                n += 1
            log.info("Wiclax %s: REWIND %s — %s, отправлено %d", self.peer, start, end, n)
        else:
            log.info("Wiclax %s: неизвестная команда: %s", self.peer, c)
        await self.writer.drain()


# --------------------------------------------------------------------------- #
#  Хаб
# --------------------------------------------------------------------------- #
class Hub:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = Store(cfg["db_path"])
        mem = int(cfg["raw_memory_lines"])
        self.sources: dict[str, SourceState] = {
            s["id"]: SourceState(s, mem) for s in cfg["sources"] if s["enabled"]}
        self.wiclax_clients: set = set()
        self.live_filter = PassingFilter(cfg["wiclax"]["forward_filter_sec"])
        # для личных портов ридеров — свой фильтр на каждый ридер: дублирующий финиш
        # не должен «съедаться» отметкой основного ридера той же точки
        self.src_filter = PassingFilter(cfg["wiclax"]["forward_filter_sec"])
        self.servers: list = []
        self.tasks: list = []
        self._rate: dict = {}
        self._clients: dict = {}       # кто открывал страницы сервера: IP → последнее обращение
        self.started_at = now_local()
        self.wiclax_clock_diff: Optional[tuple] = None
        self.stopping = asyncio.Event()
        devs = cfg["wiclax"].get("devices")
        self.wiclax_devices = set(devs) if devs else None
        self.reader_tasks: dict = {}           # ридеры из браузера: id → задача подключения
        self.db_reader_parsers: dict = {r["id"]: r["parser"] for r in self.store.readers()}
        self.wiclax_port_servers: dict = {}    # доп. порты Wiclax по точкам: порт → сервер
        self.wiclax_port_errors: dict = {}

    # ---- приём строки
    def handle_line(self, src: SourceState, line: str, rx: Optional[dt.datetime] = None) -> bool:
        rx = rx or now_local()
        return self.handle_parsed(src, line, src.parser.parse(line, rx), rx)

    def handle_parsed(self, src: SourceState, line: str, rec: Optional[ParsedRead],
                      rx: dt.datetime) -> bool:
        src.lines += 1
        src.last_line = line
        src.last_line_at = rx
        src.tail.append((rx, line, rec is not None))
        if self.cfg["store_raw"]:
            try:
                self.store.add_raw(src.id, line, rec is not None, rx)
            except sqlite3.Error as e:
                log.error("База: не удалось сохранить сырую строку: %s", e)
        if rec is None:
            src.parse_errors += 1
            return False
        device = src.device_for(rec.antenna)
        try:
            is_new = self.store.add_read(src.id, device, rec, rx)
        except sqlite3.Error as e:
            log.error("База: не удалось сохранить отметку: %s", e)
            is_new = True  # лучше отдать в Wiclax, чем потерять
        if not is_new:
            src.duplicates += 1
            return True
        src.reads += 1
        src.last_read_at = rx
        if not rec.from_rx:
            src.last_offset = (rec.ts - rx).total_seconds()
        self._forward(device, rec, src.id)
        return True

    def _chip_lower(self, source: Optional[str]) -> bool:
        src = self.sources.get(source) if source else None
        flag = src.cfg.get("chip_lower") if src else None
        if flag is None and source in self.db_reader_parsers:
            flag = self.db_reader_parsers[source] == "ipico"
        if flag is None:
            flag = bool(self.cfg["wiclax"].get("chip_lower"))
        return bool(flag)

    def _wiclax_line(self, chip: str, ts: dt.datetime, device: str, rewind: bool, source: Optional[str] = None) -> str:
        if self._chip_lower(source):
            chip = chip.lower()       # IPICO в Wiclax хранится строчными: 58003a9f837
        return f"{chip};{fmt_wiclax(ts)};{device};;;{1 if rewind else 0}"

    def _forward(self, device: str, rec: ParsedRead, source: Optional[str] = None) -> None:
        main_ok = self.live_filter.accept(device, rec.chip, rec.ts)
        src_ok = self.src_filter.accept("src:" + (source or ""), rec.chip, rec.ts)
        if not (main_ok or src_ok):
            return
        line = self._wiclax_line(rec.chip, rec.ts, device, False, source)
        for c in list(self.wiclax_clients):
            if c.sources is not None:
                if src_ok and source in c.sources:
                    c.offer(line)
            elif main_ok and (c.devices is None or device in c.devices):
                c.offer(line)

    def rewind_lines(self, start: dt.datetime, end: dt.datetime, devices: Optional[set] = None,
                     sources: Optional[set] = None):
        f = PassingFilter(self.cfg["wiclax"]["forward_filter_sec"])
        if sources:
            for sid in sorted(sources):
                for row in self.store.query_reads(start, end, source=sid):
                    device, chip, ts = row[1], row[2], parse_db(row[3])
                    if f.accept(sid, chip, ts):
                        yield self._wiclax_line(chip, ts, device, True, sid)
            return
        devs = sorted(devices) if devices else None
        for row in self.store.query_reads(start, end, devices=devs):
            source, device, chip, ts_s = row[0], row[1], row[2], row[3]
            ts = parse_db(ts_s)
            if f.accept(device, chip, ts):
                yield self._wiclax_line(chip, ts, device, True, source)

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
        out["push_wiclax"] = bool(ev.get("push_wiclax"))
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
        return out

    def known_devices(self) -> list:
        devs = {str(s.cfg["device"]) for s in self.sources.values()}
        devs.update(self.store.devices())
        return sorted(devs)

    @staticmethod
    def _bib_of(chip: str, entries: dict) -> str:
        if chip in entries:
            return entries[chip]
        return chip[1:] if chip.startswith("#") else ""

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

    def compute(self, ev: dict) -> dict:
        eid = ev["id"]
        erows = self.store.entries_rows(eid)
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
        res = {"event": self._event_view(ev), "started": bool(ev_start or wave_start),
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
            per = first[chip]
            w = chip_wave.get(chip, "")
            meta = wmeta.get(w, {})
            inf = info.get(chip, {})
            return {"bib": self._bib_of(chip, entries), "chip": "" if chip.startswith("#") else chip,
                    "wave": w, "category": inf.get("category") or meta.get("category") or "",
                    "distance": meta.get("distance") or "",
                    "name": inf.get("name") or "", "birth_year": inf.get("birth_year") or "",
                    "team": inf.get("team") or "", "coach": inf.get("coach") or "",
                    "splits": {d: self.fmt_elapsed(secs(chip, d)) for d in per},
                    "manual": sorted(d for d in per if (chip, d) in manual_set)}

        finished = [c for c in first if fin_dev in first[c]]
        finished.sort(key=lambda c: (wave_order.get(chip_wave.get(c, ""), -1), secs(c, fin_dev)))
        place_by_wave: dict = {}
        for chip in finished:
            sec = secs(chip, fin_dev)
            w = chip_wave.get(chip, "")
            place_by_wave[w] = place_by_wave.get(w, 0) + 1
            r = row(chip)
            r.update(place=place_by_wave[w], time=self.fmt_elapsed(sec), result=self.fmt_result(sec),
                     seconds=round(sec, 3), finish_at=fmt_db(first[chip][fin_dev]),
                     finish_epoch_ms=self._epoch_ms(first[chip][fin_dev]))
            res["finished"].append(r)
        # общий рейтинг: все забеги одной категории и дистанции вместе
        groups: dict = {}
        for r in res["finished"]:
            groups.setdefault((r["category"], r["distance"]), []).append(r)
        for (cat, dist), lst in groups.items():
            lst.sort(key=lambda r: r["seconds"])
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
        for chip, per in first.items():
            if fin_dev not in per:
                last_dev = max(per, key=lambda d: per[d])
                r = row(chip)
                r.update(last_point=last_dev, last_time=self.fmt_elapsed(secs(chip, last_dev)))
                res["on_course"].append(r)
        res["on_course"].sort(key=lambda r: r["last_time"], reverse=True)
        res["not_seen"] = [{"bib": r["bib"], "chip": "" if r["chip"].startswith("#") else r["chip"],
                            "wave": r["wave"] or "", "name": r["name"] or "", "birth_year": r["birth_year"] or "",
                            "team": r["team"] or "", "coach": r.get("coach") or "", "category": r["category"] or wmeta.get(r["wave"] or "", {}).get("category") or "",
                            "distance": wmeta.get(r["wave"] or "", {}).get("distance") or ""}
                           for r in erows if r["chip"] not in first]

        # ---- предупреждения
        A = res["alerts"]
        if not fin_dev:
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
        if ev.get("push_wiclax"):
            line = f"RACESTART {st:%H:%M:%S},{st.microsecond // 1000:03d}"
            for c in list(self.wiclax_clients):
                c.command(line)
            log.info("Старт «%s»%s в %s отправлен в Wiclax (%d подключений)", ev["name"],
                     f" / {wave}" if wave else "", fmt_db(st), len(self.wiclax_clients))
        return self._event_view(self.store.get_event(ev["id"]))

    ENTRY_COLS = ("bib", "chip", "wave", "name", "birth_year", "team", "category", "lane", "coach", "seed")
    _HEAD = (("bib", ("номер", "нагрудн", "№", "bib", "ст.н", "старт.ном")),
             ("chip", ("чип", "chip", "транспонд", "метка")),
             ("wave", ("забег", "волна", "heat", "старт")),
             ("name", ("фио", "фамилия", "участник", "спортсмен", "name")),
             ("birth_year", ("год", "г.р", "рожд", "birth")),
             ("team", ("команд", "клуб", "организац", "регион", "город", "team")),
             ("category", ("категор", "группа", "пол", "category")),
             ("lane", ("дорожк", "lane")),
             ("coach", ("тренер", "coach")),
             ("seed", ("заявл", "лучш", "seed")))

    @classmethod
    def parse_entries(cls, text: str) -> tuple:
        """Строки участников. Порядок колонок по умолчанию: номер;чип;забег;ФИО;год;команда;категория.
        Если первая строка — заголовки (Номер, Чип, ФИО, Год, Команда, Категория, Забег), колонки
        берутся по ним в любом порядке."""
        rows, bad = [], []
        seen = set()
        cols = list(cls.ENTRY_COLS)
        lines = text.splitlines()
        for n, line in enumerate(lines, 1):
            line = line.strip().lstrip("﻿")
            if not line or line.startswith("#"):
                continue
            sep = next((c for c in (";", "\t", ",") if c in line), None)
            parts = [p.strip().strip('"') for p in (line.split(sep) if sep else line.split())]
            if not rows and not bad and not re.search(r"\d", parts[0]):
                mapped = []
                for p in parts:
                    low = p.lower()
                    key = next((k for k, words in cls._HEAD if any(w in low for w in words)), None)
                    mapped.append(key if key not in mapped else None)
                if "bib" in mapped:
                    cols = mapped
                    continue
            rec = {k: (parts[i] if i < len(parts) else "") for i, k in enumerate(cols) if k}
            bib = re.sub(r"[^0-9A-Za-z-]", "", rec.get("bib", ""))[:12]
            chip = re.sub(r"\s", "", rec.get("chip", "")).upper()
            if not bib or (chip and not re.fullmatch(r"[0-9A-Z]+", chip)):
                bad.append(n)
                continue
            if not chip:
                chip = "#" + bib          # участник без чипа: только ручные отметки судьи
            if chip in seen:
                bad.append(n)
                continue
            seen.add(chip)
            year = rec.get("birth_year", "")
            m = re.search(r"(19|20)\d\d", year)
            rows.append({"bib": bib, "chip": chip, "wave": rec.get("wave", "")[:40] or None,
                         "name": rec.get("name", "")[:80] or None, "birth_year": m.group(0) if m else (year[:4] or None),
                         "team": rec.get("team", "")[:80] or None, "category": rec.get("category", "")[:40] or None,
                         "lane": int(rec["lane"]) if rec.get("lane", "").isdigit() else None,
                         "coach": rec.get("coach", "")[:80] or None, "seed": rec.get("seed", "")[:12] or None})
        return rows, bad

    # ---- проверка чипов перед стартом
    def check_view(self, ev: dict) -> dict:
        full = [r for r in self.store.entries_full(ev["id"]) if not r[1].startswith("#")]
        entries = {c: b for b, c, _ in full}
        since = parse_db(ev["check_since"]) if ev.get("check_since") else None
        out = {"since": ev.get("check_since"), "total": len(full), "checked": 0,
               "unchecked": [], "unknown": [], "last": []}
        if since is None:
            out["unchecked"] = [b for b, _, _ in full]
            return out
        seen = self.store.chips_after_time(since)
        out["checked"] = sum(1 for c in entries if c in seen)
        out["unchecked"] = [b for b, c, _ in full if c not in seen]
        out["unknown"] = sorted(c for c in seen if c not in entries)
        for rid, source, device, chip, ts_s in self.store.reads_after_time(since, 15):
            out["last"].append({"id": rid, "chip": chip, "device": device, "time": ts_s[11:21],
                                "bib": entries.get(chip, ""), "known": chip in entries})
        return out

    # ---- API
    def _api(self, method: str, path: str, qs: dict, body: bytes, actor: str = "", headers: Optional[dict] = None):
        J = "application/json; charset=utf-8"
        headers = headers or {}

        def ok(obj, code=200):
            return code, J, json.dumps(obj, ensure_ascii=False), None

        def err(msg, code=400):
            return code, J, json.dumps({"error": msg}, ensure_ascii=False), None

        mc = re.fullmatch(r"/api/events/(\d+)/clax", path)
        if mc and method == "POST":
            ev = self.store.get_event(int(mc.group(1)))
            if ev is None:
                return err("соревнование не найдено", 404)
            if any(w.get("start_time") for w in self.store.waves(ev["id"])) or ev.get("start_time"):
                return err("у соревнования уже был старт — импортируйте в новое соревнование")
            try:
                if qs.get("check"):
                    d = self.parse_clax(body)
                    return ok({"source": d["name"], "dates": d["dates"], "entries": len(d["entries"]),
                               "with_chip": sum(1 for e in d["entries"] if e["chip"]), "parcours": list(d["parcours"])})
                out = self.import_clax(ev, body, with_names=qs.get("names", "1") != "0")
            except Exception as e:  # noqa
                return err(f"не удалось прочитать файл Wiclax: {e}")
            self.store.audit(actor, ev["id"], "Импорт из Wiclax", f"{out['source']}: {out['entries']} участников, чипов {out['with_chip']}")
            return ok(out)

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
        if path.startswith(("/api/readers", "/api/wiclax-ports")):
            res = self._reader_api(method, path, data, actor)
            if res is not None:
                return res[0], J, json.dumps(res[1], ensure_ascii=False), None
        judge = str(data.get("judge") or "").strip()[:40]
        who = f"{actor} / {judge}" if judge else actor

        if path == "/api/clock":
            return ok({"server_epoch_ms": int(time.time() * 1000), "server_time": fmt_db(now_local())})
        if path == "/api/devices":
            return ok({"devices": self.known_devices()})
        if path == "/api/system":
            return ok(self.system_view())
        if path == "/api/system/update":
            return ok(self.update_state())
        if path == "/api/log":
            return ok({"log": self.store.audit_list(None)})
        if path == "/api/live":
            try:
                since = int(qs.get("since", "0") or 0)
                limit = max(1, min(int(qs.get("limit", "100") or 100), 500))
            except ValueError:
                return err("since/limit — числа")
            ev = None
            if qs.get("event", "").isdigit():
                ev = self.store.get_event(int(qs["event"]))
            rows = self.store.reads_since(max(self.store.last_id() - limit, 0) if since <= 0 else since, limit)
            full = self.store.entries_full(ev["id"]) if ev else []
            entries = {c: b for b, c, _ in full}
            chip_wave = {c: w for _, c, w in full if w}
            wave_start = {w["name"]: parse_db(w["start_time"]) for w in self.store.waves(ev["id"])
                          if w.get("start_time")} if ev else {}
            ev_st = parse_db(ev["start_time"]) if ev and ev.get("start_time") else None
            out = []
            for rid, source, device, chip, ts_s in rows:
                item = {"id": rid, "source": source, "device": device, "chip": chip,
                        "time": ts_s[11:21], "bib": entries.get(chip, "")}
                st = wave_start.get(chip_wave.get(chip, ""), ev_st)
                if st is not None and parse_db(ts_s) >= st:
                    item["elapsed"] = self.fmt_elapsed((parse_db(ts_s) - st).total_seconds())
                if ev:
                    item["finish"] = bool(ev.get("finish_device") and device == ev["finish_device"])
                out.append(item)
            last = out[-1]["id"] if out else (since if since > 0 else self.store.last_id())
            return ok({"last_id": last, "reads": out})
        if path == "/api/events":
            if method == "GET":
                return ok({"events": [self._event_view(e) for e in self.store.list_events()]})
            if method == "POST":
                name = str(data.get("name", "")).strip()
                if not name:
                    return err("укажите название")
                eid = self.store.add_event({**data, "name": name})
                self.store.audit(who, eid, "Создано соревнование", name)
                return ok(self._event_view(self.store.get_event(eid)), 201)
            return err("метод не поддерживается", 405)

        m = re.fullmatch(r"/api/events/(\d+)(?:/([a-z.]+))?(?:/(\d+))?", path)
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
                    vals = [r["bib"], "" if r["chip"].startswith("#") else r["chip"], r["wave"] or "",
                            r["name"] or "", r["birth_year"] or "", r["team"] or "", r["category"] or "",
                            str(r["lane"] or ""), r["coach"] or "", r["seed"] or ""]
                    while len(vals) > 2 and not vals[-1]:
                        vals.pop()
                    lines.append(";".join(vals))
                return ok({"text": "\n".join(lines), "count": len(rows)})
            if action == "check":
                return ok(self.check_view(ev))
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
                return ok(out)
            if action == "regs.csv":
                return self._regs_csv(ev)
            if action == "startlist":
                return ok(self.startlist(ev))
            if action == "template.xlsx":
                return self._template_response(ev)
            if action == "wiclax.csv":
                return self._wiclax_csv(ev)
            if action == "event.clax":
                return self._wiclax_clax(ev)
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
            self.store.update_event(eid, data)
            if data.get("reg_open") and not ev.get("reg_slug"):
                import secrets
                self.store.set_event_field(eid, reg_slug=secrets.token_urlsafe(6).replace("-", "x").replace("_", "z"))
            self.store.audit(who, eid, "Изменены настройки", ", ".join(k for k in data if k != "judge"))
            return ok(self._event_view(self.store.get_event(eid)))
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
            self.store.set_event_field(eid, status="finished", finished_at=fmt_db(now_local()))
            snap = self.snapshot_results(ev, who)
            self.store.audit(who, eid, "Соревнование завершено", f"снимок результатов: {snap['name']}" if snap else "")
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
            self.store.set_event_field(eid, status="running" if ev.get("start_time") else "planned")
            self.store.audit(who, eid, "Соревнование открыто снова")
            return ok(self._event_view(self.store.get_event(eid)))
        if action == "entries":
            rows, bad = self.parse_entries(str(data.get("text", "")))
            old = {e["bib"]: e for e in self.store.entries_rows(eid)}
            for r in rows:
                r["reg_id"] = (old.get(r["bib"]) or {}).get("reg_id")    # связь с заявкой и пол сохраняются по номеру
                r["sex"] = (old.get(r["bib"]) or {}).get("sex")
            self.store.set_entries(eid, rows)
            self.store.audit(who, eid, "Загружен список участников", f"{len(rows)} строк")
            return ok({"count": len(rows), "bad_lines": bad})
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
                                                      "archived": 0}, {**data, "consent": True})
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
            # участник уже в забеге — обновляем и стартовый список
            if r.get("bib"):
                e = {"name": " ".join(x for x in (upd.get("last_name", r["last_name"]), upd.get("first_name", r["first_name"])) if x),
                     "team": upd.get("team", r["team"]), "coach": upd.get("coach", r["coach"]),
                     "category": upd.get("category", r["category"]), "seed": upd.get("best", r["best"]),
                     "birth_year": upd.get("birth_date", r["birth_date"])[:4]}
                self.store.update_entry(eid, r["bib"], **e)
                if upd.get("status") == "rejected":
                    self.store.delete_entry(eid, r["bib"])
                    self.store.update_registration(sub_id, bib=None)
            what = {"approved": "Заявка подтверждена", "rejected": "Заявка отклонена", "pending": "Заявка возвращена"}
            self.store.audit(who, eid, what.get(upd.get("status"), "Заявка изменена"),
                             f"{r['last_name']} {r['first_name']} · {r['distance']}")
            return ok({"reg": self.store.get_registration(sub_id)})
        if action == "heats":
            try:
                out = self.generate_heats(ev, data.get("lanes") or ev.get("reg_lanes") or 8)
            except ValueError as e:
                return err(str(e))
            if data.get("lanes"):
                self.store.update_event(eid, {"reg_lanes": data["lanes"]})
            self.store.audit(who, eid, "Сформированы забеги", f"{len(out['heats'])} забегов, {out['entries']} участников")
            try:
                self.save_file(eid, f"Стартовый список {now_local():%Y-%m-%d %H-%M}.csv",
                               self._startlist_csv(self.store.get_event(eid)).encode("utf-8"), "startlist", who, "Для судей")
            except Exception:
                log.exception("стартовый список в папку «Для судей»")
            return ok(out)
        if action == "entry":
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
                if r.get("bib") and any(e["bib"] == r["bib"] for e in self.store.entries_rows(eid)):
                    return err("участник уже в стартовом списке")
                rows = self.store.entries_rows(eid)
                bib = str(max([int(e["bib"]) for e in rows if e["bib"].isdigit()] + [0]) + 1)
                if lane is None and wave:
                    taken = {e["lane"] for e in rows if e["wave"] == wave}
                    lane = next((x for x in self.lane_order(int(ev.get("reg_lanes") or 8)) if x not in taken), None)
                self.store.add_entry(eid, {"bib": bib, "chip": "#" + bib, "wave": wave,
                                           "name": f"{r['last_name']} {r['first_name']}", "birth_year": r["birth_date"][:4],
                                           "team": r["team"], "category": r["category"], "lane": lane,
                                           "coach": r["coach"], "seed": r["best"], "reg_id": r["id"], "sex": r["sex"]})
                self.store.update_registration(r["id"], bib=bib)
                self.store.audit(who, eid, "Участник добавлен в забег", f"№{bib} {r['last_name']} → {wave or 'без забега'}")
                return ok({"bib": bib})
            bib = str(data.get("bib") or "").strip()
            row = next((e for e in self.store.entries_rows(eid) if e["bib"] == bib), None)
            if not row:
                return err("нет участника с таким номером", 404)
            if row["wave"] and (self.store.get_wave(eid, row["wave"]) or {}).get("start_time") and "wave" in data \
                    and wave != row["wave"]:
                return err("забег участника уже стартовал")
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
        if action == "check":
            since = None if data.get("stop") else fmt_db(now_local())
            self.store.set_event_field(eid, check_since=since)
            self.store.audit(who, eid, "Проверка чипов: " + ("начата" if since else "остановлена"))
            return ok(self.check_view(self.store.get_event(eid)))
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
    def reg_distances(ev: dict) -> list:
        return [d.strip()[:20] for d in (ev.get("reg_distances") or "").splitlines() if d.strip()]

    def consent_text(self, ev: dict) -> str:
        if ev.get("reg_consent"):
            return ev["reg_consent"]
        op = ev.get("organizer") or "организатору соревнований"
        return (f"Я даю согласие {op} на обработку персональных данных участника (фамилия, имя, отчество, "
                f"дата рождения, пол, команда, тренер, спортивный результат, контактные данные) с целью "
                f"регистрации, проведения соревнований «{ev['name']}» и подготовки стартовых и итоговых "
                f"протоколов, включая размещение в протоколах фамилии, имени, года рождения, команды и результата. "
                f"Согласие действует до достижения целей обработки и может быть отозвано письменным заявлением. "
                f"Если участнику нет 18 лет, согласие даёт его родитель (законный представитель).")

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
                "deadline": ev.get("reg_deadline"), "open": open_, "reason": why,
                "distances": self.reg_distances(ev), "info": ev.get("reg_info") or "",
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

    def check_person(self, ev: dict, d: dict, team_mode: bool = False) -> tuple:
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
        allowed = self.reg_distances(ev)
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
                    bad.append(c(x.get("distance") if isinstance(x, dict) else x, 20))
                    continue
            if name and name not in [p[0] for p in picks]:
                picks.append((name, best))
        if not picks:
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
        clean = {"last_name": last, "first_name": first, "middle_name": middle or None,
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
                "status": status, "note": note, "consent_at": fmt_db(now_local()), "consent_hash": chash}))
        return ids, dup

    def _consent_hash(self, ev: dict) -> str:
        import hashlib
        return hashlib.sha256(self.consent_text(ev).encode("utf-8")).hexdigest()[:16]

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
                 ("representative", "Родитель / представитель (до 18 лет)", ("родит", "представ")))

    def team_template(self, ev: dict) -> bytes:
        dists = self.reg_distances(ev) or ["60 м"]
        title = f"Заявка команды — {ev['name']}" + (f", {'.'.join(reversed(ev['date'].split('-')))}" if ev.get("date") else "")
        rows = [[title], ["Одна строка — один участник на одну дистанцию. Несколько дистанций — несколько строк. "
                          "Обязательны поля со звёздочкой. Команду и тренера можно не заполнять, если они указаны в форме."],
                [h for _, h, _ in self.TEAM_COLS]]
        rows += [[""] * len(self.TEAM_COLS) for _ in range(60)]
        return xlsx_build(
            sheets=[("Заявка", rows), ("Справочник", [["Дистанции"]] + [[d] for d in dists] + [[""], ["Пол"], ["М"], ["Ж"]])],
            widths=[18, 14, 16, 15, 10, 12, 14, 24, 22, 30], header_row=3, title_row=1,
            validations=[("E4:E63", "\"М,Ж\""), ("F4:F63", f"Справочник!$A$2:$A${len(dists) + 1}")],
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
        for r in rows:
            d = {**r, "team": self._clean(r.get("team"), 80) or team, "coach": self._clean(r.get("coach"), 80) or coach,
                 "contact": data.get("contact"), "distances": [{"distance": r.get("distance"), "best": r.get("best")}]}
            errs, clean, picks = self.check_person(ev, d, team_mode=True)
            res.append({"row": r.get("_row"), "name": f"{clean['last_name']} {clean['first_name']}".strip(),
                        "birth_date": clean["birth_date"], "sex": clean["sex"], "category": clean["category"] or "",
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

    @staticmethod
    def _strip_check(chk: dict) -> dict:
        return {**chk, "rows": [{k: v for k, v in x.items() if not k.startswith("_")} for x in chk["rows"]]}

    def regs_view(self, ev: dict) -> dict:
        regs = self.store.registrations(ev["id"])
        bibs = {r["reg_id"]: r for r in self.store.entries_rows(ev["id"]) if r.get("reg_id")}
        seen: dict = {}
        for r in regs:
            key = (r["last_name"].lower(), r["first_name"].lower(), r["birth_date"], r["distance"])
            r["dup_of"] = seen.get(key) if r["status"] != "rejected" else None
            if r["status"] != "rejected":
                seen.setdefault(key, r["id"])
            e = bibs.get(r["id"])
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

    def generate_heats(self, ev: dict, lanes: int) -> dict:
        """Подтверждённые заявки → забеги по категории и дистанции, посев по лучшему результату:
        сильнейшие — в последнем забеге группы, внутри забега — на центральных дорожках."""
        eid = ev["id"]
        if any(w.get("start_time") for w in self.store.waves(eid)):
            raise ValueError("уже был старт забега — пересобрать нельзя, переносите участников вручную")
        lanes = max(1, min(int(lanes or 8), 50))
        regs = [r for r in self.store.registrations(eid) if r["status"] == "approved"]
        if not regs:
            raise ValueError("нет подтверждённых заявок")
        dist_order = {d: i for i, d in enumerate(self.reg_distances(ev))}
        cat_order = {r["name"]: i for i, r in enumerate(self.parse_rules(ev.get("reg_rules") or ""))}
        groups: dict = {}
        for r in regs:
            groups.setdefault((r["distance"], r.get("category") or ""), []).append(r)
        old = {e["reg_id"]: e for e in self.store.entries_rows(eid) if e.get("reg_id")}
        used = {e["bib"] for e in old.values()}
        nxt = [max([int(b) for b in used if b.isdigit()] + [0]) + 1]

        def bib_for(r):
            e = old.get(r["id"])
            if e:
                return e["bib"], e["chip"]
            b = str(nxt[0])
            nxt[0] += 1
            return b, "#" + b

        heats, rows, n = [], [], 0
        for key in sorted(groups, key=lambda k: (dist_order.get(k[0], 99), k[0], cat_order.get(k[1], 99), k[1])):
            lst = sorted(groups[key], key=lambda r: (r["best_sec"] is None, r["best_sec"] or 0, r["id"]))
            k = math.ceil(len(lst) / lanes)
            base, extra = divmod(len(lst), k)
            sizes = [base + (1 if i >= k - extra else 0) for i in range(k)]   # полные забеги — последние
            chunks, pos = [], 0
            for size in reversed(sizes):            # от сильнейших
                chunks.append(lst[pos:pos + size])
                pos += size
            chunks.reverse()                        # слабые забеги — первыми, сильнейший — последний
            for chunk in chunks:
                n += 1
                name = f"Забег {n}"
                heats.append({"name": name, "distance": key[0], "category": key[1], "count": len(chunk)})
                order = self.lane_order(lanes)
                for i, r in enumerate(chunk):
                    bib, chip = bib_for(r)
                    full = " ".join(x for x in (r["last_name"], r["first_name"]) if x)
                    rows.append({"bib": bib, "chip": chip, "wave": name, "name": full, "birth_year": r["birth_date"][:4],
                                 "team": r.get("team"), "category": r.get("category"), "lane": order[i],
                                 "coach": r.get("coach"), "seed": r.get("best"), "reg_id": r["id"], "sex": r.get("sex")})
        self.store.con.execute("BEGIN")
        try:
            self.store.con.execute("DELETE FROM waves WHERE event_id = ?", (eid,))
            self.store.con.execute("COMMIT")
        except Exception:
            self.store.con.execute("ROLLBACK")
            raise
        self.store.set_entries(eid, rows)
        for h in heats:
            self.store.update_wave(eid, h["name"], category=h["category"] or None, distance=h["distance"])
        for r in rows:
            self.store.update_registration(r["reg_id"], bib=r["bib"])
        return {"heats": heats, "entries": len(rows)}

    def startlist(self, ev: dict) -> dict:
        rows = self.store.entries_rows(ev["id"])
        heats = []
        for w in self.store.waves(ev["id"]):
            lst = sorted([r for r in rows if r["wave"] == w["name"]], key=lambda r: (r["lane"] is None, r["lane"] or 0,
                                                                                      int(r["bib"]) if r["bib"].isdigit() else 0))
            heats.append({"name": w["name"], "category": w.get("category") or "", "distance": w.get("distance") or "",
                          "start_time": w.get("start_time"), "state": "finished" if w.get("finished_at") else
                          ("running" if w.get("start_time") else "planned"), "entries": lst})
        loose = [r for r in rows if not r["wave"]]
        return {"event": self._event_view(ev), "heats": heats, "no_heat": loose}

    # ---- «Оборудование»: сервер, службы, VPN, кто подключён
    PAGES = {"/": "Админка", "/judge": "Судья", "/announcer": "Диктор", "/board": "Табло", "/protocol": "Протокол"}

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
        st = self.status()
        out["readers"] = st["sources"]
        out["wiclax"] = st["wiclax_clients"]
        out["clock_warn_sec"] = float(self.cfg["clock_warn_sec"])
        return out

    # ---- обмен с Wiclax: импорт файла соревнования .clax и экспорт стартового списка
    @staticmethod
    def parse_clax(blob: bytes) -> dict:
        """Файл соревнования Wiclax (.clax, XML): участники, дистанции (Parcours), чипы из прохождений, старты."""
        import xml.etree.ElementTree as ET
        root = ET.fromstring(blob)
        if root.tag != "Epreuve":
            raise ValueError("это не файл соревнования Wiclax (.clax)")
        dist = {p.get("nom"): p.get("distance") for p in root.iter("Pcs") if p.get("nom")}
        chip_of: dict = {}
        for el in root.iter("PucesDos"):          # таблица «чип.номер» — основной источник
            for p in el:
                chip, _, bib = (p.text or "").strip().rpartition(".")
                if chip and bib:
                    chip_of.setdefault(bib, chip.upper())
        for tag in ("Pass_Arr", "Pass_Ptg1", "Pass_Ptg2", "Pass_Ptg3", "Pass_Ptg4"):
            for el in root.iter(tag):
                for p in el:
                    f = (p.text or "").split("*")
                    if len(f) >= 5 and f[1] and f[4]:
                        chip_of.setdefault(f[1], f[4].upper())
        starts = {}
        for h in root.iter("H"):
            m = re.search(r"Parcours = '(.+)'", h.get("filtre") or "")
            if m and h.get("sdateheure") and h.get("actif") != "0":
                starts[m.group(1)] = h.get("sdateheure")
        entries = []
        for e in root.iter("E"):
            bib = (e.get("d") or "").strip()
            if not bib:
                continue
            parts = (e.get("n") or "").split()
            name = " ".join(w[:1].upper() + w[1:].lower() for w in parts[:2])
            pc = e.get("p") or ""
            entries.append({"bib": bib, "name": name, "full_name": " ".join(parts), "birth_year": e.get("a") or "",
                            "sex": {"M": "М", "F": "Ж"}.get(e.get("x") or "", ""), "team": e.get("c") or "",
                            "parcours": pc, "chip": chip_of.get(bib, "")})
        return {"name": root.get("nom") or "", "dates": root.get("dates") or "", "parcours": dist,
                "entries": entries, "starts": starts, "chips": len(chip_of)}

    @staticmethod
    def split_parcours(name: str, meters: Optional[str]) -> tuple:
        """«4000 м Женщины» → («4000 м», «Женщины»)."""
        m = re.match(r"\s*(\d+(?:[.,]\d+)?\s*(?:м|км|m|km)\b\.?)\s*(.*)", name or "", re.I)
        if m:
            return m.group(1).strip(), m.group(2).strip() or ""
        return (f"{meters} м" if meters and meters != "0" else ""), (name or "").strip()

    def import_clax(self, ev: dict, blob: bytes, with_names: bool = True) -> dict:
        data = self.parse_clax(blob)
        rows, seen = [], set()
        for e in data["entries"]:
            chip = e["chip"] if e["chip"] and e["chip"] not in seen else "#" + e["bib"]
            seen.add(chip)
            d, c = self.split_parcours(e["parcours"], data["parcours"].get(e["parcours"]))
            rows.append({"bib": e["bib"][:12], "chip": chip, "wave": (e["parcours"] or None) and e["parcours"][:40],
                         "name": e["name"][:80] if with_names else None, "birth_year": e["birth_year"][:4] or None,
                         "team": e["team"][:80] or None, "category": c[:40] or None, "sex": e["sex"] or None})
        self.store.set_entries(ev["id"], rows)
        for pc, meters in data["parcours"].items():
            if self.store.get_wave(ev["id"], pc[:40]):
                d, c = self.split_parcours(pc, meters)
                self.store.update_wave(ev["id"], pc[:40], distance=d or None, category=c or None)
        return {"entries": len(rows), "with_chip": sum(1 for r in rows if not r["chip"].startswith("#")),
                "parcours": len(data["parcours"]), "source": data["name"], "dates": data["dates"]}

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

    def _wiclax_csv(self, ev: dict):
        """Стартовый список для импорта в Wiclax: номер, фамилия, имя, пол (M/F), год, клуб, дистанция (Parcours), чип."""
        rows = self.store.entries_rows(ev["id"])
        waves = {w["name"]: w for w in self.store.waves(ev["id"])}
        regs = {r["id"]: r for r in self.store.registrations(ev["id"])}
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["Номер", "Фамилия", "Имя", "Отчество", "Пол", "Год рождения", "Дата рождения", "Клуб", "Дистанция",
                    "Категория", "Тренер", "Чип"])
        for r in rows:
            rg = regs.get(r.get("reg_id")) or {}
            wv = waves.get(r["wave"] or "", {})
            if rg:
                last, first, mid = rg["last_name"], rg["first_name"], rg.get("middle_name") or ""
                sex = rg["sex"]
            else:
                parts = (r["name"] or "").split()
                last, first, mid = (parts + ["", "", ""])[:3]
                sex = r.get("sex") or ""
            dist = wv.get("distance") or ""
            cat = r["category"] or wv.get("category") or ""
            parcours = " ".join(x for x in (dist, cat) if x) or (r["wave"] or "")
            w.writerow([r["bib"], last, first, mid, {"М": "M", "Ж": "F"}.get(sex, ""), r["birth_year"] or "",
                        ".".join(reversed(rg["birth_date"].split("-"))) if rg.get("birth_date") else "",
                        r["team"] or "", parcours, cat, r.get("coach") or "", "" if r["chip"].startswith("#") else r["chip"]])
        from urllib.parse import quote
        return 200, "text/csv; charset=utf-8", "\ufeff" + buf.getvalue(), {
            "Content-Disposition": f"attachment; filename=\"wiclax.csv\"; filename*=UTF-8''{quote('Wiclax ' + ev['name'] + '.csv')}"}

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
        return {"version": VERSION, "pending": os.path.exists(os.path.join(d, "incoming.zip")),
                "helper": os.path.isdir(d), "status": st, "log": log_tail}

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
        sha = hashlib.sha256(body).hexdigest()
        part = os.path.join(self.update_dir, "incoming.part")
        with open(part, "wb") as fh:
            fh.write(body)
        os.replace(part, os.path.join(self.update_dir, "incoming.zip"))   # появление файла запускает установку
        self.store.audit(actor, None, "Обновление сервера загружено", f"{VERSION} → {newv}, sha256 {sha[:16]}…")
        return 200, {"ok": True, "from": VERSION, "to": newv, "sha256": sha}

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
        return 200, {"current": VERSION, "latest": latest, "sha": head["sha"], "date": head["date"],
                     "newer": latest != VERSION, "changes": changes}

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

    @staticmethod
    def _clax_module():
        import importlib
        here = os.path.dirname(os.path.abspath(__file__))
        for d in (os.path.join(here, "tools"), os.path.join(os.path.dirname(here), "tools")):
            if os.path.isfile(os.path.join(d, "make_clax.py")) and d not in sys.path:
                sys.path.insert(0, d)
        return importlib.import_module("make_clax")

    def clax_spec(self, ev: dict) -> dict:
        """Описание соревнования для Wiclax: дистанции (по забегам/категориям), старты, участники, чипы."""
        rows = self.store.entries_rows(ev["id"])
        waves = {w["name"]: w for w in self.store.waves(ev["id"])}
        regs = {r["id"]: r for r in self.store.registrations(ev["id"])}
        parcours, entries = {}, []
        for r in rows:
            rg = regs.get(r.get("reg_id")) or {}
            wv = waves.get(r["wave"] or "", {})
            if rg:
                last, first, mid = rg["last_name"], rg["first_name"], rg.get("middle_name") or ""
                sex = rg["sex"]
            else:
                parts = (r["name"] or "").split()
                last, first, mid = (parts + ["", "", ""])[:3]
                sex = r.get("sex") or ""
            dist = wv.get("distance") or ""
            cat = r["category"] or wv.get("category") or ""
            pc = (r["wave"] or "") if len(waves) > 1 else (" ".join(x for x in (dist, cat) if x) or (r["wave"] or ""))
            pc = (pc or "Общий").replace("'", "’")
            if pc not in parcours:
                m = re.search(r"(\d+(?:[.,]\d+)?)\s*(км|km|м|m)\b", dist or pc, re.I)
                meters = 0
                if m:
                    meters = float(m.group(1).replace(",", ".")) * (1000 if m.group(2).lower() in ("км", "km") else 1)
                start = None
                if wv.get("start_time"):
                    start = parse_db(wv["start_time"]).strftime("%H:%M:%S")
                elif ev.get("start_clock"):
                    start = str(ev["start_clock"])[:8]
                parcours[pc] = {"name": pc, "distance": int(meters), "start": start}
            entries.append({"bib": r["bib"], "name": " ".join(x for x in (last.upper(), first.upper(), mid) if x),
                            "club": r["team"] or "", "sex": {"М": "M", "Ж": "F"}.get(sex, sex),
                            "birth": rg.get("birth_date") or None, "year": r["birth_year"] or "",
                            "parcours": pc, "chip": "" if (r["chip"] or "").startswith("#") else (r["chip"] or "")})
        return {"name": ev["name"], "date": ev.get("date") or now_local().strftime("%Y-%m-%d"),
                "organizer": ev.get("organizer") or "", "parcours": list(parcours.values()), "entries": entries}

    def _wiclax_clax(self, ev: dict):
        from urllib.parse import quote
        spec = self.clax_spec(ev)
        if not spec["parcours"]:
            spec["parcours"] = [{"name": "Общий", "distance": 0}]
        try:
            data = self._clax_module().build_clax(spec)
        except ValueError as e:
            return 400, "application/json; charset=utf-8", json.dumps({"error": f"не получилось собрать .clax: {e}"},
                                                                       ensure_ascii=False), None
        fname = re.sub(r'[\\/:*?"<>|]+', " ", ev["name"]) + ".clax"
        return 200, "application/octet-stream", data, {
            "Content-Disposition": f"attachment; filename=\"event.clax\"; filename*=UTF-8''{quote(fname)}"}

    def _template_response(self, ev: dict):
        from urllib.parse import quote
        fname = re.sub(r'[\\/:*?"<>|]+', " ", f"Заявка команды — {ev['name']}.xlsx")
        return 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", self.team_template(ev), {
            "Content-Disposition": f"attachment; filename=\"zayavka.xlsx\"; filename*=UTF-8''{quote(fname)}"}

    def _regs_csv(self, ev: dict):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["№ заявки", "Статус", "Фамилия", "Имя", "Отчество", "Дата рождения", "Пол", "Категория",
                    "Дистанция", "Лучший результат", "Команда", "Тренер", "Представитель", "Контакт", "Нагр. №",
                    "Подана"])
        st = {"pending": "на рассмотрении", "approved": "подтверждена", "rejected": "отклонена"}
        for r in self.store.registrations(ev["id"]):
            w.writerow([r["id"], st.get(r["status"], r["status"]), r["last_name"], r["first_name"], r["middle_name"] or "",
                        r["birth_date"], r["sex"], r["category"] or "", r["distance"], r["best"] or "", r["team"] or "",
                        r["coach"] or "", r["representative"] or "", r["contact"] or "", r["bib"] or "", r["created_at"]])
        from urllib.parse import quote
        return 200, "text/csv; charset=utf-8", "\ufeff" + buf.getvalue(), {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote('Заявки ' + ev['name'] + '.csv')}"}

    def _results_csv(self, ev: dict):
        r = self.compute(ev)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        devs = [d for d in r["devices"] if d != ev.get("finish_device")]
        w.writerow(["Дистанция", "Категория", "Место общее", "Забег", "Место в забеге", "Номер", "ФИО", "Год",
                    "Команда", "Результат", "Чип"] + devs + ["Примечание"])
        for x in sorted(r["finished"], key=lambda x: (x["distance"], x["category"], x["place_overall"])):
            w.writerow([x["distance"], x["category"], x["place_overall"], x["wave"], x["place"], x["bib"], x["name"],
                        x["birth_year"], x["team"], x["result"], x["chip"]]
                       + [x["splits"].get(d, "") for d in devs] + ["ручной хронометраж" if x["manual"] else ""])
        for x in r["on_course"]:
            w.writerow([x["distance"], x["category"], "", x["wave"], "", x["bib"], x["name"], x["birth_year"], x["team"],
                        "не финишировал", x["chip"]] + [x["splits"].get(d, "") for d in devs] + [""])
        for x in r["not_seen"]:
            w.writerow([x["distance"], x["category"], "", x["wave"], "", x["bib"], x["name"], x["birth_year"], x["team"],
                        "не стартовал", x["chip"]] + [""] * len(devs) + [""])
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

    def _ui_file(self, name: str) -> Optional[str]:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    # ---- приём по сети
    async def _read_stream(self, src: SourceState, reader: asyncio.StreamReader) -> None:
        splitter = LineSplitter()
        while True:
            data = await reader.read(65536)
            if not data:
                return
            for line in splitter.feed(data):
                self.handle_line(src, line)

    async def _ingest_conn(self, src: SourceState, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        src.peer = f"{peer[0]}:{peer[1]}" if peer else "?"
        src.connected += 1
        set_keepalive(writer.get_extra_info("socket"))
        log.info("[%s] ридер подключился: %s", src.id, src.peer)
        try:
            await self._read_stream(src, reader)
        except (ConnectionError, asyncio.IncompleteReadError, OSError) as e:
            src.last_error = str(e)
        finally:
            src.connected -= 1
            log.info("[%s] ридер отключился: %s", src.id, src.peer)
            try:
                writer.close()
            except Exception:
                pass

    async def _run_connect(self, src: SourceState) -> None:
        host, port = src.cfg["host"], int(src.cfg["port"])
        backoff = 1.0
        while not self.stopping.is_set():
            writer = None
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10)
                set_keepalive(writer.get_extra_info("socket"))
                src.connected = 1
                src.peer = f"{host}:{port}"
                src.last_error = None
                backoff = 1.0
                log.info("[%s] подключились к ридеру %s:%s", src.id, host, port)
                for cmd in src.cfg["init_commands"]:
                    writer.write(str(cmd).encode("utf-8"))
                await writer.drain()
                await self._read_stream(src, reader)
                src.last_error = "ридер закрыл соединение"
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
                src.last_error = f"{type(e).__name__}: {e}"
            finally:
                if src.connected:
                    log.info("[%s] соединение с ридером потеряно (%s)", src.id, src.last_error)
                src.connected = 0
                if writer is not None:
                    try:
                        writer.close()
                    except Exception:
                        pass
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 15.0)

    # ---- ридеры, заведённые через браузер (вкладка «Оборудование»)
    READER_PARSERS = ("ipico", "auto", "wiclax", "sim")
    _HOST_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$")

    def reader_src_cfg(self, r: dict) -> dict:
        over = {"id": r["id"], "name": r.get("name") or "", "mode": "connect", "host": r["host"],
                "port": int(r["port"]), "parser": r.get("parser") or "ipico", "device": r["device"]}
        if over["parser"] in ("ipico", "sim"):
            over.update(chip_strip_leading_zeros=True, chip_lower=True)   # 058003a9f837 → 58003a9f837, как в Wiclax
        if over["parser"] == "sim":
            over["parser"] = "auto"
        return _merge(SOURCE_DEFAULTS, over)

    def check_reader(self, d: dict) -> tuple:
        """Проверка полей ридера из формы. Возвращает (чистые данные, ошибка)."""
        rid = str(d.get("id") or "").strip()
        host = str(d.get("host") or "").strip()
        device = str(d.get("device") or "").strip().upper() or rid.upper()
        parser = str(d.get("parser") or "ipico").strip().lower()
        try:
            port = int(d.get("port") or 10000)
        except (TypeError, ValueError):
            return None, "порт — число"
        if not VALID_ID.match(rid):
            return None, "название ридера: латиница, цифры, _ или - (до 32 символов), например IPICO1"
        static = {s["id"] for s in self.cfg["sources"]}
        if rid in static:
            return None, f"{rid} уже описан в файле настроек сервера — выберите другое название"
        if parser == "sim":       # виртуальный ридер-симулятор: никуда не подключается
            host, port = "simulator", 0
        bad_ip = re.fullmatch(r"[\d.]+", host) and not (
            re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host) and all(int(x) <= 255 for x in host.split(".")))
        if not self._HOST_RE.match(host) or bad_ip:
            return None, "адрес ридера: например 10.19.1.61"
        if not 1 <= port <= 65535 and parser != "sim":
            return None, "порт от 1 до 65535 (у IPICO обычно 10000)"
        if not VALID_ID.match(device):
            return None, "точка: латиница, цифры, _ или - (например FINISH, KM5)"
        if parser not in self.READER_PARSERS:
            return None, "формат: ipico, auto или wiclax"
        return {"id": rid, "name": str(d.get("name") or "").strip()[:60], "box": str(d.get("box") or "").strip()[:40],
                "host": host, "port": port, "device": device, "parser": parser,
                "enabled": bool(d.get("enabled"))}, None

    def start_db_reader(self, r: dict) -> None:
        self.stop_db_reader(r["id"])
        cfg = self.reader_src_cfg(r)
        src = SourceState(cfg, int(self.cfg["raw_memory_lines"]))
        self.sources[r["id"]] = src
        self.db_reader_parsers[r["id"]] = cfg["parser"]
        if (r.get("parser") or "") == "sim":
            src.connected = 1
            src.peer = "симулятор"
            self.reader_tasks[r["id"]] = asyncio.ensure_future(self.stopping.wait())
            log.info("[%s] виртуальный ридер-симулятор включён", r["id"])
            return
        self.reader_tasks[r["id"]] = asyncio.ensure_future(self._run_connect(src))
        log.info("[%s] ридер из браузера: подключаюсь к %s:%s", r["id"], r["host"], r["port"])

    # ---- симулятор гонки: «прогоняет» участников соревнования через виртуальный ридер
    sim_jobs: dict = {}

    async def _simulate(self, rid: str, chips: list, minutes: float, reads_per: int) -> None:
        job = self.sim_jobs[rid]
        random.shuffle(chips)
        total = len(chips)
        # первые финишируют плотнее, хвост растянут — похоже на настоящий финиш
        offs = sorted(minutes * 60 * (random.random() ** 1.6) for _ in range(total))
        t0 = time.monotonic()
        try:
            for chip, off in zip(chips, offs):
                delay = off - (time.monotonic() - t0)
                if delay > 0:
                    await asyncio.sleep(delay)
                src = self.sources.get(rid)
                if src is None or job.get("stop"):
                    break
                base = now_local()
                for k in range(reads_per):            # ридер видит чип несколько раз за проход
                    ts = base + dt.timedelta(milliseconds=120 * k + random.randint(0, 60))
                    self.handle_parsed(src, f"SIM {chip} {fmt_db(ts)}", ParsedRead(chip=chip, ts=ts, antenna="1"), ts)
                job["sent"] += 1
        finally:
            job["running"] = False
            log.info("[%s] симуляция закончена: %s из %s", rid, job["sent"], total)

    def sim_start(self, rid: str, d: dict, actor: str) -> tuple:
        r = self.store.get_reader(rid)
        if r is None or r.get("parser") != "sim":
            return 400, {"error": "симуляция — только для виртуального ридера (формат «Симулятор»)"}
        if rid not in self.reader_tasks:
            return 400, {"error": "сначала нажмите «Подключить» у симулятора"}
        if self.sim_jobs.get(rid, {}).get("running"):
            return 409, {"error": "симуляция уже идёт"}
        chips = []
        eid = d.get("event_id")
        if eid:
            try:
                chips = [c for c in self.store.entries(int(eid)) if c and not c.startswith("#")]
            except (TypeError, ValueError):
                chips = []
        try:
            n = max(1, min(int(d.get("count") or 0), 3000))
        except (TypeError, ValueError):
            n = 0
        from_event = bool(chips)
        if not chips:
            n = n or 30
            chips = ["58003A%05X" % random.randint(0, 0xFFFFF) for _ in range(n)]
        elif d.get("count"):
            chips = chips[:n]
        try:
            minutes = max(0.2, min(float(d.get("minutes") or 3), 180))
        except (TypeError, ValueError):
            minutes = 3.0
        self.sim_jobs[rid] = {"running": True, "sent": 0, "total": len(chips), "stop": False,
                              "minutes": minutes, "event_id": eid, "started": fmt_db(now_local())}
        asyncio.ensure_future(self._simulate(rid, list(chips), minutes, 4))
        self.store.audit(actor, int(eid) if eid else None, "Симуляция гонки",
                         f"{rid}: {len(chips)} участников за {minutes:g} мин")
        return 200, {"ok": True, "total": len(chips), "from_event": from_event}

    def stop_db_reader(self, rid: str) -> None:
        t = self.reader_tasks.pop(rid, None)
        if t is not None:
            t.cancel()
            log.info("[%s] ридер отключён из браузера", rid)
        if rid not in {s["id"] for s in self.cfg["sources"]}:
            self.sources.pop(rid, None)

    def parse_reader_list(self, text: str) -> tuple:
        """Список из Excel/блокнота: «название; адрес; порт; точка; ящик» — по строке на ридер."""
        rows, errors = [], []
        for n, ln in enumerate(text.splitlines(), 1):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = [p.strip() for p in re.split(r"[;\t,]", ln)]
            if n == 1 and not re.search(r"\d+\.\d+\.\d+\.\d+", ln) and len(parts) > 1:
                continue    # строка заголовков
            parts += [""] * 5
            d = {"id": parts[0], "host": parts[1], "port": parts[2] or 10000, "device": parts[3] or "FINISH",
                 "box": parts[4], "name": parts[4], "parser": "ipico"}
            clean, e = self.check_reader(d)
            if e:
                errors.append(f"строка {n}: {e}")
            else:
                rows.append(clean)
        return rows, errors

    _scan_lock: Optional[asyncio.Lock] = None

    async def scan_readers(self, d: dict, actor: str) -> tuple:
        """«Найти ридеры»: проверяем подсеть ящика (x.x.x.1–254), где открыт порт ридера."""
        net = str(d.get("subnet") or "").strip()
        m = re.fullmatch(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\.(?:0|x|\*)?(?:/24)?)?", net)
        if not m or any(int(x) > 255 for x in m.groups()):
            return 400, {"error": "сеть ящика — например 10.19.1"}
        a, b, c = (int(x) for x in m.groups())
        if not (a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)):
            return 400, {"error": "искать можно только во внутренних сетях (10.x, 192.168.x, 172.16–31.x)"}
        try:
            port = int(d.get("port") or 10000)
        except (TypeError, ValueError):
            port = 10000
        if not 1 <= port <= 65535:
            return 400, {"error": "порт от 1 до 65535"}
        if self._scan_lock is None:
            self._scan_lock = asyncio.Lock()
        if self._scan_lock.locked():
            return 409, {"error": "поиск уже идёт — подождите несколько секунд"}
        base = f"{a}.{b}.{c}"
        known = {(r["host"], int(r["port"])): r["id"] for r in self.store.readers()}
        sem = asyncio.Semaphore(128)
        found = []

        async def probe(i: int) -> None:
            host = f"{base}.{i}"
            async with sem:
                try:
                    _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.5)
                except (OSError, asyncio.TimeoutError):
                    return
                try:
                    w.close()
                except Exception:
                    pass
                found.append({"host": host, "port": port, "known": known.get((host, port))})

        async with self._scan_lock:
            await asyncio.gather(*(probe(i) for i in range(1, 255)))
        found.sort(key=lambda x: int(x["host"].rsplit(".", 1)[1]))
        self.store.audit(actor, None, "Поиск ридеров", f"{base}.0/24 порт {port}: найдено {len(found)}")
        return 200, {"subnet": base, "port": port, "found": found}

    def readers_view(self) -> dict:
        st = {s["id"]: s for s in self.status()["sources"]}
        db = []
        for r in self.store.readers():
            live = st.get(r["id"]) if r["id"] in self.reader_tasks else None
            wp = int(r["wiclax_port"]) if r.get("wiclax_port") else None
            db.append({**r, "enabled": bool(r["enabled"]), "live": live, "sim": self.sim_jobs.get(r["id"]), "wiclax": {
                "port": wp, "listening": wp in self.wiclax_port_servers if wp else False,
                "error": self.wiclax_port_errors.get(wp) if wp else None,
                "clients": sum(1 for c in self.wiclax_clients if wp and c.port == wp)}})
        static_ids = {s["id"] for s in self.cfg["sources"]}
        static = [st[i] for i in st if i in static_ids]
        wc = self.cfg["wiclax"]
        ports = []
        for wp in self.store.wiclax_ports():
            p = int(wp["port"])
            ports.append({**wp, "listening": p in self.wiclax_port_servers, "error": self.wiclax_port_errors.get(p),
                          "clients": sum(1 for c in self.wiclax_clients if c.port == p)})
        main_clients = sum(1 for c in self.wiclax_clients if c.port == int(wc["listen_port"]))
        return {"readers": db, "static": static, "wiclax_ports": ports,
                "wiclax_main": {"host": wc["listen_host"], "port": int(wc["listen_port"]), "clients": main_clients},
                "devices": sorted({r["device"] for r in db} | {s["device"] for s in static})}

    READER_PORT_MIN, READER_PORT_MAX = 9861, 9899

    def next_reader_port(self) -> Optional[int]:
        used = {int(r["wiclax_port"]) for r in self.store.readers() if r.get("wiclax_port")}
        used |= {int(w["port"]) for w in self.store.wiclax_ports()}
        for p in range(self.READER_PORT_MIN, self.READER_PORT_MAX + 1):
            if p not in used:
                return p
        return None

    def ensure_reader_port(self, rid: str) -> Optional[int]:
        r = self.store.get_reader(rid)
        if r is None:
            return None
        if not r.get("wiclax_port"):
            p = self.next_reader_port()
            self.store.set_reader_wiclax_port(rid, p)
            return p
        return int(r["wiclax_port"])

    async def _open_reader_port(self, rid: str, port: int) -> None:
        srv = self.wiclax_port_servers.pop(port, None)
        if srv is not None:
            srv.close()
        try:
            srv = await asyncio.start_server(
                lambda r, w, s={rid}, p=port: WiclaxClient(self, r, w, None, p, s).run(),
                self.cfg["wiclax"]["listen_host"], port)
            self.wiclax_port_servers[port] = srv
            self.wiclax_port_errors.pop(port, None)
            log.info("Wiclax: порт %s — личный порт ридера %s", port, rid)
        except OSError as e:
            self.wiclax_port_errors[port] = str(e)
            log.warning("Wiclax: порт %s (ридер %s) не открыт: %s", port, rid, e)

    def _refresh_reader_port(self, rid: str, old_port: Optional[int] = None) -> None:
        if old_port:
            self._close_wiclax_port(int(old_port))
        p = self.ensure_reader_port(rid)
        if p:
            asyncio.ensure_future(self._open_reader_port(rid, p))

    async def _open_wiclax_port(self, port: int, devices: str) -> None:
        srv = self.wiclax_port_servers.pop(port, None)
        if srv is not None:
            srv.close()
        devs = {d.strip().upper() for d in devices.split(",") if d.strip()}
        try:
            srv = await asyncio.start_server(
                lambda r, w, d=devs, p=port: WiclaxClient(self, r, w, d, p).run(),
                self.cfg["wiclax"]["listen_host"], port)
            self.wiclax_port_servers[port] = srv
            self.wiclax_port_errors.pop(port, None)
            log.info("Wiclax: порт %s — только точки %s", port, ", ".join(sorted(devs)))
        except OSError as e:
            self.wiclax_port_errors[port] = str(e)
            log.warning("Wiclax: порт %s не открыт: %s", port, e)

    def _close_wiclax_port(self, port: int) -> None:
        srv = self.wiclax_port_servers.pop(port, None)
        if srv is not None:
            srv.close()
        self.wiclax_port_errors.pop(port, None)
        for c in list(self.wiclax_clients):
            if c.port == port:
                try:
                    c.writer.close()
                except Exception:
                    pass

    def _reader_api(self, method: str, path: str, data: dict, actor: str):
        """Маршруты /api/readers и /api/wiclax-ports. None — путь не наш."""
        if path == "/api/readers" and method == "GET":
            return 200, self.readers_view()
        if path == "/api/readers" and method == "POST":
            clean, e = self.check_reader(data)
            if e:
                return 400, {"error": e}
            orig = str(data.get("orig_id") or "") or None
            if orig is None and self.store.get_reader(clean["id"]):
                return 400, {"error": f"ридер {clean['id']} уже есть — измените его или выберите другое название"}
            if orig and orig != clean["id"] and self.store.get_reader(clean["id"]):
                return 400, {"error": f"ридер {clean['id']} уже есть"}
            if orig:
                was = self.store.get_reader(orig)
                clean["enabled"] = bool(was and was["enabled"]) if "enabled" not in data else clean["enabled"]
                self.stop_db_reader(orig)
                self.db_reader_parsers.pop(orig, None)
            prev = self.store.get_reader(orig or clean["id"])
            self.store.save_reader(clean, orig)
            prev_port = prev.get("wiclax_port") if prev else None
            if prev_port:
                self.store.set_reader_wiclax_port(clean["id"], int(prev_port))   # порт остаётся за ридером
            self._refresh_reader_port(clean["id"], prev_port if (orig and orig != clean["id"]) else None)
            self.db_reader_parsers[clean["id"]] = clean["parser"]
            if clean["enabled"]:
                self.start_db_reader(clean)
            self.store.audit(actor, None, "Ридер сохранён",
                             f"{clean['id']}: {clean['host']}:{clean['port']}, точка {clean['device']}")
            return 200, {"ok": True}
        if path == "/api/readers/bulk" and method == "POST":
            rows, errors = self.parse_reader_list(str(data.get("text") or ""))
            if errors:
                return 400, {"error": "; ".join(errors[:5]) + (f" и ещё {len(errors) - 5}" if len(errors) > 5 else "")}
            if not rows:
                return 400, {"error": "список пуст"}
            added = updated = 0
            for r in rows:
                was = self.store.get_reader(r["id"])
                r["enabled"] = bool(was and was["enabled"])
                self.store.save_reader(r)
                if not was:
                    self._refresh_reader_port(r["id"])
                self.db_reader_parsers[r["id"]] = r["parser"]
                if r["enabled"]:
                    self.start_db_reader(r)
                updated += 1 if was else 0
                added += 0 if was else 1
            self.store.audit(actor, None, "Список ридеров загружен", f"новых {added}, обновлено {updated}")
            return 200, {"added": added, "updated": updated}
        m = re.fullmatch(r"/api/readers/([A-Za-z0-9_-]{1,32})/(simulate|sim-stop|clear-reads)", path)
        if m and method == "POST":
            rid, act = m.group(1), m.group(2)
            if act == "simulate":
                return self.sim_start(rid, data, actor)
            if act == "sim-stop":
                if rid in self.sim_jobs:
                    self.sim_jobs[rid]["stop"] = True
                return 200, {"ok": True}
            r = self.store.get_reader(rid)
            if r is None or r.get("parser") != "sim":
                return 400, {"error": "стирать отметки можно только у симулятора"}
            n = self.store.delete_source_reads(rid)
            src = self.sources.get(rid)
            if src is not None:
                src.reads = src.lines = src.duplicates = 0
                src.tail.clear()
            self.store.audit(actor, None, "Отметки симулятора стёрты", f"{rid}: {n}")
            return 200, {"ok": True, "deleted": n}
        m = re.fullmatch(r"/api/readers/([A-Za-z0-9_-]{1,32})/point", path)
        if m and method == "POST":
            # перестановка ридера на другую точку — без переподключения, сразу для новых отметок
            rid = m.group(1)
            r = self.store.get_reader(rid)
            if r is None:
                return 404, {"error": "ридер не найден"}
            dev = str(data.get("device") or "").strip().upper()
            if not VALID_ID.match(dev):
                return 400, {"error": "точка: латиница, цифры, _ или - (например FINISH, KM5)"}
            self.store.set_reader_device(rid, dev)
            src = self.sources.get(rid)
            if src is not None and rid in self.reader_tasks:
                src.cfg["device"] = dev
            self.store.audit(actor, None, "Ридер переставлен", f"{rid}: точка {r['device']} → {dev}")
            return 200, {"ok": True, "device": dev}
        m = re.fullmatch(r"/api/readers/([A-Za-z0-9_-]{1,32})/(connect|disconnect|delete)", path)
        if m and method == "POST":
            rid, act = m.group(1), m.group(2)
            r = self.store.get_reader(rid)
            if r is None:
                return 404, {"error": "ридер не найден"}
            if act == "connect":
                self.store.set_reader_enabled(rid, True)
                self.start_db_reader(r)
                self.store.audit(actor, None, "Ридер подключён", f"{rid} ({r['host']}:{r['port']})")
            elif act == "disconnect":
                self.store.set_reader_enabled(rid, False)
                self.stop_db_reader(rid)
                self.store.audit(actor, None, "Ридер отключён", rid)
            else:
                self.stop_db_reader(rid)
                if r.get("wiclax_port"):
                    self._close_wiclax_port(int(r["wiclax_port"]))
                self.store.delete_reader(rid)
                self.db_reader_parsers.pop(rid, None)
                self.store.audit(actor, None, "Ридер удалён", rid)
            return 200, {"ok": True}
        if path == "/api/wiclax-ports" and method == "POST":
            try:
                port = int(data.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            devs = ",".join(sorted({d.strip().upper() for d in str(data.get("devices") or "").split(",") if d.strip()}))
            used = {int(self.cfg["wiclax"]["listen_port"]), int(self.cfg["web"]["listen_port"]),
                    int((self.cfg.get("public") or {}).get("listen_port") or 0)}
            used |= {int(s["listen_port"]) for s in self.cfg["sources"] if s["mode"] == "listen" and s["listen_port"]}
            if not 9855 <= port <= 9860:
                return 400, {"error": "порт точки для Wiclax — от 9855 до 9860 (9854 — общий; 9861–9899 — личные порты ридеров)"}
            if port in used:
                return 400, {"error": f"порт {port} уже занят"}
            if not devs or not all(VALID_ID.match(x) for x in devs.split(",")):
                return 400, {"error": "укажите точку (или несколько через запятую), например KM5"}
            self.store.save_wiclax_port(port, devs, str(data.get("name") or "").strip()[:40])
            asyncio.ensure_future(self._open_wiclax_port(port, devs))
            self.store.audit(actor, None, "Порт Wiclax", f"{port}: {devs}")
            return 200, {"ok": True}
        m = re.fullmatch(r"/api/wiclax-ports/(\d+)/delete", path)
        if m and method == "POST":
            port = int(m.group(1))
            self.store.delete_wiclax_port(port)
            self._close_wiclax_port(port)
            self.store.audit(actor, None, "Порт Wiclax удалён", str(port))
            return 200, {"ok": True}
        return None

    # ---- запуск
    async def start(self) -> None:
        for src in self.sources.values():
            mode = src.cfg["mode"]
            if mode == "listen":
                srv = await asyncio.start_server(
                    lambda r, w, s=src: self._ingest_conn(s, r, w),
                    src.cfg["listen_host"], int(src.cfg["listen_port"]))
                self.servers.append(srv)
                log.info("[%s] жду ридер на %s:%s", src.id, src.cfg["listen_host"], src.cfg["listen_port"])
            elif mode == "connect":
                self.tasks.append(asyncio.ensure_future(self._run_connect(src)))
                log.info("[%s] буду подключаться к %s:%s", src.id, src.cfg["host"], src.cfg["port"])
            else:
                log.info("[%s] приём по HTTP: POST /api/reads?source=%s", src.id, src.id)
        wc = self.cfg["wiclax"]
        srv = await asyncio.start_server(
            lambda r, w: WiclaxClient(self, r, w, self.wiclax_devices, int(wc["listen_port"])).run(),
            wc["listen_host"], int(wc["listen_port"]))
        self.servers.append(srv)
        log.info("Wiclax: подключайтесь к %s:%s", wc["listen_host"], wc["listen_port"])
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
        for r in self.store.readers():
            if r["enabled"]:
                self.start_db_reader(r)
        for wp in self.store.wiclax_ports():
            await self._open_wiclax_port(int(wp["port"]), wp["devices"])
        for r in self.store.readers():
            p = self.ensure_reader_port(r["id"])
            if p:
                await self._open_reader_port(r["id"], p)

    async def stop(self) -> None:
        self.stopping.set()
        for srv in self.servers:
            srv.close()
        for t in self.tasks:
            t.cancel()
        for t in self.reader_tasks.values():
            t.cancel()
        for srv in self.wiclax_port_servers.values():
            srv.close()
        for c in list(self.wiclax_clients):
            try:
                c.writer.close()
            except Exception:
                pass

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

    @staticmethod
    def _auth_user(headers: dict) -> str:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                return base64.b64decode(auth[6:].strip()).decode("utf-8").partition(":")[0] or "?"
            except Exception:
                return "?"
        return "-"

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
            if method == "POST" and path == "/api/reads":
                if not self._auth_ok(headers, allow_api_key=True):
                    await self._send(writer, 401, "application/json", '{"error":"unauthorized"}')
                    return
                await self._send(writer, *self._api_reads(qs, headers, body))
                return
            if not self._auth_ok(headers, allow_api_key=False):
                await self._send(writer, 401, "text/plain", "Нужен логин и пароль",
                                 extra={"WWW-Authenticate": 'Basic realm="timing-hub", charset="UTF-8"'})
                return
            self._note_client(writer, headers, path)
            if path.startswith("/api/") and path not in ("/api/status",):
                if method == "POST" and headers.get("x-requested-with") != "timing-hub":
                    await self._send(writer, 403, "text/plain", "нужен заголовок X-Requested-With")
                    return
                peer = writer.get_extra_info("peername")
                actor = f"{self._auth_user(headers)}@{peer[0] if peer else '?'}"
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
                            self.store.audit(actor, None, "Обновление с GitHub", f"коммит {sha[:7]}")
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
                code, ctype, data, extra = self._public_route(method, path, headers, body, peer[0] if peer else "?")
                await self._send(writer, code, ctype, data, extra=extra)
            elif method != "GET":
                await self._send(writer, 405, "text/plain", "метод не поддерживается")
            elif path in ("/", "/board", "/judge", "/announcer", "/protocol"):
                name = {"/": "ui.html", "/board": "board.html", "/judge": "judge.html",
                        "/announcer": "announcer.html", "/protocol": "protocol.html"}[path]
                page = self._ui_file(name)
                if page is None:
                    await self._send(writer, 200, "text/html; charset=utf-8", self._page_status())
                else:
                    await self._send(writer, 200, "text/html; charset=utf-8", page)
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
            elif path == "/raw":
                await self._send(writer, 200, "text/plain; charset=utf-8", self._raw_text(qs))
            elif path == "/export.csv":
                code, ctype, data = self._export_csv(qs)
                await self._send(writer, code, ctype, data,
                                 extra={"Content-Disposition": 'attachment; filename="reads.csv"'})
            else:
                await self._send(writer, 404, "text/plain", "нет такой страницы")
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ConnectionError, ValueError):
            pass
        except Exception:
            log.exception("HTTP: ошибка обработки запроса")
            try:
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

    def _public_route(self, method: str, path: str, headers: dict, body: bytes, client: str):
        J = "application/json; charset=utf-8"

        def js(obj, code=200):
            return code, J, json.dumps(obj, ensure_ascii=False), None

        if method == "GET" and path in ("/r", "/r/"):
            page = self._ui_file("reg.html")
            return 200, "text/html; charset=utf-8", page or "нет reg.html", None
        if method == "GET" and path == "/r/api/open":
            out = []
            for e in self.store.list_events():
                if e.get("reg_slug") and self.reg_state(e)[0]:
                    out.append({"name": e["name"], "date": e.get("date"), "place": e.get("place"),
                                "deadline": e.get("reg_deadline"), "slug": e["reg_slug"]})
            return js({"events": out})
        m = re.fullmatch(r"/r/([A-Za-z0-9]{4,20})(/info|/template\.xlsx|/team-check|/team)?/?", path)
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
            return js(self._public_info(ev))
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
            code, ctype, data, extra = self._public_route(method, urlsplit(target).path, headers, body, client)
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
        reasons = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                   404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
                   415: "Unsupported Media Type", 429: "Too Many Requests", 500: "Internal Server Error"}
        data = body.encode("utf-8") if isinstance(body, str) else body
        hdr = [f"HTTP/1.1 {code} {reasons.get(code, 'OK')}",
               f"Content-Type: {ctype}",
               f"Content-Length: {len(data)}",
               "Cache-Control: no-store",
               "Connection: close"]
        for k, v in (extra or {}).items():
            hdr.append(f"{k}: {v}")
        writer.write(("\r\n".join(hdr) + "\r\n\r\n").encode("utf-8") + data)
        await writer.drain()

    def _api_reads(self, qs: dict, headers: dict, body: bytes):
        sid = qs.get("source")
        src = self.sources.get(sid or "")
        if src is None:
            return 400, "application/json", json.dumps({"error": f"неизвестный source: {sid}"}, ensure_ascii=False)
        text = body.decode("utf-8", errors="replace")
        ok = bad = 0
        if "json" in headers.get("content-type", ""):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return 400, "application/json", '{"error":"bad json"}'
            items = data if isinstance(data, list) else [data]
            for it in items:
                if not isinstance(it, dict):
                    bad += 1
                    continue
                rx = now_local()
                rec = None
                chip = src.parser.norm_chip(str(it.get("chip", "")))
                ts = parse_any_time(it.get("time"), rx, src.cfg["unix_tz_offset_hours"])
                if chip and ts is not None:
                    ant = it.get("antenna")
                    rec = ParsedRead(chip=chip, ts=ts, antenna=None if ant in (None, "") else str(ant),
                                     rssi=None if it.get("rssi") is None else str(it.get("rssi")))
                line = json.dumps(it, ensure_ascii=False)
                if self.handle_parsed(src, line, rec, rx):
                    ok += 1
                else:
                    bad += 1
        else:
            for line in LineSplitter().feed(body + b"\n"):
                if self.handle_line(src, line):
                    ok += 1
                else:
                    bad += 1
        return 200, "application/json", json.dumps({"accepted": ok, "rejected": bad})

    def _raw_text(self, qs: dict) -> str:
        sid = qs.get("source")
        out = []
        for src in self.sources.values():
            if sid and src.id != sid:
                continue
            out.append(f"=== {src.id} ({src.cfg['name']}) — последние {len(src.tail)} строк ===")
            for rx, line, parsed in src.tail:
                out.append(f"{fmt_db(rx)}  {'OK ' if parsed else '-- '} {line}")
            out.append("")
        return "\n".join(out) or "нет источников"

    def _export_csv(self, qs: dict):
        def p(name):
            v = qs.get(name)
            if not v:
                return None
            for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    return dt.datetime.strptime(v, f)
                except ValueError:
                    pass
            raise ValueError(name)
        try:
            start, end = p("from"), p("to")
        except ValueError as e:
            return 400, "text/plain; charset=utf-8", f"неверный формат даты в параметре {e}; пример 2026-10-06 09:00"
        if end is not None and len(qs.get("to", "")) <= 10:
            end = end + dt.timedelta(days=1) - dt.timedelta(microseconds=1)
        rows = self.store.query_reads(start, end, source=qs.get("source"))
        if qs.get("filtered") == "1":
            f = PassingFilter(self.cfg["wiclax"]["forward_filter_sec"])
            rows = [r for r in rows if f.accept(r[1], r[2], parse_db(r[3]))]
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["source", "device", "chip", "time", "antenna", "rssi", "time_from_receive", "received_at"])
        for r in rows:
            w.writerow(r)
        return 200, "text/csv; charset=utf-8", "﻿" + buf.getvalue()

    # ---- состояние
    def status(self) -> dict:
        def t(x):
            return fmt_db(x) if x else None
        srcs = []
        for s in self.sources.values():
            srcs.append({
                "id": s.id, "name": s.cfg["name"], "mode": s.cfg["mode"], "device": s.cfg["device"],
                "connected": bool(s.connected), "peer": s.peer, "lines": s.lines, "reads": s.reads,
                "parse_errors": s.parse_errors, "duplicates": s.duplicates, "last_line": s.last_line, "last_line_at": t(s.last_line_at),
                "last_read_at": t(s.last_read_at),
                "clock_offset_sec": None if s.last_offset is None else round(s.last_offset, 3),
                "last_error": s.last_error,
            })
        clients = [{"peer": c.peer, "port": c.port, "devices": sorted(c.devices) if c.devices else None,
                    "since": t(c.since), "live": c.live, "sent": c.sent,
                    "queue": c.queue.qsize(), "last_commands": list(c.commands)} for c in self.wiclax_clients]
        st = {
            "version": VERSION,
            "server_time": t(now_local()),
            "server_epoch_ms": int(time.time() * 1000),
            "timezone": time.strftime("%Z %z"),
            "started_at": t(self.started_at),
            "totals": self.store.totals(),
            "sources": srcs,
            "wiclax_clients": clients,
        }
        if self.wiclax_clock_diff:
            st["wiclax_clock_diff_sec"] = round(self.wiclax_clock_diff[1], 1)
        return st

    def _page_status(self) -> str:
        st = self.status()
        e = html.escape
        warn_lim = float(self.cfg["clock_warn_sec"])
        rows = []
        for s in st["sources"]:
            conn = ("🟢 на связи" if s["connected"] else "🔴 нет связи") if s["mode"] != "http" else "HTTP"
            off = s["clock_offset_sec"]
            off_txt = "—" if off is None else f"{off:+.2f} с"
            off_cls = "warn" if (off is not None and abs(off) > warn_lim) else ""
            rows.append(
                f"<tr><td><b>{e(s['id'])}</b><br><small>{e(s['name'] or '')}</small></td>"
                f"<td>{conn}<br><small>{e(s['peer'] or '')}</small></td>"
                f"<td>{s['reads']} / {s['lines']}<br><small>не разобрано: {s['parse_errors']}"
                f" · повторов: {s['duplicates']}</small></td>"
                f"<td>{e(s['last_line_at'] or '—')}</td>"
                f"<td class='{off_cls}'>{off_txt}</td>"
                f"<td><a href='/raw?source={e(s['id'])}'>строки</a></td></tr>"
                + (f"<tr><td colspan=6><small class='err'>{e(s['last_error'])}</small></td></tr>"
                   if s["last_error"] and not s["connected"] else ""))
        cl = "".join(
            f"<li>{e(c['peer'])} — с {e(c['since'])}, {'приём идёт' if c['live'] else 'ПАУЗА (STOPREAD)'}, "
            f"отправлено {c['sent']}</li>" for c in st["wiclax_clients"]) or "<li>Wiclax не подключён</li>"
        last = "".join(
            f"<tr><td>{e(r[3])}</td><td>{e(r[2])}</td><td>{e(r[1])}</td><td>{e(r[0])}</td>"
            f"<td>{'время приёма' if r[5] else ''}</td></tr>" for r in self.store.last_reads(30))
        clock = ""
        if "wiclax_clock_diff_sec" in st:
            d = st["wiclax_clock_diff_sec"]
            cls = "warn" if abs(d) > warn_lim else ""
            clock = f"<p class='{cls}'>Часы компьютера Wiclax относительно сервера: {d:+.1f} с</p>"
        return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="5">
<title>Хронометраж — сервер</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:16px;color:#1b1f24;background:#f6f7f9}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:20px 0 8px}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:14px}}
td,th{{border-bottom:1px solid #e3e6ea;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#eef1f4}} small{{color:#5b6570}} .warn{{color:#b42318;font-weight:600}} .err{{color:#b42318}}
.box{{overflow-x:auto}} a{{color:#175cd3}}
</style></head><body>
<h1>Сервер хронометража</h1>
<small>Время сервера: <b>{e(st['server_time'])}</b> ({e(st['timezone'])}) · всего отметок: {st['totals']['reads']}
 · версия {VERSION}</small>
{clock}
<h2>Ридеры</h2><div class="box"><table>
<tr><th>Точка</th><th>Связь</th><th>Отметок / строк</th><th>Последняя строка</th><th>Часы ридера</th><th></th></tr>
{''.join(rows) or '<tr><td colspan=6>источники не настроены</td></tr>'}
</table></div>
<small>«Часы ридера» — насколько время в последней отметке отличается от времени сервера в момент приёма.
Проверяйте перед стартом тестовым чипом: должно быть в пределах ±{warn_lim:g} с.</small>
<h2>Wiclax</h2><ul>{cl}</ul>
<h2>Последние отметки</h2><div class="box"><table>
<tr><th>Время</th><th>Чип</th><th>Точка</th><th>Источник</th><th></th></tr>{last}</table></div>
<h2>Выгрузка</h2>
<p><a href="/export.csv">Все отметки (CSV)</a> · <a href="/export.csv?filtered=1">Только прохождения (CSV)</a>
 · <a href="/raw">Сырые строки</a> · <a href="/api/status">JSON</a></p>
<small>Фильтр по времени: /export.csv?from=2026-10-06 09:00&amp;to=2026-10-06 14:00&amp;source=FINISH</small>
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
    ap = argparse.ArgumentParser(description="Сервер хронометража: ридеры -> база -> Wiclax")
    ap.add_argument("--config", default="/etc/timing-hub/config.json")
    ap.add_argument("--check", action="store_true", help="проверить настройки и выйти")
    ap.add_argument("--test-parse", nargs=2, metavar=("SOURCE", "LINE"),
                    help="показать, как источник SOURCE разберёт строку LINE")
    ap.add_argument("--version", action="version", version=VERSION)
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"ОШИБКА НАСТРОЕК: {e}", file=sys.stderr)
        return 2

    logging.basicConfig(level=getattr(logging, str(cfg["log_level"]).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.test_parse:
        sid, line = args.test_parse
        src = next((s for s in cfg["sources"] if s["id"] == sid), None)
        if src is None:
            print(f"Нет источника {sid}", file=sys.stderr)
            return 2
        r = LineParser(src).parse(line, now_local())
        if r is None:
            print("НЕ РАЗОБРАНО: строка не подходит под настройки источника")
            return 1
        dev = SourceState(src, 1).device_for(r.antenna)
        print(f"чип:     {r.chip}\nвремя:   {fmt_db(r.ts)}{'  (время приёма!)' if r.from_rx else ''}\n"
              f"антенна: {r.antenna or '—'}\nточка:   {dev}\n"
              f"в Wiclax уйдёт: {r.chip};{fmt_wiclax(r.ts)};{dev};;;0")
        return 0

    if args.check:
        print(f"Настройки в порядке: {args.config}")
        print(f"  база: {cfg['db_path']}")
        print(f"  Wiclax: {cfg['wiclax']['listen_host']}:{cfg['wiclax']['listen_port']}")
        print(f"  страница: http://{cfg['web']['listen_host']}:{cfg['web']['listen_port']}/")
        for s in cfg["sources"]:
            where = (f"{s['listen_host']}:{s['listen_port']}" if s["mode"] == "listen" else
                     f"{s['host']}:{s['port']}" if s["mode"] == "connect" else "HTTP")
            print(f"  [{s['id']}] {'вкл ' if s['enabled'] else 'выкл'} {s['mode']:7} {where:22} "
                  f"разбор={s['parser']} точка={s['device']}  {s['name']}")
        return 0

    try:
        asyncio.run(amain(cfg))
    except OSError as e:
        log.error("Не удалось запуститься: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
