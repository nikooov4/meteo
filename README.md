# MeteoBridge

Понятная демонстрация с расшифровкой названий, полей и файлов JSON:
**[пошаговая памятка для преподавателя](docs/demo_walkthrough_ru.md)**.

Материалы для защиты: **[defense/README.md](defense/README.md)** — доклад,
сценарий программы/карты, данные и их объёмы, предполагаемая новизна, вопросы
преподавателя, примеры JSON/CSV и копии прежних отчётов.
Новый [эксперимент на реальных ERA5](reports/real_precision.md): 72 point/cycle
windows, 144 documented/controlled cases, 576 проверенных профилей и независимый LP.
Реальные значения использованы с явно контролируемой потерей детализации;
Gate B и мировой приоритет не установлены.
Дополнительно [нативная проверка без искусственного урезания](reports/real_native_resolution.md):
72 полных hourly point/cycles, Query за полчаса; 31 случай не даёт точного
ответа при eps=0, 8 — не даёт допуска eps=0.05 mm. Все исходные наблюдения сохранены.
Отдельный [partition-wide 200-GB experiment](reports/archive_precision_200gb.md)
имеет собственный фактический статус; его нельзя заменять старым storage run.
Завершён: 476/476 shards, 1904 профиля, независимый LP и повторная проверка
сертификатов. Финальная регрессия: **161 passed**. Большой run относится к
legacy-v1 и ограниченным задачам из его partitions; новые 200 GB v2 не заявляются.

2026-10-19: карта расширена до **10.084 GB** новой синтетики v2 (118 shards).
Слева сверху — начало/конец UTC и выбор сценария; кадры читаются по одному,
зум сохраняется. [Открыть запущенную карту](http://127.0.0.1:8765/synthetic_global_animation.html?view=10gb).
[Запуск, результаты, связь с научными экспериментами](reports/weather_10gb.md):
полный scan 226.16 MB/s, peak RSS 220.2 MB, 24/24 certificate invocations,
156 tests passed. Это новый scale/Query run, не доказательство преимущества
исследовательского метода на всём архиве. Независимые 12-часовые эпизоды
и сценарии не объединяются в непрерывный физический ряд.

2026-10-19: добавлен **глобальный синтетический профиль v2**, основанный на
реальных ERA5 LSP, и мировая анимационная карта с зумом и перемещением.
[Модель, подготовка, проверка и команды](docs/weather_generator_v2.md).
[Фактические результаты](reports/weather_v2.md): 1.027 GB нового набора,
120 отложенных ERA5 cycles, 24/24 valid certificates, 154 tests passed.
Среднее LSP 0.05881 против 0.05959 mm/ч в holdout; основной выигрыш даёт
resampling целых реальных эпизодов, преимущества возмущений над bootstrap
систематически не выявлено.
Старый 200-GB набор сохранён как `legacy-v1`; его нагрузочные результаты
не переносятся на новую синтетику. Статистические сценарии v2 не являются
прогнозом погоды или дополнительными независимыми наблюдениями.

2026-10-18: добавлены **карта и почасовая анимация реального ERA5 LSP**.
Streamlit → «Карта осадков» → «Построить карту»: Play/Pause, ползунок времени,
значения под курсором и offline HTML export. [Запуск и ограничения](docs/precipitation_map.md).
Это отдельная визуализация исходных данных; научные результаты и claims не изменены.
Полная проверка текущей версии: **151 tests passed**; [XML](reports/validation/map-full.xml).
Синтетический набор 200 GB (`legacy-v1`) предназначен для нагрузочных испытаний;
[его метеорологическая реалистичность не подтверждена](reports/synthetic_realism.md).

**Научный вклад и ближайшие работы:** подготовлено
[содержательное обоснование предлагаемой новизны](reports/novelty_justification.md)
и [готовая авторская формулировка для введения/защиты](paper/novelty_statement_ru.md).
Вклад сужен до конкретного метода построения и проверки полного профиля точности;
общие идеи optimal recovery, конечных альтернатив, параметрических графов и
сертификатов признаются известными. Это обоснование узкого вклада относительно
рассмотренных работ, без заявления установленного мирового приоритета.

2026-10-17: добавлен **проверяемый профиль достаточной точности нового измерения**
с ограниченной ошибкой, для всех `eta >= 0`, со скачками при неоднозначных
метаданных и явным включением/исключением предельной точности. В замороженном
development-пилоте terminal reuse быстрее полного графа с compiled SciPy Johnson
в **1.23 / 1.87 / 2.27 раза**; все 2160 action/radius comparisons согласовались
с независимым LP. **Научный приоритет не установлен; внешнего проверяющего пока
нет, Gate B pending.** Новые результаты не отменяют прежний отрицательный H3.

- [Подробное объяснение проекта с нуля, примерами и командами](docs/project_explained_ru.md).
- [Новый отчёт: измерения, проверки, Gate A/B и ограничения](reports/precision_frontier.md).
- [Математический контракт и доказательство профиля](docs/precision_frontier.md).
- [Прочитанный ближайший prior art и конкретные риски новизны](docs/literature_delta_2026_10_17.md).
- [Пакет будущему независимому проверяющему](review/README.md).

Проверка исследовательского расширения 2026-10-17: **147 tests passed**, один TestClient deprecation warning.
Ниже сохранена история предыдущих результатов; числа tests относятся к указанным
там версиям. Завершающая проверка текущего расширения приведена в новом отчёте.

Исследовательское расширение, 2026-10-16: реализован oracle полезности одного
точного измерения по **всем непрерывным допустимым рядам**, парный LP, полный
парный граф и кандидат с повторным использованием путей между терминалами.
В отдельном development-пилоте кандидат быстрее полного графа в 1.25/1.75 раза
на двух режимах; на маленьком медленнее. LP и warm cache быстрее; приоритет
новизны не установлен. [Результаты, команды и ограничения](reports/continuous_acquisition.md),
[математический вывод и контракт сертификата](docs/continuous_acquisition.md).
Прежний отрицательный H3 сохранён; новый пилот оценивает oracle, не policies.
[Что ещё нужно для подтверждения новизны](docs/novelty_validation_plan.md):
prior-art delta, независимая проверка вывода, сильные baselines и Gate B.
Текущая полная проверка: **111 tests passed**, Ruff passed; внешний HTTP client
локально проверил сертификат нового endpoint. Ниже сохранён исходный инженерный
отчёт v2.1 с его отдельными scale-результатами.

Подготовка GitHub: **112 tests passed**, включая Git revision/dirty metadata
([validation](reports/validation/github-delivery.xml)). Крупные метеомассивы и
локальные окружения исключены из Git; сохранены manifests/checksums, компактные
результаты и source snapshots. [Архив manifests измеренных наборов](experiments/data_manifests/README.md).

Локальный CPU-прототип по ТЗ **v2.1**: Query к накопленным осадкам при неоднозначных
метаданных и недостаточной временной детализации. Один case — одна физическая
серия. Граф использует точные рациональные числа; SciPy/HiGHS независимо решает LP
по неотрицательным приращениям. Отдельный checker проверяет каждый вариант H,
границы, пути, конфликт, крайние ряды и неограниченные направления.

Сертификат условен относительно H и входных допущений. Неполное/top-k H получает
`incomplete_model`. Суточная сумма не делится на часы. Разные станции, продукты,
members и cycles не соединяются. LSP ERA5 — отдельная величина, не total rain.

Проверено: **79 tests passed**; synthetic **200 040 947 956 bytes**, полный scan
всех 476 shards и 24 запуска Query с проверкой сертификатов. Synthetic scale
acceptance — **passed**. [Итоговый отчёт с командами и ограничениями](reports/delivery.md).
Gate B остаётся pending; реальный 200-GB download/scan — not_run.

## Запуск

Python **3.12.13**, зависимости зафиксированы `uv.lock`. Первый `uv sync` требует
интернет; последующие demo, tests и synthetic generation работают без ключей.

```powershell
# Windows PowerShell, из корня проекта
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) '.uv-python'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
uv sync --frozen
uv run meteo demo --case overlap-exact --output outputs/demo
uv run meteo verify --result outputs/demo/result.json --certificate outputs/demo/certificate.json
uv run meteo demo --case overlap-bounded
uv run meteo demo --case conflict
uv run meteo demo --case insufficient-data
uv run meteo demo --case metadata-label
uv run meteo demo --case incomplete-h
uv run meteo solve --case data/fixtures/local-cumulative.csv --output outputs/local
uv run pytest -p no:cacheprovider
uv run ruff check .
uv run streamlit run ui/app.py --server.address 127.0.0.1
```

Linux:

```bash
export UV_CACHE_DIR="$PWD/.uv-cache" UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
uv sync --frozen
uv run meteo demo --case overlap-exact
uv run pytest -p no:cacheprovider
uv run streamlit run ui/app.py --server.address 127.0.0.1
```

Исходно папка была пуста, без Git/AGENTS.md. Работа проверяется на Windows/NTFS;
Linux-команды и CI предусмотрены, отдельного фактического WSL2/Linux run здесь нет.
Ограниченный sandbox агента иногда блокировал native initialization SciPy;
проверки выполнялись также вне него. Обычный локальный запуск не требует admin.

Demo: `overlap-exact` → 18 mm; `overlap-bounded` → [17.7,18.3] mm;
`threshold-true` → true при τ=15; `threshold-unknown` → unknown при τ=18;
`insufficient-data` → [0,12] mm за половину суток при известных 12 mm за сутки;
`metadata-label` допускает вопрос и evidence revision. Неполное H не сертифицируется.

UI принимает Case JSON, CSV с явными интервалами и scalar CF NetCDF с bounds.
Показывает данные/Query/границы/допущения/сертификат/witnesses/actions и экспорт.
Ограничение upload — 20 MiB; большой набор регистрируется по manifest через CLI,
в браузер не загружается. CSV-шаблон: `data/fixtures/local-cumulative.csv`.
Для неоднозначной семантики используйте Case JSON: CSV не сохраняет семейство H.

## Пилот и данные

```bash
uv run meteo experiment --config configs/experiments/pilot-final.yaml
uv run python scripts/build_real_cases.py
```

[Gate A](reports/gate_a.md) и raw runs в `experiments/runs/`: H1–H4, cold/warm
solver comparisons, сильные VOI/VOI2/DRD adaptations, exact tiny tree, одинаковые
priors/actions/costs/stopping, hidden simulator answer только после действия.
Shared candidate — известная incremental STN specialization; новая сложность,
оптимальность, method novelty и A* не заявляются. Отрицательные результаты сохранены.
[Gate B](reports/gate_b.md) остаётся pending: нет независимой человеческой разметки.

Offline доступны маленькие DWD excerpts трёх станций и Case JSON с provenance.
Синтетический cumulative CSV — разрешённая локальная альтернатива CDS; он не
выдаётся за реальную загрузку CDS. Проверен один реальный NCAR ERA5 LSP NetCDF.
Его исходный файл хранится отдельно от маленьких cases. Детали и ограничения —
[data_sources](docs/data_sources.md), [annotation_guide](docs/annotation_guide.md).

Повторная реальная загрузка (сеть, без API-ключей):

```bash
uv run python scripts/fetch_dwd_subset.py
uv run meteo data prepare-real-scale --provider ncar-era5 --target-size 1MB --config configs/scale/ncar-smoke.yaml --output data/scale/ncar-lsp-small --dry-run
uv run meteo data prepare-real-scale --provider ncar-era5 --target-size 1MB --config configs/scale/ncar-smoke.yaml --output data/scale/ncar-lsp-small --resume
```

## API и внешний client

```bash
uv run uvicorn meteo_bridge.api:app --host 127.0.0.1 --port 8000
# В другом терминале
uv run python examples/integration_client.py data/fixtures/overlap-exact.json
```

`GET /health`, `POST /datasets` (multipart), `GET /datasets/{id}/schema`,
`POST /queries` (dataset_id + Query), `GET /queries/{id}`,
`/{id}/certificate`, `/witnesses`, `/actions`, `/export`,
`POST /queries/{id}/evidence`. Последний сохраняет новую revision; старые не теряются.
Client проверяет экспортированный certificate локально. CLI/UI/API используют
`services.solve_query`. SDK также предоставляет `load_dataset`, `compile_case`
(semantics), `verify_certificate`, `suggest_action`, `apply_evidence`.

## Масштаб: smoke → 1/10/50/200 GB

200 GB = **200000000000** фактических байт data shards. GB и GiB различаются.
Только завершённые уникальные полезные data files входят в объём. Нет padding,
sparse placeholders, копий одного файла или повторного учёта представлений.
Генератор ≤2 GiB, обработка вместе с workers ≤16 GiB, ограниченная рабочая модель.
Данные — chunked NetCDF или Parquet; synthetic погода нужна для IO/корректности,
а не для заявления о достоверности симулятора климата.

```bash
# Малый smoke; CI не запускает большие объёмы
uv run meteo data generate-scale --target-size 32MB --shard-size 16MiB --chunk-size 2MiB --series 4096 --series-per-shard 1024 --seed 42 --output data/scale/smoke --memory-limit 2GiB
uv run meteo data verify-scale --manifest data/scale/smoke/manifest.json --mode full
uv run meteo benchmark scale --manifest data/scale/smoke/manifest.json --sizes smoke --output reports/scale-smoke

# Проверка диска обязательна; --dry-run не создаёт data files
uv run meteo data generate-scale --target-size 200GB --format netcdf --compression none --seed 42 --output data/scale/synthetic-200gb --memory-limit 2GiB --chunk-size 32MiB --workers 4 --dry-run
uv run meteo data generate-scale --target-size 200GB --format netcdf --compression none --seed 42 --output data/scale/synthetic-200gb --memory-limit 2GiB --chunk-size 32MiB --workers 4 --resume
# В сохранённом большом run использованы --chunk-size 32MiB --workers 4:
# эти параметры нужны и при его resume.
uv run meteo data verify-scale --manifest data/scale/synthetic-200gb/manifest.json --mode full
uv run meteo benchmark scale --manifest data/scale/synthetic-200gb/manifest.json --memory-limit 16GiB --output reports/scale
uv run python scripts/finish_scale_experiment.py --manifest data/scale/synthetic-200gb/manifest.json --output reports/scale --acceptance-only
uv run meteo data register --manifest data/scale/synthetic-200gb/manifest.json --name synthetic-200gb

# Отдельный real-scale профиль; первоначально LIST/HEAD, не весь архив
uv run meteo data prepare-real-scale --provider ncar-era5 --target-size 200GB --config configs/scale/ncar-era5.yaml --output data/scale/real-200gb --dry-run
uv run meteo data prepare-real-scale --provider ncar-era5 --target-size 200GB --config configs/scale/ncar-era5.yaml --output data/scale/real-200gb --resume
```

Эквиваленты для всех CLI-параметров:

```bash
uv run python scripts/generate_scale_dataset.py --target-size 200GB --seed 42 --output data/scale/synthetic-200gb --memory-limit 2GiB --dry-run
uv run python scripts/prepare_real_scale_dataset.py --provider ncar-era5 --target-size 200GB --config configs/scale/ncar-era5.yaml --output data/scale/real-200gb --dry-run
uv run python scripts/verify_scale_dataset.py --manifest data/scale/synthetic-200gb/manifest.json --mode full
uv run python scripts/run_scale_benchmark.py --manifest data/scale/synthetic-200gb/manifest.json --memory-limit 16GiB --output reports/scale
uv run python scripts/run_storage_comparison.py
```

Resume scan: `--stop-after-shards 1`, затем те же параметры с `--resume`.
Для продолжения сохранённого большого scan используйте `meteo benchmark scale ... --resume`.
`finish_scale_experiment.py --acceptance-only` проверяет сохранённый report и пишет
`acceptance.json`, не повторяя scan. После паузы можно передать
`--previous-report reports/scale/archive/pre-pause-scale_report.json` для lineage.
Генерация: `--max-shards 1`, затем `--resume`; также сохранена отдельная проверка
принудительного прерывания workers. `--disk-budget`, `--chunk-size`, `--shard-size`,
`--workers`, даты, missing/defect fractions доступны через `--help`.
Root данных задаётся `--output`; пользовательские пути не вшиты.

Фактический статус, объём, checksums, full scan, Queries, LP samples, RAM, latency,
throughput и resume находятся в [scale report](reports/scale/scale_report.md),
а не экстраполируются с малого запуска. Real-200GB не заявляется выполненным на
основании synthetic run. Ограничения — [scale_data](docs/scale_data.md),
[assumptions](docs/assumptions.md), [claims](paper/claims.md), [progress](docs/progress.md).

Рабочее описание методов: [paper/methods.md](paper/methods.md). Таблицы результатов
обновляются из сохранённых runs командой `uv run python scripts/update_reports.py`.
`uv run python scripts/plot_results.py` создаёт `reports/figures.html`: автономные
интерактивные графики solver/policies/scale с встроенным Plotly, без CDN.
Незавершённые scale-профили в графики не включаются.
