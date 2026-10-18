"""Local FastAPI adapter. All numerical answers come from services.solve_query."""

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import Field

from .action_domain import AcquisitionAction
from .catalog import archives, connect
from .domain import Case, Model, Query, digest
from .imports import import_file
from .map_archive import make_map_router
from .resources import sha256_file
from .services import apply_evidence, solve_query

app = FastAPI(title="MeteoBridge", version="0.1.0")
MAX_UPLOAD = 20 * 2**20
_NETCDF_READ_LOCK = threading.Lock()
app.include_router(make_map_router(_NETCDF_READ_LOCK))


class ArchiveSelection(Model):
    series_id: int = Field(ge=0)
    first_hour: int = Field(ge=0)
    hours: int = Field(default=6, ge=1, le=168)


class QueryRequest(Model):
    dataset_id: str
    query: Query | None = None
    selection: ArchiveSelection | None = None
    solver: str = Field(default="graph", pattern="^(graph|shared|cache|lp)$")


class AcquisitionRequest(Model):
    actions: list[AcquisitionAction] = Field(min_length=1, max_length=128)
    method: str = Field(default="terminal", pattern="^(terminal|graph|cache)$")


class PrecisionRequest(Model):
    actions: list[AcquisitionAction] = Field(min_length=1, max_length=128)
    method: str = Field(default="terminal", pattern="^(full|compiled|terminal|terminal_no_reuse)$")
    radii: list[str] = Field(default_factory=lambda: ["0", "1/2", "1"], min_length=1, max_length=64)


def _bundle(qid):
    with connect() as db:
        row = db.execute(
            "SELECT payload FROM queries WHERE id=? ORDER BY revision DESC LIMIT 1", (qid,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "query not found")
    return json.loads(row[0])


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0", "offline": True}


@app.post("/datasets")
def upload_dataset(file: UploadFile):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".json", ".yaml", ".yml", ".csv", ".nc"}:
        raise HTTPException(415, "unsupported format; archives are not accepted")
    home = Path(os.environ.get("METEOBRIDGE_HOME", ".meteo"))
    home.mkdir(parents=True, exist_ok=True)
    filename = None
    try:
        with tempfile.NamedTemporaryFile(dir=home, suffix=suffix, delete=False) as f:
            filename = f.name
            total = 0
            while block := file.file.read(65536):
                total += len(block)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, "20 MiB upload limit; large archives are registered through CLI")
                f.write(block)
        with _NETCDF_READ_LOCK:
            case = import_file(filename)
        dataset_id = digest(case)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO datasets VALUES (?,?)", (dataset_id, case.model_dump_json()))
        return {"id": dataset_id, "rows": len(case.observations), "query": case.query.model_dump()}
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if filename:
            Path(filename).unlink(missing_ok=True)


@app.get("/datasets/{dataset_id}/schema")
def schema(dataset_id: str):
    with connect() as db:
        row = db.execute("SELECT payload FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if row is None:
        archive = next((a for a in archives() if a["sha256"] == dataset_id), None)
        if archive is None:
            raise HTTPException(404, "dataset not found")
        manifest = json.loads(Path(archive["path"]).read_text())
        return {
            "name": archive["name"],
            "id": dataset_id,
            "data_bytes": manifest["data_bytes"],
            "selection_schema": ArchiveSelection.model_json_schema(),
            "selection_time_axis": "hour from start"
            if manifest["origin"] == "synthetic"
            else "forecast initialization index; hours selects hourly steps of one cycle",
            "config": manifest["config"],
        }
    case = Case.model_validate_json(row[0])
    return {
        "series": case.query.series.model_dump(),
        "observations_preview": [o.model_dump() for o in case.observations[:20]],
        "hypotheses": [h.model_dump() for h in case.hypotheses],
        "h_complete": case.h_complete,
        "provenance": [s.model_dump() for s in case.source_manifests],
    }


@app.post("/queries")
def create_query(request: QueryRequest):
    with connect() as db:
        row = db.execute("SELECT payload FROM datasets WHERE id=?", (request.dataset_id,)).fetchone()
    if row is None:
        archive = next((a for a in archives() if a["sha256"] == request.dataset_id), None)
        if archive is None or request.selection is None:
            raise HTTPException(404, "dataset not found or archive selection missing")
        if sha256_file(archive["path"]) != archive["sha256"]:
            raise HTTPException(409, "registered manifest changed")
        from .readers import scale_case

        try:
            with _NETCDF_READ_LOCK:
                case, _ = scale_case(archive["path"], **request.selection.model_dump())
        except (ValueError, NotImplementedError) as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        case = Case.model_validate_json(row[0])
    if request.query:
        case.query = request.query
    bundle = solve_query(case, request.solver)
    qid = uuid.uuid4().hex
    with connect() as db:
        db.execute("INSERT INTO queries VALUES (?,?,?)", (qid, case.revision, json.dumps(bundle)))
    return {"id": qid, **bundle}


@app.get("/queries/{qid}")
def get_query(qid: str):
    return _bundle(qid)["result"]


@app.get("/queries/{qid}/certificate")
def certificate(qid: str):
    return _bundle(qid).get("certificate")


@app.get("/queries/{qid}/witnesses")
def witnesses(qid: str):
    return _bundle(qid)["result"].get("witnesses", [])


@app.get("/queries/{qid}/actions")
def actions(qid: str):
    return _bundle(qid)["result"].get("suggested_actions", [])


@app.post("/queries/{qid}/evidence")
def evidence(qid: str, payload: dict):
    try:
        case = apply_evidence(Case.model_validate(_bundle(qid)["case"]), payload)
        bundle = solve_query(case)
        with connect() as db:
            db.execute("INSERT INTO queries VALUES (?,?,?)", (qid, case.revision, json.dumps(bundle)))
        return {"id": qid, **bundle}
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/queries/{qid}/acquisition")
def evaluate_acquisition(qid: str, request: AcquisitionRequest):
    from .continuous_acquisition import evaluate_actions

    case = Case.model_validate(_bundle(qid)["case"])
    try:
        return evaluate_actions(case, request.actions, request.method)
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(503, "acquisition incomplete: deadline exceeded; no guarantee returned") from exc


@app.get("/queries/{qid}/export")
def export(qid: str):
    return _bundle(qid)


@app.post("/queries/{qid}/precision")
def evaluate_precision(qid: str, request: PrecisionRequest):
    from .precision_frontier import build_precision_profiles, precision_values

    case = Case.model_validate(_bundle(qid)["case"])
    try:
        bundle = build_precision_profiles(case, request.actions, request.method)
        return {**bundle, "values": precision_values(case, request.actions, bundle, request.radii)}
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(503, "precision profile incomplete; no guarantee returned") from exc
