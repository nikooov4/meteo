# Глобальные синтетические осадки v2

Профиль `weather-bootstrap` предназначен для правдоподобных пространственных
сценариев и испытаний MeteoBridge. В нём используется **LSP — крупномасштабная
компонента осадков ERA5**, а не суммарные осадки и не наблюдения станций.
Это статистический surrogate: переиспользование целого реального погодного
эпизода с небольшим случайным изменением интенсивности.

Старый профиль `legacy-v1` и существующий набор 200 GB сохранены. Их прежние
нагрузочные результаты относятся именно к старому профилю. Они не доказывают
реалистичность старых данных или выполнение нового эксперимента 200 GB.

## Что изменено

В v1 wet/dry режим и интенсивности создавались хешами без климатической
привязки. Координаты старого 4-миллионного набора охватывали широты −60…39.9°.
В v2 сетка охватывает весь мир: центры −89.5…89.5° и −179.5…179.5°, шаг 1°,
64 800 точек. Это выборка точек исходной сетки 0.25°, **не среднее осадков
по площади одноградусной ячейки**. Покрытие глобальное, разрешение ограничено.

Для каждого доступного месяца используются реальные 12-часовые глобальные
последовательности. Дни 1–10 поступают только в training bank; дни 11–15 —
в отдельный holdout bank. Разбиение выполняется целыми циклами, до генерации.
Одинаковые месяц и фаза инициализации 06/18 UTC учитываются при выборе
training-блока. По умолчанию выбранный блок умножается на плавное положительное
случайное поле с логарифмическим стандартным отклонением `sigma=0.12`.
Корреляционный масштаб возмущений — около 4°; временной коэффициент — 0.95.
Эти параметры заданы заранее, не подобраны по holdout. Поправка `−sigma²/2`
соответствует нормальному lognormal mean correction; после пространственной
стандартизации она не гарантирует точного равенства конечных выборочных средних.

Внутри блока сохраняются география, wet/dry структура и движение реального
эпизода. Числа меняются; новые физические штормы не изобретаются. Циклы независимы:
на границе блоков возможен скачок. Нельзя использовать такой ряд как непрерывный
прогноз или оценивать по нему длительность многосуточной засухи. Нельзя считать
200 GB таких сценариев 200 GB независимых реальных наблюдений.

NSF NCAR ERA5 HRES в этом профиле хранит LSP в метрах за **предыдущий час**.
Код переводит m → mm, не вычитает соседние значения и не делит daily totals.
В итоговом файле явно записаны hourly bounds, quantity, synthetic member,
продукт и идентификатор цикла; количество округлено до 0.0001 mm. Сертификат
Query относится к закодированным данным и полному H схемы, а не к истинной
погоде с такой физической точностью.

## Подготовка и запуск

Из корня проекта, после `uv sync --frozen`; на Windows удобно использовать
проектные `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, как в README.

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'

# Требует интернета только для public ERA5; ключей нет.
uv run python scripts/prepare_weather_calibration.py --download --output data/calibration/era5-lsp-2023-v1

# Далее offline; новый каталог, старый 200-GB набор не перезаписывается.
uv run python scripts/generate_scale_dataset.py --profile weather-bootstrap --calibration data/calibration/era5-lsp-2023-v1/manifest.json --output data/scale/weather-global-v2 --target-size 1GB --seed 42

uv run python scripts/validate_weather_generator.py --calibration data/calibration/era5-lsp-2023-v1/manifest.json --output reports/weather-v2/heldout.json
uv run python scripts/verify_scale_dataset.py --manifest data/scale/weather-global-v2/manifest.json --mode full
uv run python scripts/run_scale_benchmark.py --manifest data/scale/weather-global-v2/manifest.json --sizes smoke --output reports/weather-v2/scale-smoke

uv run python scripts/build_precipitation_map.py --input data/scale/weather-global-v2/manifest.json --output outputs/maps/synthetic_global_animation.html
uv run streamlit run ui/app.py
```

Если January-файл уже есть, можно не скачивать его повторно: добавить
`--sources data/scale/ncar-lsp-small/ИМЯ.nc --months 2,3,4,5,6,7,8,9,10,11,12`.
Повторная загрузка использует ETag-pinned ranges, checkpoints и checksums.
Готовая calibration directory неизменяема: для другого обучения нужен новый путь.
Для полностью offline подготовки передайте `--sources` с локальными файлами
вместо `--download`. Генератор не открывает holdout bank.

## Чтение больших данных

Генератор однопроцессный, budget ≤2 GiB RSS; в памяти один 12-часовой глобальный
блок. Каждый shard содержит до 12 циклов одного member. Данные настоящие:
float64 hourly amounts + QC, без padding, sparse placeholders и копий файлов.
Независимый seed зависит от `(seed, member, initialization)`, поэтому resume
не меняет последующие значения. Завершённые файлы проверяются по SHA256;
незарегистрированный завершённый shard сверяется с повторной генерацией.

Для 200 GB нужен отдельный явный запуск, проверка диска с запасом 20% плюс
shard. Сначала dry-run:

```powershell
uv run python scripts/generate_scale_dataset.py --profile weather-bootstrap --calibration data/calibration/era5-lsp-2023-v1/manifest.json --output data/scale/weather-200gb-v2 --target-size 200GB --disk-budget 202GB --dry-run
# Уберите --dry-run для реального заполнения диска; --resume продолжает тот же запуск.
uv run python scripts/run_scale_benchmark.py --manifest data/scale/weather-200gb-v2/manifest.json --sizes 1GB,10GB,50GB,200GB --memory-limit 16GiB --output reports/weather-v2/scale-200gb
```

Не запускайте 200 GB в обычных tests/CI. Перенос calibration на другую машину
требует обновлённой конфигурации/нового output: абсолютный путь включён в hash.
Для физического воспроизведения отдельных событий требуются те же версии
NumPy/SciPy из `uv.lock`, calibration bank и manifest.
JSON/manifest читаются как UTF-8, включая кириллицу в пути к manifest. В
проверенной Windows-сборке NetCDF/HDF5 создание native файлов в каталоге с
кириллицей вернуло PermissionError; для `.nc` используйте ASCII-пути, как в
командах выше. Ограничение библиотеки сохранено, загрузка архива ради обхода
не выполняется.

### Windows: train.nc существует, но NetCDF сообщает «No such file»

В Windows-сборке netCDF4 1.7.5 воспроизведено: Python видит и хеширует файл
в каталоге с кириллицей, но `nc.Dataset` с его абсолютным путём возвращает
FileNotFoundError. Поэтому проверяйте наличие отдельно:

```powershell
Test-Path -LiteralPath '.\data\calibration\era5-lsp-2023-v1\train.nc'
```

Если True, скопируйте полный calibration folder в новый каталог, чей полный
путь содержит только ASCII. Для пользователя с ASCII-именем профиля:

```powershell
$meteoData = Join-Path $env:USERPROFILE 'meteo-data'
New-Item -ItemType Directory -Force "$meteoData\calibration" | Out-Null
Copy-Item -LiteralPath '.\data\calibration\era5-lsp-2023-v1' -Destination "$meteoData\calibration" -Recurse

uv run python scripts/generate_scale_dataset.py --profile weather-bootstrap --calibration "$meteoData\calibration\era5-lsp-2023-v1\manifest.json" --output "$meteoData\weather-global-10gb-v2" --target-size 10GB --seed 42 --disk-budget 11GB --memory-limit 2GiB --dry-run
uv run python scripts/generate_scale_dataset.py --profile weather-bootstrap --calibration "$meteoData\calibration\era5-lsp-2023-v1\manifest.json" --output "$meteoData\weather-global-10gb-v2" --target-size 10GB --seed 42 --disk-budget 11GB --memory-limit 2GiB --resume
```

Сам репозиторий можно оставить на месте. Для генерации нужны manifest и train.nc;
для оценки реалистичности также нужен holdout.nc. Исходники ERA5 заново скачивать
ради копирования готовых banks не требуется. Используйте новый output: абсолютный
calibration path входит в конфигурационный hash, старый manifest не редактируйте.
В дальнейших командах verify/scan/map указывайте новый путь к manifest архива.
Если каталог назначения уже содержит другую калибровку, выберите новое имя.

Если Test-Path вернул False, калибровка неполна: один manifest не заменяет
train.nc. Подготовьте её в новом ASCII-каталоге, сохранив прежнюю:

```powershell
$meteoData = Join-Path $env:USERPROFILE 'meteo-data'
uv run python scripts/prepare_weather_calibration.py --download --output "$meteoData\calibration\era5-lsp-restored-v1"
```

Готовые источники в стандартном references-каталоге проверяются и используются
повторно. Затем передайте полученный manifest генератору и выберите новый output.
Обновлённый dry-run открывает training bank до выдачи плана; проверка полного
SHA256 по-прежнему выполняется перед реальной генерацией.

## Карта

Новый файл `outputs/maps/synthetic_global_animation.html` содержит весь мир,
12 hourly frames одного synthetic member/cycle, Play/Pause, ползунок времени,
зум колёсиком и перемещение мышью. Кнопка «Весь мир / сброс» возвращает исходный
масштаб. После изменения часа выбранная область сохраняется. Кнопки панели
дают масштабирование и PNG export; HTML и границы Natural Earth работают offline.
Это плоская карта longitude/latitude, не трёхмерный глобус.

В Streamlit → «Карта осадков» → «Синтетика v2» можно выбрать manifest, member,
начало 12-часового цикла и bbox. Нельзя склеить members/cycles в одну физическую
функцию. Для оригинального ERA5 мировой вид ограничивается spatial stride,
чтобы не передавать браузеру десятки миллионов значений. Увеличение карты
не восстанавливает отсутствующую детализацию. Цветовая шкала общая по кадрам.

## Что подтверждает проверка

`reports/weather-v2/heldout.json` содержит реальные измерения после запуска:
глобальные cos(latitude)-weighted mean/wet/zero, sample p95/p99, log1p temporal
и соседние spatial correlations, wet persistence внутри цикла. Сравниваются
real holdout, v1, обычный bootstrap и v2 на одинаковой географии/сезоне/фазе.
Квантили оценены по фиксированным 512 точкам; это не точные глобальные квантили.
По этим данным не подбираются параметры задним числом.

Это development holdout одного года, а не независимая климатическая валидация.
Повторяющиеся training storms ограничивают разнообразие и хвосты. Для прогноза
экстремумов нужны многолетние источники, региональные проверки, более сильные
weather-generator baselines и независимая экспертиза. Научный смысл этой работы
— честный benchmark и проверка Query; новый weather algorithm не заявляется.

Известность пространственной и временной зависимости в генераторах осадков:
[Wilks, 1998](https://www.sciencedirect.com/science/article/pii/S0022169498001863).
Использование исторической структуры полей также известно, например
[Clark et al., 2004, Schaake Shuffle](https://journals.ametsoc.org/view/journals/hydr/5/1/1525-7541_2004_005_0243_tssamf_2_0_co_2.xml).
Наш block bootstrap не является реализацией Schaake Shuffle и не претендует
на его идею. Источник и conventions:
[NSF NCAR ERA5 on AWS](https://registry.opendata.aws/nsf-ncar-era5/),
[GDEX d633000](https://gdex.ucar.edu/datasets/d633000/),
[ECMWF ERA5 documentation](https://confluence.ecmwf.int/pages/viewpage.action?pageId=85415489).
