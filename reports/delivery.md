# Итоговый отчёт MeteoBridge v2.1

Инженерный CPU-прототип реализован и проверен на Windows. Научная новизна не установлена; Gate B остаётся pending. Исходная папка была пустой, без Git/AGENTS.md, версии 1 или пользовательского кода. Документы сохранены с hashes в docs/input; пользовательские файлы не удалялись.

## Реализовано

Domain одной физической серии, ручные fixtures, независимый SciPy/HiGHS LP, rational graph solver, enumeration, bounded LRU, shared incremental STN candidate, независимый certificate/witness/ray checker. Demo показывает точный ответ, диапазон, конфликт, unbounded и недостаток наблюдений, не устраняемый метаданными. Полнота H и входные допущения остаются условиями вывода.

Policies сравниваются отдельно от solver: одинаковые public priors/actions/costs/stopping; simulator раскрывает ответ после действия. Есть VOI, VOI2, DRD/EC2 adaptation и tiny exact tree. Общий service используют CLI, Streamlit, FastAPI и внешний client. Чтение partitioned/chunked, graph строится только для ограниченного Query.

## Gate A / Gate B

H1: 213/213 совпадений solver/case с LP; наблюдаемые false certifications 0/12 certified outputs. Это не доказательство общей soundness или полноты H. H2 показана ручными fixtures и относится к известному принципу query-specific inference.

H3 **не подтверждена**. Cold medians, seconds: {'cache': 0.01293439999972179, 'shared': 0.026037600000563543}. Candidate применяет известный incremental STN closure; новая сложность/оптимальность не заявляются.

| Policy | Expected cost, шесть synthetic families |
|---|---|
| fixed | 2.435000 |
| random | 3.333333 |
| entropy | 2.318333 |
| voi | 2.583333 |
| voi2 | 2.068333 |
| drd | 2.193333 |
| witness | 1.953333 |
| optimal | 1.943333 |

H4: преимущество witness на этих шести конечных конструкциях наблюдается, но не устанавливает новый метод или переносимость. Costs — условные единицы finite simulator; continuous DRD/HEC не решена.

Gate B / H5: **pending**. Нет независимой человеческой разметки и held-out проверки на новых схемах. Публикация, принятие статьи, A* и методическая новизна не заявлены. [Gate A](gate_a.md), [Gate B](gate_b.md), [claims](../paper/claims.md), [methods](../paper/methods.md), [results](../paper/results.md).

## Фактический масштаб

Synthetic data: **200040947956 bytes**, 200.040947956 GB / 186.302651 GiB, 476 уникальных shards. Padding, sparse placeholders и копии одного файла не применялись. Full SHA256: **full_verified**.

| Цель GB | Фактические bytes | Scan seconds | MB/s | Peak tree RSS MiB | Query p50 / p95 ms |
|---|---|---|---|---|---|
| 1 | 1278907323 | 21.916 | 58.355 | 189.984 | 13.386 / 18.543 |
| 10 | 10231257624 | 153.192 | 66.787 | 194.215 | 13.203 / 18.748 |
| 50 | 50318700487 | 774.938 | 64.933 | 195.293 | 17.512 / 395.150 |
| 200 | 200040947956 | 3936.506 | 50.817 | 198.332 | 148.562 / 439.900 |

Полный scan 200 GB: **22141808640 строк**. Пакет — 24 invocations: 12 Query first/repeat; checker 24/24, generating truth внутри bounds 24/24; LP 8 invocations для четырёх Query. Scan — IO/нормализация, не solver на всех строках.

Логические precipitation+QC: 199276277760 bytes; все числовые NetCDF arrays с coordinates: 200022563328 bytes; allocated: 200040947956 bytes. Служебные файлы data root: 235188 bytes; остаточные partial: 0 bytes. Исторический peak временного места не измерен.

Генерация: seed 42, NetCDF без компрессии, четыре workers, 32-MiB chunks, бюджет 2 GiB. Последний успешный запуск: 724.562 MiB sampled tree RSS. Forced worker crash и generation resume проверены; scan возобновлён после пользовательской паузы. Пик RSS убитой фазы и полное generation wall time через crash не сохранены. `written_bytes_this_run` учитывает завершённые/adopted shards, а не независимый OS write-counter.

Benchmark budget — 16 GiB на машине с ~32 GiB RAM. RSS sampled каждые 50 ms, включая descendants, исключая OS filesystem cache; это не hard kernel/job limit. Диск: HDD ST1000LM048-2E7172, NTFS. OS cache не сбрасывался; isolated idle-host и настоящий cold-cache SLA не заявлены. Во время resume выполнялись малые validation/HTTP/metadata задачи.

Scan wall time суммирует завершённые shard phases разных invocations; revalidation отражена также в invocation wall time и IO. Source lineage до/после pause сохранена. Application spill = 0. OS IO counters, hashes, normalized digests, ошибки и resume: [scale report](scale/scale_report.json).

Synthetic acceptance: **passed**. Report SHA256: `97a5b0c6a6dbec7c7d6a1fae3ba771348e44f0cae22edbe80fd6e9d432be1896`.

## Реальные источники и интерфейсы

DWD: три станции по 168 строк, raw/subset hashes. mm/hour/UTC проверены; точный исторический end-label не подтверждён независимо, native Cases имеют incomplete_model. Assumed-end Cases — controlled. Локальный cumulative CSV явно synthetic и служит разрешённой альтернативой CDS.

NCAR: скачан и проверен один 269320412-byte ERA5 LSP NetCDF. LSP — large-scale precipitation, отдельная величина; native previous-hour accumulation не трактуется как cumulative с начала прогноза. Cycles сохраняются раздельно.

Реальный профиль: LIST/HEAD подтвердили 735 объектов, 200208579407 выбранных bytes; [pinned download plan](../data/manifests/ncar-200gb-download-plan.json). **Real-200GB download/scan: not_run**. Metadata plan не считается локальными data bytes.

Внешний client действительно выполнил loopback HTTP Query по последнему shard, partition [41, 5040], series_id 2686977, first_hour 5041; локальный checker valid. [Артефакт](validation/external-client-200gb.json). Временный сервер остановлен. Streamlit regression проверяет смену набора/длительности и отказ при изменённом manifest.

## Проверки и команды

Полный suite: **79 passed**, zero failures/errors, 56.81 s; [JUnit](validation/resumed-final.xml), [context](validation/resumed-final-context.json). Ruff прошёл. Ранние ошибки/исправления/native startup stalls сохранены в [history](validation/history.json) и [restart log](scale/sandbox-restart.json). Linux/WSL2 и remote CI здесь не исполнялись; обычный CI создаёт только smoke datasets.

Из корня проекта; PowerShell env и Linux-вариант — в [README](../README.md):

```text
uv sync --frozen
uv run meteo demo --case overlap-exact --output outputs/demo
uv run meteo verify --result outputs/demo/result.json --certificate outputs/demo/certificate.json
uv run meteo demo --case overlap-bounded
uv run meteo demo --case conflict
uv run meteo demo --case insufficient-data
uv run meteo demo --case incomplete-h
uv run pytest -p no:cacheprovider
uv run ruff check .
uv run streamlit run ui/app.py --server.address 127.0.0.1
uv run uvicorn meteo_bridge.api:app --host 127.0.0.1 --port 8000
# В другом терминале
uv run python examples/integration_client.py data/fixtures/overlap-exact.json
```

Большой эксперимент запускается явно, после проверки диска. Существующие completed checkpoints используют `--resume`:

```text
uv run meteo benchmark scale --manifest data/scale/synthetic-200gb/manifest.json --memory-limit 16GiB --output reports/scale --resume
uv run python scripts/finish_scale_experiment.py --manifest data/scale/synthetic-200gb/manifest.json --output reports/scale --acceptance-only --previous-report reports/scale/archive/pre-pause-scale_report.json
uv run python scripts/update_reports.py
uv run python scripts/plot_results.py
```

Все четыре обязательных scripts, generate/dry-run/resume, verify full, real-profile подготовка и регистрация приведены в README. [Standalone figures](figures.html) работают offline без CDN. Повторение Gate A перезапишет output-директорию конфигурации: сохраните прежний run либо задайте отдельный output.

Ограничения: поддерживаемые precipitation amount/interval mean/cumulative, явные UTC offsets/reset/cycle; 4096 observations, 256 H, 1024 union endpoints и 65536 observation/world и endpoint/world pairs. Shared dense closure ≤256 endpoints, independent dense LP ≤512. Неполная модель или бюджет не становятся certified. Нет восстановления hourly из daily, общего matcher/LLM, смешивания продуктов или production multi-user deployment.

Final source SHA256: `bfd75d1dea311baf49f1caa29ab653144a1d276b26b69de649ee0bb9339fa55b`; benchmark source: `f4e970f5f8dee5e42b83b2959ae1c7d9684e7b9c976cc5de0f22a46689af5b99`. ZIP snapshots, Python/library versions и uv.lock hash находятся в runs. Git revision — not_a_git_repository. Методы следуют сохранённому коду, числа — сохранённым runs.
