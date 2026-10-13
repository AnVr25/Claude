#!/usr/bin/env bash
# =============================================================================
#  Проверка восстановления из зашифрованной копии SakhStart.
#    sudo timing-restore-check                 — последняя копия из /var/lib/timing-hub/offsite
#    sudo timing-restore-check ФАЙЛ.db.gz.enc  — конкретная копия
#    sudo timing-restore-check ФАЙЛ --restore-to /tmp/reads.db   — расшифровать в файл (для восстановления)
#  Копия расшифровывается во временную папку, база проверяется (PRAGMA integrity_check), считаются
#  соревнования, заявки и тренеры. Временные файлы удаляются. Рабочую базу скрипт не трогает.
# =============================================================================
set -euo pipefail
CFG_DIR="${CFG_DIR:-/etc/timing-hub}"
OUT="${DATA_DIR:-/var/lib/timing-hub}/offsite"
KEY="${BACKUP_KEY:-$CFG_DIR/backup.key}"
FILE="${1:-}"
DEST=""
[[ "${2:-}" == "--restore-to" ]] && DEST="${3:?укажите файл}"
[[ -n "$FILE" ]] || FILE="$(ls -1t "$OUT"/sakhstart-*.db.gz.enc 2>/dev/null | head -n 1 || true)"
[[ -n "$FILE" && -f "$FILE" ]] || { echo "нет копии для проверки"; exit 1; }
[[ -s "$KEY" ]] || { echo "нет ключа $KEY"; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEY" -in "$FILE" 2>/dev/null | gunzip -c > "$TMP/reads.db" 2>/dev/null; then
  echo "не расшифровывается: неверный ключ или повреждённый файл"; exit 1
fi
ic="$(sqlite3 "$TMP/reads.db" 'PRAGMA integrity_check;' 2>&1 | head -n 1)"
[[ "$ic" == "ok" ]] || { echo "база повреждена: $ic"; exit 1; }
cnt() { sqlite3 "$TMP/reads.db" "SELECT COUNT(*) FROM $1;" 2>/dev/null || echo 0; }
if [[ -n "$DEST" ]]; then cp "$TMP/reads.db" "$DEST"; echo "расшифровано в $DEST"; fi
echo "восстановление проверено: соревнований $(cnt events), заявок $(cnt registrations), тренеров $(cnt trainers)"
