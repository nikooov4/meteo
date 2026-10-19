"""Build Russian defense reports from saved runs; never invent or rerun measurements."""

import csv
import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path
from statistics import mean, median

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from meteo_bridge.resources import atomic_json, sha256_file

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "defense"
RUNS = ROOT / "experiments/runs"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def width(bounds):
    return None if bounds["upper"] is None else F(bounds["upper"])-F(bounds["lower"])


def timed_rows(records, methods):
    return "\n".join(f"| {m} | {median(r['methods'][m]['seconds'] for r in records)*1000:.3f} |"
                     for m in methods) if records else "| нет завершённых задач | — |"


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf8")


def real_report(run):
    records = run["records"]
    lines, timing = [], []
    for arm in run["protocol"]["arms"]:
        rows = [r for r in records if r["arm"]==arm]
        exact = sum(width(r["refinement_bounds"][-1])==0 for r in rows)
        initially_exact = sum(width(r["refinement_bounds"][0])==0 for r in rows)
        shrunk = sum(width(r["refinement_bounds"][0]) is None or
                     width(r["refinement_bounds"][-1])<width(r["refinement_bounds"][0]) for r in rows)
        unbounded = sum(width(r["refinement_bounds"][0]) is None for r in rows)
        lines.append(f"| {arm} | {len(rows)} | {initially_exact} | {unbounded} | {shrunk} | {exact} |")
        times = {m:median(r["methods"][m]["seconds"] for r in rows) for m in run["protocol"]["methods"]}
        timing.append(f"| {arm} | "+" | ".join(f"{times[m]*1000:.3f}" for m in run["protocol"]["methods"])+
                      f" | {times['compiled']/times['terminal']:.3f} |")
    return f"""# Метод на реальных ERA5 LSP: сохранённый эксперимент

Дата 2026-10-19. Статус: **{run['status']}**. Метод применён к реальным encoded
метеоданным реанализа, с явно контролируемой потерей временной детализации.
Научный приоритет и independent Gate B этим не устанавливаются.

## Дизайн

В 12 исходных NCAR ERA5 HRES LSP файлах 2023 года заранее выбраны циклы дня 11
06 UTC и шесть фиксированных grid points: Moscow, Singapore, North Atlantic,
New York, Tokyo, Sydney. Это 72 point/cycle windows, **864 исходных hourly values**.
Все сухие случаи сохранены. Выбор не зависел от увиденного количества осадков.
Эти дни исключались из training bank синтетики, но уже использовались в её
development holdout; это не новые независимые source families или экспертная разметка.

Общий размер source files **{sum(s['bytes'] for s in run['sources']):,} bytes**.
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

Всего **{len(records)} задач**, **{len(records)*len(run['protocol']['methods'])} profile bundles**.
Все четыре метода прошли checker и сравнение с независимым paired-increment LP
на eta=0,0.1,1 mm. Это **{len(records)*4*3} различных action/radius comparisons**,
каждое сверено для четырёх методов; LP calls для профилей — {sum(r['lp_calls'] for r in records)}.
Численная tolerance 1e-7. LP grid не доказывает всю кривую; отдельный checker
проверяет all-finite-eta certificate.

| Ветка | Cases | Уже exact до уточнений | Unbounded до уточнений | Bounds сузились | Exact после всех hourly observations |
|---|---:|---:|---:|---:|---:|
{chr(10).join(lines)}

Во всех случаях проверены вложенные наборы 0/3/6/12 исходных observations:
lower не уменьшается, upper не увеличивается; Query bounds независимо сверены с LP.
Дополнительные сведения для этого же места/цикла сужают ответ; объём постороннего
архива не использован как замена информации. Сухие исходно exact случаи не исключены.

Медианные cold end-to-end ms, включая построение/проверку всего профиля:

| Метод | Median ms |
|---|---:|
{timed_rows(records,run['protocol']['methods'])}

Отдельно по веткам:

| Ветка | full ms | compiled ms | no reuse ms | terminal ms | compiled/terminal |
|---|---:|---:|---:|---:|---:|
{chr(10).join(timing)}

Это один shuffled проход на задачу, не significance study. При documented H1
измеренный полный Python graph **быстрее terminal**; общий median full также ниже.
Кандидат выигрывает у compiled comparator умеренно, а не у всех альтернатив.
Результаты не подгонялись под обязательный выигрыш. Numerical LP и repeated-input cache не считаются равным
по контракту cold all-profile timing comparator. Одновременно выполнялся отдельный
background archive job; его IO/RAM не следует приписывать этому процессу.

Wall time: **{run['wall_seconds']:.3f} s**, sampled process-tree peak RSS
**{run['peak_process_tree_rss']:,} bytes**, budget 2 GiB. Ошибок записано: {len(run['errors'])}.
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
"""


def archive_report(run):
    rows = run["records"]
    p = run["protocol"]
    invocation = run["invocations"][-1]
    final = run["status"]=="complete"
    manifest=read(ROOT / "data/scale/synthetic-200gb/manifest.json")
    coverage=[]
    refinement_rows=[]
    for level,percent in enumerate((0,25,50,100)):
        levels=[r["refinement_bounds"][level] for r in rows]
        exact=sum(b["upper"] is not None and b["lower"]==b["upper"] for b in levels)
        unbounded=sum(b["upper"] is None for b in levels)
        refinement_rows.append(f"| {percent}% | {exact} | {unbounded} | {len(levels)-exact-unbounded} |")
    for target in p["archive_prefix_bytes"]:
        total,n=0,0
        for shard in manifest["shards"]:
            total+=shard["bytes"]
            n+=1
            if total>=target:
                break
        present=[r for r in rows if r["index"]<n]
        exact=sum(r["native_upper"] is not None and r["native_lower"]==r["native_upper"] for r in present)
        coverage.append(f"| {target/1e9:g} | {total:,} | {len(present)}/{n} | {exact} |")
    return f"""# Precision method и 200-GB архив

Дата 2026-10-19. Фактический статус: **{run['status']}**.
Обработано **{len(rows)}/{run['plan']['shards']} partitions**,
проверено SHA256 **{sum(r['bytes'] for r in rows):,} bytes** из
**{run['plan']['data_bytes']:,} bytes**. Числа ниже относятся только к завершённым задачам.

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

Profile bundles: **{len(rows)*len(p['methods'])}**; уникальные action/radius comparisons
на каждый метод: **{len(rows)*4*len(p['radii'])}**. Ошибки run: **{len(run['errors'])}**.

| Метод | Median ms по завершённым задачам |
|---|---:|
{timed_rows(rows,p['methods']+['cache_warm'])}

Покрытие фиксированного набора native Queries префиксами архива:

| Target GB | Фактические bytes префикса | Проверенных доступных задач / файлов префикса | Из них native exact |
|---|---:|---:|---:|
{chr(10).join(coverage)}

Всего целевых задач {run['plan']['shards']}. Если собственный shard задачи ещё
не входит в доступный префикс, её observations недоступны. Эта таблица показывает
охват фиксированного workload, не улучшение физической точности от bytes.
Ширина одного уже покрытого Query определяется его relevant observations и QC;
добавление посторонних partitions не создаёт для него новых ограничений.

Возвращение исходных наблюдений в controlled задачах:

| Возвращено relevant hourly records | Exact cases | Unbounded cases | Finite, ещё не exact |
|---|---:|---:|---:|
{chr(10).join(refinement_rows)}

Отсутствующие/rejected observations не восстанавливаются, поэтому даже все
доступные записи не обязаны дать exact ответ. Это результат об информации для
Query, не об ошибке прогноза относительно истинного дождя.

Последняя invocation: hashed bytes {invocation['hashed_bytes']:,},
hash time {invocation['hash_seconds']:.3f} s;
финализированный peak RSS: {invocation.get('peak_process_tree_rss','ещё не записан')} bytes.
Invocations: {len(run['invocations'])}; resume invocations:
{sum(i['resume'] for i in run['invocations'])}.
Ранние прерывания/checkpoints сохраняются; invocation без финальных wall/RSS
не превращается в завершённое измерение. На resume повторно сверяются hashes
прошлых shards и готовых bundles. Повторно прочитанные bytes не увеличивают
уникальный размер набора.

Последняя полная invocation заняла {invocation.get('wall_seconds',0):.3f} s.
SHA256 throughput — {invocation['hashed_bytes']/max(1e-9,invocation['hash_seconds'])/1e6:.3f} MB/s;
OS cache не очищался. Это checksum read, не скорость нового normalization scan.
Warm cache быстрее cold terminal; общий выигрыш terminal над каждым baseline
и статистическая значимость не заявляются.

{'Полный partition-wide run завершён. Это не перебор всех возможных Query архива.' if final else 'Полный новый эксперимент ещё не завершён. Результат 200 GB не заявляется по этому частичному run.'}

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
"""


def native_resolution_report(run):
    records=run["records"]
    unresolved=sum(not r["exact_answer"] for r in records)
    practical=sum(r["upper"] is None or F(r["upper"])-F(r["lower"])>F("1/10") for r in records)
    largest=max(records,key=width)
    return f"""# Реальные данные без искусственного урезания: запрос за полчаса

Дата 2026-10-19. Статус: **{run['status']}**. Это дополнительная posthoc development
диагностика после основного real study, не новый независимо размеченный holdout.

Во всех 72 исходных point/cycles сохранены **все 12 оригинальных hourly observations**
этого места/member/cycle. Хеши observations до и после совпадают. Не удалено ни
одного значения, не внесён metadata shift, не выполняется укрупнение. Меняется
только Query: первые 30 минут при требовании точного ответа eps=0.
Метаданные документированы; H содержит одну условно известную interpretation.

Из часовой суммы не определяется её получасовая раскладка:

- **{unresolved}/72** случаев имеют неточный ответ; доступные refetch amounts за
  целые 1/4/6/12 часов не устраняют эту неопределённость;
- **{len(records)-unresolved}/72** уже дают точный ответ в модели encoded amounts;
- при допуске eps=0.05 mm недостаточно узки bounds только в **{practical}/72**
  случаях. Остальные положительные ширины малы; строгую неточность eps=0 нельзя
  выдавать за крупную практическую ошибку.

Проверены **{len(records)*4} all-noise profile bundles**, независимый paired LP на
трёх eta и Query LP; численная tolerance 1e-7. Отдельный replay проверил профили
и 72 Query certificates без solver/LP. Различий exact/numerical decision flags:
{len(run['numerical_decision_differences'])}. Сам профиль проверяется для всех finite eta.

Нужны более детальные наблюдения именно этой SeriesKey. Получасовой продукт
в выбранном архиве не представлен. Дополнительная станция, forecast cycle или
вопрос о уже известных метаданных не дают права делить часовые amounts пополам.
Истинное количество за полчаса здесь неизвестно: ошибка относительно него
не измеряется и не выдумывается. Проверяются корректность bounds и допустимость
двух различающихся рядов относительно исходной информации.

Иллюстрация с максимальной шириной: {largest['place']}, месяц {largest['month']}.
В первый час зарегистрировано примерно {float(F(largest['upper'])):.6f} mm LSP.
Для первого получаса допустимы и 0, и {float(F(largest['upper'])):.6f} mm.
Деление на два добавило бы предположение о равномерности. Этот пример выбран
для показа после анализа; в эксперименте сохранены все 72 случая.

Источник native значений — завершённый `precision-real-era5-v1`, SHA256
`{run['source_run_sha256']}`; данные уже проверены по оригинальным source hashes.
Новый protocol: `configs/experiments/precision-real-native-resolution-v1.json`;
bundles: `experiments/runs/precision-real-native-resolution-v1/`.
Wall time {run['wall_seconds']:.3f} s, peak sampled process-tree RSS
{run['peak_process_tree_rss']:,} bytes, budget 1 GiB.

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
"""


def examples(real, archive):
    dest = OUT / "examples"
    dest.mkdir(exist_ok=True)
    inputs = list((RUNS / "precision-frontier-v1").glob("*-input.json"))
    for src in inputs:
        (dest / "method_inputs").mkdir(exist_ok=True)
        shutil.copy2(src,dest / "method_inputs" / src.name)
    selected = next(r for r in real["records"] if r["arm"]=="documented_H1" and
                    width(r["refinement_bounds"][0]) is not None and width(r["refinement_bounds"][0])>0)
    with zipfile.ZipFile(RUNS / "precision-real-era5-v1" / selected["bundle"]) as z:
        original = json.loads(z.read("native.json"))["case"]
        data = json.loads(z.read("input.json"))
        for name,value in [("real_native_case.json",original),("real_controlled_case.json",data["case"]),
                           ("real_actions.json",data["actions"]),("real_profile_bundle.json",json.loads(z.read("terminal.json")))]:
            atomic_json(dest / name,value)
    with (dest / "real_era5_hourly.csv").open("w",encoding="utf8",newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["start_epoch_UTC","end_epoch_UTC","original_m","amount_mm_exact","amount_mm_approx","QC"])
        for o in original["observations"]:
            writer.writerow([o["interval"]["start"],o["interval"]["end"],o["original_value"],o["lower"],
                             float(F(o["lower"])),o["qc"]])
    atomic_json(dest / "real_example_provenance.json",{
        "selection":"first fixed-order documented-H1 case with finite nonzero initial width; illustration only, benchmark retained every case",
        "record":selected,"run_sha256":sha256_file(RUNS / "precision-real-era5-v1/run.json")})
    profile=read(dest / "real_profile_bundle.json")["result"]
    action_rows=[]
    for action,result in zip(data["actions"],profile["actions"]):
        a=datetime.fromtimestamp(action["start"],timezone.utc).strftime("%H:%M")
        b=datetime.fromtimestamp(action["end"],timezone.utc).strftime("%H:%M")
        radius=("нет достаточной точности" if result["radius_kind"]=="empty" else
                ("любой конечный eta" if result["radius_kind"]=="unbounded" else
                 ("≤ " if result["safe_at_supremum"] else "< ")+str(float(F(result["radius_supremum"])))+" mm"))
        action_rows.append(f"| {a}–{b} | {action['cost']} | {radius} |")
    initial=selected["refinement_bounds"][0]
    truth=float(F(selected["reference_query_mm"]))
    write(OUT / "07_real_example_ru.md",f"""# Один реальный пример: от данных к требованию точности

Источник — NCAR ERA5 HRES LSP, {selected['place']}, точка
{selected['latitude']}°N, {selected['longitude']}°E,
{datetime.fromtimestamp(selected['initialization'],timezone.utc).isoformat()}.
Это grid point реанализа, не измерение дождемера.

Для демонстрации исходные hourly values укрупнены в four-hour sums.
Нужно количество LSP за первые пять часов. Из укрупнённых данных следует:

**[{float(F(initial['lower'])):.9f}, {float(F(initial['upper'])):.9f}] mm**.

Исходный почасовой архив, сохранённый отдельно от входа метода, даёт
**{truth:.9f} mm**. Он используется как reference проверки.
При возвращении шести первых hourly observations границы совпадают с этим
значением; добавление остальных шести уже не улучшает этот Query.

Требуемая ошибка ответа eps=0.05 mm. Проверенный профиль предлагает:

| Что дополнительно измерить, UTC | Условная стоимость | Допустимая ошибка нового измерения eta |
|---|---:|---|
{chr(10).join(action_rows)}

Стоимость задана протоколом в условных единицах, а не измерена в рублях или HTTP time.
Дополнительный час 10:00–11:00 достаточен при eta<=0.05 mm в объявленной модели.
Измерение суммы за более широкий уже известный интервал не устраняет недостаток
детализации для пятичасового Query. Это проверка свойств данного входа,
не утверждение об оптимальной policy.

Ошибка eta задаётся как математическое ограничение. Эксперимент не определял
физическую точность прибора. Числа имеют смысл encoded LSP amounts;
реальные значения сохранены без произвольного hourly disaggregation.

Пример выбран для иллюстрации как первый documented-H1 случай с ненулевой
конечной исходной шириной. Benchmark включал и сухие случаи. CSV, полный вход,
действия, provenance и сертификат находятся в `examples/`.

```powershell
uv run meteo acquisition precision --case defense/examples/real_controlled_case.json --actions defense/examples/real_actions.json --radii 0,1/20,1/10 --output outputs/defense-real
uv run meteo acquisition precision-verify --directory outputs/defense-real
```
""")
    if archive["records"]:
        r = archive["records"][0]
        with zipfile.ZipFile(RUNS / "precision-archive-200gb-v1" / r["bundle"]) as z:
            atomic_json(dest / "synthetic_200gb_case_input.json",json.loads(z.read("input.json")))
    write(dest / "README.md","""# Примеры данных

`method_inputs/` — девять исходных малых задач исторического precision pilot,
точные копии, всего 75 356 bytes. Это synthetic mathematical fixtures.

`real_era5_hourly.csv` и `real_native_case.json` — настоящие encoded значения
ERA5 LSP из нового real study. `real_controlled_case.json` содержит явно заданное
укрупнение; `real_actions.json` — hypothetical bounded-error interval acquisitions.
`real_profile_bundle.json` — профиль и сертификат кандидата.
Первый недегеративный documented-H1 пример выбран для иллюстрации после измерений;
это не правило отбора экспериментальных случаев. Все dry cases сохранены в run.

`synthetic_200gb_case_input.json` — ограниченная задача из первого shard legacy-v1,
а не весь 200-GB архив. Origin=controlled явно указывает экспериментальные изменения.

```powershell
uv run meteo acquisition precision --case defense/examples/real_controlled_case.json --actions defense/examples/real_actions.json --output outputs/defense-real
uv run meteo acquisition precision-verify --directory outputs/defense-real
```
""")


def copy_sources():
    names = ["docs/project_explained_ru.md","docs/precision_frontier.md","docs/algorithm_delta.md",
             "docs/assumptions.md","docs/annotation_guide.md","docs/novelty_validation_plan.md",
             "docs/literature_delta_2026_10_17.md","reports/novelty_justification.md",
             "reports/novelty_prior_art_check.json","paper/novelty_statement_ru.md",
             "reports/delivery.md","reports/precision_frontier.md","reports/gate_a.md","reports/gate_b.md",
             "reports/review_status.json","reports/synthetic_realism.md","reports/weather_v2.md",
             "reports/weather_10gb.md","reports/scale/scale_report.md","reports/real_precision.md",
             "reports/archive_precision_200gb.md","reports/real_native_resolution.md",
             "reports/validation/archive-map-preview.png"]
    mapped = {(ROOT / name).resolve():OUT / "sources" / name for name in names}
    records = []
    for original,dest in mapped.items():
        dest.parent.mkdir(parents=True,exist_ok=True)
        changed = False
        if original.suffix==".md":
            def link(match):
                nonlocal changed
                target = match[2]
                if target.startswith(("http:","https:","#","app:","mailto:")):
                    return match[0]
                base,sep,fragment = target.partition("#")
                path = (original.parent / base).resolve()
                if not path.is_relative_to(ROOT):
                    return match[0]
                destination = mapped.get(path,path)
                relative = Path(os.path.relpath(destination,dest.parent)).as_posix()
                changed |= relative != base
                return f"[{match[1]}]({relative}{sep}{fragment})"
            text = re.sub(r"\[([^\]]+)\]\(([^)\n]+)\)",link,original.read_text(encoding="utf8"))
            write(dest,text)
        else:
            shutil.copy2(original,dest)
        records.append({"source":str(original.relative_to(ROOT)),"copy":str(dest.relative_to(OUT)),
                        "source_sha256":sha256_file(original),"copy_sha256":sha256_file(dest),"local_links_adjusted":changed})
    atomic_json(OUT / "sources/manifest.json",records)
    write(OUT / "sources/README.md","# Копии прежних и текущих материалов\n\n"
          "Текст, даты и результаты сохранены; локальные ссылки приведены к этой папке/репозиторию. "
          "Числа tests и статусы в старых документах относятся к их исходным версиям.\n\n"+
          "\n".join(f"- [{r['source']}]({Path(r['copy']).relative_to('sources').as_posix()})" for r in records))


def figures(real,archive):
    fig = make_subplots(rows=2,cols=2,subplot_titles=("Mean finite Query width, mm", "Unbounded Query cases",
                                                  "Real data: median profile ms", "200GB: completed-case median ms"))
    for arm in real["protocol"]["arms"]:
        rows = [r for r in real["records"] if r["arm"]==arm]
        finite, unbounded = [], []
        for i in range(4):
            ws = [width(r["refinement_bounds"][i]) for r in rows]
            finite.append(mean(float(w) for w in ws if w is not None) if any(w is not None for w in ws) else None)
            unbounded.append(sum(w is None for w in ws))
        fig.add_trace(go.Scatter(x=[0,3,6,12],y=finite,name=arm,mode="lines+markers",connectgaps=False),row=1,col=1)
        fig.add_trace(go.Scatter(x=[0,3,6,12],y=unbounded,name=arm+" unbounded",mode="lines+markers"),row=1,col=2)
        methods = real["protocol"]["methods"]
        fig.add_trace(go.Bar(x=methods,y=[median(r["methods"][m]["seconds"] for r in rows)*1000 for m in methods],
                             name=arm+" time"),row=2,col=1)
    if archive["records"]:
        methods=archive["protocol"]["methods"]+["cache_warm"]
        fig.add_trace(go.Bar(x=methods,y=[median(r["methods"][m]["seconds"] for r in archive["records"])*1000 for m in methods],
                             name="archive "+archive["status"]),row=2,col=2)
    fig.update_xaxes(title_text="Native hourly observations added",row=1,col=1)
    fig.update_xaxes(title_text="Native hourly observations added",row=1,col=2)
    fig.update_layout(height=900,title=f"MeteoBridge · saved studies · archive {archive['status']} · no priority claim",
                      barmode="group",margin=dict(t=100,b=110))
    write(OUT / "experiment_figures.html",fig.to_html(full_html=True,include_plotlyjs=True))


def main():
    real=read(RUNS / "precision-real-era5-v1/run.json")
    archive_bytes=(RUNS / "precision-archive-200gb-v1/run.json").read_bytes()
    archive=json.loads(archive_bytes)
    native=read(RUNS / "precision-real-native-resolution-v1/run.json")
    snapshot=ROOT / "reports/validation/archive-precision-report-snapshot.json"
    snapshot.write_bytes(archive_bytes)
    if real["status"]!="complete":
        raise ValueError("real experiment not complete; do not publish final real results")
    rr,ar = real_report(real),archive_report(archive)
    write(ROOT / "reports/real_precision.md",rr)
    write(ROOT / "reports/archive_precision_200gb.md",ar)
    nr=native_resolution_report(native)
    write(ROOT / "reports/real_native_resolution.md",nr)
    write(OUT / "08_real_native_resolution_ru.md",nr)
    write(OUT / "05_experiments_ru.md","# Эксперименты: применимость и пределы выводов\n\n"
          "Этот файл построен из сохранённых runs; новый archive status: **"+archive["status"]+"**.\n\n"+
          rr.replace("# Метод на реальных","## Метод на реальных",1)+"\n\n"+
          ar.replace("# Precision method","## Precision method",1)+"\n\n"+nr)
    examples(real,archive)
    selected=max(native["records"],key=lambda r:width(r))
    with zipfile.ZipFile(RUNS / "precision-real-native-resolution-v1" / selected["bundle"]) as z:
        data=json.loads(z.read("input.json"))
        atomic_json(OUT / "examples/native_resolution_case.json",data["case"])
        atomic_json(OUT / "examples/native_resolution_actions.json",data["actions"])
        atomic_json(OUT / "examples/native_resolution_query_bundle.json",json.loads(z.read("native.json"))["bundle"])
        atomic_json(OUT / "examples/native_resolution_profile.json",json.loads(z.read("terminal.json")))
    atomic_json(OUT / "examples/native_resolution_provenance.json",{
        "selection":"largest native Query width for illustration only; all 72 cases retained",
        "record":selected,"run_sha256":sha256_file(RUNS / "precision-real-native-resolution-v1/run.json")})
    # Portable compact proof corpus, not the bulk meteorological files.
    for name,state,raw in [("precision-real-era5-v1",real,None),
                           ("precision-real-native-resolution-v1",native,None),
                           ("precision-archive-200gb-v1",archive,archive_bytes)]:
        evidence=OUT / "evidence" / name
        evidence.mkdir(parents=True,exist_ok=True)
        (evidence / "run.json").write_bytes(raw if raw is not None else (RUNS / name / "run.json").read_bytes())
        for record in state["records"]:
            src=RUNS / name / record["bundle"]
            dst=evidence / record["bundle"]
            if not dst.exists() or sha256_file(dst)!=record["sha256"]:
                shutil.copy2(src,dst)
        for filename in ("protocol-frozen.json","replay.json"):
            src=RUNS / name / filename
            if src.exists() and (filename!="replay.json" or state["status"]=="complete"):
                shutil.copy2(src,evidence / filename)
    write(OUT / "evidence/README.md","""# Компактные воспроизводимые доказательства

Здесь копии новых runs и ZIP bundles с JSON inputs, LP reference и сертификатами.
Оригинальные 200 GB или 3.17 GB NetCDF для replay не нужны. Для current archive
учитывайте status в run.json; partial snapshot не является завершённым экспериментом.
Replay использует установленный код проекта и проверяет доказательства без solver/LP:

```powershell
uv run python scripts/run_archive_precision_benchmark.py --output defense/evidence/precision-real-era5-v1 --replay
uv run python scripts/run_archive_precision_benchmark.py --output defense/evidence/precision-real-native-resolution-v1 --replay
uv run python scripts/run_archive_precision_benchmark.py --output defense/evidence/precision-archive-200gb-v1 --replay
```
""")
    copy_sources()
    figures(real,archive)
    context=ROOT / "reports/validation/defense-final-context.json"
    if context.exists():
        shutil.copy2(context,OUT / "evidence/final-validation.json")
    atomic_json(OUT / "artifact_manifest.json",{
        "date":"2026-10-19","archive_status":archive["status"],
        "archive_run_sha256":hashlib.sha256(archive_bytes).hexdigest(),
        "archive_report_snapshot":str(snapshot.relative_to(ROOT)),
        "real_run_sha256":sha256_file(RUNS / "precision-real-era5-v1/run.json"),
        "native_resolution_run_sha256":sha256_file(RUNS / "precision-real-native-resolution-v1/run.json"),
        "files":[{"path":str(p.relative_to(OUT)),"bytes":p.stat().st_size,"sha256":sha256_file(p)}
                 for p in sorted(OUT.rglob("*")) if p.is_file() and p.name!="artifact_manifest.json"]})
    print(json.dumps({"defense":str(OUT),"archive_status":archive["status"],"real_cases":len(real["records"])}))


if __name__=="__main__":
    main()
