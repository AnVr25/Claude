#!/usr/bin/env bash
# Установка новой версии по заявке из интерфейса администратора.
# Запускается systemd-сервисом gto-update от пользователя gto-deploy, когда в
# $QUEUE появляется файл request с хешем коммита. Порядок:
#   скачать архив коммита с GitHub → прогнать тесты → сохранить текущую версию →
#   подменить код → перезапустить gto → проверить, что отвечает; иначе вернуть прежнюю.
# Копия скрипта лежит вне каталога приложения (её ставит install.sh), чтобы обновление
# не подменяло работающий скрипт.
set -euo pipefail

REPO="${GTO_UPDATE_REPO:-AnVr25/Claude}"
QUEUE="${GTO_UPDATE_DIR:-/var/lib/gto-update}"
APP="${GTO_APP_DIR:-/opt/gto/app}"
WORK="${GTO_UPDATE_WORK:-/opt/gto/updates}"
NODE="${GTO_NODE:-/opt/gto/node/bin/node}"
RESTART="${GTO_RESTART_CMD:-sudo -n /usr/bin/systemctl restart gto}"
PORT="${PORT:-$(grep -s '^PORT=' /etc/gto.env | cut -d= -f2)}"
PORT="${PORT:-3100}"
SHA=""

status() { # state message
  local msg=${2//\"/\'}
  printf '{"state":"%s","message":"%s","sha":"%s","at":"%s"}\n' "$1" "$msg" "$SHA" "$(date -Is)" > "$QUEUE/status.json.tmp"
  mv -f "$QUEUE/status.json.tmp" "$QUEUE/status.json"
  echo "[$1] $2"
}

[[ -f "$QUEUE/request" ]] || exit 0
SHA=$(tr -cd '0-9a-f' < "$QUEUE/request" | head -c 40)
rm -f "$QUEUE/request"
[[ ${#SHA} -eq 40 ]] || { status error "Некорректная заявка"; exit 1; }

trap 'status error "Обновление прервано (строка $LINENO) — текущая версия не менялась"' ERR

status running "Скачиваю версию ${SHA:0:7} с GitHub"
mkdir -p "$WORK"
rm -rf "$WORK/new" && mkdir -p "$WORK/new"
curl -fsSL --max-time 120 "https://codeload.github.com/$REPO/tar.gz/$SHA" \
  | tar -xz -C "$WORK/new" --strip-components=2 --wildcards '*/gto/*'
[[ -f "$WORK/new/server.js" ]] || { trap - ERR; status error "В архиве нет приложения — обновление отменено"; exit 1; }

status running "Проверяю новую версию (автотесты)"
if ! (cd "$WORK/new" && timeout 300 "$NODE" --no-warnings=ExperimentalWarning --test test/*.test.js) > "$WORK/test.log" 2>&1; then
  trap - ERR
  status error "Автотесты не прошли — обновление отменено, работает прежняя версия"
  exit 1
fi
printf '{"sha":"%s","installed_at":"%s"}\n' "$SHA" "$(date -Is)" > "$WORK/new/VERSION.json"

status running "Устанавливаю"
rm -rf "$WORK/prev" && mkdir -p "$WORK/prev"
cp -a "$APP/." "$WORK/prev/"
find "$APP" -mindepth 1 -delete
cp -a "$WORK/new/." "$APP/"
trap - ERR

healthy() {
  for _ in $(seq 1 20); do
    curl -fsS --max-time 3 "http://127.0.0.1:$PORT/" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

status running "Перезапускаю приложение"
if $RESTART && healthy; then
  rm -rf "$WORK/new"
  status ok "Обновлено до версии ${SHA:0:7}"
else
  find "$APP" -mindepth 1 -delete
  cp -a "$WORK/prev/." "$APP/"
  $RESTART || true
  status error "Новая версия не запустилась — возвращена прежняя"
  exit 1
fi
