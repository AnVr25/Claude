#!/usr/bin/env bash
# Сбор состояния оборудования для вкладки «Оборудование» (запускается cron от root раз в минуту,
# внутри обновляет данные каждые 10 секунд). Сервер хронометража работает без прав root
# и сам эти сведения прочитать не может — поэтому они складываются в его папку данных.
set -u
OUT="${1:-/var/lib/timing-hub/system}"
OWNER="${2:-timinghub}"
WG_IF="${WG_IF:-wg0}"
mkdir -p "$OUT"
collect() {
  local t; t="$(mktemp -d)"
  for s in timing-hub openvpn-server@timing "wg-quick@${WG_IF}" nginx cron chrony; do
    printf '%s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || true)"
  done > "$t/services.txt"
  # юнит openvpn-server@ в Ubuntu может писать статус в /run (версия 2) — берём самый свежий
  sf="$(ls -t /var/log/openvpn-timing-status.log /run/openvpn-server/status-timing.log 2>/dev/null | head -1)"
  { [ -n "$sf" ] && cp "$sf" "$t/ovpn-status.txt"; } 2>/dev/null || : > "$t/ovpn-status.txt"
  : > "$t/ovpn-profiles.txt"
  for f in /etc/openvpn/server/ccd/*; do
    [ -f "$f" ] || continue
    printf '%s %s\n' "$(basename "$f")" "$(awk '/ifconfig-push/{print $2}' "$f")" >> "$t/ovpn-profiles.txt"
  done
  [ -f /etc/openvpn/server/crl.pem ] && openssl crl -in /etc/openvpn/server/crl.pem -noout -text 2>/dev/null \
    | grep -c 'Serial Number' > "$t/ovpn-revoked.txt" || echo 0 > "$t/ovpn-revoked.txt"
  wg show "$WG_IF" dump > "$t/wg-dump.txt" 2>/dev/null || : > "$t/wg-dump.txt"
  awk '/^### peer /{n=$3} /^PublicKey/{if(n!=""){print $3, n; n=""}}' "/etc/wireguard/${WG_IF}.conf" > "$t/wg-names.txt" 2>/dev/null || : > "$t/wg-names.txt"
  : > "$t/cert.txt"
  for c in /etc/letsencrypt/live/*/cert.pem; do
    [ -f "$c" ] || continue
    printf '%s %s\n' "$(basename "$(dirname "$c")")" "$(openssl x509 -enddate -noout -in "$c" | cut -d= -f2)" >> "$t/cert.txt"
  done
  ufw status 2>/dev/null | awk 'NR==1{print $2}' > "$t/ufw.txt"
  timedatectl show -p NTPSynchronized --value > "$t/ntp.txt" 2>/dev/null || :
  date +%s > "$t/updated.txt"
  chown -R "$OWNER":"$OWNER" "$t" 2>/dev/null
  chmod 644 "$t"/*
  for f in "$t"/*; do mv -f "$f" "$OUT/"; done
  rmdir "$t"
}
if [ "${LOOP:-1}" = "1" ]; then
  for i in 1 2 3 4 5 6; do collect; [ "$i" -lt 6 ] && sleep 10; done
else
  collect
fi
