# MeteoBridge: исследовательский проект и реализация для Codex

**Версия 2.1 — 16 октября 2026 года.** Дополнена обязательной поддержкой набора не менее 200 GB, генератором и загрузчиком данных, обработкой при ограниченной RAM и испытанием масштабируемости. Заменяет версии 1.0 и 2.0. Сопутствующий файл: `meteo_literature_and_novelty_review.md`.

## 1. Цель и новая постановка

Создать локальный прототип интеграции разнородных метеоданных и получить воспроизводимые результаты для научной статьи. Основной исследуемый объект — накопленные осадки и временная семантика их представления.

Рабочая тема: **«Метод интеграции накопленных метеорологических данных с проверкой восстановимости показателей и выбором недостающей информации»**.

Английское название: **Query-Directed Integration of Accumulated Weather Data under Semantic Ambiguity**.

Вопрос: можно ли получить запрошенный показатель без восстановления всего временного ряда и полного устранения неоднозначности метаданных? Если нельзя — нужны уточнения метаданных или дополнительные наблюдения?

Обзор 24 работ показал: единая схема, LLM + ограничения, типизация преобразований, отказ и информативные вопросы уже известны. Кандидат на вклад — специализированное вычисление восстановимости запроса при совместной дискретной неоднозначности смысла и непрерывной недостаточности временной информации; проверяемые обоснования/контрпримеры; эффективное повторное использование вычислений и выбор недостающей информации. Преимущество и новизна ещё требуют проверки.

**Порядок:** численное ядро → независимый oracle → сильные baselines → решающий пилот → реальные данные и минимальный UI → API и полный эксперимент → статья.

Из версии 1 сохранены модульность, provenance, CLI/UI/API, реальные источники и воспроизводимость. Универсальный matcher, многочисленные величины и обучение нейросети отложены. A* не гарантируется: рейтинг площадки/трека уточняется отдельно, Q1 не считать синонимом A*.

Голосовые 1.ogg и 2.ogg не расшифрованы. Это ТЗ основано на текстовом обсуждении; новые требования из голосовых не выдумывать.

## 2. Конечные результаты

### Прикладной

Пользователь загружает CSV/JSON/NetCDF, выбирает физическую серию и запрос. Получает число, допустимые границы или причину невозможности ответа; видит исходные метаданные, альтернативы трактовок, использованные ограничения и графики. Может подтвердить атрибут/добавить данные и экспортировать результат вместе с обоснованием.

Основная функция одинакова в CLI, Python SDK, UI и HTTP API. Разные источники не усреднять автоматически в скрытую «истинную погоду».

Обязательное требование итоговой системы: работать с локальным набором полезных метеоданных размером не менее **200 GB = 200 000 000 000 байт** при 32 GB установленной RAM. В поставку входят воспроизводимый генератор такого набора, скрипт подготовки реального набора и отчёт о фактически проведённых нагрузочных испытаниях. Большой набор обрабатывается частями; одна научная задача по-прежнему относится к одной физической серии. Подробная спецификация — разделы 9.1–9.7.

### Научный

- C1: компиляция реальных temporal conventions в модели восстановимости конкретного показателя;
- C2: проверяемые обоснования и эффективное решение семейства моделей с общими частями;
- C3: выбор metadata/data actions по причинам неоднозначности.

Полный перебор H + LP, обычный graph solver, DRD/HEC и structured VOI являются основами/конкурентами. Просто переименовать их недостаточно.

## 3. Границы первого прототипа

Поддержать одну скалярную физическую серию на case, количество осадков за интервал, cumulative от начала цикла, среднюю интенсивность за известный интервал, запрос суммы и предикат `sum >= threshold`. Неизвестные period/time-label/reset задаются конечными документированными альтернативами. Поддержать пропуски и известные детерминированные границы округления/представления значений.

Не реализовывать глобальный прогноз, полный цифровой двойник, spatial downscaling, объединение станций в одну функцию, спутниковую обработку, свободный NL-to-Python, обучение большой LLM. K↔°C и Pa↔hPa оставить инфраструктурными проверками.

Средняя интенсивность за интервал интегрируется по его длительности. Мгновенная интенсивность сама по себе не определяет количество за час. Суточная сумма не определяет точные hourly amounts.

## 4. Стек и ресурсы

- Python 3.11/3.12: выбрать совместимую версию и закрепить;
- uv, pyproject.toml, lock-файл;
- NumPy, pandas, PyArrow;
- SciPy/HiGHS для независимого LP oracle;
- графовый solver с явно описанным алгоритмом;
- Pydantic, Pint; Decimal/Fraction или направленное округление для границ;
- xarray/netCDF4 после ядра;
- для больших сеточных наборов — xarray с Dask/chunked access; для табличных — PyArrow Dataset с фильтрацией и пакетным чтением; optional Zarr/fsspec и provider-specific зависимости только для выбранного источника;
- Typer CLI, SQLite для каталога/действий, Parquet для результатов;
- Streamlit + Plotly для UI; FastAPI/Uvicorn позже;
- pytest, Hypothesis, Ruff; Matplotlib для научных фигур.

Первый этап работает на CPU без LLM и внешних ключей. RTX 4070 12 GB/32 GB RAM нужна только при необходимости семантической модели; Ollama — optional adapter. Модель, ревизию и стоимость фиксировать. Версии библиотек проверить по официальной документации в момент реализации.

Не добавлять React, Redis, Celery, Kubernetes, микросервисы и роли без подтверждённой потребности.

## 5. Архитектура

```text
meteo-bridge/
  pyproject.toml
  uv.lock
  README.md
  configs/
    demo.yaml
    queries/
    source_profiles/
    experiments/
  src/meteo_bridge/
    domain/
    readers/
    semantics/
    constraints/
    oracle/
    solvers/
    certificates/
    acquisition/
    connectors/
    execution/
    services/
    export/
    cli.py
    api.py
  ui/app.py
  examples/integration_client.py
  data/fixtures/
  data/manifests/
  benchmark/cases/
  benchmark/labels/
  benchmark/splits/
  scripts/generate_scale_dataset.py
  scripts/prepare_real_scale_dataset.py
  scripts/verify_scale_dataset.py
  scripts/run_scale_benchmark.py
  configs/scale/
  tests/unit/
  tests/properties/
  tests/integration/
  experiments/runs/
  reports/
  paper/
  docs/
```

Reader извлекает фактические значения/атрибуты. Semantics строит проверенные трактовки. Compiler создаёт ограничения. Solver отвечает на Query. Отдельный checker проверяет обоснование. Acquisition policy выбирает новую информацию. UI/API/CLI используют один application service.

Научное ядро не импортирует Streamlit/FastAPI. Oracle и graph compiler не должны собирать одну и ту же матрицу одним кодом: нужна независимая проверка.

Эксплуатационные source profiles допустимы. В эксперименте неизвестного провайдера его правильные ответы нельзя скрыто встроить в reader. Исходные CF-атрибуты доступны всем методам одинаково.

## 6. Математическая постановка

### 6.1. Одна физическая серия

`SeriesKey`: quantity, station/grid cell и spatial support, product/version, member/realization, vertical support при необходимости, forecast initialization/cycle при наличии.

Равенства одной модели принадлежат только одному SeriesKey. Разные станции, продукты, members и forecast initializations не обязаны описывать один ряд. Нельзя превращать их различия в «противоречие данных». Реанализ не становится наблюдением или operational forecast из-за внутренних forecast steps.

### 6.2. Фиксированная интерпретация

Для накопленной величины C(t):

`l_i <= C(b_i) - C(a_i) <= u_i`.

Осадки имеют неотрицательные приращения: `C(t_next) >= C(t_previous)`. Произвольный нулевой уровень C допустимо фиксировать как gauge, если это не добавляет физического ограничения.

Граф ограничений:

- a→b с weight=u;
- b→a с weight=-l;
- t_next→t_previous с weight=0 для неотрицательных приращений.

В согласованном графе верхняя граница Q[u,v] — shortest_path(u,v), нижняя — минус shortest_path(v,u). Отрицательный цикл означает несовместимость текущей модели/входных границ. Нет пути — возможна неограниченная граница.

Это классическая теория difference constraints, не новая теорема проекта. Сначала сделать LP по неотрицательным приращениям, затем graph solver и их сверку. Для общего линейного функционала использовать LP; он не обязательно выражается одним запросом разности потенциалов.

### 6.3. Неоднозначные метаданные

H — множество допустимых трактовок period, time-label, reset, units. Для каждой h задаётся множество рядов F_h. Общие границы:

`L = inf {Q(x,h): h in H, x in F_h}`

`U = sup {Q(x,h): h in H, x in F_h}`.

Пустое общее множество — inconsistent_model. Это может быть ошибка предположений, метаданных, входных границ или данных; не обязательно ошибка провайдера.

Сертификат корректен условно: истинные h и x должны принадлежать H/F_h. LLM top-k не обеспечивает полноту. Нужна консервативная ветвь other/unknown либо статус incomplete_model. Нельзя отбрасывать трактовку только потому, что score низкий, и объявлять оставшийся ответ гарантированным.

### 6.4. Цель и численная политика

Численный запрос задаёт абсолютный допуск eps. Возвращать центр диапазона как точечный ответ с этой гарантией можно только при конечных границах, `U-L <= 2*eps` и корректном наружном округлении. Иначе возвращать диапазон.

Для Q≥τ: true при L≥τ, false при U<τ, иначе unknown. Учесть точную семантику равенства.

Не смешивать уверенность matcher, детерминированные входные границы и статистические confidence intervals. Входная граница ±0.1 не автоматически означает погрешность прибора или 95% интервал.

### 6.5. Недостаток метаданных и наблюдений

Если известная h допускает несколько рядов с разными Q, одни метаданные могут не решить задачу. Если при каждой h ответ определён, но между h отличается, нужны метаданные. Оба эффекта могут сочетаться. Одна произвольная пара witnesses не всегда однозначно определяет причину.

Новый ответ эксперта сужает H; дополнительный временной фрагмент той же серии сужает F_h. Действия сохраняются отдельно от исходных данных.

Не переносить этот граф автоматически на min/max, число дождливых часов и мгновенные величины. Для signed energy flux убрать неотрицательность; это расширение после основной задачи.

## 7. Domain-модели

**SourceManifest:** dataset_id, provider, product_kind, upstream, version, request, URL/DOI, license, downloaded_at, SHA-256, extents, documentation version. Исключить секреты.

**IntervalObservation:** id, SeriesKey, original value/unit/timestamp, normalized value/unit, known/candidate interval, statistic(amount/interval_mean_rate/cumulative), reset_group, QC/missing, lower/upper bounds, evidence/provenance ids. Исходные значения сохраняются.

**SemanticHypothesis:** id, assignments, evidence ids, assumptions, compiler version, completeness scope. Unknown не становится guessed default. Статистическая правдоподобность значений не доказывает единицы/высоту/период.

**Query:** SeriesKey, unit, [start,end], timezone, objective(amount/threshold), eps/threshold, permitted assumptions, limits на acquisition.

**QueryResult:** bounds, point estimate при допустимости, reason flags, status, certificate id, witness ids, suggested actions, scope и revision.

Статусы:

| Статус | Смысл |
|---|---|
| certified | Ответ/решение следует из полной задекларированной модели |
| bounded | Есть полезные границы, но нет требуемой точности |
| needs_evidence | Доступно конкретное полезное уточнение/действие |
| insufficient_data | При известных метаданных не хватает наблюдений/доступных действий |
| inconsistent_model | Нет допустимого состояния |
| unsupported | Постановка вне модели |
| incomplete_model | Не обеспечены полнота/завершённость поиска |
| execution_failed | Техническая ошибка, не физическая несовместимость |

Reason flags независимы и могут сочетаться: metadata_ambiguity, temporal_underdetermination, conflict, missing_bounds, unsupported_calendar.

**Certificate:** input checksums, query hash, scope H, использованные observations/assumptions, normalized constraints, цепочки нижней/верхней оценки или LP dual bounds, численная политика, output bounds, checker version.

**WitnessPair:** две допустимые полные модели/ряда, их h и Q. Checker проверяет все ограничения и расхождение по цели. Это не два произвольно нарисованных графика.

В JSON не писать Infinity/NaN: null плюс bound_kind=unbounded/unknown.

## 8. Реализация ядра и baselines

### A. Independent LP oracle

Полное перечисление H для маленьких задач; отдельная LP-постановка по приращениям. Получить bounds и witnesses. Ручные примеры проверять независимо от общего compiler.

### B. Обычный graph baseline

То же H; стандартный solver для каждой модели. Floyd–Warshall допустим для небольшого reference, но плотный O(n³) для больших n не принимать без измерения. Проверять согласованность всей системы.

### C. Кандидат на эффективный метод

1. Факторизовать метаданные: общие observations и небольшие различающиеся ограничения.
2. Кэшировать query bounds/проверенные структуры по каноническому семантическому эффекту, не по test id.
3. Повторно использовать общие части при изменении одной трактовки или добавлении evidence.
4. Исключать переменные только при доказанном отсутствии влияния на bounds; вероятностное top-k pruning не даёт soundness.
5. Если оптимизация даёт внешнюю оболочку, расширять границы консервативно, никогда не создавать ложный certified.
6. При таймауте — incomplete_model либо доказанная внешняя оболочка, не скрытый недоперебор.

Сначала написать docs/algorithm_delta.md: отличие от enumeration + graph + простого cache и от известных incremental STN algorithms. Новую сложность/оптимальность не заявлять без доказательства. Если отличие тривиально, зафиксировать это и пересмотреть научный тезис.

### D. Проверяемое обоснование

Отдельный checker не зависит от поиска и LLM. Проверяет ориентацию/сумму неравенств, единицы, input hashes, полноту scope H. Inclusion-minimal explanation не называть глобально минимальной без решения этой задачи.

### E. Политики получения информации

- clarify_metadata(attribute, options): сужает H;
- fetch_interval(series, interval, permitted_source): добавляет ограничение той же физической серии.

Сначала metadata actions и корректное сообщение о необходимости новых наблюдений. Затем controlled data actions с явной стоимостью. Не подменять недостающую информацию интерполяцией.

Предлагаемая policy использует причины расхождения/witnesses, оценивает возможность сделать ответ проверяемым или сузить диапазон, учитывает стоимость. При нулевой одношаговой выгоде разрешён ограниченный lookahead. Это эвристика, пока не доказано иное.

Конкуренты: fixed/random; metadata entropy; structured VOI adaptation с тем же пространством действий/стоимостью/priors; DRD/HEC на применимых конечных задачах; оптимальный полный перебор policy на совсем маленьких задачах как ориентир.

Continuous-outcome actions не считать напрямую точным HEC: описать аппроксимацию и отдельно её ограничения. Все policies используют один checker и stopping rule. Не выдавать качество численного solver за преимущество политики. Clairvoyant oracle с доступом к скрытой истине — только нижняя оценка стоимости.

## 9. Банки данных

| Порядок | Источник | Роль |
|---|---|---|
| 0 | Hand-calculated fixtures | Точный ground truth и offline demo |
| 1 | DWD hourly precipitation | Реальные наблюдения и temporal conventions |
| 2 | Маленький ERA5-Land или CERRA subset из CDS | Накопления и cycles; выбрать после документации |
| 3 | NOAA GHCNh | Другая схема и QC |
| 4 | Open-Meteo Historical | Простой JSON demo, явный upstream |
| Опция | INMET/METBRA25Y | Внешняя проверка после ядра |

Ссылки:

- https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/precipitation/historical/
- https://cds.climate.copernicus.eu/
- https://confluence.ecmwf.int/spaces/CKB/pages/272323672/Copernicus+European+Regional+ReAnalysis+CERRA+product+user+guide
- https://www.ncei.noaa.gov/oa/global-historical-climatology-network/index.html
- https://www.nesdis.noaa.gov/news/service-location-change-integrated-surface-data-global-hourly
- https://open-meteo.com/en/docs/historical-weather-api
- https://arxiv.org/abs/2605.08701

По проверенному уведомлению NOAA ISD не обновляется после 24.08.2025; основной актуальный продукт — GHCNh. Endpoints и форматы перепроверить перед реализацией.

Open-Meteo ERA5 и CDS ERA5 не независимые физические данные. NOAA/DWD могут содержать пересекающиеся наблюдения. Отличать независимость представления, провайдера и измерений.

Научный пилот: 2–3 германские станции/точки, 7–30 дней 2023 года, первоначальную загрузку ограничить несколькими GB. Это начальный этап; итоговое нагрузочное испытание обязательно выполняется на наборе не менее 200 GB по разделам ниже. Данные разных продуктов не соединять в одну систему точных равенств. Controlled representations строить из одного ряда с явным provenance.

Коннекторы: cache, retries/backoff, timeout, лимит объёма, raw bytes, checksum, manifest и версия документации. Проверить лицензии и CDS credentials. При недоступности сервера/ключа продолжать локальные задачи, не выдавать synthetic за real.

### 9.1. Объём и критерий «200 GB»

Основной профиль `scale-200gb` должен содержать минимум 200 000 000 000 байт завершённых файлов с полезной нагрузкой данных. Поддержать явные суффиксы GB (10^9) и GiB (2^30); например, 200 GiB = 214 748 364 800 байт. В отчёте всегда указывать число байт и обе единицы.

Зачётный объём — реальные сериализованные data shards выбранного формата **после заданной компрессии**, суммированные один раз по manifest. Отдельно показать несжатый логический объём массивов, размер файлов, доступный показатель allocated bytes и размер временных/индексных файлов. Разреженный файл с большим apparent size не считается физически подготовленными данными. При filesystem compression/deduplication явно указать ограничения измерения физического размещения.

Нельзя набирать 200 GB padding, нулевыми заполнителями, бессмысленным случайным payload, копированием одного файла, резервированием пустого места, переименованными дублями или повторным учётом одного исходника в нескольких представлениях. Уникальные осмысленные наблюдения/ячейки/временные интервалы должны обеспечивать основной объём. Альтернативные схемы одного ряда сохраняют общий family_id и не становятся независимыми научными примерами.

Для синтетики по умолчанию разрешены несжатые NetCDF data arrays или Parquet без компрессии: это явный профиль хранения реальных генерируемых значений, не скрытое раздувание. Дополнительный сжатый профиль нужен для сравнения storage/IO; он не получает зачёт 200 GB по размеру своего несжатого предшественника.

Финальный shard может превысить целевой объём не более чем на один заданный shard. Каталог, labels, indexes, logs, временные файлы и экспорт результатов в основной объём не входят.

### 9.2. Генератор большого тестового набора

Обязательно реализовать `scripts/generate_scale_dataset.py` и CLI `meteo data generate-scale` с общей реализацией. Скрипт должен работать без сети и API-ключей. Параметры: target size, seed, output directory, format/compression, chunk/shard size, число серий/регионов, временной диапазон/шаг, доля пропусков и контролируемых дефектов, workers, memory limit, resume и dry-run.

Генерировать:

- множество различных станционных либо сеточных серий с уникальными series_id, координатами и часами;
- осадки с неотрицательными amount, временной зависимостью, сухими периодами и событиями; cumulative сбрасывается только по заданному cycle;
- контрольные temperature/pressure при необходимости, с корректными единицами/опорой;
- несколько документированных схем (amount/cumulative/interval_mean_rate, единицы, time labels), пропуски, QC и специально размеченные противоречия;
- скрытую истину/metadata labels для небольших выбранных научных задач и детерминированный способ восстановить её по seed/partition, без второй 200-GB копии;
- manifest с sha256, rows/cells/times, series/cycle ranges, schema/seed/version и происхождением synthetic.

Погодная правдоподобность здесь служит нагрузочному тесту, не доказательству достоверности симулятора атмосферы. Научный ground truth определяется конструкцией наблюдений и интервалов. Не обещать генерацию реального климата.

Генерация потоковая. Chunk, например, 64–256 MiB необработанных значений; завершённый shard — ориентировочно 256 MiB–1 GiB. Значения зависят от seed и устойчивых координат/partition id; число workers и порядок завершения не должны менять содержательный результат. Состояние временного процесса переносится между соседними chunks; новая граница файла не создаёт ложный reset.

Перед записью dry-run оценивает rows, files, bytes и необходимый запас места. Реальный `--resume` проверяет уже завершённые shards, продолжает по manifest, пишет через `.partial` с атомарным завершением и обрабатывает исчерпание диска без порчи готовой части. Периодически проверять свободное место. Плановый запас — целевой объём плюс максимальные временные данные, индексы/результаты и минимум 20% свободного резерва; не требовать вторую полную копию без необходимости.

Профили: `smoke` (десятки MB), `1gb`, `10gb`, `50gb`, `200gb`. Большой запуск выполняется явно указанной командой на машине с достаточным диском; обычные tests/CI никогда не создают 200 GB автоматически.

### 9.3. Где получить реальный большой набор

Скрипт `scripts/prepare_real_scale_dataset.py` и CLI `meteo data prepare-real-scale` должны позволять составить локальный набор минимум 200 GB из открытого архива. Предпочтительный профиль — **NSF NCAR ERA5, CF-compliant NetCDF4**: он совместим с планируемым reader и включает surface precipitation.

| Источник | Доступ и применение |
|---|---|
| [NSF NCAR ERA5 on AWS](https://registry.opendata.aws/nsf-ncar-era5/) | NetCDF4; официально указан anonymous S3 access. Сначала list/HEAD конкретных объектов и подбор переменных/дат, затем загрузка выбранного manifest. |
| [Google Research ARCO-ERA5](https://github.com/google-research/arco-era5) | Публичный ERA5 в cloud-optimized представлениях. Вариант для chunked Zarr; подключать после проверки текущей структуры, переменных и условий доступа. |
| [Copernicus CDS](https://cds.climate.copernicus.eu/) | ERA5/ERA5-Land/CERRA с документированной temporal semantics. Аккаунт/условия/API-ключ могут требоваться; запросы дробить по текущим лимитам, не отправлять один запрос на 200 GB. |

CDS guidance: https://confluence.ecmwf.int/pages/viewpage.action?pageId=278541744

Не брать устаревший AWS `ecmwf-era5` как основной профиль: его registry направляет к NSF NCAR. Наличие доступа к общему ERA5-архиву не подтверждает наличие нужного поля в произвольном зеркале: выбрать проверяемые keys с осадками и temporal metadata. Не добирать объём несвязанными pressure-level variables только ради размера.

Загрузчик должен:

1. Построить ограниченный manifest объектов по явно выбранным variable/product/date/region/cycle.
2. Проверить актуальность источника, лицензию, наличие/размеры и достаточность выбранных объектов для цели; показать dry-run.
3. Загружать только выбранные объекты/chunks, с retries/backoff, ограничением concurrency, cache, resume и дискового бюджета.
4. Сохранять original key/URL, размер, ETag/version при наличии и собственный sha256 завершённых файлов; ETag не считать автоматически SHA-256.
5. Проверять поддерживаемость формата и temporal semantics reader; сохранять forecast cycles раздельно.
6. Создать локальный каталог для запросов без повторного чтения/скачивания всего архива.

Сжатый download, нормализованный набор и cache считать раздельно; один и тот же физический ряд в разных форматах не выдавать за независимые данные. При загрузке подмножества из большого Zarr нельзя копировать один metadata pointer и считать весь remote dataset локальными 200 GB: нужные chunks должны быть реально получены и учтены.

Реализация обоих скриптов обязательна. Приёмка на физическом объёме 200 GB допускается на синтетическом или реальном наборе; по умолчанию — воспроизводимая синтетика плюс небольшой проверенный реальный набор. Публикационный вывод о работе на **реальных 200 GB** разрешён только после отдельного фактического real-scale run.

### 9.4. Обработка при 32 GB RAM

Архитектура хранения и чтения должна поддерживать 200 GB уже при разработке skeleton. Не загружать весь набор в pandas/NumPy, не делать глобальные `.load()`, `.compute()` или concat всех shards.

- Parquet: partition pruning, column projection, predicate pushdown и record batches.
- NetCDF/Zarr: chunked/lazy чтение по времени, координатам и переменным; согласовать физическую разбивку с запросами.
- Partition по product/series group/region/time/cycle; semantic ambiguity и graph строятся только для выбранных ограниченных cases.
- Полный scan — потоковый, с ограниченной очередью workers и incremental output; joins/sorts, если нужны, — partitioned/external с явно ограниченным spill.
- Предзаданный memory budget всего дерева процессов — 16 GiB на машине с 32 GB RAM; генератор — целевой бюджет до 2 GiB. При угрозе превышения уменьшать workers/chunks или завершать задачу с ясным статусом.
- Peak RAM измерять по всем worker-процессам, не только coordinator; disk cache ОС и используемый метод измерения описать.
- UI preview ограничен, результаты paginated. Локальный большой набор регистрируется через CLI/manifest; веб-интерфейс не требует повторной загрузки 200 GB через браузер.

Не строить единый плотный граф на все времена/ячейки всего архива. Сохранять межфайловые границы интервалов и нужный overlap/halo; partition не должна менять ответ по сравнению с маленьким непартиционированным эталоном.

### 9.5. Проверка набора и испытание масштаба

`scripts/verify_scale_dataset.py` проверяет manifest, версии/идентификаторы, реальные размеры, схему, согласованность partitions и отсутствие непреднамеренных дублей; full mode пересчитывает checksum всех data shards. Только full mode даёт статус полного byte-level verification. Выборочная проверка явно помечается sample.

`scripts/run_scale_benchmark.py` или `meteo benchmark scale` выполняет серию 1/10/50/200 GB (разные manifest-подмножества одного зафиксированного набора):

1. Каталогизация/проверка завершённых файлов.
2. Полное потоковое чтение и базовая нормализация всех поддерживаемых наблюдений с подсчётами/checksum результата.
3. Запросы по station/grid/time с warm/cold cache conditions и bytes read.
4. Пакет основных научных Query по разным partitions: bounds, statuses, certificates и выборочная независимая LP-проверка.
5. Возобновление прерванной генерации/обработки и отсутствие дублей при повторном запуске.

Полный scan не должен выдавать за выполнение научного solver на всех строках. Раздельно фиксировать долю архива, прошедшую IO/нормализацию, и число реально решённых Query.

Отчёт содержит фактические bytes/format/compression/files/rows, hardware и тип диска, wall time, MB/s, latency p50/p95 и число запросов, peak process-tree RAM, read/write/spill bytes, cache conditions, checksum/correctness, ошибки и resume status. Числа не экстраполировать с 1 GB как будто измерены на 200 GB.

Приёмка: data bytes >= 200 000 000 000, фактический проход по всему набору, завершённый batch Query с проверками корректности, память в заявленном бюджете, успешно проверенное resume, воспроизводимый scale_report. Конкретный SLA времени устанавливать после измерений на целевом диске, не выдумывать заранее.

### 9.6. Целевые команды

Команды ниже — требования к будущей реализации, а не уже существующие scripts:

```bash
uv run meteo data generate-scale --target-size 200GB --format netcdf --compression none --seed 42 --output data/scale/synthetic-200gb --memory-limit 2GiB --dry-run
uv run meteo data generate-scale --target-size 200GB --format netcdf --compression none --seed 42 --output data/scale/synthetic-200gb --memory-limit 2GiB --resume
uv run meteo data prepare-real-scale --provider ncar-era5 --target-size 200GB --config configs/scale/ncar-era5.yaml --output data/scale/real-200gb --dry-run
uv run meteo data prepare-real-scale --provider ncar-era5 --target-size 200GB --config configs/scale/ncar-era5.yaml --output data/scale/real-200gb --resume
uv run meteo data verify-scale --manifest data/scale/synthetic-200gb/manifest.json --mode full
uv run meteo benchmark scale --manifest data/scale/synthetic-200gb/manifest.json --memory-limit 16GiB --output reports/scale
```

README должен содержать эквивалентный запуск через `scripts/*.py`, пример PowerShell для Windows и Linux-команды. Data root настраивается отдельно; не вшивать пользовательский путь. Проверить поддержку целевой Windows-среды либо описать проверенный вариант WSL2 и фактические ограничения filesystem/ресурсов.

### 9.7. Связь с научной статьёй

200 GB — требование масштабируемости инженерной реализации и дополнительный эксперимент. Большое число байт не заменяет разнообразие независимых схем, корректную разметку и доказательство методической новизны.

В статье отдельно отражать scientific benchmark по cases и scale benchmark по объёму IO/обработки. Synthetic-200GB подтверждает только заявленный synthetic-scale результат; для вывода о реальных архивах использовать реально обработанные данные с provenance.

## 10. Benchmark и разметка

Case = исходная серия + семантическая схема + доступная информация + Query + action space. Строки одной станции не независимые экспериментальные задачи.

Раздельные категории:

- original: реальные файлы/conventions/естественные неоднозначности;
- controlled: маскирование атрибутов и другое представление реального ряда;
- synthetic: сконструированная задача с точным oracle.

Не называть controlled варианты одного продукта новыми провайдерами. Начать с 30–50 задач, включая 10–15 проверенных реальных/производных случаев. Затем при необходимости 150–300 разнообразных задач; независимые семейства важнее числа файлов.

Обязательные классы:

- известный итог при неизвестном внутреннем распределении;
- перекрытия с точной суммой и с bounded sum;
- порог устойчив при неточном значении;
- beginning/end timestamp;
- interval amount против cycle cumulative;
- reset и неизвестный baseline;
- разные cycles/members, которые нельзя объединять;
- amount/rate и m/mm;
- пропущенная истинная трактовка H;
- противоречия/QC/rounding bounds;
- UTC, local civil day, DST;
- полные метаданные, но недостаточно наблюдений;
- несколько неоднозначных атрибутов и полезная пара действий при нулевой одношаговой выгоде.

Labels: истинная семантика, полнота H, bounds/решение, допустимые witnesses, доступные действия/ответы, evidence. Принимать эквивалентные обоснования.

Split по source series/product/schema family делать до аугментации. Все производные остаются в одной группе. Test не участвует в словарях, prompts, правилах и выборе eps/порогов. Отдельно oracle-semantics track и end-to-end track.

Поднабор реальных задач должен проверить второй человек/специалист по документации. Разметка Codex — кандидат, не независимая экспертиза. Если проверки ещё нет, статус explicit pending.

## 11. Решающий эксперимент

Гипотезы:

- H1: bounds/решения соответствуют независимому oracle;
- H2: часть запросов разрешима без полной реконструкции входа;
- H3: shared solver снижает затраты относительно enumeration + graph + simple cache без потери корректности;
- H4: witness-directed policy снижает стоимость информации относительно VOI/DRD adaptations при одинаковом action space;
- H5: эффект сохраняется на реальных схемах, а не только artificial masking.

H1 — корректность. H2 — предметная полезность известного общего принципа. Основные претензии на новый метод требуют H3/H4 и внешней проверки H5.

Обязательные baselines: ручной проверенный pipeline (xclim/pandas) для однозначных входов; полное разрешение метаданных до ответа; typed validator с отказом при unknown; enumeration+LP; enumeration+graph+cache; policies из раздела 8; semantic/LLM matcher с тем же downstream solver только в end-to-end track.

Не заставлять SINT-Flow/ActiveClean искусственно решать осадки. Это близкая литература, но не обязательно количественные конкуренты другой постановки. Адаптации обозначать как адаптации.

Протокол:

1. Freeze cases, split, primary metric и configs до финального test.
2. Solvers сравнивать при одинаковых H/Q; policies — на одном solver/checker.
3. Скрытые ответы simulator видит policy только после действия.
4. Simulation costs помечать условными; число вопросов не объявлять измеренным человеческим временем.
5. Randomness: несколько seed; deterministic: повторные замеры runtime.
6. Confidence intervals по независимым группам, не по соседним часам.
7. Сохранять errors/timeouts/blocked наряду с успехами.

Метрики: false certification (числитель/знаменатель), certified coverage, oracle task success, H coverage, bound width/tightness, вопросы/наблюдения/bytes/API calls отдельно, объявленная total cost и sensitivity analysis, latency/RAM/states/solver calls, certificate/witness verification, лишние действия после определимости ответа.

Сравнивать coverage при одинаковой корректности, стоимость при одинаковом success. Отказ от всех задач не выигрыш. Ноль ошибок на тесте не доказывает нулевой риск вообще.

Ablations: semantic alternatives, temporal constraints, certificate reuse, query-specific stopping, entropy vs witness policy, metadata-only vs mixed actions, complete/missing/conflicting metadata. У всех одинаковые доступные сведения.

## 12. Этапы и контрольные точки

| Этап | Работы | Критерий |
|---|---|---|
| 0 | Прочитать обзор, claims.md, algorithm_delta.md | Отделены известные основы и кандидат на вклад; весь обзор без причины не повторять |
| 0a | Зафиксировать partitioning, memory budget и scale-data CLI | Дизайн допускает 200 GB без полной загрузки в RAM |
| 1 | Domain, fixtures, independent LP, graph | Совпадение на ручных/генеративных проверках |
| 2 | Certificate/witness checker | Неверные обоснования отвергаются |
| 3 | Сильные baselines, shared solver, policies, pilot | Измерен конкретный delta по H1–H4 |
| Gate A | Отчёт пилота | Основание продолжать или честно зафиксировано отсутствие вклада |
| 4 | DWD и один накопительный продукт, real cases | Проверены conventions и provenance |
| 5 | Streamlit UI | Пользователь видит Query→bounds/обоснование/witness/action/export |
| Gate B | Внешняя проверка, claims update | Вывод не держится только на синтетике |
| 6 | API и внешний client | Те же service и результаты |
| 6a | Генератор и загрузчик scale datasets, resume и verification | Smoke/1 GB проверки пройдены; реальный профиль проверен на малом subset |
| 6b | Фактический прогон 1/10/50/200 GB | >=200 GB data bytes, полный scan, batch Query, bounded RAM и scale_report |
| 7 | Полные runs/ablations/intervals | Воспроизводимые таблицы и фигуры |
| 8 | Статья | Все числа связаны с runs, ограничения указаны |

При провале H3/H4 не бесконечно подгонять метод и benchmark. Зафиксировать отрицательный результат, оценить tool/benchmark вклад. Независимые полезные части можно завершить, но это не подтверждение method novelty.

Ориентир: первый исследовательский прототип 1–2 недели с проверкой человеком; реальные данные, независимая разметка и полный эксперимент — ещё несколько недель. Это не обещание срока работы Codex или принятия статьи.

## 13. Минимальный интерфейс

Один Streamlit UI на русском, без отдельного frontend build:

1. Данные: demo/upload, preview, unit/time/product/provenance.
2. Запрос: серия, интервал, amount/threshold, eps, semantic alternatives.
3. Ответ: число/диапазон/status, использованные интервалы и предположения, checker verdict.
4. Причина неоднозначности: два допустимых ряда/witnesses, различия и suggested action.
5. Экспорт: result.json, certificate.json, report.json, допустимый CSV, команда повторного CLI.

График показывает интервалы накопления; amounts не изображать как мгновенную intensity. Различать исходные данные, допустимые сценарии и вычисленный показатель.

Подтверждение человека создаёт evidence revision; результат assisted, corrections не скрываются в automatic benchmark. Не использовать mock-числа вместо ядра.

Обязательные demo: exact, bounded, metadata question→повторный ответ и insufficient_data, которое нельзя исправить метаданными. Offline без CDN/карт.

## 14. CLI, SDK, API

Целевые команды после реализации, сейчас это спецификация:

```bash
uv sync --frozen
uv run meteo demo --case overlap-exact
uv run meteo inspect data/fixtures/overlap.csv
uv run meteo solve --case benchmark/cases/overlap.yaml --solver graph --output outputs/demo
uv run meteo verify --result outputs/demo/result.json --certificate outputs/demo/certificate.json
uv run meteo experiment --config configs/experiments/pilot.yaml
uv run streamlit run ui/app.py
uv run uvicorn meteo_bridge.api:app --host 127.0.0.1 --port 8000
uv run pytest
uv run ruff check .
```

SDK: load_dataset, compile_case, solve_query, verify_certificate, suggest_action, apply_evidence.

| Метод | Endpoint | Результат |
|---|---|---|
| GET | /health | Готовность |
| POST | /datasets | Multipart upload/id |
| GET | /datasets/{id}/schema | Исходные поля и метаданные |
| POST | /queries | dataset_id + Query → id/result |
| GET | /queries/{id} | Bounds/status/reasons |
| GET | /queries/{id}/certificate | Обоснование |
| GET | /queries/{id}/witnesses | Сценарии расхождения |
| GET | /queries/{id}/actions | Допустимые следующие действия |
| POST | /queries/{id}/evidence | Evidence revision и повторный solve |
| GET | /queries/{id}/export | Версионированный результат |

Внешний Python client получает сумму/решение и проверяет certificate без знания исходных имён провайдера. Не заявлять OGC EDR-compliance без реализации и проверки требований стандарта.

Гигиена локального сервиса: upload limits, проверка формата и архивных путей, отсутствие произвольного доступа к серверным файлам и произвольного кода. LLM может выдать только JSON известной схемы, не Python для eval/exec.

## 15. Содержательные проверки

1. [0,24]=12: полный итог известен, половина [0,12], hourly distribution неизвестно.
2. [0,12]=10; [6,18]=12; [6,12]=4: [0,18]=18.
3. Те же значения ±0.1: [17.7,18.3] с наружным округлением.
4. Threshold 15 устойчив, threshold 18 неизвестен в bounded-примере.
5. [0,24]=3 и [0,12]=4 с nonnegative increments: inconsistent_model.
6. Нет верхнего ограничения: unbounded, не ноль.
7. Metadata ambiguity и temporal underdetermination различаются.
8. Beginning/end label alternatives учитываются все.
9. Пропущенная истинная h измеряется как failure H coverage, top-k не «гарантия».
10. Перестановка строк/дублирование одинакового ограничения/m↔mm не меняют ответ.
11. Добавление истинного ограничения не расширяет множество фиксированной модели.
12. Разные SeriesKey/cycles/members не смешиваются.
13. Reset без baseline не создаёт выдуманный первый amount.
14. Instantaneous rate не становится hourly amount без модели.
15. Неверные знак/путь/unit/hash/witness отвергаются checker.
16. Shared/cache solver совпадает с oracle и после evidence; stale cache исключён.
17. Таймаут не certified; unbounded корректно экспортируется.
18. 360_day не меняется молча на Gregorian.
19. UTC, local civil day/DST и local solar time различаются.
20. CLI/UI/API используют общий service и одинаковые численные результаты.
21. Scale generator при одинаковом seed/partition не меняет данные из-за workers или resume; границы shards не создают ложные reset.
22. Verify-scale не считает padding, partial, metadata, дубли и удалённые незагруженные chunks полезными 200 GB.
23. Partitioned/chunked Query совпадает с маленьким непартиционированным oracle, включая интервал через границу файлов.
24. Memory/IO limits, исчерпание диска и прерывание обрабатываются без порчи завершённых shards; обычный CI использует малый профиль.

Integer/rational fixtures сравнивать точно; float — по описанной политике. Не исправлять пороговое решение произвольным допуском, который меняет его смысл.

## 16. Воспроизводимость

Run хранит code revision, Python/lock hash/hardware, input SHA-256, case/split, manifest, H/completeness, Query, numerical policy, method/config, seeds, action budget/cost, predictions/bounds/certificates/witnesses, checker verdict, выполненные actions, timing/RAM/solver calls/errors и metrics.

Переменные timestamps исключить из содержательного checksum. Таблицы/фигуры строить из runs, не ручными числами.

Документы: docs/requirements.md, architecture.md, assumptions.md, algorithm_delta.md, data_sources.md, annotation_guide.md, progress.md, reproducibility.md; paper/claims.md, related_work.csv, references.bib, outline.md.

Не коммитить большие сырые архивы, секреты и повторимые outputs. Коммитить разрешённые маленькие fixtures, manifests, schemas, Queries. Проверять лицензии данных.

Для scale run дополнительно сохранять dataset byte accounting, generator/source config, format/compression, seed/partition plan, source object versions, read/write bytes, disk/cache conditions и process-tree peak RAM. Малые проверяемые manifests и scripts входят в репозиторий; сами 200 GB в git не добавлять. Документы: docs/scale_data.md и reports/scale/scale_report.md.

## 17. Статья

1. Проблема физической/временной неоднозначности накопленных переменных.
2. Related work: обзор 24 работ, особенно S06/S10/S16/S19/S20–S23.
3. Постановка Query, discrete semantics, continuous underdetermination, conditional correctness.
4. Compiler, shared solver, certificate/witness checker, acquisition policy.
5. Доказательства заявленной soundness/консервативности поддерживаемого фрагмента; классические леммы выделены.
6. Benchmark, real/controlled/synthetic происхождение, independent annotation и splits.
7. Correctness, algorithm delta, policy delta, ресурсы, end-to-end coverage.
8. Ограничения: H coverage, неверные метаданные, различия продуктов, numerical bounds и simulator costs.
9. Только подтверждённые выводы.

Фигуры: интервалы/Query; семейство интерпретаций; certificate/witness; latency/RAM vs размер; cost–coverage; ошибки по классам. Таблицы: related work, benchmark, main results, ablations. Не перегружать UI screenshots.

Сначала manuscript содержит `[TO BE MEASURED]`; результаты — только из runs. Не присваивать себе shortest paths/possible worlds/DRD/VOI/unit conversion. После пилота выбрать method/data/tool track; не обещать A* заранее.

## 18. Референс и чтение

Референс: https://github.com/igorrus2302/MapGenerationAndResourseRecognition

Просмотренная ранее версия b4b72fca2cf037f54b4533c6ed13c3626b4d4726 содержит генератор синтетической геологической карты, configs, offline viewer и тесты. Перенять принцип «воспроизводимый случай → ядро → проверка → просмотр». Это не scientific baseline нашей темы. Копирование требует отдельной проверки лицензии; код писать свой.

Читать сопутствующий обзор и первичные источники S01–S24. Основные документы:

- https://cfconventions.org/Data/cf-conventions/cf-conventions-1.12/cf-conventions.html
- https://space.oscar.wmo.int/variables/view/accumulated_precipitation
- CERRA guide из раздела 9
- https://proceedings.mlr.press/v33/javdani14.html
- https://aclanthology.org/2026.findings-acl.2028/
- https://iris.unical.it/handle/20.500.11770/386101
- https://arxiv.org/abs/2102.11796

Если найдена работа с тем же конкретным алгоритмом, обновить claims до крупных затрат. Не проводить бесконечный поиск вместо прототипа: обзор выполнен, теперь нужен проверяемый delta.

## 19. Стартовый промпт Codex

```text
Реализуй MeteoBridge по meteo_project_codex_plan.md версии 2.1.
Прочитай meteo_literature_and_novelty_review.md. Используй новую постановку:
запросы к накопленным метеоданным при неоднозначных метаданных и
недостаточной временной детализации.

Сначала прочитай AGENTS.md и состояние репозитория. Сохрани пользовательские
изменения. Если проект начат по версии 1, переиспользуй совместимые части,
но сопоставь их с новой моделью; не удаляй старый код автоматически.

Начни с этапов 0–3: domain, ручные fixtures, независимый LP oracle,
обычный graph solver, certificate/witness checker, enumeration/cache
baselines и минимальный кандидат на эффективный метод. Demo должен
показывать точный ответ, диапазон, конфликт и недостаток наблюдений,
который нельзя устранить вопросом о метаданных.

Не начинай с большого UI, множества коннекторов или LLM. Используй Python,
SciPy/NumPy/Pydantic; зафиксируй зависимости uv. Offline demo на CPU.

Difference constraints, possible worlds, type checking, DRD и VOI известны.
Напиши конкретный algorithm_delta против enumeration+graph+simple cache.
Не заявляй недоказанные soundness/оптимальность или новую сложность.

Сертификат зависит от полноты H и входных предположений. LLM top-k не
обеспечивает полноту: other/unknown или incomplete_model обязательны.
Не соединяй разные станции, продукты, members и cycles в одну точную
функцию. Не восстанавливай hourly amounts произвольным делением daily total.

Сравни policies отдельно от solver. У всех одинаковые действия, стоимость,
сведения и stopping rule. Policy не читает скрытые ответы simulator до
действия. Нужны сильные VOI/DRD adaptations, одного random недостаточно.

Сохрани Gate A report с результатами H1–H4 и фактическим вкладом. Если
преимущества нет — честно зафиксируй, не подгоняй benchmark. Независимые
полезные части можно завершить, но без выдуманного подтверждения новизны.

Затем подключи маленький DWD subset и один накопительный CDS-продукт
либо локальный файл. Проверь conventions. Сделай минимальный Streamlit:
данные, Query, bounds, обоснование, witnesses, действия и экспорт.
После этого общий FastAPI и внешний client.

Обязательна поддержка набора минимум 200 GB при 32 GB RAM. Уже сейчас
проектируй chunked/partitioned чтение и ограниченную рабочую модель.
Реализуй scripts/generate_scale_dataset.py, prepare_real_scale_dataset.py,
verify_scale_dataset.py и run_scale_benchmark.py с CLI из раздела 9.
Нужны seed, manifest/checksums, dry-run, resume, memory/disk budgets,
проверенный реальный профиль NSF NCAR ERA5 и offline synthetic profile.
200 GB считаются по фактическим полезным data files; не использовать
padding, sparse placeholders и копии одного файла. Общий memory budget
процесса с workers — 16 GiB; генератора — 2 GiB. Не загружай архив целиком.
Испытания объёма: 1/10/50/200 GB, полный streaming scan и пакет Query с
certificates. Фиксируй bytes, throughput, RAM, latency, ошибки и resume.
В обычных tests/CI запускай smoke, не автоматические 200 GB. Для большого
прогона проверь диск; если ресурсов нет, дай готовые scripts/команды и
статус not_run, не заявляй проведённый 200-GB эксперимент.

Веди docs/progress.md, assumptions.md, algorithm_delta.md,
annotation_guide.md и paper/claims.md. Сохраняй runs, hashes, версии,
метрики, ошибки и ограничения. Продолжай самостоятельно, если нет
реального блокера; credentials не должны блокировать offline задачи.

Не выдумывай новизну, статьи, публикационный статус, метрики и гарантию A*.
Методы статьи следуют коду, результаты — сохранённым runs. В отчёте дай
команды запуска, проверки, Gate A/Gate B и оставшиеся ограничения.
```

## 20. Приёмка

Исследовательский прототип: один CLI запуск воспроизводит Query→bounds/status→certificate/witness→verification; independent oracle подтверждает ядро; есть сильные baselines и отчёт о фактическом delta.

Прикладной demo: пользователь загружает свой поддерживаемый файл, задаёт Query, видит осмысленный результат/ограничение и экспортирует проверяемый отчёт через UI/API.

Масштабируемость: существуют работоспособные scripts генерации, загрузки и проверки; набор содержит минимум 200 000 000 000 байт полезных data shards; выполнены полный потоковый scan и пакет основных Query при памяти до 16 GiB; сохранены проверенные correctness/resume и фактический scale_report. Если 200-GB run ещё не выполнен, этот критерий остаётся not_run, даже когда scripts уже написаны.

Статья для оценки руководителем: конкретный установленный вклад, реальные внешние cases, независимая проверка разметки, корректные splits, воспроизводимые сравнения и честные ограничения. Наличие кода само по себе не выполняет этот критерий.
