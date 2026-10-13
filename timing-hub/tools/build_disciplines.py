#!/usr/bin/env python3
"""Собирает справочник дисциплин лёгкой атлетики для стадиона: hub/seed/disciplines.json.

Запуск:  python3 tools/build_disciplines.py
Источники (проверено 13.10.2026):
  • World Athletics, Technical Rules (TR 22–23, 24, 32): высоты и расстояния барьеров, массы снарядов,
    составы многоборий U18/U20/взрослых;
  • классификация ЕВСК / положения ВФЛА: младшие возрасты (до 14, 14–15), состав многоборий для юношей и
    девушек, мяч 140 г. Для младших возрастов окончательно ориентируйтесь на положение конкретных соревнований.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "hub", "seed", "disciplines.json")

GROUPS = [
    ("sprint", "Спринт", "30–400 м"),
    ("middle", "Средние дистанции", "500 м – 2000 м"),
    ("long", "Длинные дистанции", "3000 м и дальше"),
    ("hurdles", "Барьерный бег", "с/б"),
    ("steeple", "Стипль-чез", "с/п"),
    ("relay", "Эстафеты", "команда из нескольких этапов"),
    ("walk", "Спортивная ходьба", "по стадиону"),
    ("jumps", "Прыжки", "высота, шест, длина, тройной"),
    ("throws", "Метания", "ядро, диск, молот, копьё, мяч"),
    ("combined", "Многоборья", "результат — очки по таблице"),
]

RESULT_TYPES = {
    "time": {"name": "Время", "unit": "с", "hint": "12.84 · 1:05.32 · 2:05:31", "better": "lower"},
    "distance": {"name": "Расстояние", "unit": "м", "hint": "7.85 (метры)", "better": "higher"},
    "height": {"name": "Высота", "unit": "м", "hint": "1.95 (метры)", "better": "higher"},
    "points": {"name": "Очки", "unit": "очк.", "hint": "7250 (целое число)", "better": "higher"},
}

IN, OUT_ = "indoor", "outdoor"
BOTH = [IN, OUT_]

D = []


def add(did, name, group, rtype="time", sex="MF", venue=None, attempts=False, maximum=None, legs=None,
        specs=None, aliases=None, note=None, parts=None):
    d = {"id": did, "name": name, "group": group, "result": rtype, "sex": sex, "venue": venue or [OUT_]}
    if attempts:
        d["attempts"] = True
    if maximum:
        d["max"] = maximum
    if legs:
        d["legs"] = legs
    if specs:
        d["specs"] = specs
    if aliases:
        d["aliases"] = aliases
    if note:
        d["note"] = note
    if parts:
        d["parts"] = parts
    D.append(d)


# ---- бег
for m in (30, 50):
    add(f"{m}m", f"{m} м", "sprint", venue=BOTH, note="для детей, нормативы и тесты")
add("60m", "60 м", "sprint", venue=BOTH, aliases=["60", "60м"])
add("100m", "100 м", "sprint", aliases=["100", "100м"])
add("200m", "200 м", "sprint", venue=BOTH, aliases=["200", "200м"])
add("300m", "300 м", "sprint", venue=BOTH, aliases=["300", "300м"])
add("400m", "400 м", "sprint", venue=BOTH, aliases=["400", "400м"])
add("500m", "500 м", "middle", venue=BOTH, aliases=["500", "500м"])
add("600m", "600 м", "middle", venue=BOTH, aliases=["600", "600м"])
add("800m", "800 м", "middle", venue=BOTH, aliases=["800", "800м"])
add("1000m", "1000 м", "middle", venue=BOTH, aliases=["1000", "1000м"])
add("1500m", "1500 м", "middle", venue=BOTH, aliases=["1500", "1500м"])
add("mile", "1 миля", "middle", venue=BOTH, aliases=["Миля"])
add("2000m", "2000 м", "middle", venue=BOTH, aliases=["2000", "2000м"])
add("3000m", "3000 м", "long", venue=BOTH, aliases=["3000", "3000м"])
add("5000m", "5000 м", "long", aliases=["5000", "5000м"])
add("10000m", "10000 м", "long", aliases=["10000", "10000м", "10 000 м"])

# ---- барьеры (WA TR 22; младшие возрасты — ЕВСК)
H_110 = [
    {"who": "Мужчины", "text": "высота 106,7 см · 13,72 / 9,14 / 14,02 м"},
    {"who": "Юниоры до 20", "text": "высота 99,1 см · 13,72 / 9,14 / 14,02 м"},
    {"who": "Юноши до 18", "text": "высота 91,4 см · 13,72 / 9,14 / 14,02 м"},
]
H_100 = [
    {"who": "Женщины и юниорки до 20", "text": "высота 83,8 см · 13,00 / 8,50 / 10,50 м"},
    {"who": "Девушки до 18", "text": "высота 76,2 см · 13,00 / 8,50 / 10,50 м"},
    {"who": "Девочки до 14 (ЕВСК)", "text": "высота 65 см"},
]
add("60mh", "60 м с/б", "hurdles", venue=[IN], aliases=["60 с/б", "60 м/б", "60м с/б"],
    specs=[{"who": "Мужчины", "text": "106,7 см · 13,72 / 9,14 / 9,72 м"},
           {"who": "Юниоры до 20", "text": "99,1 см"}, {"who": "Юноши до 18", "text": "91,4 см"},
           {"who": "Женщины и юниорки", "text": "83,8 см · 13,00 / 8,50 / 13,00 м"},
           {"who": "Девушки до 18", "text": "76,2 см"},
           {"who": "Мальчики до 14 (ЕВСК)", "text": "84 см"}, {"who": "Девочки до 14 (ЕВСК)", "text": "65 см"}])
add("80mh", "80 м с/б", "hurdles", sex="F", aliases=["80 с/б"],
    note="девочки младших возрастов, параметры — по положению соревнований")
add("100mh", "100 м с/б", "hurdles", sex="F", aliases=["100 с/б", "100 м/б"], specs=H_100)
add("110mh", "110 м с/б", "hurdles", sex="M", aliases=["110 с/б", "110 м/б"], specs=H_110)
add("300mh", "300 м с/б", "hurdles", venue=BOTH, aliases=["300 с/б"],
    note="молодёжные и юношеские возрасты, параметры — по положению соревнований")
add("400mh", "400 м с/б", "hurdles", aliases=["400 с/б", "400 м/б"],
    specs=[{"who": "Мужчины и юниоры до 20", "text": "высота 91,4 см · 45 / 35 / 40 м"},
           {"who": "Юноши до 18", "text": "высота 83,8 см"},
           {"who": "Женщины, юниорки, девушки", "text": "высота 76,2 см"}])

# ---- стипль-чез (WA TR 23)
ST = [{"who": "Мужчины и юниоры до 20", "text": "барьер 91,4 см"}, {"who": "Юноши до 18", "text": "барьер 83,8 см"},
      {"who": "Женщины, юниорки, девушки", "text": "барьер 76,2 см"}]
add("2000msc", "2000 м с/п", "steeple", aliases=["2000 с/п", "2000 стипль"], specs=ST)
add("3000msc", "3000 м с/п", "steeple", aliases=["3000 с/п", "3000 стипль"], specs=ST)

# ---- эстафеты (этапы — по умолчанию 4)
add("4x60", "4×60 м", "relay", venue=[IN], legs=4, aliases=["4x60"])
add("4x100", "4×100 м", "relay", legs=4, aliases=["4x100", "4х100", "4*100"])
add("4x200", "4×200 м", "relay", venue=BOTH, legs=4, aliases=["4x200", "4х200"])
add("4x400", "4×400 м", "relay", venue=BOTH, legs=4, aliases=["4x400", "4х400"])
add("4x400mix", "4×400 м смешанная", "relay", venue=BOTH, legs=4, aliases=["4x400 микст"],
    note="два юноши и две девушки")
add("4x800", "4×800 м", "relay", legs=4, aliases=["4x800"])
add("4x1500", "4×1500 м", "relay", legs=4, aliases=["4x1500"])
add("swedish", "Шведская эстафета", "relay", legs=4, aliases=["Шведская"],
    note="этапы 100, 200, 300 и 400 м")

# ---- ходьба
for m, venue in ((1500, BOTH), (2000, BOTH), (3000, BOTH), (5000, BOTH), (10000, [OUT_])):
    add(f"walk{m}", f"Ходьба {m} м", "walk", venue=venue, aliases=[f"Ходьба {m}"],
        note="судейство по правилам спортивной ходьбы: предупреждения и дисквалификация")

# ---- прыжки и метания (расстояние и высота в метрах, с точностью до сантиметра)
add("hj", "Прыжок в высоту", "jumps", "height", venue=BOTH, attempts=True, maximum=2.7,
    aliases=["Высота", "Прыжок в высоту"], note="лучшая взятая высота; попытки по высотам — в протоколе судей")
add("pv", "Прыжок с шестом", "jumps", "height", venue=BOTH, attempts=True, maximum=7.0,
    aliases=["Шест", "Прыжок с шестом"], note="лучшая взятая высота")
add("lj", "Прыжок в длину", "jumps", "distance", venue=BOTH, attempts=True, maximum=10.0,
    aliases=["Длина", "Прыжок в длину"], note="лучший результат из попыток; ветер — в протоколе судей")
add("tj", "Тройной прыжок", "jumps", "distance", venue=BOTH, attempts=True, maximum=19.5,
    aliases=["Тройной", "Тройной прыжок"], note="лучший результат из попыток")
IMPL = {
    "sp": [("Мужчины", "7,26 кг"), ("Юниоры до 20", "6 кг"), ("Юноши до 18", "5 кг"), ("Юноши до 14 (ЕВСК)", "4 кг"),
           ("Женщины и юниорки", "4 кг"), ("Девушки до 18", "3 кг")],
    "dt": [("Мужчины", "2 кг"), ("Юниоры до 20", "1,75 кг"), ("Юноши до 18", "1,5 кг"), ("Юноши до 14 (ЕВСК)", "1 кг"),
           ("Женщины, юниорки, девушки", "1 кг"), ("Девочки до 14 (ЕВСК)", "0,75 кг")],
    "ht": [("Мужчины", "7,26 кг"), ("Юниоры до 20", "6 кг"), ("Юноши до 18", "5 кг"),
           ("Женщины и юниорки", "4 кг"), ("Девушки до 18", "3 кг")],
    "jt": [("Мужчины и юниоры до 20", "800 г"), ("Юноши до 18", "700 г"), ("Женщины и юниорки", "600 г"),
           ("Девушки до 18", "500 г")],
}


def impl(k):
    return [{"who": w, "text": t} for w, t in IMPL[k]]


add("sp", "Толкание ядра", "throws", "distance", venue=BOTH, attempts=True, maximum=25.0, aliases=["Ядро", "Толкание ядра"],
    specs=impl("sp"), note="лучший результат из попыток")
add("dt", "Метание диска", "throws", "distance", attempts=True, maximum=82.0, aliases=["Диск", "Метание диска"], specs=impl("dt"),
    note="лучший результат из попыток")
add("ht", "Метание молота", "throws", "distance", attempts=True, maximum=92.0, aliases=["Молот", "Метание молота"], specs=impl("ht"),
    note="лучший результат из попыток")
add("jt", "Метание копья", "throws", "distance", attempts=True, maximum=105.0, aliases=["Копьё", "Копье", "Метание копья", "Метание копья"],
    specs=impl("jt"), note="лучший результат из попыток")
add("ball", "Метание мяча", "throws", "distance", attempts=True, maximum=90.0, aliases=["Мяч", "Метание мяча 140 г"],
    specs=[{"who": "Дети", "text": "мяч 140 г"}], note="дети до 14 лет")

# ---- многоборья: результат — сумма очков по таблице, состав по дням
COMB = [
    ("dec", "Десятиборье", "M", [OUT_], 9500, "Юниоры до 20, юноши до 18 (с 16 лет), мужчины",
     [["100 м", "Длина", "Ядро", "Высота", "400 м"], ["110 м с/б", "Диск", "Шест", "Копьё", "1500 м"]]),
    ("oct", "Восьмиборье", "M", [OUT_], 7500, "Юноши до 16 лет",
     [["100 м", "Длина", "Ядро", "400 м"], ["110 м с/б", "Высота", "Копьё", "1000 м"]]),
    ("hep", "Семиборье", "F", [OUT_], 7500, "Девушки, юниорки, женщины (с 14 лет)",
     [["100 м с/б", "Высота", "Ядро", "200 м"], ["Длина", "Копьё", "800 м"]]),
    ("hepi", "Семиборье (зал)", "M", [IN], 7000, "Юниоры, юноши, мужчины в помещении",
     [["60 м", "Длина", "Ядро", "Высота"], ["60 м с/б", "Шест", "1000 м"]]),
    ("peni", "Пятиборье (зал)", "F", [IN], 5500, "Девушки, юниорки, женщины в помещении",
     [["60 м с/б", "Высота", "Ядро", "Длина", "800 м"]]),
    ("hex", "Шестиборье", "M", BOTH, 6000, "Юноши до 14–15 лет",
     [["60 м с/б", "Длина", "Ядро"], ["Высота", "Копьё", "1000 м"]]),
    ("tet", "Четырёхборье", "MF", BOTH, 4500, "Дети до 14 лет",
     [["60 м", "Прыжок (длина или высота)"], ["Мяч", "600 м (девочки), 800 м (мальчики)"]]),
    ("tri", "Троеборье", "MF", BOTH, 3500, "Дети до 13 лет, юноши и девушки до 18 лет: бег, прыжок и метание по выбору",
     [["Бег", "Прыжок", "Ядро или метание"]]),
]
for did, name, sex, venue, mx, who, days in COMB:
    add(did, name, "combined", "points", sex=sex, venue=venue, maximum=mx, parts=[{"day": i + 1, "events": e} for i, e in enumerate(days)],
        specs=[{"who": "Участники", "text": who}], note="очки по таблице многоборий World Athletics")

# ---- пресеты для мастера создания соревнования
def ids(*a):
    return list(a)


PRESETS = [
    {"id": "indoor", "name": "Манеж: основная программа", "hint": "бег до 3000 м, 60 м с/б, прыжки, ядро",
     "venue": "indoor", "disciplines": ids("60m", "200m", "400m", "800m", "1500m", "3000m", "60mh", "hj", "pv", "lj", "tj", "sp")},
    {"id": "outdoor", "name": "Стадион: основная программа", "hint": "бег, барьеры, стипль, прыжки, метания, эстафеты",
     "venue": "outdoor", "disciplines": ids("100m", "200m", "400m", "800m", "1500m", "5000m", "100mh", "110mh", "400mh",
                                            "3000msc", "hj", "pv", "lj", "tj", "sp", "dt", "ht", "jt", "4x100", "4x400")},
    {"id": "cup", "name": "Кубок: бег и прыжки", "hint": "компактная программа на один день",
     "disciplines": ids("60m", "100m", "200m", "400m", "800m", "1500m", "lj", "hj")},
    {"id": "kids", "name": "Дети до 14 лет", "hint": "60 м, 300 м, 600 м, 1000 м, барьеры, длина, высота, мяч, ядро",
     "disciplines": ids("60m", "300m", "600m", "1000m", "60mh", "lj", "hj", "ball", "sp")},
    {"id": "boys-combined", "name": "Многоборье юношей", "hint": "десятиборье и восьмиборье",
     "disciplines": ids("dec", "oct")},
    {"id": "girls-combined", "name": "Многоборье девушек", "hint": "семиборье и пятиборье в зале",
     "disciplines": ids("hep", "peni")},
    {"id": "jumps", "name": "Прыжки", "hint": "высота, шест, длина, тройной",
     "disciplines": ids("hj", "pv", "lj", "tj")},
    {"id": "throws", "name": "Метания", "hint": "ядро, диск, молот, копьё, мяч",
     "disciplines": ids("sp", "dt", "ht", "jt", "ball")},
    {"id": "relays", "name": "Эстафеты", "hint": "4×100 м и 4×400 м",
     "disciplines": ids("4x100", "4x400")},
    {"id": "walk", "name": "Спортивная ходьба", "hint": "3000 м и 5000 м",
     "disciplines": ids("walk3000", "walk5000")},
]

AGES = [
    {"id": "u12", "name": "до 12 лет"}, {"id": "u14", "name": "до 14 лет"}, {"id": "u16", "name": "до 16 лет"},
    {"id": "u18", "name": "до 18 лет"}, {"id": "u20", "name": "юниоры до 20 лет"}, {"id": "u23", "name": "молодёжь до 23 лет"},
    {"id": "sen", "name": "взрослые"},
]


def main():
    data = {
        "version": 1,
        "updated": "2026-10-13",
        "sources": ["World Athletics Technical Rules (TR 22, 23, 24, 32)", "ЕВСК и положения ВФЛА (младшие возрасты)"],
        "groups": [{"id": i, "name": n, "hint": h} for i, n, h in GROUPS],
        "result_types": RESULT_TYPES,
        "ages": AGES,
        "disciplines": D,
        "presets": PRESETS,
    }
    names = [d["name"] for d in D]
    assert len(set(names)) == len(names), "дублируются названия"
    assert all(len(n) <= 20 for n in names), [n for n in names if len(n) > 20]
    assert len({d["id"] for d in D}) == len(D), "дублируются id"
    known = {d["id"] for d in D}
    assert all(x in known for p in PRESETS for x in p["disciplines"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{len(D)} дисциплин, {len(PRESETS)} пресетов → {OUT}")


if __name__ == "__main__":
    main()
