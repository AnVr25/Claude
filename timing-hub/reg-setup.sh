#!/usr/bin/env bash
# Публикация формы регистрации в интернет по HTTPS: https://ДОМЕН/r/...
#   sudo bash reg-setup.sh reg.fla65.ru admin@example.ru
#
# Что делает:
#   1. ставит nginx и certbot, получает бесплатный сертификат Let's Encrypt (нужен порт 80);
#   2. nginx слушает только 127.0.0.1:8443 и пропускает наружу ТОЛЬКО страницы /r/ (форма регистрации);
#   3. OpenVPN на 443 получает «port-share»: VPN-клиенты работают как раньше,
#      а обычные браузеры на https://ДОМЕН попадают в nginx;
#   4. прописывает адрес в настройки сервера хронометража (для ссылки и QR в админке).
# Админка, судья, API и Wiclax по-прежнему доступны только через VPN.
# Перед запуском: в DNS домена создайте A-запись ДОМЕН → IP этого сервера.
set -euo pipefail
DOMAIN="${1:-}"; EMAIL="${2:-}"
CFG=/etc/timing-hub/config.json
OVPN_CONF=/etc/openvpn/server/timing.conf
die(){ echo "ОШИБКА: $*" >&2; exit 1; }
ok(){ echo "  ✓ $*"; }
[[ $EUID -eq 0 ]] || die "запустите через sudo"
[[ -n "$DOMAIN" && -n "$EMAIL" ]] || die "использование: sudo bash $0 reg.fla65.ru почта@для.уведомлений"
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "странное имя домена: $DOMAIN"
[[ -f "$CFG" ]] || die "нет $CFG — сначала install.sh"
[[ -f "$OVPN_CONF" ]] || die "нет OpenVPN ($OVPN_CONF) — сначала: timing-ovpn setup"

echo "==> Проверяю DNS: $DOMAIN"
MYIP="$(curl -4 -s --max-time 5 https://ifconfig.me || true)"
DNSIP="$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}' || true)"
[[ -n "$DNSIP" ]] || die "$DOMAIN не находится в DNS. Создайте A-запись на ${MYIP:-IP сервера} и подождите 5–30 минут"
if [[ -n "$MYIP" && "$DNSIP" != "$MYIP" ]]; then
  die "$DOMAIN указывает на $DNSIP, а у сервера адрес $MYIP. Исправьте A-запись"
fi
ok "$DOMAIN → $DNSIP"

echo "==> Ставлю nginx и certbot"
apt-get update -q >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx certbot >/dev/null
rm -f /etc/nginx/sites-enabled/default
mkdir -p /var/www/acme

cat > /etc/nginx/conf.d/timing-reg-limits.conf <<'NG'
limit_req_zone $binary_remote_addr zone=reg:1m rate=5r/s;
NG

cat > /etc/nginx/sites-available/timing-reg-http <<NG
# порт 80: только проверка Let's Encrypt и перенаправление на HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    server_tokens off;
    location /.well-known/acme-challenge/ { root /var/www/acme; }
    location / { return 301 https://\$host\$request_uri; }
}
NG
ln -sf /etc/nginx/sites-available/timing-reg-http /etc/nginx/sites-enabled/timing-reg-http
# прежний HTTPS-конфиг (если скрипт запускают повторно) не должен мешать проверке
rm -f /etc/nginx/sites-enabled/timing-reg-https
nginx -t >/dev/null 2>&1 || die "ошибка конфигурации nginx: nginx -t"
systemctl enable --now nginx >/dev/null 2>&1; systemctl reload nginx
ufw allow 80/tcp comment 'HTTP: Lets Encrypt + redirect' >/dev/null
ok "nginx на 80 порту"

echo "==> Получаю сертификат Let's Encrypt"
certbot certonly --webroot -w /var/www/acme -d "$DOMAIN" -m "$EMAIL" --agree-tos -n --keep-until-expiring \
  || die "сертификат не выдан. Проверьте, что порт 80 открыт и в панели хостинга (файрвол RUVDS) тоже"
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\nsystemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
ok "сертификат получен, продлевается сам"

PUBPORT="$(python3 -c "import json;print(json.load(open('$CFG',encoding='utf-8')).get('public',{}).get('listen_port',8081))")"
cat > /etc/nginx/sites-available/timing-reg-https <<NG
# HTTPS для формы регистрации. Слушает только локально: снаружи 443 принимает OpenVPN (port-share)
server {
    listen 127.0.0.1:8443 ssl;
    http2 on;
    server_name ${DOMAIN};
    server_tokens off;
    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 3m;
    location = / { return 302 /r/; }
    location /r/ {
        limit_req zone=reg burst=30 nodelay;
        proxy_pass http://127.0.0.1:${PUBPORT};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 20s;
    }
    location = /r { return 301 /r/; }
    location / { return 404; }
}
NG
# nginx старше 1.25 не знает «http2 on»
if ! nginx -V 2>&1 | grep -q 'nginx/1\.\(2[5-9]\|[3-9][0-9]\)'; then
  sed -i 's/^    listen 127.0.0.1:8443 ssl;/    listen 127.0.0.1:8443 ssl http2;/; /^    http2 on;/d' /etc/nginx/sites-available/timing-reg-https
fi
ln -sf /etc/nginx/sites-available/timing-reg-https /etc/nginx/sites-enabled/timing-reg-https
nginx -t >/dev/null 2>&1 || { nginx -t; die "ошибка конфигурации nginx"; }
systemctl reload nginx
ok "nginx HTTPS на 127.0.0.1:8443"

echo "==> OpenVPN: делю порт 443 с HTTPS (port-share)"
touch /etc/timing-hub/portshare
if ! grep -q '^port-share' "$OVPN_CONF"; then
  printf '# не-VPN трафик на 443 (браузеры) — в nginx с формой регистрации\nport-share 127.0.0.1 8443\n' >> "$OVPN_CONF"
fi
systemctl restart openvpn-server@timing
sleep 3
systemctl is-active --quiet openvpn-server@timing || die "OpenVPN не запустился: journalctl -u openvpn-server@timing -n 30"
ok "VPN работает, VPN-клиенты переподключатся сами через несколько секунд"

echo "==> Адрес формы в настройках сервера"
python3 - "$CFG" "https://$DOMAIN" <<'PY'
import json, sys
p, url = sys.argv[1], sys.argv[2]
c = json.load(open(p, encoding="utf-8"))
c.setdefault("public", {})
c["public"].update({"enabled": True, "url": url})
c["public"].setdefault("listen_host", "127.0.0.1")
c["public"].setdefault("listen_port", 8081)
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
systemctl restart timing-hub
sleep 2
ok "сервер хронометража перезапущен"

echo "==> Проверка"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/r/" || true)"
[[ "$CODE" == "200" ]] && ok "https://$DOMAIN/r/ отвечает" || echo "  ! https://$DOMAIN/r/ ответил $CODE — проверьте: journalctl -u timing-hub -n 30"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/events" || true)"
[[ "$CODE" == "404" ]] && ok "админка снаружи закрыта (404)" || echo "  ! /api/events снаружи ответил $CODE — так быть не должно"
echo
echo "Готово. Ссылки на формы — во вкладке «Регистрация» (кнопка «Копировать» и QR)."
echo "Список открытых регистраций: https://$DOMAIN/r/"
