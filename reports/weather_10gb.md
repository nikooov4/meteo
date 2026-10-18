# Карта из архива 10 GB и выбор времени

2026-10-19. Основная ссылка:
[глобальная карта](http://127.0.0.1:8765/synthetic_global_animation.html?view=10gb).
Слева сверху задаются начало и конец в UTC, сценарий и кнопка «Показать».
Конец периода не включён. Ползунок и Play работают внутри выбранного периода;
смена периода сохраняет зум. Панорамирование, PNG, fullscreen и «Весь мир» сохранены.

## Что подготовлено

Новый каталог `data/scale/weather-global-10gb-v2/` содержит **10 083 749 720 bytes**
(10.08375 GB, 9.39122 GiB), 118 различных полезных NetCDF shards,
1 099 526 400 hourly-point records. Нет padding, sparse placeholders или копий
одного файла. Старые наборы 1 GB v2 и 200 GB legacy-v1 сохранены.
Manifest SHA256: `07ae01c688ffb1b2d4a7870266eb8113aa2e424a4ed796fc748c7dde7a248663`.
[Байт-в-байт копия manifest](../experiments/data_manifests/weather-global-10gb-v2.json).

Генератор и calibration прежние: monthly whole-cycle bootstrap ERA5 LSP,
seed=42, sigma=0.12, сетка 180×360, шаг 1°, выборка native grid points.
LSP — крупномасштабная компонента, не total precipitation. Возмущение не
объявляется новым методом генерации или доказанным улучшением над bootstrap.
Генерация заняла 173.226 s, sampled process-tree peak RSS — 195 231 744 bytes.
До запуска проверен диск: свободно 246 406 582 272 bytes, требовалось
12 086 584 576; [dry-run](weather-10gb/generation-plan.json).

| Сценарий | Доступное время UTC, конец не включён | Часов |
|---|---|---:|
| 0 | 2023-01-01 06:00 → 2024-01-01 06:00 | 8760 |
| 1 | 2023-01-01 06:00 → 2023-12-09 06:00 | 8208 |

Большой диапазон — последовательный просмотр отдельных hourly fields.
Каждые 12 часов начинается независимый синтетический эпизод; его идентификатор
показан под датами и меняется на границе. Это не непрерывный годовой прогноз.
Нет объединения members/cycles в одну точную функцию или расчёта cross-cycle
totals. Переходы кадров дискретные, hourly amounts не получены делением daily total.

## Фактические проверки

[Сохранённый run](weather-10gb/scale/scale_report.json) включает SHA256 всех
118 файлов, full streaming scan и пакет Query с проверкой сертификатов.

| Профиль | Фактические bytes | Scan MB/s | Peak process-tree RSS, bytes | Query/checker invocations | Из них LP |
|---|---:|---:|---:|---:|---:|
| 1 GB prefix | 1 026 890 064 | 179.667 | 210 329 600 | 24 | 8 |
| 10 GB full | 10 083 749 720 | 226.157 | 220 205 056 | 24 | 8 |
| 50 GB v2 | — | not_run | — | — | — |
| 200 GB v2 | — | not_run | — | — | — |

В каждом выполненном профиле — 12 задач, first/repeat по два invocations,
сертификаты валидны, ошибки не записаны, generating truth попадает в bounds.
Для полного 10-GB профиля latency p50=8.835 ms, p95=14.566 ms.
OS cache не очищался; throughput не следует считать cold-disk результатом.
Scan resume_count=0: новый большой scan не прерывался; механизм resume проверяется
в smoke tests, старые результаты больших resume сохранены отдельно.
Полный максимум принятого hourly LSP — 42.065 mm; одна цветовая шкала применяется
ко всем выбранным кадрам и сценариям, не перенастраивается на каждый час.

Полная регрессия: **156 passed**, 41.75 s, ноль ошибок/провалов,
один существующий TestClient deprecation warning;
[XML](validation/archive-full.xml). Отдельные проверки архивного reader/API,
карты и scale: [16 passed](validation/archive-map.xml).
В реальном headless Edge проверены выбор марта, переход между shards/cycles,
смена сценария, крайний час годового диапазона, play/pause, сохранение зума
и reset: [результат](validation/archive-map-browser.json),
[скриншот](validation/archive-map-preview.png).
[Версии, source snapshots и hashes](validation/archive-map-context.json).

## Как читаются 10 GB

Общий FastAPI предоставляет `/map-archive/catalog`, `/range`, `/frame`, `/metrics`.
В HTML встроена только начальная картинка. Запрос кадра читает один hourly slice
и отдаёт 259 200 bytes float32; в браузере LRU не более четырёх кадров.
На сервере кешируется до 16 проверенных signatures/checksums файлов, а не массивы.
Перед первым чтением нового shard проверяется его SHA256. NetCDF доступ разделяет
lock с остальным API. Один worker, process-tree memory guard ≤16 GiB;
генератор ≤2 GiB. Весь год или архив в RAM/HTML не помещается.

Для выбора произвольных дат нужен локальный сервер ниже. Интернет, CDN, API keys
и GPU не нужны; `file://` для архивного режима не подходит. CLI без `--archive-api`
по-прежнему создаёт автономную карту одного цикла с встроенными кадрами.
Исходная пользовательская `era5_lsp_animation.html` сохранена. Предыдущая основная
синтетическая карта с metadata сохранена в `.meteo/map-ui-backups/`.

## Команды

Из корня проекта после `uv sync --frozen`, при наличии calibration bank:

```powershell
uv run python scripts/generate_scale_dataset.py --profile weather-bootstrap --calibration data/calibration/era5-lsp-2023-v1/manifest.json --output data/scale/weather-global-10gb-v2 --target-size 10GB --seed 42 --disk-budget 11GB --memory-limit 2GiB --dry-run
# Та же команда без --dry-run создаёт data files; --resume продолжает тот же output.
uv run python scripts/generate_scale_dataset.py --profile weather-bootstrap --calibration data/calibration/era5-lsp-2023-v1/manifest.json --output data/scale/weather-global-10gb-v2 --target-size 10GB --seed 42 --disk-budget 11GB --memory-limit 2GiB --resume
uv run python scripts/run_scale_benchmark.py --manifest data/scale/weather-global-10gb-v2/manifest.json --sizes 1GB,10GB,50GB,200GB --memory-limit 16GiB --output reports/weather-10gb/scale
# Для новой сборки выбирайте свободный output, существующий CLI не перезаписывает.
uv run python scripts/build_precipitation_map.py --input data/scale/weather-global-10gb-v2/manifest.json --archive-api /map-archive --output outputs/maps/synthetic_global_10gb.html
uv run python scripts/serve_precipitation_map.py --manifest data/scale/weather-global-10gb-v2/manifest.json --scale-report reports/weather-10gb/scale/scale_report.json --port 8765
```

На этой машине сервер уже запущен; повторно занимать порт не нужно.
Для воспроизведения после clone bulk NetCDF/calibration нужно подготовить отдельно:
Git содержит manifest, код и компактные результаты, а не сами 10 GB.

## Связь с научной частью

Данные карты участвуют в новом **10-GB scale/Query/checker run** выше.
Оценка реалистичности использует тот же генератор/calibration, но отдельные
синтетические сценарии и 120 отложенных реальных циклов; она не повторялась
на всех 10 GB. Сам viewer не вычисляет uncertainty или precision frontier.

Исследовательский кандидат — проверяемый полный профиль достаточной точности
нового измерения при неоднозначных метаданных — проверялся в отдельных
ограниченных задачах с независимым LP и сильными baselines.
Ограниченный размер нужен для независимой проверки, но сам по себе не даёт
научной новизны. Удаление/укрупнение observations в контролируемых задачах
моделирует недостаток информации; это не выдаётся за независимо размеченные
естественные дефекты архива.

Прежние **200 GB legacy-v1** действительно прошли нагрузочный scan/Query pipeline,
но не весь эксперимент по преимуществу precision-frontier метода. Увеличение
карты до 10 GB не превращает нагрузочный результат в доказательство новизны.
Gate A: исторические H1–H4 и отрицательный H3 сохранены; новые method pilots
не заменяют их. Gate B и независимая проверка приоритета остаются pending.
[Предлагаемый вклад и ближайшие работы](novelty_justification.md) сохранены
без заявления установленного мирового приоритета.
