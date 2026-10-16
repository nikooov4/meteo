"""Standalone offline figures from saved measurements; no fitted/extrapolated results."""

import argparse
import html
import json
import statistics
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from meteo_bridge.resources import sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=Path("experiments/runs/gate-a-final/run.json"))
    parser.add_argument("--scale", type=Path, default=Path("reports/scale/scale_report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/figures.html"))
    args = parser.parse_args()
    run = json.loads(args.run.read_text())
    fig = make_subplots(
        rows=3,
        cols=2,
        subplot_titles=(
            "Solver: median of three repetitions, no confidence interval",
            "Policy: mean cost on six constructed families",
            "Full scan: measured throughput",
            "Query batch: measured latency",
            "Full scan / Query batch: sampled process-tree peak RSS",
            "",
        ),
        vertical_spacing=0.13,
    )
    sizes = list(dict.fromkeys((r["n"], r["H"]) for r in run["solver_comparison"]))
    for solver in ("cache", "shared"):
        for condition in ("cold", "warm"):
            times = [
                statistics.median(
                    r["wall_s"]
                    for r in run["solver_comparison"]
                    if (r["n"], r["H"]) == size and r["solver"] == solver and r["condition"] == condition
                )
                for size in sizes
            ]
            fig.add_trace(
                go.Scatter(
                    x=[f"n={n}, H={h}" for n, h in sizes],
                    y=times,
                    name=f"{solver} / {condition}",
                    mode="markers+lines",
                ),
                row=1,
                col=1,
            )
    policies = list(dict.fromkeys(r["policy"] for r in run["policies"]))
    costs = [
        statistics.mean(
            r["expected_cost"]
            for r in run["policies"]
            if r["policy"] == policy and r["fetch_cost_multiplier"] == 1
        )
        for policy in policies
    ]
    fig.add_trace(go.Bar(x=policies, y=costs, name="Expected action cost"), row=1, col=2)
    notes = [
        f"Gate A run SHA256: {sha256_file(args.run)}.",
        "H3 is negative. Policy costs are conditional simulation units; no population CI or new policy claim.",
        "Connected solver points compare discrete input profiles, not a fitted scaling law.",
    ]
    if args.scale.exists():
        scale = json.loads(args.scale.read_text())
        profiles = [p for p in scale["profiles"] if p["status"] == "complete"]
        gb = [p["data_bytes"] / 1e9 for p in profiles]
        fig.add_trace(
            go.Scatter(x=gb, y=[p["scan_throughput_MB_s"] for p in profiles], mode="markers", name="Scan MB/s"),
            row=2,
            col=1,
        )
        for percentile in (50, 95):
            fig.add_trace(
                go.Scatter(
                    x=gb,
                    y=[p[f"latency_p{percentile}_s"] for p in profiles],
                    mode="markers",
                    name=f"Query p{percentile}",
                ),
                row=2,
                col=2,
            )
        fig.add_trace(
            go.Scatter(
                x=gb,
                y=[p["peak_process_tree_rss"] / 2**30 for p in profiles],
                mode="markers",
                name="Peak RSS GiB",
            ),
            row=3,
            col=1,
        )
        notes += [
            f"Scale report SHA256: {sha256_file(args.scale)}.",
            f"Synthetic scale acceptance: {scale.get('acceptance', {}).get('status', 'pending')}.",
            "Only complete measured profiles are plotted. No extrapolation. OS cache is uncontrolled.",
            "A scan normalizes archive rows; the small Query batch separately checks certificates and LP samples.",
            "Sampled process-tree RSS excludes OS filesystem cache. Scan times can span resumed invocations.",
            "Real-200GB: not_run. Independent annotation / Gate B: pending.",
        ]
    fig.update_yaxes(title_text="seconds", row=1, col=1)
    fig.update_yaxes(title_text="expected action cost", row=1, col=2)
    fig.update_yaxes(title_text="MB/s", row=2, col=1)
    fig.update_yaxes(title_text="seconds", row=2, col=2)
    fig.update_yaxes(title_text="GiB", row=3, col=1)
    for row, col in ((2, 1), (2, 2), (3, 1)):
        fig.update_xaxes(title_text="Actual serialized data GB (10^9 bytes)", row=row, col=col)
    fig.update_layout(
        height=1250,
        title="MeteoBridge — saved development and synthetic-scale measurements",
        template="plotly_white",
        legend={"orientation": "h", "y": -0.12},
        margin={"b": 180},
    )
    plot = fig.to_html(full_html=False, include_plotlyjs=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>MeteoBridge measurements</title>'
        + "<body>"
        + "".join("<p>" + html.escape(note) + "</p>" for note in notes)
        + plot
        + "</body></html>",
        encoding="utf8",
    )
    print(json.dumps({"output": str(args.output), "sha256": sha256_file(args.output)}))


if __name__ == "__main__":
    main()
