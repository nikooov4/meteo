from pathlib import Path

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from meteo_bridge.acquisition import policy_tasks, select_action
from meteo_bridge.api import app
from meteo_bridge.certificates import verify_certificate
from meteo_bridge.domain import Case
from meteo_bridge.fixtures import fixture
from meteo_bridge.imports import csv_case
from meteo_bridge.services import solve_query


def test_http_roundtrip_evidence_and_local_checker(tmp_path, monkeypatch):
    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        source = fixture("metadata-label").model_dump_json().encode()
        uploaded = client.post("/datasets", files={"file": ("../../case.json", source)}).json()
        response = client.post("/queries", json={"dataset_id": uploaded["id"]}).json()
        qid = response["id"]
        assert response["result"]["status"] == "needs_evidence"
        revised = client.post(
            f"/queries/{qid}/evidence",
            json={"kind": "clarify_metadata", "attribute": "label", "value": "begin"},
        )
        assert revised.status_code == 200
        exported = client.get(f"/queries/{qid}/export").json()
        assert exported["result"]["point_estimate"] == "5"
        assert verify_certificate(
            Case.model_validate(exported["case"]), exported["result"], exported["certificate"]
        )["valid"]
        assert client.get(f"/queries/{qid}/certificate").json() == exported["certificate"]
        assert client.post("/datasets", files={"file": ("archive.zip", b"bad")}).status_code == 415
        assert client.get("/queries/absent").status_code == 404


def test_local_csv_cumulative_and_explicit_metadata():
    case = csv_case(Path("data/fixtures/local-cumulative.csv").read_text())
    case.query.start += 3600
    assert solve_query(case)["result"]["point_estimate"] == "3"


def test_policy_cannot_receive_simulator_truth():
    # Signature accepts only public likelihood model and observed posterior.
    import inspect

    assert set(inspect.signature(select_action).parameters) == {
        "task",
        "states",
        "available",
        "policy",
        "seed",
    }
    task = policy_tasks()[0]
    for policy in ("fixed", "random", "entropy", "voi", "drd", "witness", "optimal"):
        assert select_action(task, tuple(range(8)), tuple(range(4)), policy, 42) in range(4)


def test_streamlit_uses_real_service():
    at = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=30).run()
    assert not at.exception
    assert any("certified" in text.value for text in at.markdown)
    at.sidebar.selectbox[0].select("insufficient-data").run()
    assert not at.exception
    assert any("insufficient_data" in text.value for text in at.markdown)
    at.sidebar.selectbox[0].select("metadata-label").run()
    assert not at.exception
    next(s for s in at.selectbox if s.label == "Подтвердить label").select("begin")
    next(b for b in at.button if b.label == "Сохранить evidence: label").click().run()
    assert not at.exception
    assert any("5 mm" in text.value for text in at.markdown)
