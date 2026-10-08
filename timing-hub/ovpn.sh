#!/usr/bin/env bash
# =============================================================================
#  План Б: VPN поверх TCP-порта 443 (OpenVPN) — для сетей, где режется UDP.
#
#    bash ovpn.sh setup          один раз: поставить OpenVPN-сервер на TCP 443
#    bash ovpn.sh add ИМЯ        создать доступ -> /root/ovpn-clients/ИМЯ.ovpn
#    bash ovpn.sh list           список доступов и их адреса
#    bash ovpn.sh remove ИМЯ     отозвать доступ (потерян телефон, уволился судья)
#    bash ovpn.sh add-box ИМЯ 10.19.1.0/24
#                                доступ для роутера «ящика» с ридерами: сервер
#                                будет видеть всю сеть ящика (10.19.1.x) через VPN
#
#  Клиенты OpenVPN получают адреса 10.67.0.X и маршрут к 10.66.0.0/24,
#  поэтому сервер хронометража доступен по прежнему адресу 10.66.0.1
#  (Wiclax: 10.66.0.1:9854, страница: http://10.66.0.1:8080).
# =============================================================================
set -euo pipefail

OVPN_DIR="${OVPN_DIR:-/etc/openvpn/server}"
PKI_DIR="${PKI_DIR:-/etc/openvpn/easy-rsa}"
OUT_DIR="${OUT_DIR:-/root/ovpn-clients}"
NET="10.67.0"
PORT=443
c_red=$'\033[1;31m'; c_green=$'\033[1;32m'; c_off=$'\033[0m'
die() { echo "${c_red}ОШИБКА: $*${c_off}" >&2; exit 1; }
ok()  { echo "${c_green}$*${c_off}"; }

endpoint() {
  if [[ -f /etc/wireguard/timing-hub.env ]]; then
    # shellcheck disable=SC1091
    . /etc/wireguard/timing-hub.env
    echo "$ENDPOINT"
  else
    curl -4 -fsS --max-time 6 https://ifconfig.me
  fi
}

cmd_setup() {
  [[ $EUID -eq 0 ]] || die "запустите от root"
  export DEBIAN_FRONTEND=noninteractive
  echo "==> Ставлю OpenVPN"
  apt-get update -q >/dev/null
  apt-get install -y -q openvpn easy-rsa >/dev/null

  if [[ ! -f "$PKI_DIR/pki/ca.crt" ]]; then
    echo "==> Создаю ключи (1–2 минуты)"
    rm -rf "$PKI_DIR"
    make-cadir "$PKI_DIR"
    cd "$PKI_DIR"
    ./easyrsa --batch init-pki >/dev/null
    EASYRSA_REQ_CN="timing-hub-ca" ./easyrsa --batch build-ca nopass >/dev/null 2>&1
    ./easyrsa --batch build-server-full server nopass >/dev/null 2>&1
  fi
  mkdir -p "$OVPN_DIR/ccd" "$OUT_DIR"
  cp "$PKI_DIR/pki/ca.crt" "$PKI_DIR/pki/issued/server.crt" "$PKI_DIR/pki/private/server.key" "$OVPN_DIR/"
  gen_crl
  [[ -f "$OVPN_DIR/tc.key" ]] || openvpn --genkey secret "$OVPN_DIR/tc.key"
  chmod 600 "$OVPN_DIR/server.key" "$OVPN_DIR/tc.key"

  cat > "$OVPN_DIR/timing.conf" <<EOF
# OpenVPN сервера хронометража (TCP 443)
port ${PORT}
proto tcp
dev tun
ca ca.crt
cert server.crt
key server.key
dh none
tls-crypt tc.key
topology subnet
server ${NET}.0 255.255.255.0
client-config-dir ccd
crl-verify crl.pem
push "route 10.66.0.0 255.255.255.0"
client-to-client
keepalive 10 60
data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305
persist-key
persist-tun
user nobody
group nogroup
status /var/log/openvpn-timing-status.log 10
verb 3
$( [[ -f /etc/timing-hub/portshare ]] && echo "# не-VPN трафик на 443 (браузеры) — в nginx с формой регистрации"; [[ -f /etc/timing-hub/portshare ]] && echo "port-share 127.0.0.1 8443" )
EOF

  echo "==> Открываю порт ${PORT}/tcp и маршруты"
  ufw allow ${PORT}/tcp comment 'OpenVPN TCP' >/dev/null
  ufw allow in on tun0 comment 'OpenVPN -> server' >/dev/null
  ufw route allow in on tun0 out on tun0 comment 'OpenVPN <-> OpenVPN' >/dev/null
  ufw route allow in on tun0 out on wg0 comment 'OpenVPN -> WG' >/dev/null
  ufw route allow in on wg0 out on tun0 comment 'WG -> OpenVPN' >/dev/null

  systemctl enable openvpn-server@timing >/dev/null 2>&1
  systemctl restart openvpn-server@timing
  sleep 3
  systemctl is-active --quiet openvpn-server@timing || die "OpenVPN не запустился: journalctl -u openvpn-server@timing -n 30"
  ok "OpenVPN работает на $(endpoint):${PORT}/tcp"
  echo "Дальше: bash $0 add wiclax-laptop"
}

cmd_add() {
  local name="$1"
  [[ "$name" =~ ^[A-Za-z0-9_-]{1,32}$ ]] || die "имя: только латиница, цифры, - и _"
  [[ -f "$OVPN_DIR/timing.conf" ]] || die "сначала: bash $0 setup"
  [[ ! -f "$OVPN_DIR/ccd/$name" ]] || die "доступ «$name» уже есть: $OUT_DIR/$name.ovpn"
  cd "$PKI_DIR"
  ./easyrsa --batch build-client-full "$name" nopass >/dev/null 2>&1
  # постоянный адрес клиента: 10.67.0.10, .11, ...
  local used ip=""
  used="$(cat "$OVPN_DIR"/ccd/* 2>/dev/null | grep -oE "${NET//./\\.}\.[0-9]+" | grep -oE '[0-9]+$' || true)"
  for i in $(seq 10 250); do
    if ! grep -qx "$i" <<<"$used"; then ip="${NET}.$i"; break; fi
  done
  [[ -n "$ip" ]] || die "закончились адреса"
  echo "ifconfig-push ${ip} 255.255.255.0" > "$OVPN_DIR/ccd/$name"

  mkdir -p "$OUT_DIR"
  local f="$OUT_DIR/$name.ovpn"
  {
    cat <<EOF
# Сервер хронометража — доступ «${name}» (адрес в VPN ${ip})
client
dev tun
proto tcp
remote $(endpoint) ${PORT}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305
verb 3
<ca>
EOF
    cat "$PKI_DIR/pki/ca.crt"
    echo "</ca>"
    echo "<cert>"
    sed -n '/BEGIN CERTIFICATE/,/END CERTIFICATE/p' "$PKI_DIR/pki/issued/$name.crt"
    echo "</cert>"
    echo "<key>"
    cat "$PKI_DIR/pki/private/$name.key"
    echo "</key>"
    echo "<tls-crypt>"
    cat "$OVPN_DIR/tc.key"
    echo "</tls-crypt>"
  } > "$f"
  chmod 600 "$f"
  ok "Создан доступ «${name}»: адрес в VPN ${ip}"
  echo "Файл для импорта: $f  (скачайте через WinSCP)"
}

# роутер ящика: профиль + маршрут к его локальной сети (site-to-site)
cmd_add_box() {
  local name="$1" lan="$2"
  [[ "$lan" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.0/24$ ]] || die "сеть ящика пишите так: 10.19.1.0/24"
  local net3="${lan%.0/24}"
  case "$net3" in 10.66.0|10.67.0) die "сеть $lan занята самим VPN — выберите другую" ;; esac
  if grep -rqs "^iroute ${net3//./\\.}\.0 " "$OVPN_DIR/ccd/"; then
    die "сеть $lan уже закреплена за другим ящиком (bash $0 list)"
  fi
  cmd_add "$name"
  echo "iroute ${net3}.0 255.255.255.0" >> "$OVPN_DIR/ccd/$name"
  grep -q "^route ${net3}.0 255.255.255.0" "$OVPN_DIR/timing.conf" || echo "route ${net3}.0 255.255.255.0" >> "$OVPN_DIR/timing.conf"
  systemctl restart openvpn-server@timing
  ok "Ящик «${name}»: сервер будет видеть сеть ${lan} через этот роутер"
  echo "Дальше: импортируйте $OUT_DIR/$name.ovpn в роутер ящика (OpenVPN-клиент)."
  echo "У ридеров в ящике шлюз (gateway) должен быть адресом этого роутера, например ${net3}.1"
}

gen_crl() {
  ( cd "$PKI_DIR" && EASYRSA_CRL_DAYS=3650 ./easyrsa --batch gen-crl >/dev/null 2>&1 )
  cp "$PKI_DIR/pki/crl.pem" "$OVPN_DIR/crl.pem"
  chmod 644 "$OVPN_DIR/crl.pem"
}

cmd_remove() {
  local name="$1"
  [[ "$name" =~ ^[A-Za-z0-9_-]{1,32}$ ]] || die "имя: только латиница, цифры, - и _"
  [[ -f "$OVPN_DIR/ccd/$name" ]] || die "доступа «$name» нет (bash $0 list)"
  ( cd "$PKI_DIR" && ./easyrsa --batch revoke "$name" >/dev/null 2>&1 ) || die "не удалось отозвать сертификат"
  gen_crl
  local lan
  lan="$(awk '/^iroute/{print $2}' "$OVPN_DIR/ccd/$name")"
  [[ -n "$lan" ]] && sed -i "/^route ${lan//./\\.} 255\.255\.255\.0$/d" "$OVPN_DIR/timing.conf"
  rm -f "$OVPN_DIR/ccd/$name" "$OUT_DIR/$name.ovpn"
  systemctl restart openvpn-server@timing 2>/dev/null || true
  ok "Доступ «${name}» отозван: с этим файлом больше не подключиться"
}

cmd_list() {
  shopt -s nullglob
  for f in "$OVPN_DIR"/ccd/*; do
    echo "$(basename "$f")  $(awk '/ifconfig-push/{print $2}' "$f")$(awk '/^iroute/{print "  сеть ящика " $2 "/24"}' "$f")"
  done
  echo "--- сейчас на связи:"
  grep -E '^CLIENT_LIST' /var/log/openvpn-timing-status.log 2>/dev/null | awk -F, '{print $2"  "$4"  с "$8}' || true
}

case "${1:-}" in
  setup) cmd_setup ;;
  add)   [[ -n "${2:-}" ]] || die "укажите имя: bash $0 add ИМЯ"; cmd_add "$2" ;;
  list)  cmd_list ;;
  add-box) [[ -n "${2:-}" && -n "${3:-}" ]] || die "пример: bash $0 add-box box1 10.19.1.0/24"; cmd_add_box "$2" "$3" ;;
  remove|rm) [[ -n "${2:-}" ]] || die "укажите имя: bash $0 remove ИМЯ"; cmd_remove "$2" ;;
 *) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
