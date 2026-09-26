"""Command line entry point.

    python -m recon demo                  # generate data, reconcile, write report
    python -m recon generate --out data
    python -m recon run --data data --out output
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .generate import generate
from .reconcile import reconcile
from .report import write_outputs


def _load(folder: Path):
    return (
        pd.read_csv(folder / "crm_transactions.csv"),
        pd.read_csv(folder / "ledger_deposits.csv"),
        pd.read_csv(folder / "location_entity_map.csv"),
    )


def _run(data: Path, out: Path, window: int) -> None:
    crm, ledger, loc_map = _load(data)
    result = reconcile(crm, ledger, loc_map, timing_window_days=window)
    path = write_outputs(result, out)
    t = result.tie_out
    print(f"CRM ${t['crm_total_cents']/100:,.2f} vs ledger ${t['ledger_total_cents']/100:,.2f}")
    print(f"{len(result.exceptions):,} exceptions, fully explained: {t['fully_explained']}")
    print(f"Report: {path}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="recon", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="create synthetic data")
    g.add_argument("--out", default="data")
    g.add_argument("--entities", type=int, default=11)
    g.add_argument("--locations", type=int, default=58)
    g.add_argument("--days", type=int, default=90)
    g.add_argument("--seed", type=int, default=42)

    r = sub.add_parser("run", help="reconcile data in a folder")
    r.add_argument("--data", default="data")
    r.add_argument("--out", default="output")
    r.add_argument("--window", type=int, default=3, help="timing window in days")

    sub.add_parser("demo", help="generate + run with defaults")

    a = p.parse_args(argv)
    if a.cmd == "generate":
        generate(a.entities, a.locations, a.days, seed=a.seed).save(a.out)
        print(f"Synthetic data written to {a.out}/")
    elif a.cmd == "run":
        _run(Path(a.data), Path(a.out), a.window)
    else:
        generate().save("data")
        _run(Path("data"), Path("output"), 3)


if __name__ == "__main__":
    main()
