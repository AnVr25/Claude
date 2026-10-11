<?php
/**
 * API для работы с дисциплинами легкой атлетики
 * Проект: SAKHSTART (reg.fla65.ru)
 * Версия: 2.8
 * Дата: 2026-10-11
 */

class DisciplinesAPI {

    private $db;

    public function __construct($database) {
        $this->db = $database;
    }

    /**
     * Получить список всех категорий дисциплин
     *
     * @return array
     */
    public function getCategories() {
        $query = "SELECT * FROM discipline_categories ORDER BY sort_order";
        $stmt = $this->db->prepare($query);
        $stmt->execute();
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }

    /**
     * Получить подкатегории по категории
     *
     * @param string $categoryCode Код категории
     * @return array
     */
    public function getSubcategories($categoryCode) {
        $query = "
            SELECT dsc.*
            FROM discipline_subcategories dsc
            JOIN discipline_categories dc ON dsc.category_id = dc.id
            WHERE dc.code = :category_code
            ORDER BY dsc.sort_order
        ";
        $stmt = $this->db->prepare($query);
        $stmt->execute(['category_code' => $categoryCode]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }

    /**
     * Получить список дисциплин с фильтрами
     *
     * @param array $filters Массив фильтров
     * @return array
     */
    public function getDisciplines($filters = []) {
        $query = "SELECT * FROM v_disciplines_full WHERE 1=1";
        $params = [];

        // Фильтр по категории
        if (!empty($filters['category'])) {
            $query .= " AND category_code = :category";
            $params['category'] = $filters['category'];
        }

        // Фильтр по подкатегории
        if (!empty($filters['subcategory'])) {
            $query .= " AND subcategory_code = :subcategory";
            $params['subcategory'] = $filters['subcategory'];
        }

        // Фильтр по месту проведения
        if (!empty($filters['venue'])) {
            $query .= " AND FIND_IN_SET(:venue, venue) > 0";
            $params['venue'] = $filters['venue'];
        }

        // Фильтр по полу
        if (!empty($filters['gender'])) {
            $query .= " AND FIND_IN_SET(:gender, available_genders) > 0";
            $params['gender'] = $filters['gender'];
        }

        // Фильтр по возрастной группе
        if (!empty($filters['age_group'])) {
            $query .= " AND FIND_IN_SET(:age_group, available_age_groups) > 0";
            $params['age_group'] = $filters['age_group'];
        }

        // Только активные
        if (!isset($filters['include_inactive']) || !$filters['include_inactive']) {
            $query .= " AND is_active = 1";
        }

        $query .= " ORDER BY sort_order, name_ru";

        $stmt = $this->db->prepare($query);
        $stmt->execute($params);

        $disciplines = $stmt->fetchAll(PDO::FETCH_ASSOC);

        // Преобразование строк в массивы
        foreach ($disciplines as &$discipline) {
            $discipline['venue'] = explode(',', $discipline['venue']);
            $discipline['available_genders'] = !empty($discipline['available_genders'])
                ? explode(',', $discipline['available_genders'])
                : [];
            $discipline['available_age_groups'] = !empty($discipline['available_age_groups'])
                ? explode(',', $discipline['available_age_groups'])
                : [];
        }

        return $disciplines;
    }

    /**
     * Получить полную информацию о дисциплине
     *
     * @param string $code Код дисциплины
     * @return array|null
     */
    public function getDisciplineByCode($code) {
        $query = "SELECT * FROM v_disciplines_full WHERE code = :code";
        $stmt = $this->db->prepare($query);
        $stmt->execute(['code' => $code]);
        $discipline = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$discipline) {
            return null;
        }

        // Преобразование строк в массивы
        $discipline['venue'] = explode(',', $discipline['venue']);
        $discipline['available_genders'] = !empty($discipline['available_genders'])
            ? explode(',', $discipline['available_genders'])
            : [];
        $discipline['available_age_groups'] = !empty($discipline['available_age_groups'])
            ? explode(',', $discipline['available_age_groups'])
            : [];

        // Дополнительная информация для многоборий
        if ($discipline['is_combined_event']) {
            $discipline['combined_disciplines'] = $this->getCombinedEventDisciplines($discipline['id']);
        }

        // Дополнительная информация для барьеров
        if ($discipline['hurdles_count'] > 0) {
            $discipline['hurdle_heights'] = $this->getHurdleHeights($discipline['id']);
        }

        // Дополнительная информация для метаний
        if (in_array($discipline['subcategory_code'], ['throws'])) {
            $discipline['implement_weights'] = $this->getImplementWeights($discipline['id']);
        }

        return $discipline;
    }

    /**
     * Получить состав многоборья
     *
     * @param int $combinedEventId ID многоборья
     * @return array
     */
    private function getCombinedEventDisciplines($combinedEventId) {
        $query = "
            SELECT
                ced.day_number,
                ced.event_order,
                d.code,
                d.name_ru,
                d.name_en
            FROM combined_event_disciplines ced
            JOIN disciplines d ON ced.discipline_id = d.id
            WHERE ced.combined_event_id = :combined_id
            ORDER BY ced.event_order
        ";
        $stmt = $this->db->prepare($query);
        $stmt->execute(['combined_id' => $combinedEventId]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }

    /**
     * Получить высоты барьеров
     *
     * @param int $disciplineId ID дисциплины
     * @return array
     */
    private function getHurdleHeights($disciplineId) {
        $query = "
            SELECT gender, height
            FROM discipline_hurdle_heights
            WHERE discipline_id = :discipline_id
        ";
        $stmt = $this->db->prepare($query);
        $stmt->execute(['discipline_id' => $disciplineId]);

        $heights = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $heights[$row['gender']] = floatval($row['height']);
        }
        return $heights;
    }

    /**
     * Получить веса снарядов
     *
     * @param int $disciplineId ID дисциплины
     * @return array
     */
    private function getImplementWeights($disciplineId) {
        $query = "
            SELECT gender, age_group, weight
            FROM discipline_implement_weights
            WHERE discipline_id = :discipline_id
            ORDER BY gender, age_group
        ";
        $stmt = $this->db->prepare($query);
        $stmt->execute(['discipline_id' => $disciplineId]);

        $weights = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $key = $row['gender'] . '_' . $row['age_group'];
            $weights[$key] = floatval($row['weight']);
        }
        return $weights;
    }

    /**
     * Получить дисциплины для формирования события
     * Группирует дисциплины по категориям и подкатегориям для удобного выбора
     *
     * @param string $venue Место проведения (outdoor/indoor)
     * @return array
     */
    public function getDisciplinesForEventCreation($venue = 'outdoor') {
        $categories = $this->getCategories();
        $result = [];

        foreach ($categories as $category) {
            $categoryData = [
                'code' => $category['code'],
                'name_ru' => $category['name_ru'],
                'name_en' => $category['name_en'],
                'subcategories' => []
            ];

            // Получить подкатегории
            $subcategories = $this->getSubcategories($category['code']);

            if (!empty($subcategories)) {
                // Есть подкатегории
                foreach ($subcategories as $subcategory) {
                    $disciplines = $this->getDisciplines([
                        'category' => $category['code'],
                        'subcategory' => $subcategory['code'],
                        'venue' => $venue
                    ]);

                    if (!empty($disciplines)) {
                        $categoryData['subcategories'][] = [
                            'code' => $subcategory['code'],
                            'name_ru' => $subcategory['name_ru'],
                            'name_en' => $subcategory['name_en'],
                            'disciplines' => $disciplines
                        ];
                    }
                }
            } else {
                // Нет подкатегорий, дисциплины напрямую в категории
                $disciplines = $this->getDisciplines([
                    'category' => $category['code'],
                    'venue' => $venue
                ]);

                if (!empty($disciplines)) {
                    $categoryData['disciplines'] = $disciplines;
                }
            }

            // Добавить категорию только если есть дисциплины
            if (!empty($categoryData['subcategories']) || !empty($categoryData['disciplines'])) {
                $result[] = $categoryData;
            }
        }

        return $result;
    }

    /**
     * Поиск дисциплин
     *
     * @param string $searchTerm Поисковый запрос
     * @param string $language Язык (ru/en)
     * @return array
     */
    public function searchDisciplines($searchTerm, $language = 'ru') {
        $nameField = $language === 'en' ? 'name_en' : 'name_ru';

        $query = "
            SELECT * FROM v_disciplines_full
            WHERE $nameField LIKE :search
               OR code LIKE :search
            ORDER BY $nameField
            LIMIT 50
        ";

        $stmt = $this->db->prepare($query);
        $stmt->execute(['search' => '%' . $searchTerm . '%']);

        $disciplines = $stmt->fetchAll(PDO::FETCH_ASSOC);

        foreach ($disciplines as &$discipline) {
            $discipline['venue'] = explode(',', $discipline['venue']);
            $discipline['available_genders'] = !empty($discipline['available_genders'])
                ? explode(',', $discipline['available_genders'])
                : [];
            $discipline['available_age_groups'] = !empty($discipline['available_age_groups'])
                ? explode(',', $discipline['available_age_groups'])
                : [];
        }

        return $disciplines;
    }

    /**
     * Получить рекомендуемые дисциплины для спортсмена
     * На основе пола, возраста и специализации
     *
     * @param array $athleteData Данные спортсмена
     * @return array
     */
    public function getRecommendedDisciplines($athleteData) {
        $filters = [
            'gender' => $athleteData['gender'],
            'age_group' => $athleteData['age_group']
        ];

        if (!empty($athleteData['venue_preference'])) {
            $filters['venue'] = $athleteData['venue_preference'];
        }

        if (!empty($athleteData['specialization'])) {
            $filters['category'] = $athleteData['specialization'];
        }

        return $this->getDisciplines($filters);
    }

    /**
     * Валидация возможности участия спортсмена в дисциплине
     *
     * @param string $disciplineCode Код дисциплины
     * @param array $athleteData Данные спортсмена
     * @return array ['valid' => bool, 'reason' => string]
     */
    public function validateAthleteForDiscipline($disciplineCode, $athleteData) {
        $discipline = $this->getDisciplineByCode($disciplineCode);

        if (!$discipline) {
            return [
                'valid' => false,
                'reason' => 'Дисциплина не найдена'
            ];
        }

        // Проверка пола
        if (!in_array($athleteData['gender'], $discipline['available_genders'])) {
            return [
                'valid' => false,
                'reason' => 'Дисциплина недоступна для данного пола'
            ];
        }

        // Проверка возрастной группы
        if (!in_array($athleteData['age_group'], $discipline['available_age_groups'])) {
            return [
                'valid' => false,
                'reason' => 'Дисциплина недоступна для данной возрастной группы'
            ];
        }

        return [
            'valid' => true,
            'reason' => ''
        ];
    }
}

/**
 * REST API эндпоинты
 */

// Подключение к БД
try {
    $pdo = new PDO(
        "mysql:host=localhost;dbname=fla65_reg_db;charset=utf8mb4",
        "fla65_user",
        "",
        [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
        ]
    );
} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'Database connection failed']);
    exit;
}

$api = new DisciplinesAPI($pdo);

// Обработка запросов
header('Content-Type: application/json; charset=utf-8');

$method = $_SERVER['REQUEST_METHOD'];
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$pathParts = explode('/', trim($path, '/'));

// GET /api/disciplines/categories
if ($method === 'GET' && end($pathParts) === 'categories') {
    echo json_encode($api->getCategories());
    exit;
}

// GET /api/disciplines/subcategories/{categoryCode}
if ($method === 'GET' && $pathParts[count($pathParts) - 2] === 'subcategories') {
    $categoryCode = end($pathParts);
    echo json_encode($api->getSubcategories($categoryCode));
    exit;
}

// GET /api/disciplines/search?q={term}
if ($method === 'GET' && end($pathParts) === 'search') {
    $searchTerm = $_GET['q'] ?? '';
    $language = $_GET['lang'] ?? 'ru';
    echo json_encode($api->searchDisciplines($searchTerm, $language));
    exit;
}

// GET /api/disciplines/for-event?venue={venue}
if ($method === 'GET' && end($pathParts) === 'for-event') {
    $venue = $_GET['venue'] ?? 'outdoor';
    echo json_encode($api->getDisciplinesForEventCreation($venue));
    exit;
}

// GET /api/disciplines/{code}
if ($method === 'GET' && count($pathParts) >= 3) {
    $code = end($pathParts);
    $discipline = $api->getDisciplineByCode($code);

    if ($discipline) {
        echo json_encode($discipline);
    } else {
        http_response_code(404);
        echo json_encode(['error' => 'Discipline not found']);
    }
    exit;
}

// GET /api/disciplines
if ($method === 'GET' && end($pathParts) === 'disciplines') {
    $filters = [
        'category' => $_GET['category'] ?? null,
        'subcategory' => $_GET['subcategory'] ?? null,
        'venue' => $_GET['venue'] ?? null,
        'gender' => $_GET['gender'] ?? null,
        'age_group' => $_GET['age_group'] ?? null,
        'include_inactive' => isset($_GET['include_inactive'])
    ];

    echo json_encode($api->getDisciplines($filters));
    exit;
}

// POST /api/disciplines/validate
if ($method === 'POST' && end($pathParts) === 'validate') {
    $input = json_decode(file_get_contents('php://input'), true);
    $result = $api->validateAthleteForDiscipline(
        $input['discipline_code'],
        $input['athlete_data']
    );
    echo json_encode($result);
    exit;
}

// POST /api/disciplines/recommend
if ($method === 'POST' && end($pathParts) === 'recommend') {
    $input = json_decode(file_get_contents('php://input'), true);
    echo json_encode($api->getRecommendedDisciplines($input));
    exit;
}

http_response_code(404);
echo json_encode(['error' => 'Endpoint not found']);
