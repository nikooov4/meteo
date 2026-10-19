# Эксперименты: применимость и пределы выводов

Этот файл построен из сохранённых runs; новый archive status: **complete**.

## Метод на реальных ERA5 LSP: сохранённый эксперимент

Дата 2026-10-19. Статус: **complete**. Метод применён к реальным encoded
метеоданным реанализа, с явно контролируемой потерей временной детализации.
Научный приоритет и independent Gate B этим не устанавливаются.

## Дизайн

В 12 исходных NCAR ERA5 HRES LSP файлах 2023 года заранее выбраны циклы дня 11
06 UTC и шесть фиксированных grid points: Moscow, Singapore, North Atlantic,
New York, Tokyo, Sydney. Это 72 point/cycle windows, **864 исходных hourly values**.
Все сухие случаи сохранены. Выбор не зависел от увиденного количества осадков.
Эти дни исключались из training bank синтетики, но уже использовались в её
development holdout; это не новые независимые source families или экспертная разметка.

Общий размер source files **3,166,788,003 bytes**.
SHA256 всех 12 файлов заново проверены. Для анализа читается один native 12-hour
global field за раз, около 50 MB float32; в solver поступают ограниченные point cases.
Не весь глобальный архив передаётся в один граф.

Conventions: documented previous-hour LSP amount, native units m, точный rational
перевод encoded binary float в mm. Соседние amounts не вычитаются. LSP — только
крупномасштабная компонента реанализа, не total precipitation и не gauge observation.

Почасовые значения укрупняются в четыре-часовые суммы при accepted QC; отсутствующие
значения не восстанавливаются. Запрос — первые пять часов, eps=0.05 mm.
Сравниваются documented H1 и controlled shift H2. Во второй ветке сдвиг внесён
нами в один укрупнённый интервал; он способен оставить непокрытый час и unbounded
ответ. Это проверка явно объявленного perturbation model, а не естественный дефект ERA5.
Гипотетическая eta — bounded error добавляемого наблюдения, не sensor calibration.

## Результаты

Всего **144 задач**, **576 profile bundles**.
Все четыре метода прошли checker и сравнение с независимым paired-increment LP
на eta=0,0.1,1 mm. Это **1728 различных action/radius comparisons**,
каждое сверено для четырёх методов; LP calls для профилей — 4968.
Численная tolerance 1e-7. LP grid не доказывает всю кривую; отдельный checker
проверяет all-finite-eta certificate.

| Ветка | Cases | Уже exact до уточнений | Unbounded до уточнений | Bounds сузились | Exact после всех hourly observations |
|---|---:|---:|---:|---:|---:|
| documented_H1 | 72 | 37 | 0 | 35 | 72 |
| controlled_shift_H2 | 72 | 0 | 72 | 72 | 72 |

Во всех случаях проверены вложенные наборы 0/3/6/12 исходных observations:
lower не уменьшается, upper не увеличивается; Query bounds независимо сверены с LP.
Дополнительные сведения для этого же места/цикла сужают ответ; объём постороннего
архива не использован как замена информации. Сухие исходно exact случаи не исключены.

Медианные cold end-to-end ms, включая построение/проверку всего профиля:

| Метод | Median ms |
|---|---:|
| full | 14.234 |
| compiled | 18.347 |
| terminal_no_reuse | 19.329 |
| terminal | 17.933 |

Отдельно по веткам:

| Ветка | full ms | compiled ms | no reuse ms | terminal ms | compiled/terminal |
|---|---:|---:|---:|---:|---:|
| documented_H1 | 6.373 | 7.781 | 8.291 | 7.047 | 1.104 |
| controlled_shift_H2 | 26.967 | 29.939 | 30.804 | 25.707 | 1.165 |

Это один shuffled проход на задачу, не significance study. При documented H1
измеренный полный Python graph **быстрее terminal**; общий median full также ниже.
Кандидат выигрывает у compiled comparator умеренно, а не у всех альтернатив.
Результаты не подгонялись под обязательный выигрыш. Numerical LP и repeated-input cache не считаются равным
по контракту cold all-profile timing comparator. Одновременно выполнялся отдельный
background archive job; его IO/RAM не следует приписывать этому процессу.

Wall time: **170.579 s**, sampled process-tree peak RSS
**330,211,328 bytes**, budget 2 GiB. Ошибок записано: 0.
Источник runs: `experiments/runs/precision-real-era5-v1/`, protocol в
`configs/experiments/precision-real-era5-v1.json`; там же input/certificates/LP,
source snapshot, версии, hashes и replay.json. ZIP bundles содержат обычный JSON.

```powershell
uv run python scripts/run_real_precision_experiment.py --output experiments/runs/precision-real-era5-reproduction
```

Применимость означает корректную работу реализованного математического контракта
на указанных реальных значениях. Она не означает доказанную полноту всех реальных
metadata alternatives, природное происхождение controlled дефектов, независимый
Gate B, лучший прогноз или установленную новизну.


## Precision method и 200-GB архив

Дата 2026-10-19. Фактический статус: **complete**.
Обработано **476/476 partitions**,
проверено SHA256 **200,040,947,956 bytes** из
**200,040,947,956 bytes**. Числа ниже относятся только к завершённым задачам.

## Что именно проверяется

Это существующий synthetic legacy-v1, не новая реалистичная синтетика v2.
Одна seeded серия и 12/24-hour window из каждого manifest shard выбираются
без анализа rainfall values. Сохраняются zero/missing/rejected случаи.
Amount и mean rate агрегируются только по accepted источникам, cumulative
сохраняется на документированных four-hour endpoints в пределах одного reset cycle.
В constructed задаче задаются 2/3 явные controlled metadata alternatives;
полнота H относится к этим объявленным сдвигам, не ко всем смыслам реального файла.

Каждая рабочая задача содержит 3/6 укрупнённых наблюдений, 2/3 H и четыре действия.
Это проверка покрытия большого storage ограниченными задачами, а не решение
200 GB constraints в одном графе или доказательство новой scaling complexity.

Полный точный graph, compiled full graph, terminal без reuse и terminal reuse
получают одинаковые данные, действия, стоимость и proof contract.
Сравнивается вычисление oracle, не policy. Нет доступа к скрытым ответам simulator.
Whole-profile four-entry cache проверяется отдельно на повторном одинаковом входе;
warm hit не сравнивается с cold candidate как одинаковый режим.

Профиль независимо сравнивается с paired LP для eta=0,0.1,1 mm и проверяется checker.
Native Query и четыре вложенных уровня возвращённых observations также сверяются
с LP и сохраняют сертификаты. Проверяется сужение bounds при добавлении полезных
наблюдений. Нет произвольного hourly disaggregation или соединения физических серий.

## Текущее измеренное состояние

Profile bundles: **1904**; уникальные action/radius comparisons
на каждый метод: **5712**. Ошибки run: **0**.

| Метод | Median ms по завершённым задачам |
|---|---:|
| full | 49.639 |
| compiled | 58.091 |
| terminal_no_reuse | 52.126 |
| terminal | 47.543 |
| cache_warm | 14.472 |

Покрытие фиксированного набора native Queries префиксами архива:

| Target GB | Фактические bytes префикса | Проверенных доступных задач / файлов префикса | Из них native exact |
|---|---:|---:|---:|
| 1 | 1,278,907,323 | 3/3 | 3 |
| 10 | 10,231,257,624 | 24/24 | 23 |
| 50 | 50,318,700,487 | 119/119 | 114 |
| 200 | 200,040,947,956 | 476/476 | 453 |

Всего целевых задач 476. Если собственный shard задачи ещё
не входит в доступный префикс, её observations недоступны. Эта таблица показывает
охват фиксированного workload, не улучшение физической точности от bytes.
Ширина одного уже покрытого Query определяется его relevant observations и QC;
добавление посторонних partitions не создаёт для него новых ограничений.

Возвращение исходных наблюдений в controlled задачах:

| Возвращено relevant hourly records | Exact cases | Unbounded cases | Finite, ещё не exact |
|---|---:|---:|---:|
| 0% | 86 | 315 | 75 |
| 25% | 86 | 283 | 107 |
| 50% | 453 | 22 | 1 |
| 100% | 453 | 22 | 1 |

Отсутствующие/rejected observations не восстанавливаются, поэтому даже все
доступные записи не обязаны дать exact ответ. Это результат об информации для
Query, не об ошибке прогноза относительно истинного дождя.

Последняя invocation: hashed bytes 200,040,947,956,
hash time 2312.106 s;
финализированный peak RSS: 170975232 bytes.
Invocations: 3; resume invocations:
2.
Ранние прерывания/checkpoints сохраняются; invocation без финальных wall/RSS
не превращается в завершённое измерение. На resume повторно сверяются hashes
прошлых shards и готовых bundles. Повторно прочитанные bytes не увеличивают
уникальный размер набора.

Последняя полная invocation заняла 2731.235 s.
SHA256 throughput — 86.519 MB/s;
OS cache не очищался. Это checksum read, не скорость нового normalization scan.
Warm cache быстрее cold terminal; общий выигрыш terminal над каждым baseline
и статистическая значимость не заявляются.

Полный partition-wide run завершён. Это не перебор всех возможных Query архива.

Исторический full-normalization streaming scan 1/10/50/200 GB уже сохранён
отдельно в `reports/scale/scale_report.json`. В новом исследовании выполняется
SHA256 streaming read каждого data file плюс bounded extraction и profile study;
это не новый full normalization scan всех rainfall records. Старые результаты
не переименовываются в новые и не доказывают реалистичность legacy-v1.

```powershell
uv run python scripts/run_archive_precision_benchmark.py --dry-run
uv run python scripts/run_archive_precision_benchmark.py --resume
uv run python scripts/run_archive_precision_benchmark.py --replay
```

Для независимого повторного запуска выбирайте новый `--output`.
Не запускайте второй writer одновременно с активным run. Resume проверяет source
и uv.lock; после изменения Python-файлов для продолжения нужен сохранённый source
snapshot исходного run, а для нового эксперимента — новый output.
Обычные tests/CI используют только маленький smoke, не автоматические 200 GB.
Protocol: `configs/experiments/precision-archive-200gb-v1.json`; входы, все четыре
профиля, LP grids и refinements сохранены в отдельных ZIP bundles в
`experiments/runs/precision-archive-200gb-v1/`. Budget process+workers 16 GiB,
один worker, report disk budget 1 GiB. Архив целиком в RAM не помещается.
Gate B остаётся pending, приоритет unestablished.


# Реальные данные без искусственного урезания: запрос за полчаса

Дата 2026-10-19. Статус: **complete**. Это дополнительная posthoc development
диагностика после основного real study, не новый независимо размеченный holdout.

Во всех 72 исходных point/cycles сохранены **все 12 оригинальных hourly observations**
этого места/member/cycle. Хеши observations до и после совпадают. Не удалено ни
одного значения, не внесён metadata shift, не выполняется укрупнение. Меняется
только Query: первые 30 минут при требовании точного ответа eps=0.
Метаданные документированы; H содержит одну условно известную interpretation.

Из часовой суммы не определяется её получасовая раскладка:

- **31/72** случаев имеют неточный ответ; доступные refetch amounts за
  целые 1/4/6/12 часов не устраняют эту неопределённость;
- **41/72** уже дают точный ответ в модели encoded amounts;
- при допуске eps=0.05 mm недостаточно узки bounds только в **8/72**
  случаях. Остальные положительные ширины малы; строгую неточность eps=0 нельзя
  выдавать за крупную практическую ошибку.

Проверены **288 all-noise profile bundles**, независимый paired LP на
трёх eta и Query LP; численная tolerance 1e-7. Отдельный replay проверил профили
и 72 Query certificates без solver/LP. Различий exact/numerical decision flags:
0. Сам профиль проверяется для всех finite eta.

Нужны более детальные наблюдения именно этой SeriesKey. Получасовой продукт
в выбранном архиве не представлен. Дополнительная станция, forecast cycle или
вопрос о уже известных метаданных не дают права делить часовые amounts пополам.
Истинное количество за полчаса здесь неизвестно: ошибка относительно него
не измеряется и не выдумывается. Проверяются корректность bounds и допустимость
двух различающихся рядов относительно исходной информации.

Иллюстрация с максимальной шириной: Singapore, месяц 7.
В первый час зарегистрировано примерно 2.128601 mm LSP.
Для первого получаса допустимы и 0, и 2.128601 mm.
Деление на два добавило бы предположение о равномерности. Этот пример выбран
для показа после анализа; в эксперименте сохранены все 72 случая.

Источник native значений — завершённый `precision-real-era5-v1`, SHA256
`b6be175abc19ac6d005264907e67cc166d0e4cb20fffb74f5776967e5c2bf32c`; данные уже проверены по оригинальным source hashes.
Новый protocol: `configs/experiments/precision-real-native-resolution-v1.json`;
bundles: `experiments/runs/precision-real-native-resolution-v1/`.
Wall time 16.889 s, peak sampled process-tree RSS
145,743,872 bytes, budget 1 GiB.

```powershell
uv run python scripts/run_native_resolution_experiment.py --output experiments/runs/precision-real-native-resolution-reproduction
uv run meteo solve --case defense/examples/native_resolution_case.json --output outputs/defense-native
uv run meteo verify --result outputs/defense-native/result.json --certificate outputs/defense-native/certificate.json
```

Для повторного experiment run выбирайте новый output; готовая
папка не перезаписывается. Команды solve/verify показывают сохранённый пример.
Это прямой пример применимости к настоящим native hourly данным с недостаточной
детализацией. Он не является первым открытием этой общей проблемы, доказательством
новизны, физической точности реанализа или независимым Gate B.
