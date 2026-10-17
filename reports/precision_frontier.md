# Проверяемый профиль точности: исследовательский результат

2026-10-17. **Реализован кандидат на узкий методический вклад; научный приоритет
не установлен.** Нет независимого проверяющего (ответ пользователя); внешняя
проверка и Gate B остаются pending. GitHub, тесты и ускорение не доказывают новизну.

Подробное объяснение проекта с нуля: [project_explained_ru.md](../docs/project_explained_ru.md).
Математическая постановка и вывод: [precision_frontier.md](../docs/precision_frontier.md).
Ближайшие прочитанные работы и пересечения: [literature delta](../docs/literature_delta_2026_10_17.md).

## Что добавлено

Для одного будущего interval amount с ошибкой |y-m|<=eta вычисляется ВЕСЬ профиль
максимальной остающейся неопределённости Query при любом ответе, для всех конечных
eta>=0. Никакого распределения ошибки и скрытых ответов simulator не используется.
Два допустимых ряда могут дать один ответ тогда и только тогда, когда разность
их измеряемых сумм не больше 2*eta. H остаётся конечным, ряды внутри H непрерывны.

Для ordered h-пары профиль — минимум не больше трёх affine bounds на области её
активации либо unbounded. Global maximum может иметь скачки при активации пары.
Итоговая допустимая точность содержит признак включения верхней границы. В ручном
примере безопасно eta<1, а eta=1 уже не подходит; в daily-complement примере
W_eta=min(12,2*eta), eps=1/2 требует eta<=1/2 с включённой границей.

Сертификат содержит исходные пути, исключающие циклы, достигающие полные ряды в
концах кусков и affine/recession directions. Отдельный checker проверяет весь
континуум через linear interpolation/rays, не вызывает shortest-path search и
SciPy. Точность доказательства условна относительно H, модели ошибок и conventions.
Это не доказательство полноты H, физической точности прибора или новой общей
теории parametric shortest paths/optimal recovery. Ограничение «<=3» не объявлено tight.

## Замороженный вычислительный пилот

Seed 20261017; три заранее заданных режима, три повтора, четыре
метода, перемешанный порядок. Замер cold end-to-end включает preprocessing,
построение полного сертификата и его проверку; исключает общий native startup и
запись файлов. Режимы и go/no-go не менялись после измерений.

`full` — полный pair graph с Fraction Bellman–Ford; `compiled` — такой же полный
граф со SciPy Johnson и обязательной точной проверкой предложенных путей/fallback;
`terminal` — shared per-world paths и не больше семи value-вершин пары;
`terminal_no_reuse` — та же projection с повторным расчётом путей для каждого action.
Все четыре метода возвращают одинаковый all-parameter proof contract.

| segments/H/actions | full, s | compiled, s | no reuse, s | terminal, s | compiled/terminal | no reuse/terminal |
|---|---:|---:|---:|---:|---:|---:|
| 12/2/6 | 0.111449 | 0.109945 | 0.093184 | 0.089062 | 1.234 | 1.046 |
| 24/3/10 | 0.794658 | 0.772152 | 0.475230 | 0.412666 | 1.871 | 1.152 |
| 48/3/14 | 1.988016 | 1.939678 | 1.016548 | 0.853069 | 2.274 | 1.192 |

Все **36** bundles прошли checker; в них **2880** ordered pair
profiles. Все **2160** action/radius comparisons согласовались с независимым
paired-increment LP (numerical tolerance 1e-7). LP проверяет конечную сетку из шести
eta, не доказывает всю кривую и не является equal-contract comparator её времени
построения. Сохранены входы, LP results, bundles, ошибки, версии и source ZIP.

Peak sampled process-tree RSS: **98377728 bytes**
(93.82 MiB); sampling 50 ms, OS cache исключён.
Budget 1 GiB. Fallback compiled->exact в измеренном пилоте: 0; отдельно
тестируется намеренно неверный floating proposal и правильный exact fallback.
Ошибок пилота: 0. Предзаданный go criterion выполнен:
true. Это development evidence; три повтора
не устанавливают статистическую значимость, general speed law или научный приоритет.

## Проверка и совместимость

Полный завершающий набор: **147 tests**, failures/errors **0**;
[XML](validation/precision-final.xml). История первоначальных запусков сохраняется
в validation, включая обнаруженный регрессионный сбой. Все 36
сохранённых bundles повторно проверены без search/LP: [replay](validation/precision-replay.json).
Внешний HTTP client получил новый профиль и локально проверил сертификат;
временный loopback server остановлен: [context](validation/precision-http/context.json).

Diagnostics: **33** cases, errors 0,
включая два ручных, 27 ранее существовавших original/controlled DWD/NCAR и четыре
controlled missing-record производных. Эти производные сохраняют исходные family_id;
не считаются новыми независимыми семействами. Eta у реальных excerpts — гипотетическая
граница coarsening, не измеренная calibration. Native DWD сохраняет incomplete_model.
Действия не объявляются реально доступными без проверки conventions/availability.

## Что относится к новизне

Кандидат на проверяемое отличие: batch calculation всего bounded-error precision
frontier для одного interval view над конечным объединением temporal models,
включая pair activation, строгую/нестрогую границу eta и независимо проверяемое
all-parameter доказательство. Старые STN projection, flow duality, optimal recovery
с observation errors и parametric shortest paths признаются prior art.

Получен работающий инструмент и воспроизводимое вычислительное свидетельство
пользы terminal reuse против compiled full graph. Ещё НЕ получены: доказательство
приоритета этой специализации, внешняя проверка вывода, независимый held-out real
study, новая complexity или новая continuous policy. If closest prior art already
contains this construction, method novelty must be rejected, without changing runs.

Пакет будущему проверяющему: [review](../review/README.md), proof checklist и четыре
blind development-family packets без наших H/предсказаний; annotations=0,
reviewer=UNASSIGNED. Это подготовка проверки, не сама проверка и не held-out Gate B.
Публикационный статус: manuscript/research prototype, принятие статьи не заявляется.

## Gate A / Gate B / масштаб

Старый [Gate A](gate_a.md) сохранён: H1 213/213 agreement, H2 fixtures, H3 negative,
H4 только шесть finite tasks. Новый oracle pilot не переименован в подтверждение
старого H3; policies с этим noisy oracle не сравнивались. Gate B **pending**:
независимой разметки/новых withheld families нет. Никому ничего не отправлялось.

Предыдущий synthetic full streaming scan 200040947956 bytes сохранён отдельно
в [delivery](delivery.md). Этот запуск не повторял 200-GB эксперимент и не проверял
новый oracle на всём архиве. Oracle ограничен Case: 128 endpoints, 16 H, 128 actions,
4096 action*ordered-pairs. Реальный 200-GB download/scan по-прежнему **not_run**.
Noisy threshold profiles, несколько новых измерений и коррелированные ошибки
не поддерживаются новым расширением; базовый exact threshold остаётся отдельным.

## Команды (из корня)

```powershell
uv sync --frozen
uv run python scripts/verify_precision_run.py
uv run meteo acquisition precision --case experiments/runs/precision-diagnostics-v1/daily/case.json --actions experiments/runs/precision-diagnostics-v1/daily/actions.json --radii "0,1/2,1,6" --output outputs/precision
uv run meteo acquisition precision-verify --directory outputs/precision
uv run python scripts/check_acquisition_http.py --precision
uv run pytest -q -p no:cacheprovider --basetemp=.meteo/pytest-local
uv run ruff check .
uv run streamlit run ui/app.py --server.address 127.0.0.1
# Новый повтор пилота всегда в ДРУГОЙ каталог; сохранённый не перезаписывать:
uv run meteo acquisition precision-pilot --config configs/experiments/precision-frontier-v1.json --output experiments/runs/precision-frontier-replication
```

Для повторных CPU runs установите OPENBLAS_NUM_THREADS=1 и OMP_NUM_THREADS=1;
после uv sync локальное выполнение offline. Проверка отчёта из сохранённых runs:
`uv run python scripts/report_precision_research.py`.

Run SHA256: `0142d76e2537c379552b48a9bb43b83df7a66eb895e6b28cef9f2b7733c28fd9`.
Protocol SHA256: `11688c5dcf78d72ee27dbe70a2519d9c08cdcd41e214cf20e72221b8903cc506`.
Измеренный source SHA256: `add3d4ed4066ae5a40025864c74f77e31264d64425f45271a42aa19dda010191`.
Source ZIP/versions и отдельный текущий validation snapshot перечислены в
[validation context](validation/precision-final-context.json). Добавление documentation,
report/review helpers после timings не подменяет сохранённый source измеренного пилота.
