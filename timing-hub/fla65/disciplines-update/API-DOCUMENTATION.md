# API Дисциплин легкой атлетики - Документация

**Проект:** SAKHSTART (reg.fla65.ru)  
**Версия:** 2.8  
**Дата:** 11 октября 2026

---

## Содержание

1. [Обзор](#обзор)
2. [Базовый URL](#базовый-url)
3. [Аутентификация](#аутентификация)
4. [Эндпоинты](#эндпоинты)
5. [Примеры использования](#примеры-использования)
6. [Коды ошибок](#коды-ошибок)

---

## Обзор

API предоставляет доступ к полному справочнику дисциплин легкой атлетики с возможностью фильтрации по различным параметрам.

### Основные возможности:
- ✅ Получение списка всех категорий и подкатегорий
- ✅ Фильтрация дисциплин по месту проведения, полу, возрасту
- ✅ Получение детальной информации о дисциплине
- ✅ Поиск дисциплин
- ✅ Формирование списка для создания события
- ✅ Валидация возможности участия спортсмена
- ✅ Рекомендации дисциплин для спортсмена

---

## Базовый URL

```
https://reg.fla65.ru/api/disciplines
```

---

## Аутентификация

В текущей версии API открыто для чтения. Для модификации данных требуется JWT токен.

**Заголовки запроса:**
```
Content-Type: application/json
Authorization: Bearer {token}  // Для защищенных эндпоинтов
```

---

## Эндпоинты

### 1. Получить категории дисциплин

Возвращает список всех основных категорий (беговые, технические, многоборья и т.д.)

**Запрос:**
```http
GET /api/disciplines/categories
```

**Ответ:**
```json
[
  {
    "id": 1,
    "code": "track",
    "name_ru": "Беговые дисциплины",
    "name_en": "Track Events",
    "description_ru": null,
    "description_en": null,
    "sort_order": 1
  },
  {
    "id": 2,
    "code": "field",
    "name_ru": "Технические дисциплины",
    "name_en": "Field Events",
    "sort_order": 2
  }
]
```

---

### 2. Получить подкатегории

Возвращает подкатегории для указанной категории.

**Запрос:**
```http
GET /api/disciplines/subcategories/{categoryCode}
```

**Параметры пути:**
- `categoryCode` - код категории (track, field, combined, race_walk, road)

**Пример:**
```http
GET /api/disciplines/subcategories/track
```

**Ответ:**
```json
[
  {
    "id": 1,
    "category_id": 1,
    "code": "sprints",
    "name_ru": "Спринт",
    "name_en": "Sprints",
    "sort_order": 1
  },
  {
    "id": 2,
    "category_id": 1,
    "code": "middle_distance",
    "name_ru": "Средние дистанции",
    "name_en": "Middle Distance",
    "sort_order": 2
  }
]
```

---

### 3. Получить список дисциплин

Возвращает список дисциплин с возможностью фильтрации.

**Запрос:**
```http
GET /api/disciplines?{параметры}
```

**Параметры запроса:**

| Параметр | Тип | Описание | Пример |
|----------|-----|----------|--------|
| `category` | string | Код категории | `track` |
| `subcategory` | string | Код подкатегории | `sprints` |
| `venue` | string | Место проведения | `outdoor`, `indoor` |
| `gender` | string | Пол | `M`, `W`, `Mixed` |
| `age_group` | string | Возрастная группа | `adults`, `u20`, `u18` |
| `include_inactive` | boolean | Включить неактивные | `true` |

**Примеры запросов:**

```http
# Все беговые дисциплины на открытом стадионе
GET /api/disciplines?category=track&venue=outdoor

# Спринтерские дисциплины для женщин
GET /api/disciplines?subcategory=sprints&gender=W

# Дисциплины для юниоров (U20)
GET /api/disciplines?age_group=u20
```

**Ответ:**
```json
[
  {
    "id": 1,
    "code": "100M",
    "name_ru": "100 метров",
    "name_en": "100 metres",
    "short_name_ru": null,
    "short_name_en": null,
    "category_code": "track",
    "category_name_ru": "Беговые дисциплины",
    "category_name_en": "Track Events",
    "subcategory_code": "sprints",
    "subcategory_name_ru": "Спринт",
    "subcategory_name_en": "Sprints",
    "distance": 100,
    "distance_unit": "m",
    "result_type": "time",
    "venue": ["outdoor"],
    "has_heats": true,
    "has_wind": true,
    "max_wind_speed": 2.0,
    "attempts": null,
    "is_combined_event": false,
    "is_olympic": true,
    "is_active": true,
    "available_genders": ["M", "W"],
    "available_age_groups": ["adults", "u23", "u20", "u18", "u16"]
  }
]
```

---

### 4. Получить дисциплину по коду

Возвращает детальную информацию о конкретной дисциплине.

**Запрос:**
```http
GET /api/disciplines/{code}
```

**Параметры пути:**
- `code` - код дисциплины (100M, HJ, DEC и т.д.)

**Пример:**
```http
GET /api/disciplines/110MH
```

**Ответ для барьерного бега:**
```json
{
  "id": 10,
  "code": "110MH",
  "name_ru": "110 метров с барьерами",
  "name_en": "110 metres hurdles",
  "category_code": "track",
  "subcategory_code": "hurdles",
  "distance": 110,
  "distance_unit": "m",
  "result_type": "time",
  "venue": ["outdoor"],
  "has_heats": true,
  "has_wind": true,
  "max_wind_speed": 2.0,
  "hurdles_count": 10,
  "hurdle_heights": {
    "M": 1.067
  },
  "available_genders": ["M"],
  "available_age_groups": ["adults", "u23", "u20", "u18"]
}
```

**Ответ для многоборья:**
```json
{
  "id": 50,
  "code": "DEC",
  "name_ru": "Десятиборье (мужчины)",
  "name_en": "Decathlon",
  "category_code": "combined",
  "result_type": "points",
  "venue": ["outdoor"],
  "is_combined_event": true,
  "combined_disciplines": [
    {
      "day_number": 1,
      "event_order": 1,
      "code": "100M",
      "name_ru": "100 метров",
      "name_en": "100 metres"
    },
    {
      "day_number": 1,
      "event_order": 2,
      "code": "LJ",
      "name_ru": "Прыжок в длину",
      "name_en": "Long Jump"
    }
    // ... остальные дисциплины
  ],
  "available_genders": ["M"],
  "available_age_groups": ["adults", "u23", "u20", "u18"]
}
```

**Ответ для метания:**
```json
{
  "id": 30,
  "code": "SP",
  "name_ru": "Толкание ядра",
  "name_en": "Shot Put",
  "category_code": "field",
  "subcategory_code": "throws",
  "result_type": "distance",
  "measurement_unit": "m",
  "venue": ["outdoor", "indoor"],
  "attempts": 6,
  "implement_weights": {
    "M_adults": 7.26,
    "M_u20": 6.0,
    "M_u18": 5.0,
    "W_adults": 4.0,
    "W_u20": 4.0,
    "W_u18": 3.0
  },
  "available_genders": ["M", "W"],
  "available_age_groups": ["adults", "u23", "u20", "u18", "u16"]
}
```

---

### 5. Поиск дисциплин

Поиск по названию или коду дисциплины.

**Запрос:**
```http
GET /api/disciplines/search?q={searchTerm}&lang={language}
```

**Параметры запроса:**
- `q` - поисковый запрос (обязательный)
- `lang` - язык поиска: `ru` или `en` (по умолчанию: `ru`)

**Примеры:**
```http
# Поиск по русскому названию
GET /api/disciplines/search?q=барьер

# Поиск по английскому названию
GET /api/disciplines/search?q=hurdles&lang=en

# Поиск по коду
GET /api/disciplines/search?q=100
```

**Ответ:**
```json
[
  {
    "id": 1,
    "code": "100M",
    "name_ru": "100 метров",
    "name_en": "100 metres"
    // ... остальные поля
  },
  {
    "id": 10,
    "code": "100MH",
    "name_ru": "100 метров с барьерами",
    "name_en": "100 metres hurdles"
    // ... остальные поля
  }
]
```

---

### 6. Дисциплины для создания события

Возвращает структурированный список дисциплин, сгруппированный по категориям и подкатегориям. Удобен для формирования выпадающих списков при создании события.

**Запрос:**
```http
GET /api/disciplines/for-event?venue={venue}
```

**Параметры запроса:**
- `venue` - место проведения: `outdoor` (по умолчанию) или `indoor`

**Пример:**
```http
GET /api/disciplines/for-event?venue=outdoor
```

**Ответ:**
```json
[
  {
    "code": "track",
    "name_ru": "Беговые дисциплины",
    "name_en": "Track Events",
    "subcategories": [
      {
        "code": "sprints",
        "name_ru": "Спринт",
        "name_en": "Sprints",
        "disciplines": [
          {
            "id": 1,
            "code": "100M",
            "name_ru": "100 метров",
            "name_en": "100 metres",
            "available_genders": ["M", "W"],
            "available_age_groups": ["adults", "u23", "u20", "u18", "u16"]
          }
          // ... остальные спринтерские дисциплины
        ]
      },
      {
        "code": "middle_distance",
        "name_ru": "Средние дистанции",
        "name_en": "Middle Distance",
        "disciplines": [
          // ... дисциплины средних дистанций
        ]
      }
    ]
  },
  {
    "code": "field",
    "name_ru": "Технические дисциплины",
    "name_en": "Field Events",
    "subcategories": [
      // ... подкатегории технических дисциплин
    ]
  }
]
```

**Использование в UI:**

Этот эндпоинт идеален для построения каскадных выпадающих списков:
1. Категория → Подкатегория → Дисциплина
2. Выбор дисциплины автоматически показывает доступные полы и возрастные группы

---

### 7. Валидация участия спортсмена

Проверяет, может ли спортсмен участвовать в указанной дисциплине.

**Запрос:**
```http
POST /api/disciplines/validate
Content-Type: application/json

{
  "discipline_code": "100M",
  "athlete_data": {
    "gender": "W",
    "age_group": "u20"
  }
}
```

**Ответ (успешная валидация):**
```json
{
  "valid": true,
  "reason": ""
}
```

**Ответ (неуспешная валидация):**
```json
{
  "valid": false,
  "reason": "Дисциплина недоступна для данного пола"
}
```

---

### 8. Рекомендации дисциплин

Возвращает список рекомендуемых дисциплин для спортсмена на основе его параметров.

**Запрос:**
```http
POST /api/disciplines/recommend
Content-Type: application/json

{
  "gender": "M",
  "age_group": "u18",
  "venue_preference": "outdoor",
  "specialization": "track"
}
```

**Параметры:**
- `gender` - пол (обязательный): `M`, `W`
- `age_group` - возрастная группа (обязательный): `adults`, `u23`, `u20`, `u18`, `u16`
- `venue_preference` - предпочтение места (опциональный): `outdoor`, `indoor`
- `specialization` - специализация (опциональный): `track`, `field`, `combined`

**Ответ:**
```json
[
  {
    "id": 1,
    "code": "100M",
    "name_ru": "100 метров",
    "name_en": "100 metres"
    // ... остальные поля
  },
  {
    "id": 2,
    "code": "200M",
    "name_ru": "200 метров",
    "name_en": "200 metres"
    // ... остальные поля
  }
  // ... другие подходящие дисциплины
]
```

---

## Примеры использования

### JavaScript (Fetch API)

```javascript
// Получить все спринтерские дисциплины
async function getSprints() {
  const response = await fetch(
    'https://reg.fla65.ru/api/disciplines?subcategory=sprints&venue=outdoor'
  );
  const disciplines = await response.json();
  console.log(disciplines);
}

// Получить дисциплины для выбора в форме создания события
async function getDisciplinesForEventForm() {
  const response = await fetch(
    'https://reg.fla65.ru/api/disciplines/for-event?venue=outdoor'
  );
  const grouped = await response.json();
  
  // Построение select элемента
  grouped.forEach(category => {
    const optgroup = document.createElement('optgroup');
    optgroup.label = category.name_ru;
    
    category.subcategories.forEach(subcategory => {
      subcategory.disciplines.forEach(discipline => {
        const option = document.createElement('option');
        option.value = discipline.code;
        option.textContent = `${discipline.name_ru} (${discipline.code})`;
        optgroup.appendChild(option);
      });
    });
    
    selectElement.appendChild(optgroup);
  });
}

// Валидация участия спортсмена
async function validateAthlete(disciplineCode, athleteData) {
  const response = await fetch(
    'https://reg.fla65.ru/api/disciplines/validate',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        discipline_code: disciplineCode,
        athlete_data: athleteData
      })
    }
  );
  
  const result = await response.json();
  
  if (!result.valid) {
    alert(result.reason);
    return false;
  }
  
  return true;
}
```

### PHP

```php
<?php
// Получить дисциплину по коду
function getDiscipline($code) {
    $url = "https://reg.fla65.ru/api/disciplines/{$code}";
    $response = file_get_contents($url);
    return json_decode($response, true);
}

// Поиск дисциплин
function searchDisciplines($query) {
    $url = "https://reg.fla65.ru/api/disciplines/search?q=" . urlencode($query);
    $response = file_get_contents($url);
    return json_decode($response, true);
}

// Использование
$discipline = getDiscipline('100M');
echo $discipline['name_ru']; // "100 метров"

$results = searchDisciplines('барьер');
foreach ($results as $disc) {
    echo $disc['name_ru'] . "\n";
}
?>
```

### Python

```python
import requests

# Получить категории
def get_categories():
    response = requests.get('https://reg.fla65.ru/api/disciplines/categories')
    return response.json()

# Получить дисциплины с фильтрами
def get_disciplines(filters):
    response = requests.get(
        'https://reg.fla65.ru/api/disciplines',
        params=filters
    )
    return response.json()

# Пример использования
categories = get_categories()
for cat in categories:
    print(f"{cat['name_ru']} ({cat['code']})")

# Получить женские дисциплины для юниоров
disciplines = get_disciplines({
    'gender': 'W',
    'age_group': 'u20',
    'venue': 'outdoor'
})

for disc in disciplines:
    print(f"{disc['name_ru']} - {disc['code']}")
```

---

## Коды ошибок

| Код | Описание | Решение |
|-----|----------|---------|
| 200 | OK | Запрос выполнен успешно |
| 400 | Bad Request | Проверьте параметры запроса |
| 404 | Not Found | Дисциплина или эндпоинт не найден |
| 500 | Internal Server Error | Ошибка на сервере, обратитесь к администратору |

**Формат ошибки:**
```json
{
  "error": "Описание ошибки"
}
```

---

## Справочные данные

### Коды категорий
- `track` - Беговые дисциплины
- `field` - Технические дисциплины
- `combined` - Многоборья
- `race_walk` - Спортивная ходьба (стадион)
- `road` - Шоссейные дисциплины

### Коды подкатегорий
**Беговые:**
- `sprints` - Спринт
- `middle_distance` - Средние дистанции
- `long_distance` - Длинные дистанции
- `hurdles` - Барьерный бег
- `steeplechase` - Бег с препятствиями
- `relays` - Эстафеты

**Технические:**
- `jumps` - Прыжки
- `throws` - Метания

### Полы (gender)
- `M` - Мужчины (Men)
- `W` - Женщины (Women)
- `Mixed` - Смешанная (для эстафет)

### Возрастные группы (age_group)
- `adults` - Взрослые (20+)
- `u23` - До 23 лет (18-22)
- `u20` - Юниоры (16-19)
- `u18` - Юноши (14-17)
- `u16` - Младшие юноши (12-15)

### Места проведения (venue)
- `outdoor` - Открытый стадион
- `indoor` - Закрытое помещение
- `track` - Легкоатлетический стадион
- `road` - Шоссе

### Типы результатов (result_type)
- `time` - Время (беговые дисциплины)
- `distance` - Расстояние (прыжки, метания)
- `height` - Высота (прыжок в высоту, шест)
- `points` - Очки (многоборья)

---

## Версионирование

Текущая версия API: **2.8**

При изменении структуры API версия будет обновляться. Старые версии будут поддерживаться минимум 6 месяцев после выпуска новой.

---

## Поддержка

**Техническая поддержка:**
- Email: tech@fla65.ru
- Telegram: @sakhstart_support

**Документация проекта:**
- GitHub: github.com/fla65/sakhstart-api
- Wiki: wiki.fla65.ru

---

*Документация обновлена: 11 октября 2026, 14:18 UTC*
