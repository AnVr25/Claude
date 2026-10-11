#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт импорта дисциплин легкой атлетики в базу данных
Проект: SAKHSTART (reg.fla65.ru)
Версия: 2.8
Дата: 2026-10-11
"""

import json
import mysql.connector
from mysql.connector import Error
import sys
from datetime import datetime

# Конфигурация подключения к БД
DB_CONFIG = {
    'host': 'localhost',
    'database': 'fla65_reg_db',
    'user': 'fla65_user',
    'password': '',  # Указать пароль
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci'
}

class DisciplineImporter:
    """Класс для импорта дисциплин из JSON в MySQL"""

    def __init__(self, json_file_path, db_config):
        self.json_file_path = json_file_path
        self.db_config = db_config
        self.connection = None
        self.cursor = None
        self.stats = {
            'categories': 0,
            'subcategories': 0,
            'disciplines': 0,
            'genders': 0,
            'age_groups': 0,
            'errors': []
        }

    def connect(self):
        """Подключение к базе данных"""
        try:
            self.connection = mysql.connector.connect(**self.db_config)
            self.cursor = self.connection.cursor(dictionary=True)
            print(f"✓ Подключение к БД успешно: {self.db_config['database']}")
            return True
        except Error as e:
            print(f"✗ Ошибка подключения к БД: {e}")
            return False

    def disconnect(self):
        """Отключение от базы данных"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
            print("✓ Отключение от БД")

    def load_json(self):
        """Загрузка данных из JSON файла"""
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"✓ JSON файл загружен: {self.json_file_path}")
            return data
        except Exception as e:
            print(f"✗ Ошибка загрузки JSON: {e}")
            return None

    def get_or_create_category(self, code, name_ru, name_en, sort_order=0):
        """Получить или создать категорию"""
        try:
            # Проверка существования
            self.cursor.execute(
                "SELECT id FROM discipline_categories WHERE code = %s",
                (code,)
            )
            result = self.cursor.fetchone()

            if result:
                return result['id']

            # Создание новой категории
            self.cursor.execute(
                """INSERT INTO discipline_categories
                   (code, name_ru, name_en, sort_order)
                   VALUES (%s, %s, %s, %s)""",
                (code, name_ru, name_en, sort_order)
            )
            self.connection.commit()
            self.stats['categories'] += 1
            return self.cursor.lastrowid

        except Error as e:
            print(f"✗ Ошибка создания категории {code}: {e}")
            self.stats['errors'].append(f"Category {code}: {str(e)}")
            return None

    def get_or_create_subcategory(self, category_id, code, name_ru, name_en, sort_order=0):
        """Получить или создать подкатегорию"""
        try:
            # Проверка существования
            self.cursor.execute(
                "SELECT id FROM discipline_subcategories WHERE code = %s",
                (code,)
            )
            result = self.cursor.fetchone()

            if result:
                return result['id']

            # Создание новой подкатегории
            self.cursor.execute(
                """INSERT INTO discipline_subcategories
                   (category_id, code, name_ru, name_en, sort_order)
                   VALUES (%s, %s, %s, %s, %s)""",
                (category_id, code, name_ru, name_en, sort_order)
            )
            self.connection.commit()
            self.stats['subcategories'] += 1
            return self.cursor.lastrowid

        except Error as e:
            print(f"✗ Ошибка создания подкатегории {code}: {e}")
            self.stats['errors'].append(f"Subcategory {code}: {str(e)}")
            return None

    def create_discipline(self, discipline_data, category_id, subcategory_id=None):
        """Создание дисциплины"""
        try:
            code = discipline_data['code']

            # Проверка существования
            self.cursor.execute(
                "SELECT id FROM disciplines WHERE code = %s",
                (code,)
            )
            existing = self.cursor.fetchone()

            if existing:
                print(f"  ⚠ Дисциплина {code} уже существует, пропускаем")
                return existing['id']

            # Подготовка данных
            venue = ','.join(discipline_data.get('venue', ['outdoor']))

            insert_data = {
                'code': code,
                'category_id': category_id,
                'subcategory_id': subcategory_id,
                'name_ru': discipline_data['name'],
                'name_en': discipline_data['name_en'],
                'distance': discipline_data.get('distance'),
                'distance_unit': discipline_data.get('unit', 'm'),
                'result_type': discipline_data.get('result_type', 'time'),
                'measurement_unit': discipline_data.get('measurement_unit', 'm'),
                'venue': venue,
                'has_heats': discipline_data.get('has_heats', False),
                'has_wind': discipline_data.get('has_wind', False),
                'max_wind_speed': discipline_data.get('max_wind'),
                'attempts': discipline_data.get('attempts'),
                'has_progression': discipline_data.get('progression', False),
                'hurdles_count': discipline_data.get('hurdles_count'),
                'has_water_jump': discipline_data.get('water_jump', False),
                'team_size': discipline_data.get('team_size'),
                'exchange_zones': discipline_data.get('exchange_zones'),
                'is_combined_event': False,
                'is_olympic': True,  # Можно добавить флаг в JSON
                'is_active': True
            }

            # SQL запрос
            columns = ', '.join(insert_data.keys())
            placeholders = ', '.join(['%s'] * len(insert_data))
            sql = f"INSERT INTO disciplines ({columns}) VALUES ({placeholders})"

            self.cursor.execute(sql, list(insert_data.values()))
            self.connection.commit()
            discipline_id = self.cursor.lastrowid

            self.stats['disciplines'] += 1
            print(f"  ✓ Создана дисциплина: {discipline_data['name']} ({code})")

            # Добавление полов
            if 'gender' in discipline_data:
                for gender in discipline_data['gender']:
                    self.add_discipline_gender(discipline_id, gender)

            # Добавление возрастных групп
            if 'age_groups' in discipline_data:
                for age_group in discipline_data['age_groups']:
                    self.add_discipline_age_group(discipline_id, age_group)

            # Добавление высот барьеров
            if 'hurdle_height' in discipline_data:
                for gender, height in discipline_data['hurdle_height'].items():
                    self.add_hurdle_height(discipline_id, gender, height)

            # Добавление весов снарядов
            if 'implement_weight' in discipline_data:
                for key, weight in discipline_data['implement_weight'].items():
                    parts = key.split('_')
                    gender = parts[0]
                    age_group = parts[1] if len(parts) > 1 else 'adults'
                    self.add_implement_weight(discipline_id, gender, age_group, weight)

            return discipline_id

        except Error as e:
            print(f"✗ Ошибка создания дисциплины {code}: {e}")
            self.stats['errors'].append(f"Discipline {code}: {str(e)}")
            return None

    def add_discipline_gender(self, discipline_id, gender):
        """Добавление пола для дисциплины"""
        try:
            self.cursor.execute(
                """INSERT IGNORE INTO discipline_genders
                   (discipline_id, gender) VALUES (%s, %s)""",
                (discipline_id, gender)
            )
            self.connection.commit()
            self.stats['genders'] += 1
        except Error as e:
            print(f"    ✗ Ошибка добавления пола {gender}: {e}")

    def add_discipline_age_group(self, discipline_id, age_group):
        """Добавление возрастной группы для дисциплины"""
        try:
            self.cursor.execute(
                """INSERT IGNORE INTO discipline_age_groups
                   (discipline_id, age_group) VALUES (%s, %s)""",
                (discipline_id, age_group)
            )
            self.connection.commit()
            self.stats['age_groups'] += 1
        except Error as e:
            print(f"    ✗ Ошибка добавления возрастной группы {age_group}: {e}")

    def add_hurdle_height(self, discipline_id, gender, height):
        """Добавление высоты барьера"""
        try:
            self.cursor.execute(
                """INSERT IGNORE INTO discipline_hurdle_heights
                   (discipline_id, gender, height) VALUES (%s, %s, %s)""",
                (discipline_id, gender, height)
            )
            self.connection.commit()
        except Error as e:
            print(f"    ✗ Ошибка добавления высоты барьера: {e}")

    def add_implement_weight(self, discipline_id, gender, age_group, weight):
        """Добавление веса снаряда"""
        try:
            self.cursor.execute(
                """INSERT IGNORE INTO discipline_implement_weights
                   (discipline_id, gender, age_group, weight)
                   VALUES (%s, %s, %s, %s)""",
                (discipline_id, gender, age_group, weight)
            )
            self.connection.commit()
        except Error as e:
            print(f"    ✗ Ошибка добавления веса снаряда: {e}")

    def create_combined_event(self, combined_data, category_id):
        """Создание многоборья"""
        try:
            code = combined_data['code']

            # Проверка существования
            self.cursor.execute(
                "SELECT id FROM disciplines WHERE code = %s",
                (code,)
            )
            existing = self.cursor.fetchone()

            if existing:
                print(f"  ⚠ Многоборье {code} уже существует, пропускаем")
                return existing['id']

            venue = ','.join(combined_data.get('venue', ['outdoor']))

            insert_data = {
                'code': code,
                'category_id': category_id,
                'subcategory_id': None,
                'name_ru': combined_data['name'],
                'name_en': combined_data['name_en'],
                'result_type': 'points',
                'venue': venue,
                'is_combined_event': True,
                'combined_days': combined_data.get('days', 1),
                'is_olympic': True,
                'is_active': True
            }

            columns = ', '.join(insert_data.keys())
            placeholders = ', '.join(['%s'] * len(insert_data))
            sql = f"INSERT INTO disciplines ({columns}) VALUES ({placeholders})"

            self.cursor.execute(sql, list(insert_data.values()))
            self.connection.commit()
            combined_id = self.cursor.lastrowid

            self.stats['disciplines'] += 1
            print(f"  ✓ Создано многоборье: {combined_data['name']} ({code})")

            # Добавление полов и возрастных групп
            if 'gender' in combined_data:
                for gender in combined_data['gender']:
                    self.add_discipline_gender(combined_id, gender)

            if 'age_groups' in combined_data:
                for age_group in combined_data['age_groups']:
                    self.add_discipline_age_group(combined_id, age_group)

            # Добавление входящих дисциплин
            if 'events' in combined_data:
                for event in combined_data['events']:
                    self.add_combined_event_discipline(
                        combined_id,
                        event['discipline_code'],
                        event['day'],
                        event['order']
                    )

            return combined_id

        except Error as e:
            print(f"✗ Ошибка создания многоборья {code}: {e}")
            self.stats['errors'].append(f"Combined event {code}: {str(e)}")
            return None

    def add_combined_event_discipline(self, combined_id, discipline_code, day, order):
        """Добавление дисциплины в состав многоборья"""
        try:
            # Найти ID дисциплины по коду
            self.cursor.execute(
                "SELECT id FROM disciplines WHERE code = %s",
                (discipline_code,)
            )
            result = self.cursor.fetchone()

            if not result:
                print(f"    ✗ Дисциплина {discipline_code} не найдена")
                return

            discipline_id = result['id']

            self.cursor.execute(
                """INSERT INTO combined_event_disciplines
                   (combined_event_id, discipline_id, day_number, event_order)
                   VALUES (%s, %s, %s, %s)""",
                (combined_id, discipline_id, day, order)
            )
            self.connection.commit()

        except Error as e:
            print(f"    ✗ Ошибка добавления дисциплины в многоборье: {e}")

    def import_all(self):
        """Основной метод импорта всех данных"""
        print("\n" + "="*60)
        print("ИМПОРТ ДИСЦИПЛИН ЛЕГКОЙ АТЛЕТИКИ")
        print("="*60 + "\n")

        # Загрузка JSON
        data = self.load_json()
        if not data:
            return False

        # Подключение к БД
        if not self.connect():
            return False

        try:
            categories_data = data['categories']

            # 1. Импорт беговых дисциплин
            print("\n[1/5] Импорт беговых дисциплин...")
            track_data = categories_data['track']
            track_category_id = self.get_or_create_category(
                'track',
                track_data['name'],
                track_data['name_en'],
                1
            )

            for subcat_code, subcat_data in track_data['subcategories'].items():
                print(f"\n  Подкатегория: {subcat_data['name']}")
                subcat_id = self.get_or_create_subcategory(
                    track_category_id,
                    subcat_code,
                    subcat_data['name'],
                    subcat_data['name_en']
                )

                for discipline in subcat_data['disciplines']:
                    self.create_discipline(discipline, track_category_id, subcat_id)

            # 2. Импорт технических дисциплин
            print("\n[2/5] Импорт технических дисциплин...")
            field_data = categories_data['field']
            field_category_id = self.get_or_create_category(
                'field',
                field_data['name'],
                field_data['name_en'],
                2
            )

            for subcat_code, subcat_data in field_data['subcategories'].items():
                print(f"\n  Подкатегория: {subcat_data['name']}")
                subcat_id = self.get_or_create_subcategory(
                    field_category_id,
                    subcat_code,
                    subcat_data['name'],
                    subcat_data['name_en']
                )

                for discipline in subcat_data['disciplines']:
                    self.create_discipline(discipline, field_category_id, subcat_id)

            # 3. Импорт многоборий
            print("\n[3/5] Импорт многоборий...")
            combined_data = categories_data['combined']
            combined_category_id = self.get_or_create_category(
                'combined',
                combined_data['name'],
                combined_data['name_en'],
                3
            )

            for combined in combined_data['disciplines']:
                self.create_combined_event(combined, combined_category_id)

            # 4. Импорт спортивной ходьбы
            print("\n[4/5] Импорт спортивной ходьбы (стадион)...")
            racewalk_data = categories_data['race_walk']
            racewalk_category_id = self.get_or_create_category(
                'race_walk',
                racewalk_data['name'],
                racewalk_data['name_en'],
                4
            )

            for discipline in racewalk_data['disciplines']:
                self.create_discipline(discipline, racewalk_category_id)

            # 5. Импорт шоссейных дисциплин
            print("\n[5/5] Импорт шоссейных дисциплин...")
            road_data = categories_data['road']
            road_category_id = self.get_or_create_category(
                'road',
                road_data['name'],
                road_data['name_en'],
                5
            )

            for discipline in road_data['disciplines']:
                self.create_discipline(discipline, road_category_id)

            # Статистика
            print("\n" + "="*60)
            print("ИТОГИ ИМПОРТА")
            print("="*60)
            print(f"✓ Категорий создано: {self.stats['categories']}")
            print(f"✓ Подкатегорий создано: {self.stats['subcategories']}")
            print(f"✓ Дисциплин создано: {self.stats['disciplines']}")
            print(f"✓ Полов добавлено: {self.stats['genders']}")
            print(f"✓ Возрастных групп добавлено: {self.stats['age_groups']}")

            if self.stats['errors']:
                print(f"\n⚠ Ошибок: {len(self.stats['errors'])}")
                for error in self.stats['errors']:
                    print(f"  - {error}")
            else:
                print("\n✓ Импорт завершен без ошибок!")

            print("="*60 + "\n")

            return True

        except Exception as e:
            print(f"\n✗ КРИТИЧЕСКАЯ ОШИБКА: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            self.disconnect()


def main():
    """Главная функция"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Импорт дисциплин легкой атлетики в БД'
    )
    parser.add_argument(
        'json_file',
        nargs='?',
        default='athletics-disciplines.json',
        help='Путь к JSON файлу с дисциплинами'
    )
    parser.add_argument(
        '--host',
        default='localhost',
        help='Хост БД'
    )
    parser.add_argument(
        '--database',
        default='fla65_reg_db',
        help='Имя базы данных'
    )
    parser.add_argument(
        '--user',
        default='fla65_user',
        help='Пользователь БД'
    )
    parser.add_argument(
        '--password',
        required=True,
        help='Пароль БД'
    )

    args = parser.parse_args()

    # Обновление конфигурации БД
    db_config = DB_CONFIG.copy()
    db_config.update({
        'host': args.host,
        'database': args.database,
        'user': args.user,
        'password': args.password
    })

    # Запуск импорта
    importer = DisciplineImporter(args.json_file, db_config)
    success = importer.import_all()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
