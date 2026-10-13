#!/usr/bin/env python3
"""Нормы ЕВСК по лёгкой атлетике (лист «нормы» приложения к приказу Минспорта) → hub/seed/rank_norms.json.

Запуск:  python3 tools/norms_import.py Legkaya_atletika.xls [--source "Приказ Минспорта от 10.03.2026"]
Нужен пакет xlrd (pip install xlrd) — только для этого скрипта, сервер его не использует.

Каждая строка таблицы — одна норма: дисциплина (ключ как у сервера: run:60, hurdles:110, throw:jt …), пол,
хронометраж (ручной / авто / любой), круг (200 / 400 м), возрастные группы (высота барьеров, масса снаряда)
и значения для МСМК … 3 юн. Ячейки, нарушающие порядок (норма разряда ниже строже нормы выше), считаются
опечаткой таблицы и пропускаются — список таких ячеек печатается.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "hub"))
from hub import Hub  # noqa: E402

RANKS = ("МСМК", "МС", "КМС", "1 р.", "2 р.", "3 р.", "1 юн.", "2 юн.", "3 юн.")


def parse_value(cell, unit: str):
    """Ячейка нормы → число: секунды для времени, метры, очки. None — нормы нет."""
    is_time = unit.startswith(("c", "с", "мин", "ч"))
    if isinstance(cell, float):
        if cell == 0:
            return None
        if is_time and cell < 1:                   # Excel сохранил «мм:сс» как долю суток
            return round(cell * 86400, 2)
        if is_time and cell < 3 and ("мин" in unit or "ч" in unit):
            return round(cell * 1440, 2)           # «44:40» прочитано Excel как 44 ч 40 мин
        return round(cell, 2)
    t = str(cell).strip().replace(" ", "")
    if not t:
        return None
    m = re.fullmatch(r"(\d+)\.(\d\d):(\d\d)(?:[.,](\d+))?", t)              # ч.мм:сс
    if m:
        return round(int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + float("0." + (m[4] or "0")), 2)
    m = re.fullmatch(r"(\d+):(\d\d)(?:[.,](\d+))?", t)                        # м:сс,д
    if m:
        return round(int(m[1]) * 60 + int(m[2]) + float("0." + (m[3] or "0")), 2)
    m = re.fullmatch(r"\d+(?:[.,]\d+)?", t)
    if m:
        return round(float(t.replace(",", ".")), 2)
    return None


def ages_of(cond: str) -> list:
    c = cond.lower()
    out = [f"u{n}" for n in re.findall(r"до\s*(\d+)\s*лет", c)]
    if re.search(r"мужчин|женщин", c):
        out.append("sen")
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xls")
    ap.add_argument("--source", default="")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "hub", "seed", "rank_norms.json"))
    a = ap.parse_args()
    import xlrd
    sh = xlrd.open_workbook(a.xls).sheet_by_name("нормы")
    head = " ".join(str(sh.cell_value(r, 2)) + str(sh.cell_value(r, 0)) for r in range(3))
    norms, skipped, unknown = [], [], set()
    sex, name, sub = None, "", ""
    for r in range(sh.nrows):
        c0 = str(sh.cell_value(r, 0)).strip()
        row = [sh.cell_value(r, c) for c in range(sh.ncols)]
        if c0.upper().startswith("МУЖСКОЙ ПОЛ И ЖЕНСКИЙ"):
            sex = None
            continue
        if c0.upper().startswith("МУЖСКОЙ"):
            sex = "М"
            continue
        if c0.upper().startswith("ЖЕНСКИЙ"):
            sex = "Ж"
            continue
        if c0.startswith("Иные"):
            break
        if not sex:
            continue
        if str(row[1]).strip():
            name, sub = re.sub(r"\s+", " ", str(row[1])).strip(), ""
        if str(row[2]).strip():
            sub = re.sub(r"\s+", " ", str(row[2])).strip()
        unit = str(row[4]).strip().lower()
        if not unit or "км" in unit:                # «Бег 24 часа» — километры, не поддерживаем
            continue
        cond = re.sub(r"\s+", " ", str(row[3])).strip()
        text = (("Ходьба " if "ходьб" in name.lower() else "Бег ") + sub) if sub else name
        if "шоссе" in name.lower():
            text = name
        key = Hub.norm_key(text)
        if "борье" in name and "круг 200" in cond.lower():
            pass
        if not key:
            unknown.add(name)
            continue
        cl = cond.lower()
        timing = "hand" if "ручн" in cl and "авто" not in cl else "auto" if "автохронометр" in cl and "ручн" not in cl else "any"
        lap = "200" if "круг 200" in cl else "400" if "круг 400" in cl else None
        var = "water" if "с ямой" in cl else "nowater" if "без ямы" in cl else "road" if "шоссе" in cl else \
            "track" if "стадион" in cl else ""
        vals = {}
        for i, rk in enumerate(RANKS):
            v = parse_value(row[5 + i], unit)
            if v is not None:
                vals[rk] = v
        better = "lower" if "не более" in unit else "higher"
        # проверка порядка: каждый следующий разряд — не строже предыдущего
        prev = None
        for rk in RANKS:
            if rk not in vals:
                continue
            if prev is not None and ((better == "lower" and vals[rk] < prev[1]) or (better == "higher" and vals[rk] > prev[1])):
                skipped.append(f"{'М' if sex == 'М' else 'Ж'} · {name} {sub} · {cond[:60]} · {rk}: {vals[rk]} (строже, чем {prev[0]}: {prev[1]})")
                del vals[rk]
                continue
            prev = (rk, vals[rk])
        if not vals:
            continue
        norms.append({"key": key, "sex": sex, "timing": timing, "lap": lap, "ages": ages_of(cond), "var": var,
                      "better": better, "v": vals, "src": " · ".join(x for x in (name, sub, cond) if x)})
    out = {"source": a.source or head.strip()[:200], "count": len(norms), "skipped": skipped, "norms": norms}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    print(f"норм: {len(norms)} → {a.out}")
    if unknown:
        print("дисциплины без ключа (пропущены):", ", ".join(sorted(unknown)))
    for s in skipped:
        print("пропущена ячейка:", s)


if __name__ == "__main__":
    main()
