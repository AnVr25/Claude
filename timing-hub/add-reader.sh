#!/usr/bin/env bash
# Подключить ридер, к которому сервер подключается сам (через VPN), и перезапустить сервер.
#   sudo timing-add-reader ID АДРЕС [ПОРТ] [ТОЧКА] [ФОРМАТ]
#   sudo timing-add-reader IPICO1 10.67.0.10 10000 FINISH ipico
#   sudo timing-add-reader --remove IPICO1
#   sudo timing-add-reader --list
# ФОРМАТ: ipico (по умолчанию) | auto | wiclax
set -euo pipefail
CFG=/etc/timing-hub/config.json
APP=/opt/timing-hub/hub.py
[[ $EUID -eq 0 ]] || { echo "запустите через sudo"; exit 1; }
python3 - "$CFG" "$@" <<'PY'
import json, sys
p, args = sys.argv[1], sys.argv[2:]
c = json.load(open(p, encoding="utf-8"))
src = c.setdefault("sources", [])
if not args or args[0] in ("-h", "--help"):
    print(__doc__ or "timing-add-reader ID АДРЕС [ПОРТ] [ТОЧКА] [ФОРМАТ] | --remove ID | --list"); sys.exit(0)
if args[0] == "--list":
    for s in src:
        print(f"{s.get('id'):12} {s.get('mode'):8} {str(s.get('host') or s.get('listen_port') or ''):16} {str(s.get('port') or ''):6} "
              f"точка={s.get('device') or s.get('id')} формат={s.get('parser','auto')} {'(выкл)' if s.get('enabled') is False else ''}")
    sys.exit(0)
if args[0] == "--remove":
    n = len(src); c["sources"] = [s for s in src if s.get("id") != args[1]]
    print("удалён" if len(c["sources"]) < n else "такого нет")
else:
    sid, host = args[0], args[1]
    port = int(args[2]) if len(args) > 2 else 10000
    dev = args[3] if len(args) > 3 else sid
    parser = args[4] if len(args) > 4 else "ipico"
    c["sources"] = [s for s in src if s.get("id") != sid]
    s = {"id": sid, "name": f"{parser.upper()} {host}:{port}", "mode": "connect", "host": host, "port": port,
         "parser": parser, "device": dev}
    if parser == "ipico":
        s["chip_strip_leading_zeros"] = True       # 058003a9f837 → 58003A9F837, как в Wiclax
        c.setdefault("wiclax", {})["chip_lower"] = True
    c["sources"].append(s)
    print(f"добавлен {sid}: {host}:{port}, точка {dev}, формат {parser}")
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
[[ "${1:-}" == "--list" || "${1:-}" == "-h" || "${1:-}" == "--help" || -z "${1:-}" ]] && exit 0
python3 "$APP" --config "$CFG" --check >/dev/null || { echo "ошибка в настройках — проверьте $CFG"; exit 1; }
systemctl restart timing-hub
sleep 4
journalctl -u timing-hub -n 8 --no-pager -o cat
echo
echo "Проверьте вкладку «Оборудование»: ридер должен быть «на связи»."
