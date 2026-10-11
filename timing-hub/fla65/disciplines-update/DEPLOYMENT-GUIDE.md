# Инструкция по развертыванию справочника дисциплин на сервере

**Проект:** SAKHSTART (reg.fla65.ru)  
**Дата:** 11 октября 2026  
**Время:** 14:28 UTC

---

## 🎯 Цель

Развернуть новый справочник дисциплин легкой атлетики на production-сервере reg.fla65.ru

---

## ✅ Предварительные требования

Перед началом убедитесь, что у вас есть:

- [ ] SSH-доступ к серверу reg.fla65.ru
- [ ] Доступ к MySQL/MariaDB на сервере
- [ ] Права sudo (или root)
- [ ] Резервная копия текущей БД (важно!)

---

## 📋 План развертывания

### Этап 1: Подготовка (5-10 минут)
### Этап 2: Резервное копирование (5 минут)
### Этап 3: Загрузка файлов (5 минут)
### Этап 4: Создание структуры БД (5 минут)
### Этап 5: Импорт данных (10 минут)
### Этап 6: Развертывание API (10 минут)
### Этап 7: Тестирование (10-15 минут)

**Общее время:** 50-60 минут

---

## 🚀 Пошаговая инструкция

---

## ЭТАП 1: Подготовка

### Шаг 1.1: Подключение к серверу

```bash
# С вашего компьютера
ssh user@reg.fla65.ru

# Или если используется нестандартный порт
ssh user@reg.fla65.ru -p 22
```

### Шаг 1.2: Проверка окружения

```bash
# Проверка версии PHP
php -v
# Требуется: PHP 7.4+

# Проверка версии MySQL
mysql --version
# Требуется: MySQL 5.7+ или MariaDB 10.3+

# Проверка Python (для импорта)
python3 --version
# Требуется: Python 3.8+

# Проверка свободного места
df -h
# Нужно минимум 100 МБ свободного места
```

### Шаг 1.3: Создание рабочей директории

```bash
# Создать директорию для обновления
mkdir -p /tmp/disciplines-update
cd /tmp/disciplines-update

# Создать директорию для логов
mkdir -p /var/log/fla65
```

---

## ЭТАП 2: Резервное копирование

**⚠️ КРИТИЧЕСКИ ВАЖНО! Не пропускайте этот шаг!**

### Шаг 2.1: Запуск скрипта backup.sh

```bash
# Если backup.sh уже установлен
sudo /root/scripts/backup.sh

# Проверить, что backup создан
ls -lh /var/backups/fla65/daily/
```

### Шаг 2.2: Ручное резервное копирование (если скрипт не установлен)

```bash
# Создать директорию для бэкапа
sudo mkdir -p /var/backups/fla65/manual

# Бэкап базы данных
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
sudo mysqldump -u fla65_user -p fla65_reg_db | gzip > \
  /var/backups/fla65/manual/db_before_disciplines_${TIMESTAMP}.sql.gz

# Бэкап текущего API (если существует)
if [ -f /var/www/reg.fla65.ru/api/disciplines.php ]; then
  sudo cp /var/www/reg.fla65.ru/api/disciplines.php \
    /var/backups/fla65/manual/api_disciplines_backup_${TIMESTAMP}.php
fi

echo "✓ Резервная копия создана: ${TIMESTAMP}"
```

---

## ЭТАП 3: Загрузка файлов на сервер

### Вариант A: Через SCP (с вашего компьютера)

```bash
# С вашего локального компьютера (Windows)
# Открыть PowerShell в папке C:\bat\fla65-project\

# Загрузить все необходимые файлы
scp athletics-disciplines.json user@reg.fla65.ru:/tmp/disciplines-update/
scp database-schema.sql user@reg.fla65.ru:/tmp/disciplines-update/
scp import_disciplines.py user@reg.fla65.ru:/tmp/disciplines-update/
scp api-disciplines.php user@reg.fla65.ru:/tmp/disciplines-update/

# Или одной командой
scp athletics-disciplines.json database-schema.sql import_disciplines.py api-disciplines.php \
  user@reg.fla65.ru:/tmp/disciplines-update/
```

### Вариант B: Через Git (если используете репозиторий)

```bash
# На сервере
cd /tmp/disciplines-update
git clone https://github.com/fla65/sakhstart-disciplines.git .

# Или обновить существующий репозиторий
git pull origin main
```

### Вариант C: Прямое копирование (если файлы уже на сервере)

```bash
# Скопировать файлы из другой директории
cp /path/to/files/* /tmp/disciplines-update/
```

### Шаг 3.1: Проверка загруженных файлов

```bash
cd /tmp/disciplines-update
ls -lh

# Должны быть файлы:
# - athletics-disciplines.json
# - database-schema.sql
# - import_disciplines.py
# - api-disciplines.php
```

---

## ЭТАП 4: Создание структуры базы данных

### Шаг 4.1: Подключение к MySQL

```bash
# Вариант 1: С запросом пароля
mysql -u fla65_user -p fla65_reg_db

# Вариант 2: Из файла конфигурации
mysql --defaults-file=/etc/mysql/my.cnf fla65_reg_db
```

### Шаг 4.2: Проверка существующих таблиц

```sql
-- В MySQL консоли
SHOW TABLES LIKE 'discipline%';

-- Если таблицы уже есть, решить:
-- A) Удалить старые таблицы (ОСТОРОЖНО!)
-- B) Создать новые с префиксом (например, discipline_new_*)
-- C) Пропустить создание, только данные обновить
```

### Шаг 4.3: Выполнение SQL-схемы

```bash
# Выход из MySQL (если вошли)
exit;

# Выполнение SQL-файла
mysql -u fla65_user -p fla65_reg_db < /tmp/disciplines-update/database-schema.sql

# Или с логированием
mysql -u fla65_user -p fla65_reg_db < /tmp/disciplines-update/database-schema.sql \
  2>&1 | tee /var/log/fla65/schema-creation.log
```

### Шаг 4.4: Проверка созданных таблиц

```bash
mysql -u fla65_user -p fla65_reg_db -e "SHOW TABLES;"

# Должны увидеть:
# - discipline_categories
# - discipline_subcategories
# - disciplines
# - discipline_genders
# - discipline_age_groups
# и другие...
```

---

## ЭТАП 5: Импорт данных

### Шаг 5.1: Установка зависимостей Python (если нужно)

```bash
# Проверка наличия модуля
python3 -c "import mysql.connector" 2>/dev/null && echo "✓ Модуль установлен" || echo "✗ Нужна установка"

# Если модуль отсутствует
sudo pip3 install mysql-connector-python

# Или через apt (Debian/Ubuntu)
sudo apt-get install python3-mysql.connector
```

### Шаг 5.2: Запуск импорта

```bash
cd /tmp/disciplines-update

# Запуск скрипта импорта
python3 import_disciplines.py athletics-disciplines.json \
  --host localhost \
  --database fla65_reg_db \
  --user fla65_user \
  --password "ВАШ_ПАРОЛЬ"

# С логированием
python3 import_disciplines.py athletics-disciplines.json \
  --host localhost \
  --database fla65_reg_db \
  --user fla65_user \
  --password "ВАШ_ПАРОЛЬ" \
  2>&1 | tee /var/log/fla65/import-disciplines.log
```

### Шаг 5.3: Проверка импортированных данных

```bash
# Подсчет записей
mysql -u fla65_user -p fla65_reg_db -e "
SELECT 
  'Categories' as Table_Name, COUNT(*) as Count FROM discipline_categories
UNION ALL
SELECT 'Subcategories', COUNT(*) FROM discipline_subcategories
UNION ALL
SELECT 'Disciplines', COUNT(*) FROM disciplines
UNION ALL
SELECT 'Genders', COUNT(*) FROM discipline_genders
UNION ALL
SELECT 'Age Groups', COUNT(*) FROM discipline_age_groups;
"

# Ожидаемые значения:
# Categories:     5
# Subcategories:  8
# Disciplines:    84+
# Genders:        168+
# Age Groups:     336+
```

### Шаг 5.4: Тестовые запросы

```bash
# Проверить несколько дисциплин
mysql -u fla65_user -p fla65_reg_db -e "
SELECT code, name_ru, name_en, category_code 
FROM v_disciplines_full 
LIMIT 10;
"

# Проверить спринтерские дисциплины
mysql -u fla65_user -p fla65_reg_db -e "
SELECT code, name_ru, distance 
FROM v_disciplines_full 
WHERE subcategory_code = 'sprints';
"
```

---

## ЭТАП 6: Развертывание API

### Шаг 6.1: Определение структуры директорий

```bash
# Обычно API находится в:
# /var/www/reg.fla65.ru/api/
# или
# /var/www/html/reg.fla65.ru/api/

# Найти корневую директорию проекта
find /var/www -name "reg.fla65.ru" -type d
```

### Шаг 6.2: Создание директории API (если не существует)

```bash
# Создать директорию для API
sudo mkdir -p /var/www/reg.fla65.ru/api

# Установить права
sudo chown -R www-data:www-data /var/www/reg.fla65.ru/api
```

### Шаг 6.3: Копирование API файла

```bash
# Скопировать API файл
sudo cp /tmp/disciplines-update/api-disciplines.php \
  /var/www/reg.fla65.ru/api/disciplines.php

# Установить права
sudo chown www-data:www-data /var/www/reg.fla65.ru/api/disciplines.php
sudo chmod 644 /var/www/reg.fla65.ru/api/disciplines.php
```

### Шаг 6.4: Настройка конфигурации БД в API

```bash
# Отредактировать файл API
sudo nano /var/www/reg.fla65.ru/api/disciplines.php

# Найти и обновить строки:
# $pdo = new PDO(
#     "mysql:host=localhost;dbname=fla65_reg_db;charset=utf8mb4",
#     "fla65_user",
#     "ПАРОЛЬ",  // ← Указать правильный пароль
```

**Или через sed:**

```bash
# Автоматическая замена пароля
sudo sed -i 's/"",  \/\/ Указать пароль/"ВАШ_ПАРОЛЬ",/' \
  /var/www/reg.fla65.ru/api/disciplines.php
```

### Шаг 6.5: Настройка веб-сервера

#### Для Nginx:

```bash
# Проверить конфигурацию Nginx
sudo nano /etc/nginx/sites-available/reg.fla65.ru

# Добавить location для API (если еще нет)
# location /api/ {
#     try_files $uri $uri/ /api/disciplines.php?$query_string;
# }

# Проверить конфигурацию
sudo nginx -t

# Перезагрузить Nginx
sudo systemctl reload nginx
```

#### Для Apache:

```bash
# Проверить .htaccess в директории api/
sudo nano /var/www/reg.fla65.ru/api/.htaccess

# Добавить правила (если нужно)
# RewriteEngine On
# RewriteCond %{REQUEST_FILENAME} !-f
# RewriteCond %{REQUEST_FILENAME} !-d
# RewriteRule ^ disciplines.php [QSA,L]

# Перезагрузить Apache
sudo systemctl reload apache2
```

---

## ЭТАП 7: Тестирование

### Шаг 7.1: Тестирование API локально на сервере

```bash
# Тест 1: Получить категории
curl http://localhost/api/disciplines/categories

# Тест 2: Получить список дисциплин
curl http://localhost/api/disciplines

# Тест 3: Получить конкретную дисциплину
curl http://localhost/api/disciplines/100M

# Тест 4: Поиск
curl "http://localhost/api/disciplines/search?q=барьер"

# Тест 5: Для создания события
curl "http://localhost/api/disciplines/for-event?venue=outdoor"
```

### Шаг 7.2: Тестирование через внешний URL

```bash
# С вашего компьютера или браузера
# Открыть в браузере:

https://reg.fla65.ru/api/disciplines/categories
https://reg.fla65.ru/api/disciplines
https://reg.fla65.ru/api/disciplines/100M
https://reg.fla65.ru/api/disciplines/search?q=прыжок
https://reg.fla65.ru/api/disciplines/for-event?venue=outdoor
```

### Шаг 7.3: Проверка производительности

```bash
# Время ответа API
time curl -s http://localhost/api/disciplines >/dev/null

# Должно быть < 1 секунды

# Нагрузочное тестирование (опционально)
ab -n 100 -c 10 http://localhost/api/disciplines/categories
```

### Шаг 7.4: Проверка логов

```bash
# Проверить логи веб-сервера
sudo tail -f /var/log/nginx/error.log
# или
sudo tail -f /var/log/apache2/error.log

# Проверить логи PHP
sudo tail -f /var/log/php-fpm/error.log

# Проверить логи MySQL
sudo tail -f /var/log/mysql/error.log
```

---

## 📊 Проверочный чек-лист

После завершения всех этапов проверьте:

- [ ] Резервная копия БД создана
- [ ] SQL-схема выполнена без ошибок
- [ ] Данные импортированы (84+ дисциплины)
- [ ] API файл скопирован и настроен
- [ ] API отвечает на запросы
- [ ] Нет ошибок в логах
- [ ] Время ответа приемлемое (< 1 сек)
- [ ] Кодировка UTF-8 работает корректно (русский текст)

---

## 🔧 Устранение проблем

### Проблема 1: API возвращает 500 ошибку

**Решение:**
```bash
# Проверить логи PHP
sudo tail -f /var/log/php-fpm/error.log

# Проверить права доступа
ls -l /var/www/reg.fla65.ru/api/disciplines.php

# Проверить подключение к БД
mysql -u fla65_user -p fla65_reg_db -e "SELECT 1;"
```

### Проблема 2: Кракозябры вместо русского текста

**Решение:**
```bash
# Проверить кодировку в MySQL
mysql -u fla65_user -p fla65_reg_db -e "
SHOW VARIABLES LIKE 'character_set%';
SHOW VARIABLES LIKE 'collation%';
"

# Должно быть utf8mb4
# Если нет, установить:
mysql -u fla65_user -p fla65_reg_db -e "
ALTER DATABASE fla65_reg_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"
```

### Проблема 3: Импорт данных не работает

**Решение:**
```bash
# Проверить Python модуль
python3 -m pip show mysql-connector-python

# Переустановить модуль
sudo pip3 install --upgrade mysql-connector-python

# Запустить импорт с verbose
python3 import_disciplines.py athletics-disciplines.json \
  --host localhost \
  --database fla65_reg_db \
  --user fla65_user \
  --password "ПАРОЛЬ" \
  --verbose
```

### Проблема 4: API не найден (404)

**Решение:**
```bash
# Проверить конфигурацию Nginx/Apache
sudo nginx -t
# или
sudo apache2ctl configtest

# Проверить routing
curl -I http://localhost/api/disciplines/categories

# Перезагрузить веб-сервер
sudo systemctl restart nginx
# или
sudo systemctl restart apache2
```

---

## ⚠️ Откат изменений (если что-то пошло не так)

### Вариант 1: Через скрипт rollback.sh

```bash
sudo /root/scripts/rollback.sh
```

### Вариант 2: Вручную

```bash
# Найти последнюю резервную копию
ls -lh /var/backups/fla65/daily/

# Восстановить БД
BACKUP_FILE="/var/backups/fla65/daily/fla65_reg_db_TIMESTAMP.sql.gz"
gunzip < $BACKUP_FILE | mysql -u fla65_user -p fla65_reg_db

# Удалить новые таблицы (если нужно)
mysql -u fla65_user -p fla65_reg_db -e "
DROP TABLE IF EXISTS discipline_categories;
DROP TABLE IF EXISTS discipline_subcategories;
DROP TABLE IF EXISTS disciplines;
DROP TABLE IF EXISTS discipline_genders;
DROP TABLE IF EXISTS discipline_age_groups;
DROP TABLE IF EXISTS discipline_hurdle_heights;
DROP TABLE IF EXISTS discipline_implement_weights;
DROP TABLE IF EXISTS combined_event_disciplines;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS event_registrations;
DROP TABLE IF EXISTS results;
DROP TABLE IF EXISTS attempts;
"

# Удалить API файл
sudo rm /var/www/reg.fla65.ru/api/disciplines.php
```

---

## 📝 После успешного развертывания

### Шаг 1: Очистка временных файлов

```bash
# Удалить временную директорию
sudo rm -rf /tmp/disciplines-update

# Или оставить для истории
sudo mv /tmp/disciplines-update /var/backups/fla65/deployment-$(date +%Y%m%d)
```

### Шаг 2: Обновление документации

```bash
# Записать версию развертывания
echo "Disciplines database v2.8 deployed on $(date)" | \
  sudo tee -a /var/www/reg.fla65.ru/CHANGELOG.txt
```

### Шаг 3: Уведомление команды

```bash
# Отправить уведомление (если настроено)
echo "✓ Справочник дисциплин обновлен до версии 2.8" | \
  mail -s "SAKHSTART: API Disciplines Deployed" admin@fla65.ru
```

### Шаг 4: Мониторинг первые 24 часа

```bash
# Следить за логами
sudo tail -f /var/log/nginx/access.log | grep "api/disciplines"

# Проверять производительность
watch -n 60 'curl -w "@curl-format.txt" -o /dev/null -s http://localhost/api/disciplines/categories'
```

---

## 🎯 Следующие шаги (интеграция с фронтендом)

После успешного развертывания API:

1. **Обновить фронтенд** для использования нового API
2. **Обучить организаторов** работе с новым интерфейсом
3. **Мигрировать существующие данные** (если есть старые события)
4. **Настроить мониторинг** использования API
5. **Собрать обратную связь** от пользователей

---

## 📞 Контакты для поддержки

**Если возникли проблемы:**
- Email: tech@fla65.ru
- Telegram: @sakhstart_support
- GitHub Issues: github.com/fla65/sakhstart-disciplines/issues

---

**✅ Развертывание завершено!**

*Инструкция создана: 11 октября 2026, 14:28 UTC*  
*Версия: 2.8*
