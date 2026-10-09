# Публичные данные SakhStart для сайта fla65.ru

Сервер хронометража — единая база событий федерации. Сайт fla65.ru (Tilda, HTML-блоки)
показывает календарь и страницы событий, забирая данные отсюда. Всё публичное — под `/r/…`
(только этот путь nginx на reg.fla65.ru отдаёт без входа).

## Календарь
`GET https://reg.fla65.ru/r/api/calendar?year=2026` → JSON, CORS для `https://fla65.ru`, `https://www.fla65.ru`.

```json
{
  "year": 2026,
  "updated": "2026-10-08T14:00:00",
  "events": [
    {
      "slug": "kubok26",                       // адрес страницы события: /r/<slug>
      "name": "Кубок Сахалинской области",
      "date": "2026-06-12", "date_end": "2026-06-13",   // date_end = null, если один день
      "place": "Стадион «Спартак»",            // объект (может быть пусто)
      "city": "Южно-Сахалинск",
      "venue": {"name": "Стадион «Спартак»", "address": "Южно-Сахалинск, ул. Горького, 7",
                "map": "https://yandex.ru/maps/?text=…"},   // или null. Если место не указано, для Южно-Сахалинска
                // по правилу федерации: «кросс» в названии — ЛБК «Триумф» (Горького, 25А); апрель–октябрь —
                // стадион «Спартак» (Горького, 7); остальное и «в помещении» — легкоатлетический манеж (Горького, 39).
                // Массовые забеги по улицам и другие города не угадываются.
      "level": "region",                       // russia | dfo | interregion | region | mass
      "adaptive": false,                       // адаптивный спорт
      "note": "Более 200 легкоатлетов из семи городов",
      "ours": true,                            // проводит ФЛАСО / SakhStart
      "kind": "stadium",                       // mass (массовый старт, чипы) | stadium
      "status": "planned",                     // planned | running | finished
      "page": "https://reg.fla65.ru/r/kubok26", // null, если не наше событие и страницы нет
      "reg": {"open": true, "deadline": "2026-06-10T20:00", "url": "https://reg.fla65.ru/r/kubok26"}, // или null
      "start_list": "https://reg.fla65.ru/r/kubok26/protocol?kind=start",   // или null — не опубликован
      "results": "https://reg.fla65.ru/r/kubok26/protocol",                 // или null
      "teams": "https://reg.fla65.ru/r/kubok26/protocol?kind=teams",        // командный зачёт или null
      "results_live": false,                   // true — идёт старт, результаты обновляются
      "live": "https://vk.com/video…",         // трансляция или null
      "photo": "https://disk.yandex.ru/…",     // фото или null
      "links": [{"title": "Итоги в новостях", "url": "https://fla65.ru/news/…"}],
      "files": [{"title": "Положение.pdf", "url": "https://reg.fla65.ru/r/kubok26/files/12", "size": 182000, "ext": "pdf"}]
    }
  ]
}
```
В календарь попадают только события с отметкой «Показывать на сайте». Сортировка — по дате.

## Страница события
- `GET /r/<slug>` — страница события (reg.html): шапка, регистрация (если открыта), протоколы, документы, фото, трансляция.
- `GET /r/<slug>/info` — данные формы регистрации (как раньше) + `"card": {…элемент календаря…}`.
- `GET /r/<slug>/startlist.json` — стартовый протокол (только если опубликован), формат как `/api/events/<id>/startlist` без чипов.
- `GET /r/<slug>/results.json` — результаты (только если опубликованы), формат как `/api/events/<id>/results` без чипов; `final: true`, когда соревнование завершено; `teams` — командный зачёт (группы → команды, очки по категориям, итог, место).
- `GET /r/<slug>/protocol[?kind=start|teams][&team=…]` — печатный протокол (protocol.html в публичном режиме); `team` — только участники одной команды (ссылка для тренера).
- `GET /r/<slug>/files/<id>` — файл, отмеченный «на сайте».

## Встраивание на fla65.ru
HTML-блок (T123) на странице «Соревнования»:
```html
<div id="sakhstart-calendar"></div>
<script src="https://reg.fla65.ru/r/assets/calendar.js" defer></script>
```
