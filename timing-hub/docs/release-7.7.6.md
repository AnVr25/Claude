# 7.7.6 — сервер не падает на Windows из-за os.getloadavg (14.10.2026)
- `Hub.system_view` (страница «Система» в админке) вызывал `os.getloadavg()`, которого в Windows нет: `AttributeError` не ловился (ловился только `OSError`) и запрос падал. Теперь `try … except (AttributeError, OSError)` → нагрузка `[0.0, 0.0, 0.0]`; число ядер показывается как раньше.
- Остальные Linux-зависимые места «Системы» (`/proc/uptime`, `/proc/meminfo`, `/etc/localtime`) уже были защищены и на Windows просто не показываются.
- Автотест убирает `os.getloadavg` и проверяет, что `system_view` возвращает нули.
- Запускчик `Запустить_СахСтарт.bat` — v7.7.6.
