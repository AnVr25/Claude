-- SQL Schema для базы данных дисциплин легкой атлетики
-- Проект: SAKHSTART (reg.fla65.ru)
-- Версия: 2.8
-- Дата: 2026-10-11

-- ==============================================
-- 1. СПРАВОЧНИК КАТЕГОРИЙ ДИСЦИПЛИН
-- ==============================================

CREATE TABLE IF NOT EXISTS discipline_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name_ru VARCHAR(255) NOT NULL,
    name_en VARCHAR(255) NOT NULL,
    description_ru TEXT,
    description_en TEXT,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Заполнение категорий
INSERT INTO discipline_categories (code, name_ru, name_en, sort_order) VALUES
('track', 'Беговые дисциплины', 'Track Events', 1),
('field', 'Технические дисциплины', 'Field Events', 2),
('combined', 'Многоборья', 'Combined Events', 3),
('race_walk', 'Спортивная ходьба (стадион)', 'Race Walking (Stadium)', 4),
('road', 'Шоссейные дисциплины', 'Road Events', 5);

-- ==============================================
-- 2. СПРАВОЧНИК ПОДКАТЕГОРИЙ
-- ==============================================

CREATE TABLE IF NOT EXISTS discipline_subcategories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_id INT NOT NULL,
    code VARCHAR(50) UNIQUE NOT NULL,
    name_ru VARCHAR(255) NOT NULL,
    name_en VARCHAR(255) NOT NULL,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (category_id) REFERENCES discipline_categories(id) ON DELETE CASCADE,
    INDEX idx_category (category_id),
    INDEX idx_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Заполнение подкатегорий
INSERT INTO discipline_subcategories (category_id, code, name_ru, name_en, sort_order) VALUES
-- Беговые
(1, 'sprints', 'Спринт', 'Sprints', 1),
(1, 'middle_distance', 'Средние дистанции', 'Middle Distance', 2),
(1, 'long_distance', 'Длинные дистанции', 'Long Distance', 3),
(1, 'hurdles', 'Барьерный бег', 'Hurdles', 4),
(1, 'steeplechase', 'Бег с препятствиями', 'Steeplechase', 5),
(1, 'relays', 'Эстафеты', 'Relays', 6),
-- Технические
(2, 'jumps', 'Прыжки', 'Jumps', 1),
(2, 'throws', 'Метания', 'Throws', 2);

-- ==============================================
-- 3. ОСНОВНОЙ СПРАВОЧНИК ДИСЦИПЛИН
-- ==============================================

CREATE TABLE IF NOT EXISTS disciplines (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    category_id INT NOT NULL,
    subcategory_id INT,
    name_ru VARCHAR(255) NOT NULL,
    name_en VARCHAR(255) NOT NULL,
    short_name_ru VARCHAR(100),
    short_name_en VARCHAR(100),

    -- Для беговых дисциплин
    distance DECIMAL(10,2),
    distance_unit ENUM('m', 'km') DEFAULT 'm',

    -- Тип результата
    result_type ENUM('time', 'distance', 'height', 'points') DEFAULT 'time',
    measurement_unit VARCHAR(10),

    -- Условия проведения
    venue SET('outdoor', 'indoor', 'track', 'road') NOT NULL,

    -- Особенности
    has_heats BOOLEAN DEFAULT FALSE,
    has_wind BOOLEAN DEFAULT FALSE,
    max_wind_speed DECIMAL(3,1),

    -- Попытки (для технических дисциплин)
    attempts INT,
    has_progression BOOLEAN DEFAULT FALSE,

    -- Барьеры
    hurdles_count INT,
    has_water_jump BOOLEAN DEFAULT FALSE,

    -- Эстафеты
    team_size INT,
    exchange_zones INT,

    -- Многоборье
    is_combined_event BOOLEAN DEFAULT FALSE,
    combined_days INT,

    -- Статус
    is_olympic BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,

    sort_order INT DEFAULT 0,
    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (category_id) REFERENCES discipline_categories(id),
    FOREIGN KEY (subcategory_id) REFERENCES discipline_subcategories(id),

    INDEX idx_code (code),
    INDEX idx_category (category_id),
    INDEX idx_subcategory (subcategory_id),
    INDEX idx_venue (venue),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 4. ПОЛЫ ДЛЯ ДИСЦИПЛИН
-- ==============================================

CREATE TABLE IF NOT EXISTS discipline_genders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    discipline_id INT NOT NULL,
    gender ENUM('M', 'W', 'Mixed') NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (discipline_id) REFERENCES disciplines(id) ON DELETE CASCADE,
    UNIQUE KEY unique_discipline_gender (discipline_id, gender),
    INDEX idx_discipline (discipline_id),
    INDEX idx_gender (gender)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 5. ВОЗРАСТНЫЕ ГРУППЫ ДЛЯ ДИСЦИПЛИН
-- ==============================================

CREATE TABLE IF NOT EXISTS discipline_age_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    discipline_id INT NOT NULL,
    age_group ENUM('adults', 'u23', 'u20', 'u18', 'u16', 'u14') NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (discipline_id) REFERENCES disciplines(id) ON DELETE CASCADE,
    UNIQUE KEY unique_discipline_age (discipline_id, age_group),
    INDEX idx_discipline (discipline_id),
    INDEX idx_age_group (age_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 6. ВЫСОТЫ БАРЬЕРОВ ПО ПОЛАМ
-- ==============================================

CREATE TABLE IF NOT EXISTS discipline_hurdle_heights (
    id INT AUTO_INCREMENT PRIMARY KEY,
    discipline_id INT NOT NULL,
    gender ENUM('M', 'W') NOT NULL,
    height DECIMAL(4,3) NOT NULL COMMENT 'Высота в метрах',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (discipline_id) REFERENCES disciplines(id) ON DELETE CASCADE,
    UNIQUE KEY unique_discipline_gender_hurdle (discipline_id, gender),
    INDEX idx_discipline (discipline_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 7. ВЕСА СНАРЯДОВ ПО ПОЛАМ И ВОЗРАСТАМ
-- ==============================================

CREATE TABLE IF NOT EXISTS discipline_implement_weights (
    id INT AUTO_INCREMENT PRIMARY KEY,
    discipline_id INT NOT NULL,
    gender ENUM('M', 'W') NOT NULL,
    age_group ENUM('adults', 'u23', 'u20', 'u18', 'u16') NOT NULL,
    weight DECIMAL(6,2) NOT NULL COMMENT 'Вес в кг',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (discipline_id) REFERENCES disciplines(id) ON DELETE CASCADE,
    UNIQUE KEY unique_implement (discipline_id, gender, age_group),
    INDEX idx_discipline (discipline_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 8. СОСТАВ МНОГОБОРИЙ
-- ==============================================

CREATE TABLE IF NOT EXISTS combined_event_disciplines (
    id INT AUTO_INCREMENT PRIMARY KEY,
    combined_event_id INT NOT NULL COMMENT 'ID многоборья из disciplines',
    discipline_id INT NOT NULL COMMENT 'ID входящей дисциплины',
    day_number INT NOT NULL DEFAULT 1,
    event_order INT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (combined_event_id) REFERENCES disciplines(id) ON DELETE CASCADE,
    FOREIGN KEY (discipline_id) REFERENCES disciplines(id) ON DELETE CASCADE,
    UNIQUE KEY unique_combined_order (combined_event_id, event_order),
    INDEX idx_combined (combined_event_id),
    INDEX idx_day (day_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 9. СПРАВОЧНИК ВОЗРАСТНЫХ ГРУПП
-- ==============================================

CREATE TABLE IF NOT EXISTS age_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    name_ru VARCHAR(100) NOT NULL,
    name_en VARCHAR(100) NOT NULL,
    age_from INT,
    age_to INT,
    category ENUM('senior', 'youth', 'masters') DEFAULT 'senior',
    sort_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_code (code),
    INDEX idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO age_groups (code, name_ru, name_en, age_from, age_to, category, sort_order) VALUES
('adults', 'Взрослые', 'Senior', 20, NULL, 'senior', 1),
('u23', 'До 23 лет', 'Under 23', 18, 22, 'youth', 2),
('u20', 'Юниоры', 'Junior (Under 20)', 16, 19, 'youth', 3),
('u18', 'Юноши', 'Youth (Under 18)', 14, 17, 'youth', 4),
('u16', 'Младшие юноши', 'Under 16', 12, 15, 'youth', 5),
('u14', 'Младшие юноши', 'Under 14', 10, 13, 'youth', 6);

-- ==============================================
-- 10. СОБЫТИЯ (СОРЕВНОВАНИЯ)
-- ==============================================

CREATE TABLE IF NOT EXISTS events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    competition_id INT NOT NULL COMMENT 'ID соревнования',
    discipline_id INT NOT NULL,
    gender ENUM('M', 'W', 'Mixed') NOT NULL,
    age_group ENUM('adults', 'u23', 'u20', 'u18', 'u16', 'u14') NOT NULL,

    event_date DATE NOT NULL,
    start_time TIME,
    venue ENUM('outdoor', 'indoor', 'track', 'road') NOT NULL,

    -- Формат
    round_type ENUM('final', 'heat', 'semifinal', 'qualification') DEFAULT 'final',
    has_multiple_rounds BOOLEAN DEFAULT FALSE,

    -- Статус
    status ENUM('scheduled', 'in_progress', 'completed', 'cancelled') DEFAULT 'scheduled',

    -- Лимиты
    max_participants INT,
    registration_deadline DATETIME,

    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (discipline_id) REFERENCES disciplines(id),

    INDEX idx_competition (competition_id),
    INDEX idx_discipline (discipline_id),
    INDEX idx_date (event_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 11. РЕГИСТРАЦИЯ НА СОБЫТИЯ
-- ==============================================

CREATE TABLE IF NOT EXISTS event_registrations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_id INT NOT NULL,
    athlete_id INT NOT NULL COMMENT 'ID спортсмена',
    club_id INT COMMENT 'ID клуба/организации',
    coach_id INT COMMENT 'ID тренера',

    -- Личные рекорды (для сидирования)
    personal_best VARCHAR(50),
    season_best VARCHAR(50),

    -- Статус заявки
    registration_status ENUM('pending', 'approved', 'rejected', 'withdrawn') DEFAULT 'pending',
    payment_status ENUM('unpaid', 'paid', 'refunded') DEFAULT 'unpaid',

    -- Для эстафет
    team_name VARCHAR(255),
    is_team_event BOOLEAN DEFAULT FALSE,

    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_date TIMESTAMP NULL,
    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,

    INDEX idx_event (event_id),
    INDEX idx_athlete (athlete_id),
    INDEX idx_status (registration_status),
    INDEX idx_payment (payment_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 12. РЕЗУЛЬТАТЫ
-- ==============================================

CREATE TABLE IF NOT EXISTS results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_id INT NOT NULL,
    registration_id INT NOT NULL,

    -- Результат
    result_value VARCHAR(50) NOT NULL,
    result_numeric DECIMAL(12,4) COMMENT 'Для сортировки',

    -- Для многоборий
    points INT COMMENT 'Очки в многоборье',

    -- Место
    place INT,

    -- Ветер (для соответствующих дисциплин)
    wind_speed DECIMAL(3,1),

    -- Статус результата
    is_record BOOLEAN DEFAULT FALSE,
    record_type ENUM('WR', 'CR', 'NR', 'PB', 'SB') COMMENT 'WR-мировой, CR-рекорд соревнований, NR-национальный, PB-личный, SB-сезона',

    disqualified BOOLEAN DEFAULT FALSE,
    disqualification_reason TEXT,

    result_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
    FOREIGN KEY (registration_id) REFERENCES event_registrations(id) ON DELETE CASCADE,

    INDEX idx_event (event_id),
    INDEX idx_registration (registration_id),
    INDEX idx_place (place),
    INDEX idx_record (is_record)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- 13. ПОПЫТКИ (для технических дисциплин)
-- ==============================================

CREATE TABLE IF NOT EXISTS attempts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    result_id INT NOT NULL,
    attempt_number INT NOT NULL,

    -- Значение попытки
    attempt_value VARCHAR(50),
    attempt_numeric DECIMAL(12,4),

    -- Ветер (для прыжков)
    wind_speed DECIMAL(3,1),

    -- Статус
    is_valid BOOLEAN DEFAULT TRUE,
    foul_type ENUM('foul', 'pass', 'dns', 'dnf') COMMENT 'foul-заступ, pass-пропуск, dns-не вышел, dnf-не закончил',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (result_id) REFERENCES results(id) ON DELETE CASCADE,
    UNIQUE KEY unique_attempt (result_id, attempt_number),
    INDEX idx_result (result_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- ПРЕДСТАВЛЕНИЯ ДЛ�Я УДОБНОЙ ВЫБОРКИ
-- ==============================================

-- Полная информация о дисциплине с категориями
CREATE OR REPLACE VIEW v_disciplines_full AS
SELECT
    d.id,
    d.code,
    d.name_ru,
    d.name_en,
    d.short_name_ru,
    d.short_name_en,

    dc.code AS category_code,
    dc.name_ru AS category_name_ru,
    dc.name_en AS category_name_en,

    dsc.code AS subcategory_code,
    dsc.name_ru AS subcategory_name_ru,
    dsc.name_en AS subcategory_name_en,

    d.distance,
    d.distance_unit,
    d.result_type,
    d.venue,
    d.has_heats,
    d.has_wind,
    d.max_wind_speed,
    d.attempts,
    d.is_combined_event,
    d.is_olympic,
    d.is_active,

    GROUP_CONCAT(DISTINCT dg.gender) AS available_genders,
    GROUP_CONCAT(DISTINCT dag.age_group) AS available_age_groups

FROM disciplines d
LEFT JOIN discipline_categories dc ON d.category_id = dc.id
LEFT JOIN discipline_subcategories dsc ON d.subcategory_id = dsc.id
LEFT JOIN discipline_genders dg ON d.id = dg.discipline_id
LEFT JOIN discipline_age_groups dag ON d.id = dag.discipline_id
WHERE d.is_active = TRUE
GROUP BY d.id;

-- Дисциплины с фильтром по месту проведения
CREATE OR REPLACE VIEW v_outdoor_disciplines AS
SELECT * FROM v_disciplines_full
WHERE FIND_IN_SET('outdoor', venue) > 0;

CREATE OR REPLACE VIEW v_indoor_disciplines AS
SELECT * FROM v_disciplines_full
WHERE FIND_IN_SET('indoor', venue) > 0;

-- События с полной информацией
CREATE OR REPLACE VIEW v_events_full AS
SELECT
    e.id,
    e.name,
    e.event_date,
    e.start_time,
    e.venue,
    e.round_type,
    e.status,

    d.code AS discipline_code,
    d.name_ru AS discipline_name_ru,
    d.name_en AS discipline_name_en,

    e.gender,
    e.age_group,

    ag.name_ru AS age_group_name_ru,
    ag.name_en AS age_group_name_en,

    COUNT(er.id) AS registrations_count,
    e.max_participants

FROM events e
LEFT JOIN disciplines d ON e.discipline_id = d.id
LEFT JOIN age_groups ag ON e.age_group = ag.code
LEFT JOIN event_registrations er ON e.id = er.event_id AND er.registration_status = 'approved'
GROUP BY e.id;

-- ==============================================
-- КОММЕНТАРИИ К ТАБЛИЦАМ
-- ==============================================

ALTER TABLE disciplines COMMENT = 'Справочник всех дисциплин легкой атлетики';
ALTER TABLE discipline_categories COMMENT = 'Основные категории дисциплин';
ALTER TABLE discipline_subcategories COMMENT = 'Подкатегории внутри основных категорий';
ALTER TABLE events COMMENT = 'События (виды программы) на соревнованиях';
ALTER TABLE event_registrations COMMENT = 'Заявки спортсменов на участие в событиях';
ALTER TABLE results COMMENT = 'Результаты выступлений';
ALTER TABLE attempts COMMENT = 'Попытки в технических дисциплинах';
