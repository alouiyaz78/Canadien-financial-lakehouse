"""Command-line entry point: ``uv run cfl <command>``.

cfl ingest [--only NAME ...] [--source SOURCE]               download raw data (Bronze)
cfl silver                                                    parse + quality report
cfl gold                                                      monthly model table (ML, real-time aligned)
cfl bi                                                        Power BI star schema at reference dates
cfl run [--force]                                             ingest, then silver + gold only if data changed
cfl freshness                                                 flag series whose latest observation is late
cfl status                                                    last observation per series
cfl history                                                   Delta versions of Silver and Gold (time travel)
cfl verify-sources                                            check ids against source metadata
"""

from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from cfl import bronze, gold, silver
from cfl.config import data_dir, load_registry
from cfl.sources import client_for
from cfl.sources.base import make_session

log = logging.getLogger("cfl")


def _ingest(args: argparse.Namespace) -> list[bronze.IngestResult]:
    specs = load_registry().select(args.only, args.source)
    results = bronze.ingest(specs, tag=args.source or "")
    failed = [r for r in results if not r.ok]
    changed = [r.name for r in results if r.changed]
    print(
        f"\nBronze: {len(results) - len(failed)}/{len(results)} series fetched, "
        f"{len(changed)} changed, into {data_dir() / 'bronze'}"
    )
    if changed:
        print("  changed: " + ", ".join(changed))
    for r in failed:
        print(f"  FAILED {r.name}: {r.error}")
    return results


def _cmd_ingest(args: argparse.Namespace) -> int:
    return 1 if any(not r.ok for r in _ingest(args)) else 0


def _cmd_silver(_: argparse.Namespace) -> int:
    _, report = silver.build_silver(load_registry().series)
    print(f"\nSilver quality report → {silver.silver_dir() / 'quality_report.csv'}")
    return 0


def _cmd_gold(_: argparse.Namespace) -> int:
    table = gold.build_gold(silver.read_silver(), load_registry())
    print(f"\nGold table: {table.shape[0]} months x {table.shape[1]} columns → {gold.gold_dir()}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    results = _ingest(args)
    code = 1 if any(not r.ok for r in results) else 0
    silver_exists = (silver.silver_dir() / "observations" / "_delta_log").exists()
    if not (args.force or not silver_exists or any(r.changed for r in results)):
        print("\nNo source changed since the last run: Silver and Gold are up to date (use --force to rebuild).")
        return code
    _cmd_silver(args)
    _cmd_gold(args)
    _cmd_bi(args)
    return code


def _cmd_bi(_: argparse.Namespace) -> int:
    from cfl import bi

    tables = bi.build_bi_tables(silver.read_silver(), load_registry())
    out = bi.write_local(tables)
    print(f"\nBI marts ({len(tables)} tables) → {out}")
    for name, frame in tables.items():
        print(f"  {name:28s} {len(frame):>7} rows")
    return 0


def _cmd_freshness(_: argparse.Namespace) -> int:
    from cfl.freshness import freshness_report

    report = pd.read_csv(silver.silver_dir() / "quality_report.csv", parse_dates=["last_date"])
    fresh = freshness_report(report.set_index("name")["last_date"], load_registry())
    with pd.option_context("display.width", 160, "display.max_rows", 200):
        print(fresh.drop(columns="checked_at").to_string(index=False))
    late = fresh[fresh["status"].isin(["late", "missing"])]
    print(f"\n{len(late)} series late or missing" if len(late) else "\nAll series are fresh.")
    return 1 if len(late) else 0


def _cmd_status(_: argparse.Namespace) -> int:
    report = pd.read_csv(silver.silver_dir() / "quality_report.csv")
    cols = ["name", "source", "frequency", "first_date", "last_date", "last_value", "n_clean"]
    if "parse_error" in report.columns:
        cols.append("parse_error")
    with pd.option_context("display.width", 160, "display.max_rows", 200):
        print(report[cols].to_string(index=False))
    return 0


def _cmd_history(_: argparse.Namespace) -> int:
    from cfl.storage import history

    for label, path in [
        ("silver/observations", silver.silver_dir() / "observations"),
        ("gold/model_table_monthly", gold.gold_dir() / "model_table_monthly"),
    ]:
        print(f"\n{label}")
        if not (path / "_delta_log").exists():
            print("  (no Delta table yet — run `uv run cfl run`)")
            continue
        print(history(path).to_string(index=False))
    return 0


def _cmd_verify(_: argparse.Namespace) -> int:
    session = make_session()
    problems = 0
    for spec in load_registry().series:
        if spec.source == "fred":
            continue  # FRED ids are self-describing; a bad id fails loudly at ingestion
        try:
            meta = client_for(spec.source).fetch_metadata(spec.source_id, session)
            title = meta.get("SeriesTitleEn") or meta.get("label") or meta.get("description") or "?"
            flag = "" if spec.verified else "   <-- compare with the registry description"
            print(f"ok   {spec.name:28s} {spec.source}:{spec.source_id:24s} {title}{flag}")
        except Exception as exc:  # noqa: BLE001
            problems += 1
            print(f"FAIL {spec.name:28s} {spec.source}:{spec.source_id:24s} {exc}")
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfl", description="Canadian Financial Lakehouse pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, func, help_text in [
        ("ingest", _cmd_ingest, "download raw data into Bronze"),
        ("run", _cmd_run, "ingest + silver + gold"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--only", nargs="+", metavar="NAME", help="restrict to these series names")
        p.add_argument("--source", choices=["valet", "statcan", "fred", "census"])
        if name == "run":
            p.add_argument("--force", action="store_true", help="rebuild Silver and Gold even if nothing changed")
        p.set_defaults(func=func)

    for name, func, help_text in [
        ("silver", _cmd_silver, "parse Bronze into the Silver table"),
        ("gold", _cmd_gold, "build the monthly model table"),
        ("bi", _cmd_bi, "build the Power BI star schema (data/gold/bi/)"),
        ("status", _cmd_status, "show last observation per series"),
        ("history", _cmd_history, "list Delta table versions (time travel)"),
        ("freshness", _cmd_freshness, "flag series whose latest observation is late"),
        ("verify-sources", _cmd_verify, "check series ids against source metadata"),
    ]:
        sub.add_parser(name, help=help_text).set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
