#!/usr/bin/env bash
# Управление пользователями на сервере:
#   sudo bash /opt/gto/app/deploy/gto-user.sh list-users
#   sudo bash /opt/gto/app/deploy/gto-user.sh add-user ivanova viewer "Иванова М. П."
#   sudo bash /opt/gto/app/deploy/gto-user.sh reset-password admin
set -euo pipefail
cd /opt/gto/app
exec runuser -u gto -- env GTO_DB=/var/lib/gto/gto.sqlite /opt/gto/node/bin/node --no-warnings=ExperimentalWarning cli.js "$@"
