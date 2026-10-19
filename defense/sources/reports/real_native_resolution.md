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
