#!/usr/bin/env bash
# Установка / обновление «ГТО: учёт результатов» на Ubuntu 22.04+ рядом с уже работающими сайтами.
#
#   sudo bash deploy/install.sh gto.fla65.ru admin@fla65.ru
#
# Что делает (повторный запуск безопасен — обновляет код и сохраняет базу):
#   • ставит Node.js 22 отдельно в /opt/gto/node — системный Node и другие программы не трогает;
#   • копирует приложение в /opt/gto/app, база — /var/lib/gto/gto.sqlite;
#   • запускает сервис systemd «gto» на свободном локальном порту;
#   • добавляет в nginx отдельный сайт для домена (чужие сайты не меняет) и получает HTTPS-сертификат;
#   • настраивает ежедневную резервную копию базы (/var/backups/gto, 30 дней);
#   • при первой установке создаёт администратора и печатает его пароль.
set -euo pipefail

DOMAIN="${1:-gto.fla65.ru}"
EMAIL="${2:-}"
APP_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE=/opt/gto
DATA=/var/lib/gto
BACKUPS=/var/backups/gto
NODE_MAJOR=22

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "запустите через sudo"
[[ -f "$APP_SRC/server.js" ]] || die "не найден server.js рядом со скриптом ($APP_SRC)"
command -v apt-get >/dev/null || die "нужна Ubuntu/Debian"

say "Пакеты: curl, xz, sqlite3, cron (на minimized-Ubuntu их может не быть)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl xz-utils sqlite3 ca-certificates cron iproute2 >/dev/null
systemctl enable --now cron >/dev/null 2>&1 || warn "не удалось включить cron — резервные копии по расписанию работать не будут"

# ---------- Node.js отдельно от системного ----------
NODE_BIN="$BASE/node/bin/node"
need_node=1
if [[ -x "$NODE_BIN" ]]; then
  v=$("$NODE_BIN" -p 'process.versions.node')
  [[ "${v%%.*}" -ge $NODE_MAJOR ]] && need_node=0
fi
if [[ $need_node -eq 1 ]]; then
  say "Node.js $NODE_MAJOR → $BASE/node"
  case "$(uname -m)" in
    x86_64) arch=x64 ;; aarch64) arch=arm64 ;; *) die "неизвестная архитектура $(uname -m)" ;;
  esac
  tmp=$(mktemp -d)
  url="https://nodejs.org/dist/latest-v${NODE_MAJOR}.x"
  curl -fsSL "$url/SHASUMS256.txt" -o "$tmp/SHASUMS256.txt"
  file=$(grep -o "node-v[0-9.]*-linux-${arch}.tar.xz" "$tmp/SHASUMS256.txt" | head -1)
  [[ -n "$file" ]] || die "не нашёл сборку Node.js"
  curl -fsSL "$url/$file" -o "$tmp/$file"
  (cd "$tmp" && grep " $file\$" SHASUMS256.txt | sha256sum -c --quiet -) || die "контрольная сумма Node.js не совпала"
  rm -rf "$BASE/node" && mkdir -p "$BASE/node"
  tar -xJf "$tmp/$file" -C "$BASE/node" --strip-components=1
  rm -rf "$tmp"
fi
echo "Node.js $("$NODE_BIN" -v)"

# ---------- пользователь и файлы ----------
say "Приложение → $BASE/app"
id gto >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin gto
mkdir -p "$BASE/app" "$DATA" "$BACKUPS"
# копируем только код; база живёт в $DATA и при обновлении не затирается
tar -C "$APP_SRC" --exclude=./data --exclude=./node_modules --exclude='*.sqlite*' -cf - . | tar -C "$BASE/app" -xf -
chown -R root:root "$BASE/app"
chown gto:gto "$DATA"
chmod 750 "$DATA"
chmod 700 "$BACKUPS"

# ---------- порт ----------
ENV_FILE=/etc/gto.env
if [[ -f "$ENV_FILE" ]] && grep -q '^PORT=' "$ENV_FILE"; then
  PORT=$(grep '^PORT=' "$ENV_FILE" | cut -d= -f2)
else
  PORT=3100
  while ss -ltn "( sport = :$PORT )" | grep -q LISTEN; do PORT=$((PORT + 1)); done
fi
echo "Порт приложения: 127.0.0.1:$PORT"

# ---------- nginx ----------
HAVE_NGINX=0
if command -v nginx >/dev/null; then
  HAVE_NGINX=1
elif ss -ltnp '( sport = :80 )' | grep -q LISTEN; then
  warn "Порт 80 занят не nginx: $(ss -ltnp '( sport = :80 )' | tail -n +2 | awk '{print $NF}')"
  warn "nginx ставить не буду. Направьте $DOMAIN на 127.0.0.1:$PORT в вашем веб-сервере вручную."
else
  say "Устанавливаю nginx"
  apt-get install -y -qq nginx >/dev/null
  HAVE_NGINX=1
fi

SECURE=0
if [[ $HAVE_NGINX -eq 1 ]]; then
  say "nginx: сайт $DOMAIN"
  if [[ -d /etc/nginx/sites-available ]]; then
    SITE=/etc/nginx/sites-available/gto
    LINK=/etc/nginx/sites-enabled/gto
  else
    SITE=/etc/nginx/conf.d/gto.conf
    LINK=""
  fi
  # если сертификат уже получали — certbot дописал свои строки, не перезаписываем
  if [[ -f "$SITE" ]] && grep -q 'managed by Certbot' "$SITE"; then
    sed -i "s#proxy_pass http://127.0.0.1:[0-9]*;#proxy_pass http://127.0.0.1:$PORT;#" "$SITE"
  else
    cat > "$SITE" <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    client_max_body_size 15m;   # загрузка списков .xlsx

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
NGINX
  fi
  [[ -n "$LINK" ]] && ln -sf "$SITE" "$LINK"
  nginx -t || die "конфигурация nginx не прошла проверку — сайт $SITE можно удалить, остальное не тронуто"
  systemctl reload nginx || systemctl restart nginx

  # ---------- HTTPS ----------
  # Домен должен указывать на этот сервер: сверяем с адресами интерфейсов, внешний сервис — запасной вариант
  dns_ip=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}' || true)
  server_ip=""
  if [[ -n "$dns_ip" ]] && hostname -I | tr ' ' '\n' | grep -qx "$dns_ip"; then
    server_ip=$dns_ip
  else
    server_ip=$(curl -fsS4 --max-time 8 https://api.ipify.org 2>/dev/null || true)
  fi
  if grep -q 'managed by Certbot' "$SITE"; then
    SECURE=1
  elif [[ -n "$EMAIL" && -n "$server_ip" && "$dns_ip" == "$server_ip" ]]; then
    say "HTTPS-сертификат Let's Encrypt для $DOMAIN"
    apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
    if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect; then
      SECURE=1
    else
      warn "certbot не смог получить сертификат — сайт пока работает по http"
    fi
  else
    warn "HTTPS пока не настроен: DNS $DOMAIN → '${dns_ip:-нет}', IP сервера '${server_ip:-?}', e-mail '${EMAIL:-не указан}'."
    warn "Когда DNS обновится, запустите скрипт ещё раз с e-mail вторым параметром."
  fi

  # Порт 443 может держать не nginx, а, например, OpenVPN с port-share: он пересылает обычный
  # https в nginx на локальный порт (у reg.fla65.ru это 127.0.0.1:8443). Тогда https-часть сайта
  # должна слушать тот же локальный порт — nginx выберет сертификат по имени домена.
  if [[ $SECURE -eq 1 ]] && ss -ltnp '( sport = :443 )' | tail -n +2 | grep -qv nginx; then
    share=$(nginx -T 2>/dev/null | grep -oE 'listen[[:space:]]+127\.0\.0\.1:[0-9]+[[:space:]]+ssl[^;]*' | head -1 | sed -E 's/^listen[[:space:]]+//')
    if [[ -n "$share" ]]; then
      say "Порт 443 занят $(ss -ltnp '( sport = :443 )' | grep -o 'users:(("[^"]*' | cut -d'"' -f2 | head -1) — https для $DOMAIN через $share"
      sed -i -E \
        -e "s|^([[:space:]]*)listen[[:space:]]+\[::\]:443[[:space:]]+ssl[^;]*;.*$|\1# [::]:443 занят другой программой — https приходит через $share|" \
        -e "s|^([[:space:]]*)listen[[:space:]]+443[[:space:]]+ssl[^;]*;.*$|\1listen $share; # managed by Certbot (перенесено с 443)|" \
        "$SITE"
      nginx -t || die "конфигурация nginx не прошла проверку после переноса на $share"
      systemctl reload nginx
    else
      warn "Порт 443 занят не nginx, и локальный порт для https не найден — HTTPS для $DOMAIN работать не будет."
    fi
  fi

  # Проверка: какой сертификат реально отдаётся для домена
  sleep 1
  got=$(curl -skv --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/" -o /dev/null 2>&1 | grep -o 'subject: .*' | head -1 || true)
  if [[ $SECURE -eq 1 && "$got" != *"$DOMAIN"* ]]; then
    warn "Для https://$DOMAIN отдаётся чужой сертификат (${got:-нет ответа}). Проверьте: journalctl -u nginx -n 20"
  fi
fi

# ---------- systemd ----------
say "Сервис gto"
cat > "$ENV_FILE" <<ENV
PORT=$PORT
HOST=127.0.0.1
GTO_DB=$DATA/gto.sqlite
GTO_SECURE_COOKIE=$SECURE
GTO_TRUST_PROXY=$HAVE_NGINX
ENV
cat > /etc/systemd/system/gto.service <<UNIT
[Unit]
Description=GTO results (fla65)
After=network.target

[Service]
Type=simple
User=gto
Group=gto
WorkingDirectory=$BASE/app
EnvironmentFile=$ENV_FILE
ExecStart=$NODE_BIN --no-warnings=ExperimentalWarning server.js
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable gto >/dev/null 2>&1
systemctl restart gto
sleep 2
systemctl is-active --quiet gto || { journalctl -u gto -n 30 --no-pager; die "сервис не запустился"; }
curl -fsS "http://127.0.0.1:$PORT/" >/dev/null || die "приложение не отвечает на 127.0.0.1:$PORT"

# ---------- резервные копии ----------
cat > /etc/cron.daily/gto-backup <<CRON
#!/bin/sh
# Ежедневная копия базы ГТО, хранится 30 дней
sqlite3 $DATA/gto.sqlite ".backup '$BACKUPS/gto-\$(date +%F).sqlite'" && find $BACKUPS -name 'gto-*.sqlite' -mtime +30 -delete
CRON
chmod 755 /etc/cron.daily/gto-backup

# ---------- администратор ----------
cli() { (cd "$BASE/app" && runuser -u gto -- env GTO_DB="$DATA/gto.sqlite" "$NODE_BIN" --no-warnings=ExperimentalWarning cli.js "$@"); }
if [[ -z "$(cli list-users)" ]]; then
  say "Создаю администратора"
  cli add-user admin admin "Администратор"
  warn "Сохраните пароль — повторно он не показывается (сбросить: sudo bash $BASE/app/deploy/gto-user.sh reset-password admin)"
fi

scheme=http; [[ $SECURE -eq 1 ]] && scheme=https
say "Готово: $scheme://$DOMAIN"
echo "Логи:       journalctl -u gto -f"
echo "Перезапуск: systemctl restart gto"
echo "Копии базы: $BACKUPS (ежедневно)"
