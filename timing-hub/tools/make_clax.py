#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка файла соревнования Wiclax (.clax) из простого описания (JSON).

    python3 make_clax.py событие.json  [итог.clax]

Описание:
{
  "name": "Осенний кросс 2026",            — название (видно в Wiclax)
  "date": "2026-10-18",                    — дата старта
  "organizer": "РСОО «ФЛАСО»",
  "parcours": [                            — дистанции/забеги Wiclax («Parcours»)
    {"name": "1000 м девочки до 12", "distance": 1000, "start": "10:00:00"},
    {"name": "3000 м мужчины", "distance": 3000, "start": "11:30"}
  ],
  "splits": [                              — промежуточные отсечки (необязательно)
    {"name": "2 км", "dist": 2000, "parcours": ["3000 м мужчины"]}
  ],
  "entries": [                             — участники (необязательно; можно потом в Wiclax)
    {"bib": 1, "name": "ИВАНОВ ИВАН Петрович", "club": "СШОР", "sex": "M",
     "birth": "2012-05-01", "year": 2012, "parcours": "1000 м девочки до 12", "chip": "58003a9f837"}
  ]
}
Только стандартная библиотека Python. Шаблон — настройки Wiclax без персональных данных.
"""
import base64
import datetime as dt
import json
import re
import sys
import xml.etree.ElementTree as ET

TEMPLATE = '<?xml version="1.0" encoding="utf-8"?><Epreuve vMaj="10" vMin="1" nom="" organisateur="" dates="" etapeActive="1" libelleEtapes="0" sport="6" TZ="660" derSvg="" cle="" cfgeel="" date="" saison="1900-12-31" idLive="0" histFiR="" genTie="16,15,1,8,10,5" nbCoureursPodiums="0" lblSeries="Группа уровней" lblClub="1" bpse="1" idpa="1" opRE=""><DonneesSaisies><D>Année</D><D>Club</D><D>Sexe</D></DonneesSaisies><ColVisEng>Dossard,NomPrénom,Club,Sexe,Année,Parcours</ColVisEng><ColVisRes>Dossard,Place,NomPrénom,Club,Sexe,Année,Parcours,Temps,Moyenne,Progression,PtgBrut0,PtgBrut1,PtgBrut2,Pointage3,PtgBrut3,PtgBrut4</ColVisRes><ColVisEq>Club,Catégorie1,Sexe,NbPart</ColVisEq><IP /><Etapes><Etape type="0" distance="0" chrono="1" nbTours="1" ttMin="00h00\'30" dernierTempsSaisi="" finito=",,,,,,,,,,,,,," etGr=";0||"><optPoints><O c="" /></optPoints><Engages /><Resultats /><Penalites /><ClassementsAnnexes><Clt id="gpm"><Rush id="ET" nom="Этап" /><Rush id="GN" nom="Общий" /></Clt><Clt id="pts"><Rush id="AR" nom="Финиш" /><Rush id="ET" nom="Этап" /><Rush id="GN" nom="Общий" /></Clt></ClassementsAnnexes><Pointages /><Segments /><Handicaps /><Options /><Pass_Arr /><Pass_Ptg1 /><Pass_Ptg2 /><Pass_Ptg3 /><Pass_Ptg4 /></Etape></Etapes><Categories><G /></Categories><Series /><Equipes /><Parcours /><OptionsClEquipes critere="0" nbCoureursSomme="3" nbCoureursRang="3" nbFemmes="1" nbCoureursSommeRgs="3" nbCoureursMinPourDernier="3" generalsimple="1" cdp="4,1,3,2,5,6,7" /><ClassementsAnnexes><Clnx id="gpm" nom="Горная классификация" tie="11,10,8,9" /><Clnx id="pts" nom="Очковая классификация" tie="10,11,8,9" /></ClassementsAnnexes><OptionsImpr><o id="800" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="2201" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="2001" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1901" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="2101" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="801" opt="¤¤1¤0¤1¤0¤1¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="901" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1001" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1101" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1201" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1301" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1401" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1501" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1601" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1701" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /><o id="1801" opt="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /></OptionsImpr><Editions><E id="1" nom="Стандартная классификация" std="1" cls="1" /><E id="5" nom="Все участники" std="1" eng="1" /><E id="2" nom="Классификация по категориям" titre="Классификация по категориям" cls="1"><gp>Catégorie1</gp></E><E id="3" nom="Мужчины Абсолют" titre="Мужчины Абсолют" cls="1" filtre="[Sexe]=\'M\'" fsql="([Sexe] = \'M\')" /><E id="4" nom="Женщины Абсолют" titre="Женщины Абсолют" cls="1" filtre="[Sexe]=\'F\'" fsql="([Sexe] = \'F\')" /><E id="6" nom="список стартовавших" titre="список стартовавших" eng="1" filtre="Not [NonPartant]" fsql="not ([NonPartant])" /><E id="7" nom="По гонке" eng="1" cls="1"><gp>Parcours</gp></E></Editions><Grids /><Diplomes modeAttrib="1" /><PucesDos /><ImagesEditions><M nom="Основной" options="¤¤1¤0¤1¤0¤¤Основной¤¤¤0¤¤¤¤¤¤¤¤¤¤¤¤¤" /></ImagesEditions></Epreuve>'

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
OLE0 = dt.datetime(1899, 12, 30)


def _ole(d: dt.datetime) -> float:
    return (d - OLE0).total_seconds() / 86400.0


def _date(s) -> dt.date:
    s = str(s).strip()
    for f in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(f"дата «{s}»: пишите 2026-10-18 или 18.10.2026")


def _time(s) -> dt.time:
    s = str(s).strip()
    for f in ("%H:%M:%S", "%H:%M", "%H.%M"):
        try:
            return dt.datetime.strptime(s, f).time()
        except ValueError:
            pass
    raise ValueError(f"время старта «{s}»: пишите 10:30 или 10:30:00")


def build_clax(spec: dict, now: dt.datetime = None) -> bytes:
    """Возвращает содержимое .clax (UTF-8). Ошибки в описании — ValueError с понятным текстом."""
    errors = []
    name = str(spec.get("name") or "").strip()
    if not name:
        raise ValueError("нет названия соревнования (name)")
    day = _date(spec.get("date") or "")
    now = now or dt.datetime.now().replace(microsecond=0)
    root = ET.fromstring(TEMPLATE.split("?>", 1)[1])
    saved = now.strftime("%Y-%m-%d %H:%M:%S")
    root.set("nom", name[:60])
    root.set("organisateur", str(spec.get("organizer") or "")[:120])
    root.set("dates", f"{day.day} {MONTHS[day.month - 1]} {day.year} г.")
    root.set("date", str(int(_ole(dt.datetime.combine(day, dt.time())))))
    root.set("derSvg", saved)
    root.set("cle", base64.b64encode((name[:60] + saved).encode("utf-16-le")).decode())
    etape = root.find("Etapes/Etape")

    # дистанции и старты
    pcs_el = root.find("Parcours")
    hand = etape.find("Handicaps")
    names = []
    for p in spec.get("parcours") or []:
        pn = str(p.get("name") or "").strip()
        if not pn or "'" in pn:
            errors.append(f"дистанция «{pn}»: пустое название или апостроф")
            continue
        if pn in names:
            errors.append(f"дистанция «{pn}» указана дважды")
            continue
        names.append(pn)
        try:
            meters = int(float(p.get("distance") or 0))
        except (TypeError, ValueError):
            meters = 0
        ET.SubElement(pcs_el, "Pcs", {"nom": pn, "distance": str(meters)})
        if p.get("start"):
            try:
                st = dt.datetime.combine(_date(p.get("date") or day), _time(p["start"]))
            except ValueError as e:
                errors.append(f"{pn}: {e}")
                continue
            ET.SubElement(hand, "H", {"actif": "1", "dateheure": repr(_ole(st)).replace(".", ","),
                                      "sdateheure": st.strftime("%Y-%m-%d %H:%M:%S"),
                                      "filtre": f"Parcours = '{pn}'", "fa": f"Гонка = '{pn}'"})
    if not names:
        errors.append("нет ни одной дистанции (parcours)")
    # печатные формы «Гонка: …» — по одной на дистанцию, как делает сам Wiclax
    eds = root.find("Editions")
    for i, pn in enumerate(names, 8):
        ET.SubElement(eds, "E", {"id": str(i), "nom": f"Гонка: {pn}", "titre": pn, "eng": "1", "cls": "1",
                                 "filtre": f"[Parcours]='{pn}'", "fsql": f"([Parcours] = '{pn}')", "c": pn})

    # промежуточные отсечки
    ptg = etape.find("Pointages")
    for i, s in enumerate(spec.get("splits") or []):
        sp = [x for x in (s.get("parcours") or names) if x in names]
        bad = [x for x in (s.get("parcours") or []) if x not in names]
        if bad:
            errors.append(f"отсечка «{s.get('name')}»: нет дистанций {', '.join(bad)}")
        if i > 4:
            errors.append("отсечек больше пяти — шаблон рассчитан на 5")
            break
        ET.SubElement(ptg, "Pointage", {"id": str(i), "nom": str(s.get("name") or f"Отсечка {i + 1}"),
                                         "int": str(s.get("name") or f"Отсечка {i + 1}"),
                                         "dist": str(int(float(s.get("dist") or 0))), "pcs": ",".join(sp),
                                         "distpcs": ":".join("0" for _ in sp)})

    # участники и чипы
    eng = etape.find("Engages")
    puces = root.find("PucesDos")
    bibs, chips = set(), set()
    for n, e in enumerate(spec.get("entries") or [], 1):
        bib = str(e.get("bib") or "").strip()
        if not re.fullmatch(r"\d{1,6}", bib):
            errors.append(f"участник {n}: номер «{bib}» — нужны цифры")
            continue
        if bib in bibs:
            errors.append(f"номер {bib} повторяется")
            continue
        bibs.add(bib)
        a = {"d": bib, "n": str(e.get("name") or "").strip()[:80]}
        if e.get("club"):
            a["c"] = str(e["club"]).strip()[:60]
        birth = None
        if e.get("birth"):
            try:
                birth = _date(e["birth"])
            except ValueError as ex:
                errors.append(f"номер {bib}: {ex}")
        year = str(e.get("year") or (birth.year if birth else "")).strip()
        if year:
            a["a"] = year
        sex = str(e.get("sex") or "").strip().upper()[:1]
        sex = {"М": "M", "Ж": "F", "W": "F"}.get(sex, sex)
        if sex in ("M", "F"):
            a["x"] = sex
        elif sex:
            errors.append(f"номер {bib}: пол «{e.get('sex')}» — M/F или М/Ж")
        pc = str(e.get("parcours") or "").strip()
        if pc:
            if pc not in names:
                errors.append(f"номер {bib}: дистанции «{pc}» нет в списке parcours")
            a["p"] = pc
        if birth:
            a["dn"] = birth.strftime("%m%d%Y")
        ET.SubElement(eng, "E", a)
        raw = e.get("chip") or ""
        for chip in (raw if isinstance(raw, list) else re.split(r"[,; ]+", str(raw))):   # запасной чип — через запятую
            chip = str(chip).strip().lower()
            if not chip or chip.startswith("#"):
                continue
            if chip in chips:
                errors.append(f"чип {chip} выдан двум участникам")
            chips.add(chip)
            ET.SubElement(puces, "P").text = f"{chip}.{bib}"
    if errors:
        raise ValueError("; ".join(errors[:12]) + (f" … и ещё {len(errors) - 12}" if len(errors) > 12 else ""))
    return ('<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(root, encoding="unicode")).encode("utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"[^\w.-]+", "_", spec.get("name") or "event") + ".clax"
    try:
        data = build_clax(spec)
    except ValueError as e:
        print("Ошибка:", e)
        return 2
    open(out, "wb").write(data)
    print(f"Готово: {out} — дистанций {len(spec.get('parcours') or [])}, участников {len(spec.get('entries') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
