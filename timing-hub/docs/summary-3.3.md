# SakhStart 3.3.0 — сводка стартовых списков и печатных протоколов (сборка 13.10.2026)

## 1. База данных (SQLite): таблицы, связанные с забегами
entries(event_id, bib, chip, wave, name, birth_year, team, category, lane, coach, seed, reg_id, sex, result, status, points, picked_at, members, detail, rank)
waves(event_id, name, category, distance, start_time, finished_at)
registrations(... sex, rank, relay, leg, distance, category, status, bib ...)

## 2. Маршруты сервера (POST /api/events/<id>/...)
heats        {lanes, mode: 'heats'|'list'}  — формирование: по забегам и дорожкам либо ОБЩИМ СПИСКОМ (один забег «Общий список», без дорожек)
resetheats   {distance?}                     — сбросить сетку: у всех wave=NULL, lane=NULL, забеги удалены (после старта — отказ)
GET /api/events/<id>/startlist               — стартовый список: heats[{name,distance,category,rtype,slots,entries}], no_heat

## 3. Функции hub.py
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
        used = {e["bib"] for e in old.values()}

        def bib_for(r):
            e = old.get(r["id"])
            if e:
                return e["bib"], e["chip"]
            b = self.next_bib(ev, used, r["distance"])   # диапазон номеров дистанции, если задан
            used.add(b)
            return b, "#" + b

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

## 4. Печатная форма (protocol.html)
```js
const sexOf=e=>{const x=String(e.sex||"").toUpperCase(); if(x==="М"||x==="Ж") return x; const c=String(e.category||"").toLowerCase();
  if(/юнош|мальч|мужч|^муж/.test(c)) return "М"; if(/девуш|девоч|женщ|^жен/.test(c)) return "Ж"; return "";};
function renderStart(){
  if(!SL){ $("sheet").innerHTML='<div class="empty">Загрузка…</div>'; loadStart(); return; }
  const ev=(R||SL).event, gf=$("grp").value, coach=$("showCoach").checked, sf=$("sexf").value;
  const list=$("smode").value==="list";
  const fe=a=>sf?a.filter(e=>sexOf(e)===sf):a;                        // фильтр «Мальчики / Девочки»
  const heatsAll=SL.heats.map(h=>Object.assign({},h,{entries:fe(h.entries)}));
  const looseAll=fe(SL.no_heat||[]);
  // техническая дисциплина (прыжки, метания: попытки) — печатная форма сама становится альбомной
  const tech=heatsAll.some(h=>(!gf||gkey(h)===gf)&&h.entries.length&&(h.slots||0)>0);
  const land=tech||(list&&$("orient").value==="landscape");
  setPage(land); if(tech&&list) $("orient").value="landscape";
  const all=heatsAll.concat([{entries:looseAll}]);
  const anyCoach=all.some(h=>h.entries.some(e=>e.coach)), anySeed=all.some(h=>h.entries.some(e=>e.seed));
  const anyLane=all.some(h=>h.entries.some(e=>e.lane)), anyRank=all.some(h=>h.entries.some(e=>e.rank));
  // таблица: бег — три пустые графы «Сек. 1–3»; техника — «Попытка 1–6» и «Лучший результат»
  const table=(entries,slots,rtype,withLane,numbered)=>{
    const grid=slots>0, rs=grid?2:1, W=(a,b)=>land?a:b;
    const head=`${numbered?`<th rowspan="${rs}" style="width:30px">№ п/п</th>`:""}${withLane?`<th rowspan="${rs}" style="width:42px">Дор.</th>`:""}<th rowspan="${rs}" style="width:50px">Нагр. №</th><th rowspan="${rs}">Фамилия, имя</th><th rowspan="${rs}" style="width:44px">Год рожд.</th>${anyRank?`<th rowspan="${rs}" style="width:50px">Разряд</th>`:""}<th rowspan="${rs}" style="width:${W("17%","24%")}">Команда</th>`
      +(coach&&anyCoach?`<th rowspan="${rs}" style="width:${W("12%","18%")}">Тренер</th>`:"")+(anySeed?`<th rowspan="${rs}" style="width:58px">Заявл. рез.</th>`:"")
      +(grid?`<th colspan="${slots}" class="sub" style="text-align:center">${rtype==="height"?"Высоты и попытки":"Попытки"}</th><th rowspan="2" style="width:74px">Лучший результат</th>`
            :`<th class="sub swh" style="width:62px">Сек. 1</th><th class="sub swh" style="width:62px">Сек. 2</th><th class="sub swh" style="width:62px">Сек. 3</th>`)
      +(numbered?`<th rowspan="${rs}" style="width:40px">Место</th>`:"");
    const sub=grid?`<tr>${Array.from({length:slots},(_,i)=>`<th class="sub">${rtype==="height"?"":"Попытка "+(i+1)}</th>`).join("")}</tr>`:"";
    const cells=grid?Array.from({length:slots},()=>'<td class="cell"></td>').join("")+'<td class="big"></td>':'<td class="cell sw"></td><td class="cell sw"></td><td class="cell sw"></td>';
    return `<table class="${grid?"att":"swt"}"><thead><tr>${head}</tr>${sub}</thead><tbody>
      ${entries.map((e,i)=>`<tr>${numbered?`<td class="c">${i+1}</td>`:""}${withLane?`<td class="c"><b>${e.lane??""}</b></td>`:""}<td class="c">${esc(e.bib)}</td><td>${esc(e.name||"")}${mem(e)}</td><td class="c">${esc(e.birth_year||"")}</td>${anyRank?`<td class="c">${esc(e.rank||"")}</td>`:""}<td>${esc(e.team||"")}</td>${coach&&anyCoach?`<td>${esc(e.coach||"")}</td>`:""}${anySeed?`<td class="r">${esc(e.seed||"")}</td>`:""}${cells}${numbered?"<td></td>":""}</tr>`).join("")}</tbody></table>`;
  };
  let body="";
  if(!list) heatsAll.forEach(h=>{
    if(gf&&gkey(h)!==gf) return;
    if(!h.entries.length) return;
    body+=`<h2>${esc(h.name)} <small>— ${esc(gtitle(h.distance,h.category))} · ${h.entries.length} уч.</small></h2>`+table(h.entries,h.slots||0,h.rtype,anyLane,false);
  });
  else{
    // «Общим списком»: все участники одной сквозной таблицей без забегов и дорожек
    const groups={};
    heatsAll.concat(looseAll.length?[{name:"",category:"",distance:"",entries:looseAll,rtype:"time",slots:0}]:[]).forEach(h=>{
      if(gf&&gkey(h)!==gf) return;
      const k=gkey(h), g=groups[k]||(groups[k]={dist:h.distance,cat:h.category,slots:h.slots||0,rtype:h.rtype||"time",entries:[]});
      h.entries.forEach(e=>g.entries.push(e));
    });
    Object.values(groups).forEach(g=>{
      if(!g.entries.length) return;
      g.entries.sort((a,b)=>(parseInt(a.bib)||0)-(parseInt(b.bib)||0));
      body+=`<h2>${esc(gtitle(g.dist,g.cat))} <small>— общий список${sf?" · "+(sf==="М"?"мальчики / юноши / мужчины":"девочки / девушки / женщины"):""} · ${g.entries.length} уч.</small></h2>`+table(g.entries,g.slots,g.rtype,false,true);
    });
  }
  if(!body) body=PUB?'<div class="empty">Стартовый протокол пока пуст.</div>':'<div class="empty">Забегов пока нет — сформируйте их во вкладке «Регистрация».</div>';
  $("sheet").innerHTML=headHtml(ev,"СТАРТОВЫЙ ПРОТОКОЛ")+body+
    `<div class="note">${list?"Участники записаны одним сквозным списком в порядке нагрудных номеров. ":"Забеги сформированы по заявленным результатам. "}${tech?"Графы «Попытка 1–6» и «Лучший результат» — для записи судьями от руки.":"Графы «Сек. 1–3» — для записи судьями показаний трёх ручных секундомеров."}</div>`+signs(ev)+
    `<div class="foot"><span>Сформировано: ${new Date().toLocaleString("ru-RU")}</span><span>${esc(ev.name)}</span></div>`;
}
```

Правила печати:
- техника (slots>0) → альбомный лист автоматически: @media print { @page { size: landscape } }
- бег: три пустые графы «Сек. 1 | Сек. 2 | Сек. 3»
- техника: «Попытка 1…6» + «Лучший результат» (+ «Место» в общем списке)
- фильтр пола: select #sexf (все / мальчики / девочки), работает в обоих режимах

## 5. Админка (ui.html): кнопки
- «Сформировать забеги из подтверждённых» (#gHeats), «Сформировать общим списком из подтверждённых» (#gList)
- переключатель вида протокола (#gPMode), красная «❌ Удалить все забеги / Сбросить сетку» (#gResetHeats)
