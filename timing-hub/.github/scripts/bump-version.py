#!/usr/bin/env python3
"""
Автоматический инкремент версии и обновление даты сборки для timing-hub.
Вызывается из GitHub Actions при каждом push.
"""
import re
import sys
from datetime import datetime
from pathlib import Path


def bump_version(version_str: str) -> str:
    """Инкрементирует патч-версию: 2.8.1 -> 2.8.2"""
    parts = version_str.split('.')
    if len(parts) >= 3:
        # Есть патч-версия: инкрементируем её
        parts[-1] = str(int(parts[-1]) + 1)
    else:
        # Нет патч-версии: добавляем .1
        parts.append('1')
    return '.'.join(parts)


def update_hub_py(file_path: Path) -> tuple[str, str]:
    """Обновляет VERSION и BUILD_DATE в hub.py"""
    content = file_path.read_text(encoding='utf-8')

    # Находим текущую версию
    version_match = re.search(r'VERSION = "([^"]+)"', content)
    if not version_match:
        print("ERROR: VERSION not found in hub.py", file=sys.stderr)
        sys.exit(1)

    current_version = version_match.group(1)
    new_version = bump_version(current_version)

    # Получаем текущую дату (используем дату из окружения GitHub Actions или текущую)
    import os
    build_date = os.environ.get('BUILD_DATE', datetime.now().strftime('%Y-%m-%d'))

    # Обновляем VERSION
    content = re.sub(
        r'VERSION = "[^"]+"',
        f'VERSION = "{new_version}"',
        content,
        count=1
    )

    # Добавляем или обновляем BUILD_DATE
    if 'BUILD_DATE' in content:
        content = re.sub(
            r'BUILD_DATE = "[^"]+"',
            f'BUILD_DATE = "{build_date}"',
            content,
            count=1
        )
    else:
        # Добавляем BUILD_DATE после VERSION
        content = re.sub(
            r'(VERSION = "[^"]+")',
            f'\\1\nBUILD_DATE = "{build_date}"',
            content,
            count=1
        )

    file_path.write_text(content, encoding='utf-8')
    return current_version, new_version


def main():
    """Основная функция"""
    # Путь к hub.py относительно корня репозитория
    hub_py = Path(__file__).parent.parent.parent / 'hub' / 'hub.py'

    if not hub_py.exists():
        print(f"ERROR: {hub_py} not found", file=sys.stderr)
        sys.exit(1)

    old_version, new_version = update_hub_py(hub_py)

    print(f"Version bumped: {old_version} -> {new_version}")
    print(f"Build date: {datetime.now().strftime('%Y-%m-%d')}")

    # Выводим для GitHub Actions
    print(f"::set-output name=old_version::{old_version}")
    print(f"::set-output name=new_version::{new_version}")


if __name__ == '__main__':
    main()
