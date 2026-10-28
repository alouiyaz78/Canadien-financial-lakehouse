"""Command-line entry point: ``uv run cfl <command>``.

cfl ingest [--only NAME ...] [--source valet|statcan|fred]   download raw data (Bronze)
cfl silver                                                    parse + quality report
cfl gold                                                      monthly model table
cfl run                                                       ingest + silver + gold
cfl status                                                    last observation per series
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


def _cmd_ingest(args: argparse.Namespace) -> int:
    specs = load_registry().select(args.only, args.source)
    results = bronze.ingest(specs)
    failed = [r for r in results if not r.ok]
    print(f"\nBronze: {len(results) - len(failed)}/{len(results)} series ingested into {data_dir() / 'bronze'}")
    for r in failed:
        print(f"  FAILED {r.name}: {r.error}")
    return 1 if failed else 0


def _cmd_silver(_: argparse.Namespace) -> int:
    _, report = silver.build_silver(load_registry().series)
    print(f"\nSilver quality report → {silver.silver_dir() / 'quality_report.csv'}")
    return 0


def _cmd_gold(_: argparse.Namespace) -> int:
    table = gold.build_gold(silver.read_silver(), load_registry())
    print(f"\nGold table: {table.shape[0]} months x {table.shape[1]} columns → {gold.gold_dir()}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    code = _cmd_ingest(args)
    _cmd_silver(args)
    _cmd_gold(args)
    return code


def _cmd_status(_: argparse.Namespace) -> int:
    report = pd.read_csv(silver.silver_dir() / "quality_report.csv")
    cols = ["name", "source", "frequency", "first_date", "last_date", "last_value", "n_clean"]
    with pd.option_context("display.width", 160, "display.max_rows", 200):
        print(report[cols].to_string(index=False))
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
        p.set_defaults(func=func)

    for name, func, help_text in [
        ("silver", _cmd_silver, "parse Bronze into the Silver table"),
        ("gold", _cmd_gold, "build the monthly model table"),
        ("status", _cmd_status, "show last observation per series"),
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
