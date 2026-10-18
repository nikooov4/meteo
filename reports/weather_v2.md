# Глобальная синтетика и анимация: выполненная проверка

2026-10-19. Сделаны отдельный генератор правдоподобных глобальных **LSP**
сценариев v2, новый набор **1 026 890 064 bytes** и мировая анимация с зумом.
Старый набор **200 040 947 956 bytes** и прежняя карта сохранены.
LSP — крупномасштабная компонента осадков; это не total precipitation.

Новая карта: `outputs/maps/synthetic_global_animation.html`,
[открыть в локальном браузере](http://127.0.0.1:8765/synthetic_global_animation.html).
Сервер должен работать; текущий loopback viewer проверен HTTP 200.
Для повторного запуска viewer из корня проекта:

```powershell
uv run python -m http.server 8765 --bind 127.0.0.1 --directory outputs/maps
```

## Реализм: что именно проверено

Источник: 12 оригинальных глобальных файлов NSF NCAR ERA5 LSP за первую
половину каждого месяца 2023, всего **3 166 788 003 bytes**. Сетка 0.25°
выбрана в фиксированных точках через 1°, 180×360, центры покрывают весь мир.
Это выборка точек, а не spatial area average. Почасовые amounts m → mm,
без deaccumulation или деления суточных сумм. Оригинальные cycles разделены.

Дни 1–10 каждого месяца: **240 training cycles**. Дни 11–15:
**120 held-out cycles**, физически другой NetCDF bank. Ни один cycle не
встречается в обеих частях. Генератор читает только training bank, выбирает
целый 12-часовой эпизод того же месяца и фазы 06/18 UTC, затем немного меняет
интенсивности плавным положительным случайным полем. Wet/dry footprints и
движение реальных эпизодов внутри блока сохраняются. На границе блоков
возможен скачок; это статистические сценарии, не непрерывный прогноз.

Параметры заданы [до оценки](weather-v2/frozen_evaluation_io.json),
[конфигурация](../configs/weather_bootstrap_v2.json). Единственное изменение
после первоначального freeze — способ bounded IO, без изменения параметров,
точек или split: один contiguous native cycle вместо тысяч netCDF index calls.
Исходный январский smoke с orthogonal indexing занял 87.43 s; окончательная
подготовка ВСЕХ 12 месяцев — **81.58 s**, peak process-tree RSS **295.89 MiB**.
Это разные объёмы и режимы чтения, не отдельный контролируемый speedup benchmark.

Оценка: 93 312 000 cell/hour values на метод; quantiles по одинаковой фиксированной
выборке 512 точек, 737 280 значений. Mean/wet/zero взвешены cos(latitude),
correlations и persistence не взвешены, пары только внутри одного цикла.
Wet означает ≥0.1 mm за час, кодирование округлено до 0.0001 mm.

| Показатель | Real holdout | Старый закон v1 | Обычный block bootstrap | v2 с возмущением |
|---|---:|---:|---:|---:|
| Среднее, mm/ч | 0.05959 | 0.61237 | 0.05887 | 0.05881 |
| Wet, % площади | 9.3758 | 31.5228 | 9.4206 | 9.3864 |
| Нули, % площади | 46.0194 | 66.1101 | 45.8657 | 45.8657 |
| Sample p95, mm | 0.2131 | 3.5400 | 0.2089 | 0.2080 |
| Sample p99, mm | 0.9504 | 7.5700 | 0.9361 | 0.9307 |
| Lag-1 correlation log1p | 0.93759 | 0.58863 | 0.93655 | 0.93633 |
| Соседи по долготе, log1p | 0.76961 | 0.00005 | 0.77409 | 0.77449 |
| Соседи по широте, log1p | 0.65128 | −0.00004 | 0.65727 | 0.65778 |
| Wet persistence | 0.82212 | 0.87351 | 0.82214 | 0.82193 |

**Вывод ограничен этой проверкой:** v2 воспроизводит измеренные характеристики
LSP значительно ближе, чем старый некалиброванный закон. Основной эффект даёт
resampling целых реальных пространственных эпизодов. **Систематического
преимущества возмущений над обычным bootstrap не выявлено**: у bootstrap
меньше ошибка среднего, хвостовых quantiles и большинства correlations, у v2
ближе wet fraction. Параметры после просмотра не менялись. Единого «процента
реалистичности» не вычисляем.

v1 здесь — старый синтетический scalar amount law как некалиброванный контроль
на той же сетке/времени; сравнение не превращает его прежний продукт precipitation
в реальный LSP и не сравнивает реальный total rain с реальным LSP.
Его прежний непарный DWD diagnostic сохранён отдельно.

Полные значения, месячные cycle metrics, определения, seed, версии,
source snapshot и ограничения: [heldout.json](weather-v2/heldout.json).
Оценка заняла **45.25 s**, peak RSS **198.07 MiB**.

Один reference year и первые половины месяцев недостаточны для climate
validation. Нет гарантии многолетних экстремумов, климатических трендов,
разнообразия новых штормов или многосуточной persistence. Повторно выбранный
шторм не становится независимым реальным наблюдением. Coherent perturbation
не обеспечивает физический баланс воды или полноценную динамику атмосферы.

## Фактический набор и scale-проверка

`data/scale/weather-global-v2/manifest.json`: 12 настоящих NetCDF shards,
**1 026 890 064 bytes**, **111 974 400** cell/hour rows, 64 800 global points,
1728 hourly steps одного synthetic member. Данные — amount float64 + QC uint8,
координаты и интервалы; padding, sparse placeholders и копии файлов не использованы.
Metadata явно отделяют synthetic product, quantity, member и 12-hour cycle.

Генерация: сначала 1 shard и остановка, затем **resume**, ещё 11 shards.
Время двух invocations 1.43 + 14.78 s; максимальный RSS **183.96 MiB**.
QC в этом профиле clean: missing/rejected defects остаются в legacy-v1 и
ручных fixtures; карта не служит испытанием всех неоднозначных метаданных.

Full verification проверила shapes, conventions, координаты, partitions,
physical allocation и SHA256 всех файлов. Full streaming scan также остановлен
после двух shards и продолжен по checkpoint:

| Измерение | Результат |
|---|---:|
| Полезные data files | 1 026 890 064 bytes |
| Полный normalized scan, суммарное активное время | 4.7645 s |
| Throughput data-file bytes / active scan time | 215.53 MB/s |
| Peak process-tree RSS, scan + Query | 199.18 MiB |
| Query invocations / valid certificates | 24 / 24 |
| Generating truth входит в bounds | 24 / 24 |
| Дополнительная независимая LP-проверка | 8 invocations |
| Query latency p50 / p95 | 8.99 / 15.83 ms |
| Ошибки итогового scale run | 0 |

OS cache не очищался, файлы были недавно сгенерированы; throughput не заявляется
как cold-disk bandwidth. SHA256 time записано отдельно. Проверка generating
truth повторяет генератор; независимость LP относится к решению constraints,
а не к физической истинности синтетики. Это проверка bounded IO/интеграции,
не новое сравнение solver или policies.

[Scale report и сертификаты](weather-v2/scale/scale_report.json),
[прерванный scan](weather-v2/scale/interrupted.json),
[checkpoint](weather-v2/scale/1000000000-bytes-checkpoint.json).

Новые 10/50/200-GB прогоны: **not_run**. Для 200 GB выполнен только
[CLI dry-run и проверка диска](weather-v2/200gb-dry-run.json):
свободно 246 504 792 064 bytes, требуется с запасом 240 086 584 576,
`disk_feasible=true`. Диск позволяет запуск при сохранении резерва; большой
прогон здесь не выполнялся, потому что для новой карты и этой проверки
подготовлен отдельный 1-GB набор, прежние 200 GB сохранены. Прежний успешный
200-GB эксперимент относится к legacy-v1. Команда реального нового запуска
приведена в [руководстве](../docs/weather_generator_v2.md); генератор ≤2 GiB,
benchmark ≤16 GiB, один bounded worker. Нет экстраполяции результатов 1 GB.

## Карта и тестирование

Мировая HTML-анимация: 12 кадров ×180×360 = **777 600** значений,
**9 705 881 bytes** standalone HTML. Synthetic LSP явно подписан, один cycle,
общая цветовая шкала, без temporal smoothing. Play/Pause, ползунок времени,
wheel zoom, pan, reset к миру и PNG/HTML export. Мировой вид — плоские
longitude/latitude; зум не добавляет разрешения сетке.

Headless Edge открыл файл, переключил frame 5, сохранил zoom [-15,65],
затем вернул world ranges [-180,180] и [-90,90]. Скриншот визуально проверен.
[Browser evidence](validation/synthetic-world-render.json).
Новый источник Streamlit на фактическом наборе также проверен:
[UI evidence](validation/weather-streamlit.json).

Финальная полная регрессия: **154 tests passed**, 41.23 s, один прежний
Starlette TestClient deprecation warning.
[JUnit](validation/weather-delivery-full.xml). Ruff и whitespace check прошли.
Зависимости уже были в `uv.lock`, новых зависимостей нет.

Заключительный аудит Windows выявил необходимость явного UTF-8 для JSON;
исправлены readers и добавлен smoke с кириллическим именем manifest. Численные
параметры и алгоритм не менялись; heldout/scale runs сохраняют исходные snapshots.
Попытка создать `.nc` в кириллическом каталоге дала PermissionError в установленной
NetCDF/HDF5 сборке. Native data directories остаются ASCII; это ограничение
отражено в руководстве, журнал неудачной проверки сохранён.
[Итоговый source snapshot и hashes](validation/weather-delivery-context.json)
отделяют эту совместимость JSON от исходного кода численных экспериментов.

## Научная ценность и Gate A / Gate B

Научное ядро уже реализовано: условные bounds Query при неоднозначных метаданных,
проверяемые certificates/witnesses и профиль достаточной точности дополнительного
interval measurement с bounded error для всех конечных eta≥0. Это позволяет
исследовать, что следует из накопленных данных и какая новая информация нужна.
Авторская заявка на узкий вклад и границы известного:
[обоснование](novelty_justification.md), [precision frontier](precision_frontier.md).
**Мировой приоритет и независимое подтверждение пока не установлены.**

Новый weather generator — известная идея block resampling с объявленным
возмущением, инженерная поддержка эксперимента. Карта — визуализация. Их
правдоподобие само по себе не доказывает solver novelty или оптимальность.

[Gate A](gate_a.md) сохраняет прежние результаты H1–H4, включая отрицательный H3;
этот run не переоценивает policies. [Gate B](gate_b.md) **pending**: новые месяцы
того же продукта не заменяют независимую разметку, unseen-family evaluation
или независимую проверку вывода. Внешнего проверяющего пока нет.

## Воспроизведение и provenance

[Команды подготовки, генерации, проверки, Streamlit и 200-GB dry-run](../docs/weather_generator_v2.md).
Архив компактных manifests, banks/source SHA256 и generation runs:
[calibration](../experiments/data_manifests/weather-v2-calibration.json),
[generated dataset](../experiments/data_manifests/weather-global-v2.json),
[downloaded references](../experiments/data_manifests/weather-v2-sources.json).
Сетевой обрыв, повтор и resume сохранены в
[download history](weather-v2/download_history.json). Крупные массивы и локальные
checkpoints загрузки не добавляются в Git; чистый clone создаёт их командами.

Первичные данные и conventions:
[NSF NCAR ERA5](https://registry.opendata.aws/nsf-ncar-era5/),
[GDEX d633000](https://gdex.ucar.edu/datasets/d633000/),
[ECMWF](https://confluence.ecmwf.int/pages/viewpage.action?pageId=85415489).
