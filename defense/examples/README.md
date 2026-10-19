# Примеры данных

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
