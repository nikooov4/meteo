# Компактные воспроизводимые доказательства

Здесь копии новых runs и ZIP bundles с JSON inputs, LP reference и сертификатами.
Оригинальные 200 GB или 3.17 GB NetCDF для replay не нужны. Для current archive
учитывайте status в run.json; partial snapshot не является завершённым экспериментом.
Replay использует установленный код проекта и проверяет доказательства без solver/LP:

```powershell
uv run python scripts/run_archive_precision_benchmark.py --output defense/evidence/precision-real-era5-v1 --replay
uv run python scripts/run_archive_precision_benchmark.py --output defense/evidence/precision-real-native-resolution-v1 --replay
uv run python scripts/run_archive_precision_benchmark.py --output defense/evidence/precision-archive-200gb-v1 --replay
```
