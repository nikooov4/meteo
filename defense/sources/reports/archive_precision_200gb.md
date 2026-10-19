# Precision method и 200-GB архив

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
