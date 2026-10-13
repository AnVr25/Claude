# Обновление с GitHub из кабинета: код кнопки «Проверить обновления»

Кнопка живёт в кабинете SakhStart: **Система (шестерёнка) → Оборудование → блок «Обновление сервера»**.

## Куда она ведёт

1. Нажатие → браузер вызывает `GET /api/system/update/github/check`.
2. Сервер (не браузер) идёт на GitHub: берёт верхушку ветки из `GH_DEFAULT` (репозиторий `AnVr25/Claude`, ветка `claude/greeting-d2g8ji`, папка `timing-hub`), читает оттуда `hub/hub.py`, достаёт строку `VERSION = "…"` и последние 10 коммитов папки.
3. Если версия на GitHub отличается от установленной, появляется кнопка «Установить vX.Y.Z».
4. «Установить» → `POST /api/system/update/github` с хэшем коммита. Сервер сам скачивает zip этого коммита (`codeload.github.com`), собирает такой же `timing-hub.zip`, как при ручной загрузке, и отдаёт его в ту же цепочку `receive_update` → помощник `timing-update` (резервная копия, установка, перезапуск, автоматический откат при сбое).

Свой репозиторий или ветку (например, `main`) задаёт `config.json`, без правки кода:

```json
"update": {"repo": "owner/repo", "branch": "main", "dir": "timing-hub"}
```

Для приватного репозитория код выше не подойдёт: он ходит на GitHub без токена.

## Что взять в другой проект

Нужны три куска: кнопка в HTML, обработчик в браузере, два метода и два маршрута на сервере. Сервер должен уметь «принять zip и поставить» (`receive_update`): в этом проекте это отдельная цепочка, её код здесь не приведён.

### HTML

```html
<button class="primary" id="ghCheck">Проверить обновления</button>
<div id="ghBox"></div>
```

### Браузер (JavaScript)

```js
// Обновление с GitHub: сервер сам скачивает официальную версию и ставит её так же, как архив из файла
$("ghCheck").onclick = async () => {
  const box = $("ghBox");
  box.innerHTML = "⏳ Проверяю на GitHub…";
  let r;
  try{
    const res = await fetch("/api/system/update/github/check");
    r = await res.json();
    if (!res.ok) throw new Error(r.error || res.status);
  }catch(err){ box.innerHTML = `❌ ${esc(err.message)}`; return; }
  const list = (r.changes || []).map(c => `<li>${esc(c.message)} <span class="muted mono">· ${esc(c.sha)} · ${esc((c.date||"").slice(0,10))}</span></li>`).join("");
  if (!r.newer) {
    box.innerHTML = `✅ Установлена последняя версия <b>v${esc(r.current)}</b>.` + (list ? `<details style="margin-top:4px"><summary class="muted">Последние изменения</summary><ul>${list}</ul></details>` : "");
    return;
  }
  box.innerHTML = `Доступна версия <b>v${esc(r.latest)}</b> (сейчас v${esc(r.current)}). Последние изменения:<ul style="margin:4px 0">${list}</ul>` +
    `<button class="primary" id="ghInstall">⬇ Установить v${esc(r.latest)}</button>`;
  $("ghInstall").onclick = async () => {
    if (!confirm(`Установить v${r.latest} с GitHub?\n\nСервер перезапустится (около минуты). Прежняя версия сохранится, при сбое вернётся сама.`)) return;
    $("ghInstall").disabled = true; $("ghInstall").textContent = "⏳ Скачиваю…";
    try{
      const res = await fetch("/api/system/update/github", {method:"POST", body: JSON.stringify({sha: r.sha}), headers:{"X-Requested-With":"timing-hub","Content-Type":"application/json"}});
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || res.status);
      toast(`Принято: v${j.from} → v${j.to}. Устанавливаю…`);
      box.innerHTML = "";
    }catch(err){ toast("Ошибка: " + err.message); $("ghInstall").disabled = false; $("ghInstall").textContent = `⬇ Установить v${r.latest}`; }
    setTimeout(loadUpdate, 1000);
  };
};
```

### Сервер (Python): проверка и скачивание

```python
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
```

### Сервер: маршруты (внутри обработчика запросов, после проверки входа администратора; `receive_update` — приём zip и запуск установки)

```python
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
```
