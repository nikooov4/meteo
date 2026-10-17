# Что нужно для подтверждения новизны MeteoBridge

## Обновление 2026-10-17: что выполнено по этому плану

Реализовано новое узкое расширение: **весь проверяемый профиль допустимой точности
одного interval measurement с bounded error**, включая activation разных H-пар,
скачки и открытый/закрытый безопасный предел eta. [Вывод](precision_frontier.md),
[фактический пилот](../reports/precision_frontier.md),
[объяснение проекта](project_explained_ru.md).

Прочитаны определения/алгоритмы ближайших STN, parametric shortest paths и optimal
recovery with observation errors; сохранены конкретные разделы и пересечения в
[новом literature delta](literature_delta_2026_10_17.md). General bounded-error recovery
уже известен. Возможное отличие сужено до специального batch certificate/frontier
контракта; его приоритет по-прежнему НЕ установлен. Обзор не исчерпывающий.

Добавлены сильный compiled full-graph comparator (SciPy Johnson с exact validation
и fallback), ablation без междействийного reuse, отдельный заранее замороженный
пилот и independent paired LP с шумовыми inequalities. 36 certificates и 2160
action/radius comparisons проходят; выигрыш compiled/terminal 1.234/1.871/2.274
в трёх development-режимах. Это вычислительная польза, не подтверждение новизны.
Независимый search-free checker проверяет весь континуум, LP — конечную сетку.

Внешнего проверяющего пока нет (ответ пользователя). [Пакет](../review/README.md)
содержит proof checklist и четыре слепых development-family packets без наших
предсказаний/H, но **0** независимых аннотаций. Семейства уже использовались при
разработке: нельзя превратить их в held-out переименованием. Gate B остаётся pending.
Математический вывод подготовлен для внешнего review; review ещё не проведён.

Оставшиеся существенные действия: независимая проверка вывода и содержательного
отличия от ближайших работ; расширение обзора по citations/специализациям;
новые исходные семейства с проверенными conventions и реально доступными
действиями; независимая разметка до просмотра предсказаний и frozen held-out study.
Continuous policy study нужен только при отдельном claim о policy, который сейчас
не делается. Наличие кода/ускорения не разрешает объявить метод впервые предложенным.

Далее сохранён исходный план 2026-10-16 и его историческое состояние.

Статус на 2026-10-16: реализован исследовательский кандидат, приоритет не
установлен. Новый development-пилот поддержал продолжение исследования;
он не доказывает новизну. Публикация GitHub фиксирует доступную версию кода,
но не заменяет научную экспертизу и не гарантирует принятие статьи.

## Проверяемое утверждение

Кандидат на вклад: проверяемый oracle максимальной остающейся неопределённости
Query после одного точного интервального наблюдения в конечном объединении
непрерывных моделей, с повторным использованием путей между кандидатами действий.
Конкретная реализация и вывод находятся в continuous_acquisition.md.

Сами по себе difference constraints, возможные миры, минимальные temporal
networks, projection на терминалы, LP/flow duality, determinacy и minimax recovery
не являются нашим новым результатом. Сведение к шести терминалам может оказаться
прямым следствием известных конструкций. Это главный риск методической новизны.
Новые слова, метеорологическая предметная область и ускорение Python baseline
этот риск не устраняют.

## 1. Закрыть ближайший prior art и сформулировать delta

Нужна таблица ближайших работ с колонками: математическая модель, допустимые
измерения, критерий, алгоритм, результат, точность/сертификат, batch reuse,
точное отличие нашей работы. Прочитать соответствующие определения, теоремы
и алгоритмы полностью, искать предшественников и последующие работы по ссылкам.
Отсутствие похожего названия в поиске не подтверждает приоритет.

| Направление / первичный источник | Уже известное пересечение | Что ещё проверить |
|---|---|---|
| [Dechter, Meiri, Pearl: Temporal Constraint Networks](https://ftp.cs.ucla.edu/pub/stat_ser/r113-L-reprint.pdf) | STN, shortest-path closure, минимальные ограничения | Является ли наша проекция лишь стандартным elimination; сопоставить с современными реализациями |
| [MIT: shortest paths и LP duality](https://ocw.mit.edu/courses/6-854j-advanced-algorithms-fall-2005/99eac3e02c1e1c317f20ef3cad4f6a28_dualitynotes.pdf) | Potential/flow duality — классическая | Два unit-flow matching не представлять как новую duality; искать уже готовую специализацию |
| [Barber: disjunctive metric constraints](https://www.cs.cmu.edu/afs/cs/project/jair/pub/volume12/barber00a-html/Barber.html) | Контексты, дизъюнкции и логические зависимости | Полное сопоставление labelled/context reuse; ранее изучен обзор, не все алгоритмы |
| [Segoufin, Vianu: Views and Queries](https://dbucsd.github.io/paperpdfs/2005_7.pdf) | Query determinacy — известная постановка | Сопоставление достаточности нового interval view с нашими W=0 и threshold |
| [Foucart, Paouris: optimal recovery](https://arxiv.org/abs/2301.07228) | Worst-case recovery линейных функционалов имеет prior art | Здесь проверен abstract; расширить обзор radius/diameter of information, noiseless linear information и robust measurement design; не переносить их теоремы на нашу модель без проверки |
| [Zheng et al.: Active Information Acquisition for Linear Optimization](https://arxiv.org/abs/1709.10061) | Active acquisition для оптимизации известно | Сопоставить известную матрицу/неизвестные параметры, шум и критерий с конечным H и непрерывными траекториями |
| [Javdani et al.: Decision Region Determination](https://proceedings.mlr.press/v33/javdani14.html) | Достичь решения без полной идентификации известно | Разделить oracle и policy; уточнить finite/continuous adaptation, если заявляется новая policy |

Стартовые поисковые направления: `optimal recovery radius diameter information
linear functional noiseless measurements`; `robust sensor selection polyhedral
uncertainty`; `difference constraints projection temporal networks`; `active
constraint acquisition`; `query determinacy interval sum views`. Сохранять даты,
запросы, версии и конкретные страницы/теоремы. Нынешние ссылки — ориентиры,
а не исчерпывающая проверка отсутствия аналога.

Результат этапа: одно узкое утверждение «что именно у нас не следует из X/Y/Z».
Если такого утверждения нет, честная классификация — полезная специализация
и программный инструмент. Новый алгоритм нельзя подтвердить только benchmark.

## 2. Независимо проверить математический контракт

Нужна внешняя проверка вывода: эквивалентность двух миров с одинаковым ответом;
допустимость склейки ТОЛЬКО одного измерения; сохранение множества при projection;
четырёхтерминальная цель и matching; полнота обработки infeasible/unbounded;
строгий threshold; охват всех ordered h-pairs и модель unknown/incomplete H.
Отдельно проверить нулевые/cancelled coefficients, новые endpoints, disjoint
components, несовместимые ответы двух h и условность вывода относительно H.

Тесты, paired LP и checker дают воспроизводимые свидетельства корректности
реализации. Они не доказывают математический приоритет или полноту исходных H.
Новый результат следует отделить от известных лемм и изложить с точными
предпосылками; новая worst-case complexity без полного доказательства не нужна.

## 3. Провести заранее зафиксированное сравнение с сильными реализациями

Имеющийся пилот — development: graph/terminal median ratios
0.900, 1.251, 1.747; numerical LP и warm cache быстрее кандидата. Следующая
оценка должна включать оптимизированный STN/flow baseline, а не только наш
Python Bellman-Ford. Методы должны считать ОДНО и то же W/threshold с одинаковыми
действиями и точностью; numerical-only LP отдельно от exact certificate contract.

До новых замеров зафиксировать новые families/seeds, размеры n/H/actions,
sparsity, локальность/overlap, долю неоднозначности, рабочие бюджеты, primary
metric и go/no-go. Не менять выборку после просмотра результата. Измерять
end-to-end latency, preprocessing, proof generation/checking, операции, peak
process-tree RAM, proof bytes, ошибки; cold/warm отдельно. Учитывать загрузку
данных и export, если они входят в объявленный контракт.

Обязательные ablations: full graph; whole-batch cache; terminal projection без
междействийного reuse; closure reuse с полными witnesses; стоимость checker;
дешёвые SSSP только из реально нужных endpoints. Ускорение должно объясняться
предложенным механизмом. 200-GB streaming scan показывает свойства reader,
а не новизну acquisition oracle; эти результаты нельзя смешивать.

## 4. Независимая оценка на реальных семействах — Gate B

Два независимых аннотатора проверяют исходные conventions, естественную
неоднозначность и ожидаемые выводы до просмотра наших предсказаний; записываются
разногласия и их разрешение. Нужны семейства, не использованные при разработке;
derived/masked случаи остаются в исходной family и не попадают в другой split.
Нужно аннотировать реально доступные действия, их стоимость и временную
детализацию. Гипотетическое hourly измерение не является возможностью daily
архива. Top-k LLM не даёт полного H.

Нынешние 27 original/controlled DWD/NCAR cases проверяют совместимость; это не
независимая разметка и не Gate B. Native DWD сохраняет incomplete_model.

## 5. Если заявляется новая policy — отдельное сравнение

Oracle novelty не требует объявлять новую policy. Если такое утверждение
появится, необходимы сильные VOI/DRD adaptations для заявленной модели ответов,
одинаковые public actions/costs/information/stopping, hidden-answer isolation,
контроль priors и ошибок интегрирования/аппроксимации. Minimax width и expected
action cost — разные цели. Старые шесть конечных задач этот continuous claim
не подтверждают; одного random baseline недостаточно.

## Готовность и критерий решения

| Проверка | Сейчас |
|---|---|
| Реализованный непрерывный oracle и independent paired LP | Есть |
| Exact checker, adversarial tests, воспроизводимые runs/hashes/source ZIP | Есть; 111 tests и сохранённый пилот |
| Нет подмены старого отрицательного H3 | Сохранён |
| Изолированное непокрытое prior art утверждение | Не установлено |
| Независимый математический review | Не проведён |
| Оптимизированный внешний temporal/flow comparator и ablations | Не проведены |
| Независимые новые real families / Gate B | Pending |
| Continuous VOI/DRD policy study | Не проведён; policy superiority не заявляется |

Новизна становится обоснованной после точного отличия от ближайших работ и
проверки именно этого отличия; научная ценность дополнительно опирается на
корректность, значимость задачи и воспроизводимые результаты. Ни один тест,
число ускорения, GitHub-коммит или внешний отзыв по отдельности этого не гарантирует.
Если отличие оказывается стандартной композицией, следующий исследовательский
вопрос должен решать обнаруженное ограничение (например, шум или несколько
измерений) с новым проверенным результатом, а не переименовывать текущий метод.
