"""Render only saved results; no fitted metrics or unstated novelty claims."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from meteo_bridge.resources import sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=Path("experiments/runs/acquisition-continuous-v1/run.json"))
    parser.add_argument("--examples", type=Path, default=Path("experiments/runs/acquisition-examples-v1/run.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/continuous_acquisition.md"))
    parser.add_argument("--validation", type=Path, default=Path("reports/validation/continuous-final.xml"))
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf8"))
    examples = json.loads(args.examples.read_text(encoding="utf8"))
    records = run["records"]
    checked = [r for r in records if r["method"] != "paired_lp"]
    validation = ET.parse(args.validation).getroot().find("testsuite")
    comparisons = sum(r["regime"]["actions"] for r in checked)
    lines = ["# Непрерывный acquisition oracle: отдельный исследовательский пилот", "",
             "Реализован точный oracle оставшейся неопределённости Query после одного точного интервального наблюдения "
             "или детерминированного ответа о метаданных. Он рассматривает всё непрерывное множество допустимых рядов. "
             "Кандидат переиспользует кратчайшие пути между терминалами; baseline решает полный парный граф. "
             "Оба выдают проверяемые пути и достигающие границ пары рядов.", "",
             "Это конкретный кандидат на методический вклад. Приоритет и научная новизна **не установлены**. "
             "STN projection, LP/flow duality и minimax recovery известны. Положительный development-пилот "
             "не заменяет проверку предшествующих работ, независимую аннотацию и внешнюю оценку.", "",
             "| Режим: segments/H/actions | LP, s | Graph, s | Cache cold, s | Cache warm, s | Terminal, s | Graph / terminal |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for row in run["summary"]["regimes"]:
        r, t = row["regime"], row["median_seconds"]
        lines.append(f"| {r['segments']}/{r['hypotheses']}/{r['actions']} | " +
                     " | ".join(f"{t[m]:.6f}" for m in ("paired_lp", "graph", "cache_cold", "cache_warm", "terminal")) +
                     f" | {t['graph']/t['terminal']:.3f} |")
    lines += ["", "Медианы по трём заранее заданным development-повторам на CPU. "
              "Graph/terminal/cache включают построение модели, полные witnesses, сериализуемый сертификат и checker; "
              "warm cache повторно проверяет сертификат. LP — численный результат без точного сертификата; "
              "его более низкая latency не скрывается. Файловый export не входит в замер. "
              "Это одна реализация baseline; сравнение с сильной промышленной STN/flow библиотекой ещё не проведено.", "",
              f"Всего {len(records)} замеров, {len(checked)} графовых bundles; "
              f"{comparisons} сравнений action-value с LP. Совпадение всех проверок: **{run['summary']['all_agree']}**. "
              f"Ошибки: {len(run['errors'])}. Предзаданный go-критерий: **{run['summary']['go_criterion_met']}** "
              "(продолжать исследование, а не объявлять новизну). "
              f"Пиковый sampled process-tree RSS всего пилота: {run['peak_sampled_tree_rss_bytes']} bytes; "
              "это не раздельный RSS методов. Начальная загрузка библиотек прогрета до замеров.", "",
              "Диагностика: daily total=12 mm, Query=первые 12 часов. "
              "W(first6)=12 mm, W(last12)=0, W(metadata)=12 mm. "
              "При фактическом first6=0 Query остаётся [0,12]; при last12=5 Query равен 7. "
              "Никакого произвольного разложения daily total на часы. Все ответы и сертификаты сохранены.", "",
              f"Полная проверка: {validation.attrib['tests']} tests, failures={validation.attrib['failures']}, "
              f"errors={validation.attrib['errors']}, time={validation.attrib['time']} s "
              f"({args.validation.as_posix()}). Ruff проверяет весь проект. "
              "Первый integration-run сохранил два PermissionError системного temp-каталога; "
              "затем тесты прошли с workspace-local basetemp. Сохраняется предупреждение TestClient о deprecation.", "",
              f"Совместимость с ранее импортированными данными: {len(examples['records'])} cases, "
              f"passed={examples['passed']}, errors={len(examples['errors'])}. "
              "Это DWD/NCAR original и controlled cases с сохранёнными family_id, а не независимый benchmark. "
              "Доступность новых измерений гипотетическая; natural ambiguity/стоимость действий ещё нужно аннотировать. "
              "Native DWD сохраняет incomplete_model. **Gate B pending**.", "",
              "Прежний Gate A/H1–H4 и отрицательный H3 сохранены в reports/gate_a.md. "
              "Новый пилот относится к oracle, не к политике: преимуществ над VOI/DRD, оптимальности последовательности "
              "действий или A* не заявляется. Continuous policy study с одинаковыми действиями/стоимостью/сведениями/stop "
              "и сильными adaptations VOI/DRD остаётся отдельной задачей. "
              "Синтетическая приёмка 200 GB относится к прежнему reader/Query pipeline; новый oracle работает "
              "на ограниченной выборке и не проверялся заново полным 200-GB прогоном. Real-200GB остаётся not_run.", "",
              "Пределы: одно точное новое измерение; до 128 endpoints, 16 H, 128 действий, 4096 ordered action-pairs. "
              "Неполное H никогда не даёт guarantees_resolution. Шум нового измерения, несколько совместных "
              "измерений, continuous Bayesian VOI/DRD, независимая аннотация и исчерпывающий prior-art review не реализованы.", "",
              "Команды (PowerShell, из корня; для повторного пилота указать новый --output):", "", "```powershell",
              "uv run --frozen --offline meteo acquisition evaluate --case experiments/runs/acquisition-examples-v1/case.json --actions experiments/runs/acquisition-examples-v1/actions.json --output outputs/acquisition",
              "uv run --frozen --offline meteo acquisition verify --directory outputs/acquisition",
              "uv run --frozen --offline python scripts/verify_acquisition_run.py",
              "uv run --frozen --offline meteo acquisition pilot --output experiments/runs/acquisition-repeat",
              "uv run --frozen --offline python scripts/run_acquisition_examples.py --output experiments/runs/acquisition-examples-repeat",
              "uv run --frozen --offline pytest -q --basetemp=.meteo/research-tests-new",
              "uv run --frozen --offline streamlit run ui/app.py",
              "uv run --frozen --offline uvicorn meteo_bridge.api:app --host 127.0.0.1 --port 8000", "```", "",
              "API: POST /queries/{qid}/acquisition с actions и method=terminal|graph|cache. "
              "Реальный ответ действия в request не передаётся. Streamlit содержит отдельную форму оценки действий и экспорт. "
              "Выходной CLI bundle проверяется без запуска решателя.", "",
              "Внешний клиент: `uv run --frozen --offline python examples/acquisition_client.py`. "
              "Автоматический loopback smoke с остановкой сервера: "
              "`uv run --frozen --offline python scripts/check_acquisition_http.py`. "
              "Сохранённые ответы и локальная проверка клиента: reports/validation/acquisition-http/.", "",
              f"Protocol SHA256: `{run['protocol_sha256']}`. Run SHA256: `{sha256_file(args.run)}`. "
              f"Measured source SHA256: `{run['metadata']['code_sha256']}`; ZIP: `{run['metadata']['source_snapshot']}`. "
              "В run сохранены версии, seed, environment, input/bundle hashes, операции, latency, proof sizes и ошибки. "
              "В проекте нет Git checkout; source ZIP фиксирует измерявшийся код.", "",
              "Вывод и границы доказательства: [docs/continuous_acquisition.md](../docs/continuous_acquisition.md). "
              "Математическая специализация проверяется сертификатами на каждом результате, но это не доказательство "
              "полноты H или правильности входных допущений. Терминальная проекция и LP/flow duality — известные основы "
              "([Dechter et al.](https://ftp.cs.ucla.edu/pub/stat_ser/r113-L-reprint.pdf), "
              "[MIT notes](https://ocw.mit.edu/courses/6-854j-advanced-algorithms-fall-2005/99eac3e02c1e1c317f20ef3cad4f6a28_dualitynotes.pdf)); "
              "worst-case recovery также имеет предшественников "
              "([Foucart/Paouris](https://arxiv.org/abs/2301.07228)).", ""]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf8")
    print(args.output)


if __name__ == "__main__":
    main()
