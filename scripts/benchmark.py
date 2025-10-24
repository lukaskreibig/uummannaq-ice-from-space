"""Benchmark helper for the Uummannaq ice pipeline."""

from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from uummannaq_ice.config_loader import load_run_config
from uummannaq_ice.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the Uummannaq pipeline across repeated runs.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/single_tile_debug.yaml"),
        help="YAML configuration to benchmark.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of runs to execute (default: 1).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("out/benchmarks"),
        help="Directory under which benchmark runs will be stored.",
    )
    parser.add_argument(
        "--max-tiles",
        type=int,
        help="Override the max_tiles setting for benchmarking.",
    )
    parser.add_argument(
        "--device",
        type=str,
        help="Force a specific torch device (cpu, cuda, mps).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    wall_times: list[float] = []

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    base_overrides: dict[str, Any] = {}
    if args.max_tiles is not None:
        base_overrides["max_tiles"] = args.max_tiles
    if args.device:
        base_overrides["device"] = args.device

    for iteration in range(1, args.repeat + 1):
        run_output = args.output_root / f"{args.config.stem}_{timestamp}_iter{iteration}"
        overrides = {**base_overrides, "output_dir": run_output}
        config = load_run_config(args.config, overrides=overrides)

        start = time.perf_counter()
        stats = run_pipeline(config)
        elapsed = time.perf_counter() - start

        wall_times.append(elapsed)
        results.append(stats or {})

        print(
            f"Run {iteration}: {stats['tiles_processed']} tiles in "
            f"{stats['elapsed_seconds']:.2f}s (wall {elapsed:.2f}s, "
            f"avg {stats['average_seconds_per_tile']:.2f}s/tile)"
        )

    if not wall_times:
        print("No runs executed.")
        return

    mean_wall = statistics.mean(wall_times)
    p95 = statistics.quantiles(wall_times, n=20)[-1] if len(wall_times) > 1 else wall_times[0]
    total_tiles = sum(r.get("tiles_processed", 0) for r in results)

    print("\nBenchmark summary")
    print("=================")
    print(f"Runs executed : {len(wall_times)}")
    print(f"Total tiles   : {total_tiles}")
    print(f"Mean walltime : {mean_wall:.2f}s")
    print(f"P95 walltime  : {p95:.2f}s")


if __name__ == "__main__":
    main()
