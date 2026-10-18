import json
import tempfile
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from meteo_bridge.catalog import archives
from meteo_bridge.domain import Query, digest, utc_seconds
from meteo_bridge.export import interval_csv
from meteo_bridge.fixtures import NAMES, fixture
from meteo_bridge.imports import import_file
from meteo_bridge.readers import scale_case
from meteo_bridge.resources import sha256_file
from meteo_bridge.services import apply_evidence, solve_query

st.set_page_config(page_title="MeteoBridge", page_icon="🌧", layout="wide")
st.title("MeteoBridge")
st.caption("Запросы к накопленным осадкам: что следует из данных и какой информации не хватает")

source = st.sidebar.radio("Данные", ["Offline demo", "Локальный файл", "Зарегистрированный набор", "Карта осадков"])
if source == "Карта осадков":
    import streamlit.components.v1 as components

    from meteo_bridge.precipitation_map import load_era5_map, load_weather_map, map_html

    st.subheader("Карта и анимация осадков")
    st.caption("LSP: крупномасштабная компонента осадков за каждый час. Реальный ERA5 или синтетический сценарий v2.")
    map_origin = st.radio("Источник карты", ["Реальный ERA5", "Синтетика v2"], horizontal=True)
    files = sorted(Path("data/scale/ncar-lsp-small").glob("*.nc"))
    with st.form("precipitation-map"):
        map_path = st.text_input("Локальный файл NCAR ERA5 LSP", str(files[0]) if files else "")
        synthetic_manifest = st.text_input("Manifest синтетики v2", "data/scale/weather-global-v2/manifest.json")
        map_member = st.number_input("Синтетический member", min_value=0, value=0)
        map_first_hour = st.number_input("Начальный час синтетического цикла (кратен 12)", min_value=0, value=0, step=12)
        map_cycle = st.text_input("Цикл ERA5, ISO с UTC offset (пусто — первый)", "")
        cols = st.columns(4)
        west = cols[0].number_input("Запад, °E", min_value=-180.0, max_value=180.0, value=-180.0)
        east = cols[1].number_input("Восток, °E", min_value=-180.0, max_value=180.0, value=180.0)
        south = cols[2].number_input("Юг, °N", min_value=-90.0, max_value=90.0, value=-90.0)
        north = cols[3].number_input("Север, °N", min_value=-90.0, max_value=90.0, value=90.0)
        map_frames = st.number_input("Почасовых кадров", min_value=1, max_value=12, value=12)
        build_map = st.form_submit_button("Построить карту")
    if build_map:
        try:
            with st.spinner("Читаю выбранную область и строю кадры…"):
                if map_origin == "Синтетика v2":
                    map_data = load_weather_map(synthetic_manifest, (west, east, south, north), map_member, map_first_hour)
                else:
                    map_data = load_era5_map(map_path, (west, east, south, north), map_cycle or None,
                                             map_frames, allow_downsample=True)
                st.session_state.precipitation_map = (map_html(map_data), map_data["metadata"])
        except (ValueError, OSError, KeyError) as exc:
            st.error(str(exc))
    if "precipitation_map" in st.session_state:
        html, map_metadata = st.session_state.precipitation_map
        components.html(html, height=800, scrolling=True)
        st.download_button("Скачать карту с анимацией HTML", html, "precipitation_map.html", "text/html")
        st.download_button("Метаданные карты JSON", json.dumps(map_metadata, ensure_ascii=False, indent=2),
                           "precipitation_map.json", "application/json")
        st.caption("Цветовая шкала одинакова для всех кадров. Между часами нет интерполяции. "
                   "Зум: колёсико, перемещение: мышью. Детализация ограничена исходной сеткой. "
                   "Карта не является сертификатом Query.")
    st.stop()
case = None
if source == "Offline demo":
    names = NAMES + [str(p) for p in sorted(Path("benchmark/cases").glob("dwd*.json"))]
    name = st.sidebar.selectbox("Случай", names)
    case = fixture(name) if name in NAMES else import_file(name)
elif source == "Локальный файл":
    uploaded = st.sidebar.file_uploader(
        "Case JSON, CSV с явными интервалами или скалярный CF NetCDF", type=["json", "csv", "nc"]
    )
    if uploaded and uploaded.size <= 20 * 2**20:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(suffix=Path(uploaded.name).suffix, delete=False) as f:
                temporary = f.name
                f.write(uploaded.getbuffer())
            case = import_file(temporary)
            import hashlib

            case.id = uploaded.name + ":" + hashlib.sha256(uploaded.getvalue()).hexdigest()[:12]
            case.family_id = case.id
        except (ValueError, OSError, KeyError) as exc:
            st.error(str(exc))
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
    elif uploaded:
        st.error("Лимит preview: 20 MiB. Большой набор зарегистрируйте через meteo data register.")
else:
    registered = archives()
    if registered:
        chosen = st.sidebar.selectbox("Набор", registered, format_func=lambda a: a["name"])
        series_id = st.sidebar.number_input("Series ID", min_value=0, value=0)
        hour = st.sidebar.number_input("Начальный час относительно профиля", min_value=0, value=1)
        duration = st.sidebar.number_input("Часов", min_value=1, max_value=168, value=6)
        try:
            if sha256_file(chosen["path"]) != chosen["sha256"]:
                raise ValueError("Manifest изменился: зарегистрируйте текущую версию через CLI.")
            case, _ = scale_case(chosen["path"], series_id, hour, duration)
        except (ValueError, NotImplementedError) as exc:
            st.error(str(exc))
    else:
        st.info("Зарегистрируйте manifest: uv run meteo data register --manifest PATH --name local")

if case is None:
    st.stop()
identity = f"{source}:{digest(case)}"
if st.session_state.get("identity") != identity:
    st.session_state.identity, st.session_state.case = identity, case
case = st.session_state.case

st.subheader("Данные и допущения")
st.json(case.query.series.model_dump(), expanded=False)
st.write(f"H: {len(case.hypotheses)} трактовок. Revision: {case.revision}. {case.completeness_basis}")
if not case.h_complete:
    st.warning("Полнота H не обеспечена: результат будет incomplete_model.")
with st.expander("Наблюдения, метаданные и provenance", expanded=False):
    st.dataframe(pd.DataFrame([o.model_dump() for o in case.observations[:200]]), hide_index=True)
    st.json(
        {
            "assumptions": case.assumptions,
            "hypotheses": [h.model_dump() for h in case.hypotheses],
            "sources": [s.model_dump() for s in case.source_manifests],
            "evidence": case.evidence,
        }
    )

st.subheader("Query")


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


with st.form("query"):
    a, b = st.columns(2)
    start = a.text_input("Начало, ISO с UTC offset", iso(case.query.start))
    end = b.text_input("Конец, ISO с UTC offset", iso(case.query.end))
    objective = st.selectbox(
        "Цель", ["amount", "threshold"], index=0 if case.query.objective == "amount" else 1
    )
    eps = st.text_input("Допуск, mm", case.query.eps)
    threshold = st.text_input("Порог sum ≥ τ, mm", case.query.threshold or "18")
    st.form_submit_button("Вычислить")
try:
    case = case.model_copy(deep=True)
    case.query = Query(
        series=case.query.series,
        start=utc_seconds(start),
        end=utc_seconds(end),
        objective=objective,
        eps=eps,
        threshold=threshold if objective == "threshold" else None,
    )
    bundle = solve_query(case)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
result = bundle["result"]
st.subheader("Ответ")
st.write(f"Статус: **{result['status']}**")
if "lower" not in result:
    st.error(result.get("error", "Нет результата"))
    st.stop()
st.metric("Допустимые границы, mm", f"[{result['lower']}, {result['upper'] or 'unbounded'}]")
if result["point_estimate"] is not None:
    st.write("Точечный ответ:", result["point_estimate"], "mm")
if result["decision"] is not None:
    st.write("Решение sum ≥ τ:", result["decision"])
st.write("Причины:", ", ".join(result["reason_flags"]) or "Ответ определён")
st.write("Проверка сертификата:", bundle["checker"])
st.caption("Вывод условен относительно полноты H, SeriesKey, входных границ и перечисленных допущений.")

if result["witnesses"]:
    st.subheader("Допустимые сценарии расхождения")
    fig = go.Figure()
    for witness in result["witnesses"]:
        points = sorted((int(t), float(Fraction(v))) for t, v in witness["potentials"].items())
        fig.add_trace(
            go.Scatter(
                x=[iso(t) for t, _ in points],
                y=[v for _, v in points],
                mode="lines+markers",
                name=f"h={witness['hypothesis']}, Q={witness['q']}",
            )
        )
    fig.update_layout(yaxis_title="Накопленное C(t), mm; произвольный нулевой уровень", xaxis_title="UTC")
    st.plotly_chart(fig, width="stretch")
    st.caption("Это допустимые накопленные ряды. Распределение осадков между узлами не восстановлено.")
with st.expander("Обоснование: пути/конфликт, крайние ряды и scope H"):
    st.json(bundle["certificate"])

st.subheader("Следующая информация")
st.json(result["suggested_actions"])
metadata = [a for a in result["suggested_actions"] if a["kind"] == "clarify_metadata"]
for action in metadata:
    value = st.selectbox(f"Подтвердить {action['attribute']}", action["options"])
    if st.button(f"Сохранить evidence: {action['attribute']}"):
        st.session_state.case = apply_evidence(
            case,
            {
                "kind": "clarify_metadata",
                "attribute": action["attribute"],
                "value": value,
                "origin": "human-assisted",
            },
        )
        st.rerun()
with st.expander("Добавить подтверждённое наблюдение той же серии"):
    evidence_json = st.text_area("IntervalObservation JSON", "{}")
    if st.button("Добавить evidence"):
        try:
            st.session_state.case = apply_evidence(
                case,
                {
                    "kind": "add_observation",
                    "observation": json.loads(evidence_json),
                    "origin": "human-assisted",
                },
            )
            st.rerun()
        except (ValueError, KeyError) as exc:
            st.error(str(exc))

st.subheader("Экспорт")
for label, content in [
    ("result", result),
    ("certificate", bundle["certificate"]),
    ("report", bundle),
    ("case", bundle["case"]),
]:
    st.download_button(
        f"{label}.json",
        json.dumps(content, ensure_ascii=False, indent=2),
        f"{label}.json",
        "application/json",
    )
if case.h_complete and len(case.hypotheses) == 1:
    st.download_button("Подтверждённые интервалы CSV", interval_csv(case), "observations.csv", "text/csv")
else:
    st.caption("CSV требует одной подтверждённой трактовки. Case JSON сохраняет все альтернативы.")
st.code("uv run meteo solve --case case.json --solver graph --output outputs/replay")

with st.expander("Оценить дополнительное измерение по всем допустимым рядам"):
    st.caption(
        "Одно точное интервальное измерение в mm той же серии или ответ о метаданных. "
        "Результат — максимальная оставшаяся неопределённость при любом допустимом ответе. "
        "Это одношаговая minimax-оценка, без вероятностного прогноза ответа."
    )
    defaults = [{"id": "measure-query", "start": case.query.start, "end": case.query.end, "cost": "1"}]
    for action in metadata:
        defaults.append({"id": "metadata-" + action["attribute"], "kind": "metadata",
                         "attribute": action["attribute"], "cost": "1"})
    action_json = st.text_area("Actions JSON (start/end: UTC seconds)", json.dumps(defaults, indent=2),
                               key="continuous-actions-" + digest(case))
    if st.button("Оценить действия", key="evaluate-continuous-actions"):
        from meteo_bridge.action_domain import AcquisitionAction
        from meteo_bridge.continuous_acquisition import evaluate_actions

        try:
            choices = [AcquisitionAction.model_validate(a) for a in json.loads(action_json)]
            acquisition = evaluate_actions(case, choices)
            st.write("Scope:", acquisition["result"]["status"], "Checker:", acquisition["checker"])
            st.dataframe(pd.DataFrame(acquisition["result"]["actions"]), hide_index=True)
            st.caption("При incomplete_model оценка относится только к перечисленным H; гарантии нет.")
            st.json(acquisition["certificate"], expanded=False)
            st.download_button("acquisition.json", json.dumps({"case": case.model_dump(),
                                "actions": [a.model_dump() for a in choices], **acquisition},
                                ensure_ascii=False, indent=2), "acquisition.json", "application/json")
        except (ValueError, KeyError, TimeoutError, NotImplementedError) as exc:
            st.error(f"Оценка не завершена, гарантия не выдана: {exc}")
    st.caption("Профиль точности поддерживает amount Query и interval-действия. Погрешность — заданная граница, не оценка прибора.")
    noise_radii = st.text_input("Погрешности нового измерения ±η, mm, через запятую", "0,0.1,0.5,1,6")
    if st.button("Определить достаточную точность измерения", key="evaluate-precision-profile"):
        from meteo_bridge.action_domain import AcquisitionAction
        from meteo_bridge.precision_frontier import build_precision_profiles, precision_values

        try:
            choices = [AcquisitionAction.model_validate(a) for a in json.loads(action_json)]
            precision = build_precision_profiles(case, choices)
            values = precision_values(case, choices, precision, noise_radii.split(","))
            st.write("Scope:", precision["result"]["status"], "Checker:", precision["checker"])
            st.dataframe(pd.DataFrame(precision["result"]["actions"]), hide_index=True)
            st.caption("safe_at_supremum=false означает строгую границу η < radius_supremum. При неполном H гарантия отсутствует.")
            st.json(values, expanded=False)
            st.download_button("precision.json", json.dumps({"case": case.model_dump(),
                                "actions": [a.model_dump() for a in choices], **precision, "values": values},
                                ensure_ascii=False, indent=2), "precision.json", "application/json")
        except (ValueError, KeyError, TimeoutError, NotImplementedError) as exc:
            st.error(f"Профиль не завершён, гарантия не выдана: {exc}")
