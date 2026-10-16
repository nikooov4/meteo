import json
from pathlib import Path
from typing import Annotated

import typer

from .fixtures import NAMES, fixture
from .services import export_bundle, load_dataset, solve_query

app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer()
benchmark_app = typer.Typer()
app.add_typer(data_app, name="data")
app.add_typer(benchmark_app, name="benchmark")
acquisition_app = typer.Typer(no_args_is_help=True)
app.add_typer(acquisition_app, name="acquisition")


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


@acquisition_app.command("evaluate")
def acquisition_evaluate(
    case: Annotated[Path, typer.Option()],
    actions: Annotated[Path, typer.Option()],
    method: str = "terminal",
    output: Path = Path("outputs/acquisition"),
):
    from .action_domain import AcquisitionAction
    from .continuous_acquisition import evaluate_actions
    from .resources import atomic_json

    model = load_dataset(case)
    choices = [AcquisitionAction.model_validate(a) for a in json.loads(actions.read_text(encoding="utf8"))]
    bundle = evaluate_actions(model, choices, method)
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "case.json", model.model_dump())
    atomic_json(output / "actions.json", [a.model_dump() for a in choices])
    atomic_json(output / "bundle.json", bundle)
    emit({"result": bundle["result"], "checker": bundle["checker"], "metrics": bundle["metrics"]})


@acquisition_app.command("verify")
def acquisition_verify(directory: Path = Path("outputs/acquisition")):
    from .acquisition_checker import verify_acquisition
    from .action_domain import AcquisitionAction

    model = load_dataset(directory / "case.json")
    choices = [AcquisitionAction.model_validate(a) for a in json.loads((directory / "actions.json").read_text(encoding="utf8"))]
    bundle = json.loads((directory / "bundle.json").read_text(encoding="utf8"))
    verdict = verify_acquisition(model, choices, bundle["result"], bundle["certificate"])
    emit(verdict)
    if not verdict["valid"]:
        raise typer.Exit(1)


@acquisition_app.command("pilot")
def acquisition_pilot(
    config: Path = Path("configs/experiments/acquisition-continuous-v1.json"),
    output: Path = Path("experiments/runs/acquisition-continuous-v1"),
):
    from .acquisition_experiment import run_acquisition_pilot

    emit(run_acquisition_pilot(config, output))


@app.command()
def demo(case: str = "overlap-exact", solver: str = "graph", output: Path | None = None):
    bundle = solve_query(fixture(case), solver)
    if output:
        export_bundle(bundle, output)
    emit(bundle)


@app.command()
def solve(case: Annotated[Path, typer.Option()], solver: str = "graph", output: Path = Path("outputs/demo")):
    bundle = solve_query(load_dataset(case), solver)
    export_bundle(bundle, output)
    emit(bundle["result"])
    if bundle["result"]["status"] in {"execution_failed", "unsupported"}:
        raise typer.Exit(1)


@app.command()
def verify(
    result: Annotated[Path, typer.Option()],
    certificate: Annotated[Path, typer.Option()],
    case: Path | None = None,
):
    from .certificates import verify_certificate

    verdict = verify_certificate(
        load_dataset(case or result.parent / "case.json"),
        json.loads(result.read_text()),
        json.loads(certificate.read_text()),
    )
    emit(verdict)
    if not verdict["valid"]:
        raise typer.Exit(1)


@app.command("inspect")
def inspect_file(path: Path):
    if path.suffix in {".json", ".yaml", ".yml"}:
        case = load_dataset(path)
        emit(
            {
                "id": case.id,
                "rows": len(case.observations),
                "series": case.query.series.model_dump(),
                "hypotheses": len(case.hypotheses),
                "h_complete": case.h_complete,
            }
        )
    else:
        from .readers import inspect_data

        emit(inspect_data(path))


@data_app.command("register")
def register(manifest: Annotated[Path, typer.Option()], name: Annotated[str, typer.Option()]):
    from .catalog import register_manifest

    emit(register_manifest(name, manifest))


@data_app.command("generate-scale")
def generate_scale_command(
    target_size: str = "32MB",
    seed: int = 42,
    output: Path = Path("data/scale/smoke"),
    format: str = "netcdf",
    compression: str = "none",
    chunk_size: str = "64MiB",
    shard_size: str = "512MiB",
    series: int = 4000000,
    series_per_shard: int = 65536,
    regions: int = 1,
    start: str = "2023-01-01T00:00:00Z",
    end: str = "2024-01-01T00:00:00Z",
    time_step: int = 3600,
    missing_fraction: float = 0.01,
    defect_fraction: float = 0.001,
    workers: int = 1,
    memory_limit: str = "2GiB",
    disk_budget: str | None = None,
    resume: bool = False,
    dry_run: bool = False,
    max_shards: int | None = None,
):
    params = locals().copy()
    from .scale_data import generate_scale

    try:
        emit(generate_scale(**params))
    except (ValueError, OSError, MemoryError) as exc:
        emit({"status": "failed", "error": str(exc)})
        raise typer.Exit(1) from exc


@data_app.command("prepare-real-scale")
def prepare_real(
    provider: Annotated[str, typer.Option()],
    target_size: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()],
    resume: bool = False,
    dry_run: bool = False,
    memory_limit: str = "2GiB",
    disk_budget: str | None = None,
):
    params = locals().copy()
    from .real_data import prepare_real_scale

    emit(prepare_real_scale(**params))


@data_app.command("verify-scale")
def verify_scale(manifest: Annotated[Path, typer.Option()], mode: str = "full"):
    from .scale_benchmark import verify_scale_dataset

    result = verify_scale_dataset(manifest, mode)
    emit(result)
    if result["status"] == "failed":
        raise typer.Exit(1)


@benchmark_app.command("scale")
def benchmark_scale(
    manifest: Annotated[Path, typer.Option()],
    memory_limit: str = "16GiB",
    output: Path = Path("reports/scale"),
    sizes: Annotated[str, typer.Option(help="comma-separated byte sizes, or smoke")] = "1GB,10GB,50GB,200GB",
    query_count: int = 12,
    resume: bool = False,
    stop_after_shards: int | None = None,
):
    params = locals().copy()
    from .scale_benchmark import run_scale_benchmark

    result = run_scale_benchmark(**params)
    emit(result)
    if result["errors"]:
        raise typer.Exit(1)


@app.command()
def experiment(config: Path = Path("configs/experiments/pilot.yaml")):
    from .experiments import run_pilot

    emit(run_pilot(config))


@app.command("write-fixtures")
def write_fixtures():
    root = Path("data/fixtures")
    root.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        (root / f"{name}.json").write_text(fixture(name).model_dump_json(indent=2), encoding="utf8")


if __name__ == "__main__":
    app()
