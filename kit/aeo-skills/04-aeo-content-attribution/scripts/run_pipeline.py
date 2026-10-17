#!/usr/bin/env python3
"""
run_pipeline.py — Orchestrate the AEO-04 content-attribution pipeline.

End-to-end runner that wires together:
  1. Input validation
  2. Citation enrichment (skippable, idempotent)
  3. Attribution computation (attribute_content.py)
  4. Dashboard rendering (skippable)

Stdlib only. Uses argparse, logging, subprocess.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# Resolve sibling-skill script paths relative to this file:
#   <REPO>/AEO skills/04-aeo-content-attribution/scripts/run_pipeline.py
#   parents: [0]=scripts, [1]=04-aeo-content-attribution, [2]=AEO skills, [3]=REPO
AEO_SKILLS_ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTE_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "attribute_content.py"
)
EXTRACT_CITATIONS_SCRIPT = (
    AEO_SKILLS_ROOT
    / "01-aeo-brand-visibility-analysis"
    / "scripts"
    / "extract_citations.py"
)
RENDER_DASHBOARD_SCRIPT = (
    AEO_SKILLS_ROOT
    / "01-aeo-brand-visibility-analysis"
    / "scripts"
    / "render_dashboard.py"
)


DATE_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the full AEO-04 content-attribution pipeline.",
    )
    p.add_argument("--runs-dir", required=True, help="AEO-01 run history directory")
    p.add_argument("--queries", required=True, help="queries.json path")
    p.add_argument("--brand-profile", required=True, help="brand_profile.json path")
    p.add_argument("--content-planner", help="Local CSV with content planner")
    p.add_argument(
        "--sheet-url",
        help="Public Google Sheet URL or ID (mutually exclusive with --content-planner)",
    )
    p.add_argument(
        "--output-dir",
        required=True,
        help="Where attribution outputs go",
    )
    p.add_argument(
        "--dashboard-out",
        required=True,
        help="Final HTML output path",
    )
    p.add_argument(
        "--skip-citations",
        action="store_true",
        help="Skip the extract_citations.py enrichment step",
    )
    p.add_argument(
        "--skip-render",
        action="store_true",
        help="Skip the dashboard render step",
    )
    p.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    p.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help="Log output format. 'text' (default) or 'json' for structured single-line JSON.",
    )
    p.add_argument(
        "--breakout-threshold-pp",
        type=float,
        default=None,
        help="Override attribute_content's breakout threshold in pp.",
    )
    p.add_argument(
        "--strong-lift-pp",
        type=float,
        default=None,
        help="Override attribute_content's strong-lift threshold in pp.",
    )
    p.add_argument(
        "--lazy-runs",
        action="store_true",
        help="Load AEO run scored_rows.jsonl files lazily (for large run histories).",
    )
    p.add_argument(
        "--lazy-cache-size",
        type=int,
        default=None,
        help="LRU cache size for --lazy-runs (default 8).",
    )
    return p.parse_args()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":     datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }
        step = getattr(record, "step", None)
        if step:
            payload["step"] = step
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(verbose: bool, log_format: str = "text") -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stderr)
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    root.addHandler(handler)
    root.setLevel(level)


def validate_inputs(args: argparse.Namespace) -> list[Path]:
    """Confirm required inputs exist and are well-formed.

    Returns the sorted list of dated run subdirs.
    """
    if bool(args.content_planner) == bool(args.sheet_url):
        raise ValueError(
            "Provide exactly one of --content-planner or --sheet-url, not both, not neither."
        )

    runs_dir = Path(args.runs_dir)
    if not runs_dir.exists() or not runs_dir.is_dir():
        raise FileNotFoundError(f"runs-dir not found or not a directory: {runs_dir}")

    dated_subdirs = sorted(
        [
            c
            for c in runs_dir.iterdir()
            if c.is_dir() and DATE_DIR_PATTERN.match(c.name)
        ]
    )
    if len(dated_subdirs) < 2:
        raise ValueError(
            f"runs-dir {runs_dir} must contain at least 2 dated subdirs "
            f"(YYYY-MM-DD); found {len(dated_subdirs)}."
        )

    queries_path = Path(args.queries)
    if not queries_path.exists():
        raise FileNotFoundError(f"queries file not found: {queries_path}")

    brand_path = Path(args.brand_profile)
    if not brand_path.exists():
        raise FileNotFoundError(f"brand_profile file not found: {brand_path}")

    if args.content_planner:
        cp = Path(args.content_planner)
        if not cp.exists():
            raise FileNotFoundError(f"content-planner CSV not found: {cp}")

    return dated_subdirs


def scored_rows_has_citations(scored_path: Path) -> bool:
    """Return True if the first non-empty line in scored_path has a cited_urls field."""
    try:
        with scored_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                return "cited_urls" in obj
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not probe %s for cited_urls: %s", scored_path, e)
    return False


def run_step(name: str, cmd: list[str]) -> None:
    """Run a subprocess step, logging timing. Raises on non-zero exit."""
    logger.info("Step start: %s", name, extra={"step": name})
    logger.debug("Command: %s", " ".join(repr(c) for c in cmd))
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        elapsed = time.monotonic() - t0
        logger.error(
            "Step failed: %s after %.2fs (exit %d)", name, elapsed, e.returncode,
            extra={"step": name},
        )
        if e.stdout:
            logger.error("stdout:\n%s", e.stdout)
        if e.stderr:
            logger.error("stderr:\n%s", e.stderr)
        raise
    elapsed = time.monotonic() - t0
    if result.stdout.strip():
        logger.debug("stdout:\n%s", result.stdout)
    if result.stderr.strip():
        logger.debug("stderr:\n%s", result.stderr)
    logger.info("Step done:  %s (%.2fs)", name, elapsed, extra={"step": name})


def enrich_citations(dated_subdirs: list[Path]) -> tuple[int, int]:
    """For each dated subdir with both raw_responses.jsonl and scored_rows.jsonl,
    invoke extract_citations.py --in-place when cited_urls is not yet populated.

    Returns (processed, skipped) counts.
    """
    processed = 0
    skipped = 0
    for subdir in dated_subdirs:
        raw_path = subdir / "raw_responses.jsonl"
        scored_path = subdir / "scored_rows.jsonl"
        if not raw_path.exists() or not scored_path.exists():
            logger.debug(
                "Skipping %s: missing raw_responses.jsonl or scored_rows.jsonl",
                subdir.name,
            )
            skipped += 1
            continue
        if scored_rows_has_citations(scored_path):
            logger.info("Skipping %s: cited_urls already populated", subdir.name)
            skipped += 1
            continue
        cmd = [
            sys.executable,
            str(EXTRACT_CITATIONS_SCRIPT),
            "--raw",
            str(raw_path),
            "--scored",
            str(scored_path),
            "--in-place",
        ]
        run_step(f"extract_citations [{subdir.name}]", cmd)
        processed += 1
    return processed, skipped


def latest_scored_rows(dated_subdirs: list[Path]) -> Optional[Path]:
    """Return the scored_rows.jsonl in the latest dated subdir, if present."""
    for subdir in reversed(dated_subdirs):
        candidate = subdir / "scored_rows.jsonl"
        if candidate.exists():
            return candidate
    return None


def run_attribution(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [
        sys.executable,
        str(ATTRIBUTE_SCRIPT),
        "--runs-dir",
        str(args.runs_dir),
        "--brand-profile",
        str(args.brand_profile),
        "--output-dir",
        str(output_dir),
    ]
    if args.content_planner:
        cmd += ["--content-planner", str(args.content_planner)]
    else:
        cmd += ["--sheet-url", str(args.sheet_url)]
    if args.breakout_threshold_pp is not None:
        cmd += ["--breakout-threshold-pp", str(args.breakout_threshold_pp)]
    if args.strong_lift_pp is not None:
        cmd += ["--strong-lift-pp", str(args.strong_lift_pp)]
    if args.lazy_runs:
        cmd += ["--lazy-runs"]
        if args.lazy_cache_size is not None:
            cmd += ["--lazy-cache-size", str(args.lazy_cache_size)]
    if args.verbose:
        cmd += ["--verbose"]
    cmd += ["--log-format", args.log_format]
    run_step("attribute_content", cmd)


def render_dashboard(args: argparse.Namespace, dated_subdirs: list[Path]) -> None:
    scored = latest_scored_rows(dated_subdirs)
    if scored is None:
        raise FileNotFoundError(
            "No scored_rows.jsonl found under any dated subdir of runs-dir."
        )
    strategy_events = Path(args.output_dir) / "strategy_events.json"
    if not strategy_events.exists():
        raise FileNotFoundError(
            f"strategy_events.json not produced at {strategy_events}; "
            "did attribute_content step run?"
        )
    out_path = Path(args.dashboard_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [
        sys.executable,
        str(RENDER_DASHBOARD_SCRIPT),
        "--scored",
        str(scored),
        "--brand-profile",
        str(args.brand_profile),
        "--queries",
        str(args.queries),
        "--runs-dir",
        str(args.runs_dir),
        "--strategy-events",
        str(strategy_events),
        "--out",
        str(out_path),
    ]
    if args.verbose:
        cmd += ["--verbose"]
    cmd += ["--log-format", args.log_format]
    run_step("render_dashboard", cmd)


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose, args.log_format)
    logger.info("AEO skills root: %s", AEO_SKILLS_ROOT)

    try:
        dated_subdirs = validate_inputs(args)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Input validation failed: %s", e)
        return 2
    logger.info("Validated inputs. Found %d dated run subdirs.", len(dated_subdirs))

    try:
        if args.skip_citations:
            logger.info("Skipping citation enrichment (--skip-citations).")
        else:
            processed, skipped = enrich_citations(dated_subdirs)
            logger.info(
                "Citation enrichment: processed=%d skipped=%d", processed, skipped
            )

        run_attribution(args)

        if args.skip_render:
            logger.info("Skipping dashboard render (--skip-render).")
        else:
            render_dashboard(args, dated_subdirs)
    except subprocess.CalledProcessError:
        return 1
    except (FileNotFoundError, ValueError) as e:
        logger.error("Pipeline failed: %s", e)
        return 1

    logger.info("Pipeline complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
