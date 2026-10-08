#!/usr/bin/env bash
# Установка обновления, загруженного через браузер (вкладка «Оборудование» → «Обновление сервера»).
# Запускается systemd (timing-update.path) от root, когда появляется /var/lib/timing-hub/update/incoming.zip.
# Перед установкой install.sh сам сохраняет прежнюю версию; если после установки сервер не поднялся —
# автоматический откат (timing-rollback last).
set -uo pipefail
U=/var/lib/timing-hub/update
IN="$U/incoming.zip"
ST="$U/status.json"
LOG="$U/last.log"
W=/root/timing-updates
[[ -f "$IN" ]] || exit 0
mkdir -p "$W"
ts="$(date +%F_%H%M%S)"
status() {  # статус для страницы: этап, текст, время
  printf '{"state":"%s","message":"%s","at":"%s","file":"%s"}\n' "$1" "$2" "$(date '+%F %T')" "$ts.zip" > "$ST.tmp"
  chmod 644 "$ST.tmp"; mv "$ST.tmp" "$ST"
}
mv "$IN" "$W/$ts.zip"
status running "устанавливаю обновление"
exec > "$LOG" 2>&1
chmod 644 "$LOG"
echo "== $(date '+%F %T') обновление из браузера: $W/$ts.zip"
sha256sum "$W/$ts.zip"
D="$(mktemp -d)"
if ! unzip -q "$W/$ts.zip" -d "$D"; then status failed "архив повреждён — не распаковался"; exit 1; fi
KIT="$D/timing-hub"
if [[ ! -f "$KIT/install.sh" || ! -f "$KIT/hub/hub.py" ]]; then
  status failed "это не архив сервера хронометража (нет timing-hub/install.sh)"; rm -rf "$D"; exit 1
fi
if ! python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$KIT/hub/hub.py"; then
  status failed "в архиве повреждённая программа — не устанавливаю"; rm -rf "$D"; exit 1
fi
NEWV="$(grep -m1 -o 'VERSION = "[^"]*"' "$KIT/hub/hub.py" | cut -d'"' -f2)"
before="$(systemctl show -p NRestarts --value timing-hub 2>/dev/null || echo 0)"
if ! bash "$KIT/install.sh"; then
  echo "!! install.sh завершился с ошибкой — откат"
  /usr/local/sbin/timing-rollback last && status rolledback "установка $NEWV не удалась — вернул прежнюю версию" \
    || status failed "установка не удалась, откат тоже — нужен вход через консоль"
  rm -rf "$D"; exit 1
fi
sleep 10
NOWV="$(grep -m1 -o 'VERSION = "[^"]*"' /opt/timing-hub/hub.py | cut -d'"' -f2)"
if systemctl is-active --quiet timing-hub && [[ "$NOWV" == "$NEWV" ]]; then
  status ok "установлена версия $NEWV"
  echo "== готово: $NEWV"
else
  echo "!! сервер не поднялся после обновления — откат"
  journalctl -u timing-hub -n 30 --no-pager -o cat
  /usr/local/sbin/timing-rollback last && status rolledback "версия $NEWV не запустилась — вернул прежнюю" \
    || status failed "версия $NEWV не запустилась, откат не удался — нужен вход через консоль"
fi
rm -rf "$D"
ls -1t "$W"/*.zip 2>/dev/null | tail -n +6 | xargs -r rm -f   # храним 5 последних архивов
