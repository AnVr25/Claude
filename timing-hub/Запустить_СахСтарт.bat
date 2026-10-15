@echo off
chcp 65001 >nul
cd /d "%~dp0"
title SakhStart Stadium Monolith Server v8.2.2
echo =======================================================
echo   ЗАПУСК АВТОНОМНОГО СУДЕЙСКОГО СЕРВЕРА SAKHSTART v8.2.2
echo =======================================================
set PY=python
where python >nul 2>nul || set PY=py
where %PY% >nul 2>nul || (
  echo  ОШИБКА: не найден Python 3. Установите его с python.org, отметив "Add python.exe to PATH".
  pause
  exit /b 1
)
echo  [1/2] Запуск локального ядра Python...
rem config.json создаётся сам в этой папке при первом запуске
start /b %PY% hub\hub.py
timeout /t 3 > nul
echo  [2/2] Автоматическое открытие АРМ Секретаря в браузере...
start http://localhost:8080/
echo =======================================================
echo   СЕРВЕР УСПЕШНО РАБОТАЕТ! НЕ ЗАКРЫВАЙТЕ ЭТО ОКНО ДО КОНЦА.
echo =======================================================
pause >nul
