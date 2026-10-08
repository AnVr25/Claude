#!/usr/bin/env bash
# =============================================================================
#  Установка сервера хронометража на чистый Ubuntu 22.04 / 24.04 (VPS на KVM)
#
#  Запуск из папки комплекта:
#      sudo bash install.sh
#
#  Необязательные параметры:
#      --endpoint 1.2.3.4    внешний IP или домен сервера (по умолчанию определяется сам)
#      --wg-port 51820       UDP-порт VPN
#      --tz Asia/Sakhalin    часовой пояс соревнований
#      --public-ingest       открыть порты приёма от ридеров в интернет (если ридер
#                            шлёт данные через свой 4G без VPN). Без VPN кто угодно
#                            сможет отправить на этот порт подделку — включайте
#                            осознанно и только на время старта.
#
#  Повторный запуск безопасен: ключи VPN, пароли и настройки не перезаписываются,
#  обновляется только программа сервера.
# =============================================================================
set -euo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENDPOINT=""
WG_PORT="51820"
TZ_NAME="Asia/Sakhalin"
PUBLIC_INGEST=0
WG_IF="wg0"
WG_NET="10.66.0"
WG_DIR="/etc/wireguard"
APP_DIR="/opt/timing-hub"
CFG_DIR="/etc/timing-hub"
DATA_DIR="/var/lib/timing-hub"
SVC_USER="timinghub"

c_blue=$'\033[1;34m'; c_red=$'\033[1;31m'; c_green=$'\033[1;32m'; c_yel=$'\033[1;33m'; c_off=$'\033[0m'
step() { echo; echo "${c_blue}==> $*${c_off}"; }
warn() { echo "${c_yel}ВНИМАНИЕ: $*${c_off}"; }
die()  { echo "${c_red}ОШИБКА: $*${c_off}" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --endpoint)      ENDPOINT="${2:-}"; shift 2 ;;
    --wg-port)       WG_PORT="${2:-}"; shift 2 ;;
    --tz)            TZ_NAME="${2:-}"; shift 2 ;;
    --public-ingest) PUBLIC_INGEST=1; shift ;;
    -h|--help)       sed -n '2,22p' "$0"; exit 0 ;;
    *) die "неизвестный параметр: $1 (см. sudo bash install.sh --help)" ;;
  esac
done

# --------------------------------------------------------------------------- #
step "Проверяю систему"
[[ $EUID -eq 0 ]] || die "запустите от root: sudo bash install.sh"
[[ -f "$KIT_DIR/hub/hub.py" ]] || die "не найден $KIT_DIR/hub/hub.py — запускайте из распакованной папки комплекта"
. /etc/os-release
[[ "${ID:-}" == "ubuntu" || "${ID:-}" == "debian" ]] || die "нужен Ubuntu 22.04/24.04 (или Debian 12), а здесь: ${PRETTY_NAME:-неизвестно}"
[[ "$WG_PORT" =~ ^[0-9]+$ ]] || die "--wg-port должен быть числом"
VIRT="$(systemd-detect-virt 2>/dev/null || true)"
case "$VIRT" in
  openvz|lxc|lxc-libvirt)
    die "сервер работает в контейнере ($VIRT) — в нём не запустится VPN WireGuard. Нужен VPS на KVM." ;;
esac
echo "  ОС: ${PRETTY_NAME}, виртуализация: ${VIRT:-нет}"

# --------------------------------------------------------------------------- #
step "Ставлю пакеты (WireGuard, firewall, Python, синхронизация времени)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q wireguard-tools qrencode ufw python3 sqlite3 chrony cron curl iproute2 >/dev/null
PYV="$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')"
[[ "$PYV" -ge 310 ]] || die "нужен Python 3.10 или новее (стоит $(python3 --version))"

if ! ip link show "$WG_IF" >/dev/null 2>&1; then
  if ! ip link add wgtest0 type wireguard 2>/dev/null; then
    modprobe wireguard 2>/dev/null || true
    ip link add wgtest0 type wireguard 2>/dev/null \
      || die "ядро не поддерживает WireGuard. Нужен VPS на KVM с обычным ядром Ubuntu."
  fi
  ip link del wgtest0 2>/dev/null || true
fi

# --------------------------------------------------------------------------- #
step "Ставлю часовой пояс $TZ_NAME и синхронизацию времени"
timedatectl set-timezone "$TZ_NAME" || die "неизвестный часовой пояс $TZ_NAME"
systemctl enable --now chrony >/dev/null 2>&1 || systemctl enable --now chronyd >/dev/null 2>&1 || true
echo "  Время сервера: $(date '+%d.%m.%Y %H:%M:%S %Z')"

# --------------------------------------------------------------------------- #
step "Определяю внешний адрес сервера"
if [[ -z "$ENDPOINT" ]]; then
  ENDPOINT="$(curl -4 -fsS --max-time 6 https://ifconfig.me 2>/dev/null || true)"
  [[ -n "$ENDPOINT" ]] || ENDPOINT="$(curl -4 -fsS --max-time 6 https://api.ipify.org 2>/dev/null || true)"
  [[ -n "$ENDPOINT" ]] || ENDPOINT="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
fi
[[ -n "$ENDPOINT" ]] || die "не удалось определить внешний IP. Укажите вручную: sudo bash install.sh --endpoint ВАШ_IP"
if [[ "$ENDPOINT" =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) ]]; then
  warn "адрес $ENDPOINT — внутренний. Если у сервера есть внешний IP, перезапустите с --endpoint ВНЕШНИЙ_IP"
fi
echo "  Внешний адрес: $ENDPOINT"

# --------------------------------------------------------------------------- #
step "Настраиваю VPN (WireGuard)"
umask 077
mkdir -p "$WG_DIR/clients"
[[ -f "$WG_DIR/server.key" ]] || wg genkey > "$WG_DIR/server.key"
wg pubkey < "$WG_DIR/server.key" > "$WG_DIR/server.pub"
if [[ ! -f "$WG_DIR/$WG_IF.conf" ]]; then
  cat > "$WG_DIR/$WG_IF.conf" <<EOF
# VPN сервера хронометража. Клиентов добавляет команда: timing-peer add ИМЯ
[Interface]
Address = ${WG_NET}.1/24
ListenPort = ${WG_PORT}
PrivateKey = $(cat "$WG_DIR/server.key")
EOF
  echo "  Создан $WG_DIR/$WG_IF.conf"
else
  WG_PORT="$(awk -F'=' '/^[[:space:]]*ListenPort/{gsub(/[[:space:]]/,"",$2); print $2; exit}' "$WG_DIR/$WG_IF.conf")"
  echo "  VPN уже настроен ранее — ключи и клиенты сохранены (порт $WG_PORT)"
fi
cat > "$WG_DIR/timing-hub.env" <<EOF
ENDPOINT=${ENDPOINT}
WG_PORT=${WG_PORT}
WG_NET=${WG_NET}
WG_IF=${WG_IF}
EOF
umask 022
cat > /etc/sysctl.d/99-timing-hub.conf <<EOF
# VPN-клиенты сервера хронометража видят друг друга (ноутбук Wiclax <-> ридеры)
net.ipv4.ip_forward = 1
EOF
sysctl -q --system >/dev/null
systemctl enable "wg-quick@$WG_IF" >/dev/null 2>&1
systemctl restart "wg-quick@$WG_IF"
ip -4 addr show "$WG_IF" | grep -q "${WG_NET}.1" || die "VPN не поднялся: journalctl -u wg-quick@$WG_IF"
echo "  VPN работает: сервер в сети ${WG_NET}.0/24 имеет адрес ${WG_NET}.1"

# --------------------------------------------------------------------------- #
step "Ставлю программу сервера"
id "$SVC_USER" >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SVC_USER"
# копия текущей версии перед обновлением — для отката: sudo timing-rollback last
if [[ -f "$APP_DIR/hub.py" ]]; then
  SNAP="/var/backups/timing-hub/$(date +%F_%H%M%S)"
  mkdir -p "$SNAP"
  cp -a "$APP_DIR" "$SNAP/app"
  [[ -f "$CFG_DIR/config.json" ]] && cp -a "$CFG_DIR/config.json" "$SNAP/config.json"
  [[ -f "$DATA_DIR/reads.db" ]] && sqlite3 "$DATA_DIR/reads.db" ".backup '$SNAP/reads.db'" 2>/dev/null || true
  (grep -m1 -o 'VERSION = "[^"]*"' "$APP_DIR/hub.py" || echo "версия ?") > "$SNAP/version.txt"
  chmod -R go-rwx "$SNAP"
  ls -1d /var/backups/timing-hub/*/ 2>/dev/null | head -n -5 | xargs -r rm -rf   # храним 5 последних
  echo "  Копия прежней версии: $SNAP  (откат: sudo timing-rollback last)"
fi
install -d -m 755 "$APP_DIR" "$APP_DIR/tools" "$APP_DIR/wiclax"
install -m 755 "$KIT_DIR/hub/hub.py" "$APP_DIR/hub.py"
install -m 644 "$KIT_DIR"/hub/*.html "$APP_DIR/"
# фирменный стиль: шрифты, логотипы, общий brand.css (работают и без интернета)
if [[ -d "$KIT_DIR/hub/assets" ]]; then
  install -d -m 755 "$APP_DIR/assets"
  find "$APP_DIR/assets" -maxdepth 1 -type f -delete
  install -m 644 "$KIT_DIR"/hub/assets/* "$APP_DIR/assets/"
fi
[[ -f "$KIT_DIR/ovpn.sh" ]] && install -m 755 "$KIT_DIR/ovpn.sh" /usr/local/sbin/timing-ovpn
[[ -f "$KIT_DIR/reg-setup.sh" ]] && install -m 755 "$KIT_DIR/reg-setup.sh" /usr/local/sbin/timing-reg-setup
[[ -f "$KIT_DIR/rollback.sh" ]] && install -m 755 "$KIT_DIR/rollback.sh" /usr/local/sbin/timing-rollback
# обновление из браузера: сервер кладёт архив в update/, root-служба ставит его с автооткатом
if [[ -f "$KIT_DIR/update.sh" ]]; then
  install -m 755 "$KIT_DIR/update.sh" /usr/local/sbin/timing-update
  install -d -m 770 -o "$SVC_USER" -g "$SVC_USER" "$DATA_DIR/update" 2>/dev/null || install -d -m 770 "$DATA_DIR/update"
  cat > /etc/systemd/system/timing-update.path <<UEOF
[Unit]
Description=Timing hub - watch for browser-uploaded update

[Path]
PathExists=$DATA_DIR/update/incoming.zip
Unit=timing-update.service

[Install]
WantedBy=multi-user.target
UEOF
  cat > /etc/systemd/system/timing-update.service <<UEOF
[Unit]
Description=Timing hub - install browser-uploaded update

[Service]
Type=oneshot
TimeoutStartSec=900
ExecStart=/usr/local/sbin/timing-update
UEOF
  systemctl daemon-reload
  systemctl enable --now timing-update.path >/dev/null 2>&1 || true
fi
[[ -f "$KIT_DIR/add-reader.sh" ]] && install -m 755 "$KIT_DIR/add-reader.sh" /usr/local/sbin/timing-add-reader
# форма регистрации уже опубликована: разрешаем загрузку командных заявок (Excel) до 3 МБ
if [[ -f /etc/nginx/sites-available/timing-reg-https ]] && grep -q 'client_max_body_size 16k' /etc/nginx/sites-available/timing-reg-https; then
  sed -i 's/client_max_body_size 16k;/client_max_body_size 3m;/' /etc/nginx/sites-available/timing-reg-https
  nginx -t >/dev/null 2>&1 && systemctl reload nginx && echo "  nginx: загрузка файлов заявок до 3 МБ"
fi
install -m 755 "$KIT_DIR"/tools/*.py "$APP_DIR/tools/"
install -m 644 "$KIT_DIR"/wiclax/* "$APP_DIR/wiclax/" 2>/dev/null || true
install -m 644 "$KIT_DIR/config/config.example.json" "$APP_DIR/config.example.json"
install -m 755 "$KIT_DIR/timing-peer.sh" /usr/local/sbin/timing-peer
install -d -o "$SVC_USER" -g "$SVC_USER" -m 750 "$DATA_DIR"
install -d -o root -g "$SVC_USER" -m 750 "$CFG_DIR"

if [[ ! -f "$CFG_DIR/config.json" ]]; then
  python3 - "$KIT_DIR/config/config.example.json" "$CFG_DIR/config.json" "$PUBLIC_INGEST" <<'PY'
import json, secrets, sys
src, dst, public = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
cfg = json.load(open(src, encoding="utf-8"))
cfg["web"]["password"] = secrets.token_urlsafe(12)
cfg["web"]["api_key"] = secrets.token_urlsafe(24)
if public:
    for s in cfg["sources"]:
        if s.get("mode") == "listen":
            s["listen_host"] = "0.0.0.0"
with open(dst, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
  echo "  Создан $CFG_DIR/config.json (пароль страницы и API-ключ сгенерированы)"
else
  echo "  Настройки $CFG_DIR/config.json уже есть — не трогаю"
fi
chown root:"$SVC_USER" "$CFG_DIR/config.json"
chmod 640 "$CFG_DIR/config.json"
python3 "$APP_DIR/hub.py" --config "$CFG_DIR/config.json" --check >/dev/null \
  || die "ошибка в $CFG_DIR/config.json: python3 $APP_DIR/hub.py --check"

cat > /etc/systemd/system/timing-hub.service <<EOF
[Unit]
Description=Timing hub - race timing server (readers -> archive -> Wiclax)
After=network-online.target wg-quick@${WG_IF}.service
Wants=network-online.target wg-quick@${WG_IF}.service
StartLimitIntervalSec=0

[Service]
User=${SVC_USER}
Group=${SVC_USER}
ExecStart=/usr/bin/python3 ${APP_DIR}/hub.py --config ${CFG_DIR}/config.json
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=${DATA_DIR}

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/cron.daily/timing-hub-backup <<EOF
#!/bin/sh
# Ежедневная копия базы отметок; хранятся 30 дней
D=${DATA_DIR}/backups
mkdir -p "\$D"
sqlite3 ${DATA_DIR}/reads.db ".backup '\$D/reads-\$(date +%F).db'" 2>/dev/null || exit 0
chown -R ${SVC_USER}:${SVC_USER} "\$D"
find "\$D" -name 'reads-*.db' -mtime +30 -delete
EOF
chmod 755 /etc/cron.daily/timing-hub-backup

# состояние VPN, служб и сертификата для вкладки «Оборудование» (обновляется каждые 10 с)
if [[ -f "$KIT_DIR/sysinfo.sh" ]]; then
  install -m 755 "$KIT_DIR/sysinfo.sh" /usr/local/sbin/timing-sysinfo
  echo "* * * * * root WG_IF=${WG_IF} /usr/local/sbin/timing-sysinfo ${DATA_DIR}/system ${SVC_USER} >/dev/null 2>&1" > /etc/cron.d/timing-hub-sysinfo
  chmod 644 /etc/cron.d/timing-hub-sysinfo
  LOOP=0 WG_IF=${WG_IF} /usr/local/sbin/timing-sysinfo "${DATA_DIR}/system" "${SVC_USER}" >/dev/null 2>&1 || true
fi

systemctl enable --now cron >/dev/null 2>&1 || true   # резервные копии и «Оборудование»
systemctl daemon-reload
systemctl enable timing-hub >/dev/null 2>&1
systemctl restart timing-hub
sleep 2
systemctl is-active --quiet timing-hub || die "сервер не запустился: journalctl -u timing-hub -n 50"
echo "  Сервер запущен"

# --------------------------------------------------------------------------- #
step "Настраиваю firewall"
SSH_PORTS="$( (sshd -T 2>/dev/null | awk '/^port /{print $2}'; echo "${SSH_CONNECTION:-}" | awk '{print $4}') | grep -E '^[0-9]+$' | sort -u)"
[[ -n "$SSH_PORTS" ]] || SSH_PORTS="22"
for p in $SSH_PORTS; do ufw allow "$p/tcp" comment 'SSH' >/dev/null; done
ufw allow "$WG_PORT/udp" comment 'WireGuard VPN' >/dev/null
ufw allow in on "$WG_IF" comment 'VPN -> server' >/dev/null
ufw route allow in on "$WG_IF" out on "$WG_IF" comment 'VPN <-> VPN' >/dev/null
if [[ "$PUBLIC_INGEST" == "1" ]]; then
  for p in $(python3 -c "
import json; c=json.load(open('$CFG_DIR/config.json', encoding='utf-8'))
print(' '.join(str(s['listen_port']) for s in c['sources'] if s.get('enabled', True) and s.get('mode')=='listen' and s.get('listen_host')=='0.0.0.0'))"); do
    ufw allow "$p/tcp" comment 'timing reader ingest (public)' >/dev/null
    warn "порт $p открыт в интернет для приёма от ридеров"
  done
fi
ufw --force enable >/dev/null
echo "  Открыто снаружи: SSH ($(echo $SSH_PORTS | tr " " ",")/tcp), VPN ($WG_PORT/udp). Всё остальное — только через VPN."

# --------------------------------------------------------------------------- #
if ! ls "$WG_DIR/clients/"*.conf >/dev/null 2>&1; then
  step "Создаю VPN-доступ для ноутбука с Wiclax"
  /usr/local/sbin/timing-peer add wiclax-laptop --quiet
fi

PASS="$(python3 -c "import json; print(json.load(open('$CFG_DIR/config.json', encoding='utf-8'))['web']['password'])")"
WEBP="$(python3 -c "import json; print(json.load(open('$CFG_DIR/config.json', encoding='utf-8'))['web']['listen_port'])")"
WICP="$(python3 -c "import json; print(json.load(open('$CFG_DIR/config.json', encoding='utf-8'))['wiclax']['listen_port'])")"

echo
echo "${c_green}=================================================================${c_off}"
echo "${c_green}  ГОТОВО. Сервер хронометража установлен и работает.${c_off}"
echo "${c_green}=================================================================${c_off}"
cat <<EOF

  Внешний адрес сервера (для VPN):  ${ENDPOINT}:${WG_PORT}/udp
  Адрес сервера внутри VPN:         ${WG_NET}.1

  Wiclax подключать к:              ${WG_NET}.1  порт ${WICP}
  Страница состояния (через VPN):   http://${WG_NET}.1:${WEBP}/
      логин: admin   пароль: ${PASS}

  ЗАПИШИТЕ ПАРОЛЬ. Его также можно посмотреть: sudo cat ${CFG_DIR}/config.json

  Что дальше:
    1. VPN для ноутбука с Wiclax уже создан. Показать файл настроек:
           sudo timing-peer show wiclax-laptop
       Скопируйте текст в программу WireGuard на ноутбуке
       («Добавить туннель» -> «Добавить пустой туннель» -> вставить).
    2. VPN для 4G-роутера каждого ридера:
           sudo timing-peer add finish-router --mikrotik
    3. Проверка сервера:   python3 ${APP_DIR}/tools/selftest.py --hub ${APP_DIR}/hub.py
    4. Журнал сервера:     journalctl -u timing-hub -f
    5. Изменили настройки: sudo systemctl restart timing-hub

EOF
