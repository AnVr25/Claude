#!/usr/bin/env bash
# Откат сервера хронометража к версии до последнего обновления.
#   sudo timing-rollback            — список сохранённых версий
#   sudo timing-rollback last       — вернуть программу и настройки из последней копии
#   sudo timing-rollback ИМЯ        — из конкретной копии (имя из списка)
#   sudo timing-rollback last --with-db — ещё и базу (отметки после копии пропадут!)
set -euo pipefail
B=/var/backups/timing-hub
APP=/opt/timing-hub
CFG=/etc/timing-hub/config.json
DB=/var/lib/timing-hub/reads.db
[[ $EUID -eq 0 ]] || { echo "запустите от root"; exit 1; }
if [[ -z "${1:-}" ]]; then
  echo "Сохранённые версии (новые внизу):"
  ls -1 "$B" 2>/dev/null | while read -r d; do
    v="$(cat "$B/$d/version.txt" 2>/dev/null || echo '?')"; echo "  $d   ($v)"; done
  echo; echo "Откат:  timing-rollback last   (или имя из списка)"
  exit 0
fi
name="$1"; [[ "$name" == last ]] && name="$(ls -1 "$B" | tail -1)"
S="$B/$name"; [[ -d "$S/app" ]] || { echo "нет копии $name"; exit 1; }
echo "Откатываю программу из $S"
systemctl stop timing-hub
rm -rf "$APP.failed"; [[ -d "$APP" ]] && mv "$APP" "$APP.failed"
cp -a "$S/app" "$APP"
[[ -f "$S/config.json" ]] && cp -a "$S/config.json" "$CFG"
if [[ "${2:-}" == "--with-db" && -f "$S/reads.db" ]]; then
  cp -a "$DB" "$DB.before-rollback.$(date +%F-%H%M)" 2>/dev/null || true
  rm -f "$DB-wal" "$DB-shm"
  cp -a "$S/reads.db" "$DB"; chown timinghub:timinghub "$DB" 2>/dev/null || true
  echo "База тоже возвращена (текущая сохранена рядом как .before-rollback)"
fi
systemctl start timing-hub; sleep 3
systemctl is-active --quiet timing-hub && echo "Готово: сервер работает на старой версии." \
  || { echo "Сервер не запустился: journalctl -u timing-hub -n 30"; exit 1; }
echo "Неудачная новая версия лежит в $APP.failed (можно удалить)."
