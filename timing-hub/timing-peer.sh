#!/usr/bin/env bash
# =============================================================================
#  timing-peer — управление VPN-доступами сервера хронометража
#
#    sudo timing-peer add ИМЯ [--mikrotik]   создать доступ (ноутбук, 4G-роутер ридера)
#    sudo timing-peer show ИМЯ [--mikrotik]  показать файл настроек и QR-код
#    sudo timing-peer list                   список доступов и когда были на связи
#    sudo timing-peer remove ИМЯ             удалить доступ
#
#  ИМЯ — латиницей, без пробелов: wiclax-laptop, finish-router, km5-router.
#  --mikrotik — дополнительно напечатать команды для роутера MikroTik (RouterOS 7).
# =============================================================================
set -euo pipefail

WG_DIR="${WG_DIR:-/etc/wireguard}"
ENV_FILE="$WG_DIR/timing-hub.env"
c_red=$'\033[1;31m'; c_green=$'\033[1;32m'; c_off=$'\033[0m'
die() { echo "${c_red}ОШИБКА: $*${c_off}" >&2; exit 1; }
usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

[[ -f "$ENV_FILE" ]] || die "не найден $ENV_FILE — сначала выполните install.sh"
# shellcheck disable=SC1090
. "$ENV_FILE"
WG_IF="${WG_IF:-wg0}"
CONF="$WG_DIR/$WG_IF.conf"
CLIENTS="$WG_DIR/clients"
[[ -f "$CONF" ]] || die "не найден $CONF"
SERVER_PUB="$(cat "$WG_DIR/server.pub")"

valid_name() { [[ "$1" =~ ^[A-Za-z0-9_-]{1,32}$ ]] || die "имя «$1»: только латиница, цифры, - и _ (до 32 символов)"; }

apply() {
  if ip link show "$WG_IF" >/dev/null 2>&1; then
    wg syncconf "$WG_IF" <(wg-quick strip "$CONF")
  fi
}

conf_get() {  # conf_get ФАЙЛ КЛЮЧ — значение первой строки «Ключ = значение»
  awk -v k="$2" -F'=' '
    { line=$0; sub(/^[[:space:]]+/, "", line) }
    index(line, k) == 1 { sub(/^[^=]*=[[:space:]]*/, "", line); sub(/[[:space:]]+$/, "", line); print line; exit }
  ' "$1"
}

print_mikrotik() {
  local name="$1" f="$CLIENTS/$1.conf"
  local priv psk addr
  priv="$(conf_get "$f" PrivateKey)"; psk="$(conf_get "$f" PresharedKey)"; addr="$(conf_get "$f" Address)"
  addr="${addr%/*}"
  cat <<EOF

----- Команды для MikroTik (RouterOS 7): терминал роутера -> вставить -----
/interface wireguard add name=wg-timing private-key="${priv}" comment="timing-hub ${name}"
/interface wireguard peers add interface=wg-timing public-key="${SERVER_PUB}" preshared-key="${psk}" endpoint-address=${ENDPOINT} endpoint-port=${WG_PORT} allowed-address=${WG_NET}.0/24 persistent-keepalive=25s
/ip address add address=${addr}/24 interface=wg-timing
/ip firewall nat add chain=srcnat out-interface=wg-timing action=masquerade comment="timing: ридер -> сервер"
# Если сервер сам подключается к ридеру (mode=connect), пробросьте порт ридера
# (192.168.88.10 и 10000 замените на адрес ридера в сети роутера и его порт):
# /ip firewall nat add chain=dstnat in-interface=wg-timing protocol=tcp dst-port=10000 action=dst-nat to-addresses=192.168.88.10 to-ports=10000
---------------------------------------------------------------------------
В настройках ридера адрес сервера: ${WG_NET}.1, порт — из config.json (например 7001).
Адрес этого роутера внутри VPN: ${addr}
EOF
}

cmd_show() {
  local name="$1" mk="$2" f="$CLIENTS/$1.conf"
  [[ -f "$f" ]] || die "доступа «$name» нет. Список: timing-peer list"
  echo "===== $name — файл настроек WireGuard ($f) ====="
  cat "$f"
  echo "==========================================================="
  if command -v qrencode >/dev/null 2>&1; then
    echo "QR-код (для телефона или роутера с приложением WireGuard):"
    qrencode -t ansiutf8 < "$f"
  fi
  [[ "$mk" == "1" ]] && print_mikrotik "$name"
  return 0
}

cmd_add() {
  local name="$1" mk="$2" quiet="$3"
  valid_name "$name"
  [[ ! -f "$CLIENTS/$name.conf" ]] || die "доступ «$name» уже есть. Показать: timing-peer show $name"
  grep -q "^### peer ${name}\$" "$CONF" && die "«$name» уже записан в $CONF"
  local used ip=""
  used="$(grep -oE "AllowedIPs[[:space:]]*=[[:space:]]*${WG_NET//./\\.}\.[0-9]+" "$CONF" | grep -oE '[0-9]+$' || true)"
  for i in $(seq 2 254); do
    if ! grep -qx "$i" <<<"$used"; then ip="${WG_NET}.$i"; break; fi
  done
  [[ -n "$ip" ]] || die "свободные адреса в VPN закончились"
  local priv pub psk
  priv="$(wg genkey)"; pub="$(wg pubkey <<<"$priv")"; psk="$(wg genpsk)"
  umask 077
  mkdir -p "$CLIENTS"
  cat >> "$CONF" <<EOF

### peer ${name}
[Peer]
PublicKey = ${pub}
PresharedKey = ${psk}
AllowedIPs = ${ip}/32
### end ${name}
EOF
  cat > "$CLIENTS/$name.conf" <<EOF
# Сервер хронометража — VPN-доступ «${name}»
[Interface]
PrivateKey = ${priv}
Address = ${ip}/32

[Peer]
PublicKey = ${SERVER_PUB}
PresharedKey = ${psk}
Endpoint = ${ENDPOINT}:${WG_PORT}
AllowedIPs = ${WG_NET}.0/24
PersistentKeepalive = 25
EOF
  apply
  echo "${c_green}Создан доступ «${name}»: адрес в VPN ${ip}${c_off}"
  if [[ "$quiet" == "1" ]]; then
    echo "Показать настройки: sudo timing-peer show ${name}"
  else
    cmd_show "$name" "$mk"
  fi
}

cmd_list() {
  local hs now
  hs="$(wg show "$WG_IF" latest-handshakes 2>/dev/null || true)"
  now="$(date +%s)"
  echo "ИМЯ                  АДРЕС          НА СВЯЗИ"
  shopt -s nullglob
  local any=0
  for f in "$CLIENTS"/*.conf; do
    any=1
    local name ip pub t ago
    name="$(basename "$f" .conf)"
    ip="$(conf_get "$f" Address)"; ip="${ip%/*}"
    pub="$(awk -v n="### peer ${name}" '$0==n{f=1} f && /^PublicKey/{sub(/^[^=]*=[[:space:]]*/,""); print; exit}' "$CONF")"
    t="$(awk -v p="$pub" '$1==p{print $2}' <<<"$hs")"
    if [[ -z "$t" || "$t" == "0" ]]; then ago="ни разу"
    else
      ago=$(( now - t ))
      if (( ago < 180 )); then ago="да (${ago} с назад)"; else ago="$(date -d "@$t" '+%d.%m %H:%M')"; fi
    fi
    printf "%-20s %-14s %s\n" "$name" "$ip" "$ago"
  done
  [[ "$any" == "1" ]] || echo "(доступов пока нет: sudo timing-peer add ИМЯ)"
}

cmd_remove() {
  local name="$1"
  valid_name "$name"
  grep -q "^### peer ${name}\$" "$CONF" || [[ -f "$CLIENTS/$name.conf" ]] || die "доступа «$name» нет"
  local tmp
  tmp="$(mktemp)"
  awk -v s="### peer ${name}" -v e="### end ${name}" '
    $0==s {skip=1; next}
    skip && $0==e {skip=0; next}
    !skip {print}
  ' "$CONF" > "$tmp"
  cat "$tmp" > "$CONF"
  rm -f "$tmp" "$CLIENTS/$name.conf"
  apply
  echo "Доступ «${name}» удалён"
}

[[ $# -ge 1 ]] || usage 1
[[ $EUID -eq 0 || -n "${TIMING_PEER_TEST:-}" ]] || die "запустите через sudo"
CMD="$1"; shift
NAME=""; MK=0; QUIET=0
for a in "$@"; do
  case "$a" in
    --mikrotik) MK=1 ;;
    --quiet) QUIET=1 ;;
    -*) die "неизвестный параметр $a" ;;
    *) NAME="$a" ;;
  esac
done
case "$CMD" in
  add)    [[ -n "$NAME" ]] || usage 1; cmd_add "$NAME" "$MK" "$QUIET" ;;
  show)   [[ -n "$NAME" ]] || usage 1; cmd_show "$NAME" "$MK" ;;
  list)   cmd_list ;;
  remove|rm|del) [[ -n "$NAME" ]] || usage 1; cmd_remove "$NAME" ;;
  -h|--help|help) usage 0 ;;
  *) usage 1 ;;
esac
