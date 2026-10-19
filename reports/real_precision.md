# Метод на реальных ERA5 LSP: сохранённый эксперимент

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
