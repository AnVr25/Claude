#!/usr/bin/env bash
# =============================================================================
#  Внешняя резервная копия базы SakhStart (раз в сутки из cron, установщик ставит сам).
#
#   1. снимок базы (sqlite3 .backup — безопасно на работающем сервере);
#   2. сжатие и шифрование AES-256 (openssl, ключ /etc/timing-hub/backup.key — создаётся при первом запуске);
#   3. если задан REMOTE в /etc/timing-hub/offsite.env — копия уходит на другой сервер по SSH (rsync);
#   4. проверка восстановления: копия расшифровывается во временную папку и проверяется (timing-restore-check);
#   5. итог — в /var/lib/timing-hub/offsite/status.json (его показывает «Система»).
#
#  Без ключа копия бесполезна: сохраните /etc/timing-hub/backup.key отдельно от сервера (флешка, сейф).
#  Копии в /var/lib/timing-hub/offsite можно скачать из «Системы» на компьютер Федерации.
#
#  /etc/timing-hub/offsite.env (необязательно):
#     REMOTE="backup@10.0.0.5:/srv/sakhstart"     # куда копировать по SSH
#     SSH_KEY="/root/.ssh/sakhstart_backup"        # ключ доступа к тому серверу
#     KEEP=14                                      # сколько копий хранить здесь
# =============================================================================
set -euo pipefail
DATA_DIR="${DATA_DIR:-/var/lib/timing-hub}"
CFG_DIR="${CFG_DIR:-/etc/timing-hub}"
SVC_USER="${SVC_USER:-timinghub}"
KEY="$CFG_DIR/backup.key"
OUT="$DATA_DIR/offsite"
REMOTE="" SSH_KEY="" KEEP=14
[[ -f "$CFG_DIR/offsite.env" ]] && . "$CFG_DIR/offsite.env"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$(command -v timing-restore-check || echo "$HERE/restore-check.sh")"

install -d -m 750 -o root -g "$SVC_USER" "$OUT" 2>/dev/null || mkdir -p "$OUT"
if [[ ! -s "$KEY" ]]; then
  ( umask 077; openssl rand -base64 48 > "$KEY" )
  echo "Создан ключ шифрования копий $KEY — сохраните его отдельно от сервера"
fi

TS="$(date +%F_%H%M)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
sqlite3 "$DATA_DIR/reads.db" ".backup '$TMP/reads.db'"
FILE="$OUT/sakhstart-$TS.db.gz.enc"
gzip -c "$TMP/reads.db" | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$KEY" -out "$FILE.part"
mv "$FILE.part" "$FILE"
chown root:"$SVC_USER" "$FILE" 2>/dev/null || true
chmod 640 "$FILE"

remote="off" remote_err=""
if [[ -n "$REMOTE" ]]; then
  ssh_opts="-o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new"
  [[ -n "$SSH_KEY" ]] && ssh_opts="$ssh_opts -i $SSH_KEY"
  if out="$(rsync -a --timeout=120 -e "ssh $ssh_opts" "$FILE" "$REMOTE/" 2>&1)"; then
    remote="ok"
  else
    remote="fail"; remote_err="$(echo "$out" | tail -n 1 | tr -d '"\\' | cut -c1-200)"
  fi
fi

check="fail" detail=""
if detail="$(bash "$CHECK" "$FILE" 2>&1)"; then check="ok"; fi
detail="$(echo "$detail" | tail -n 1 | tr -d '"\\' | cut -c1-200)"

# храним KEEP последних копий
ls -1t "$OUT"/sakhstart-*.db.gz.enc 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

size="$(stat -c %s "$FILE")"
host="${REMOTE%%:*}"; host="${host#*@}"
cat > "$OUT/status.json.part" <<EOF
{"at": "$(date '+%F %T')", "file": "$(basename "$FILE")", "size": $size, "keep": $KEEP,
 "remote": "$remote", "remote_host": "$host", "remote_error": "$remote_err",
 "check": "$check", "check_detail": "$detail",
 "key_fingerprint": "$(sha256sum "$KEY" | cut -c1-12)"}
EOF
mv "$OUT/status.json.part" "$OUT/status.json"
chown root:"$SVC_USER" "$OUT/status.json" 2>/dev/null || true
chmod 640 "$OUT/status.json"
echo "копия: $FILE · на другой сервер: $remote · проверка восстановления: $check ($detail)"
[[ "$check" == "ok" && "$remote" != "fail" ]]
