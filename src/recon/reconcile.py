"""Reconcile CRM revenue against accounting deposits across many legal entities.

Matching runs in tiers, from strictest to loosest, so every deposit is claimed
by the most confident rule that fits it:

1. exact             same location, entity, date and amount
2. entity_mismatch   same location, date and amount, but booked to another entity
3. timing            same location, entity and amount, posted within N days
4. amount_variance   same location, entity and date, different amount

Anything left over is classified as missing, duplicated, unexpected or
unmapped. All money is handled as integer cents, so the tie-out is exact.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

MATCHED = {"matched", "matched_timing"}


@dataclass
class ReconResult:
    lines: pd.DataFrame          # one row per expected deposit or leftover ledger deposit
    unmapped_crm: pd.DataFrame   # CRM rows whose location has no entity mapping
    tie_out: dict                # totals and the fully explained difference

    @property
    def exceptions(self) -> pd.DataFrame:
        return self.lines[~self.lines["status"].isin(MATCHED)].reset_index(drop=True)


def _to_cents(s: pd.Series) -> pd.Series:
    return (s.astype(float) * 100).round().astype("int64")


def _to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.date


def reconcile(
    crm: pd.DataFrame,
    ledger: pd.DataFrame,
    location_map: pd.DataFrame,
    timing_window_days: int = 3,
) -> ReconResult:
    crm = crm.copy()
    ledger = ledger.copy()
    crm["txn_date"] = _to_date(crm["txn_date"])
    crm["cents"] = _to_cents(crm["amount"])
    ledger["deposit_date"] = _to_date(ledger["deposit_date"])
    ledger["cents"] = _to_cents(ledger["amount"])

    # --- 1. Map every CRM location to its legal entity ---------------------
    crm = crm.merge(location_map, on="location_id", how="left")
    unmapped_crm = crm[crm["entity_id"].isna()].drop(columns="entity_id")
    unmapped_locations = set(unmapped_crm["location_id"])

    expected = (
        crm.dropna(subset=["entity_id"])
        .groupby(["entity_id", "location_id", "txn_date"], as_index=False)
        .agg(expected_cents=("cents", "sum"), txn_count=("txn_id", "count"))
    )

    # --- 2. Index ledger deposits for fast lookups -------------------------
    open_deposits = set(ledger.index)
    by_exact = defaultdict(list)  # (location, date, cents) -> [idx]
    by_loc_cents = defaultdict(list)  # (location, cents) -> [idx]
    by_loc_date = defaultdict(list)  # (location, date) -> [idx]
    for idx, r in ledger.iterrows():
        by_exact[(r.location_id, r.deposit_date, r.cents)].append(idx)
        by_loc_cents[(r.location_id, r.cents)].append(idx)
        by_loc_date[(r.location_id, r.deposit_date)].append(idx)

    def claim(candidates, predicate):
        for idx in candidates:
            if idx in open_deposits and predicate(ledger.loc[idx]):
                open_deposits.discard(idx)
                return idx
        return None

    lines = []

    def record(status, exp=None, dep_idx=None):
        dep = ledger.loc[dep_idx] if dep_idx is not None else None
        exp_c = int(exp.expected_cents) if exp is not None else 0
        dep_c = int(dep.cents) if dep is not None else 0
        lines.append({
            "status": status,
            "entity_id": exp.entity_id if exp is not None else dep.entity_id,
            "ledger_entity_id": dep.entity_id if dep is not None else None,
            "location_id": exp.location_id if exp is not None else dep.location_id,
            "crm_date": exp.txn_date if exp is not None else None,
            "ledger_date": dep.deposit_date if dep is not None else None,
            "expected_cents": exp_c,
            "ledger_cents": dep_c,
            "delta_cents": exp_c - dep_c,
            "deposit_id": dep.deposit_id if dep is not None else None,
        })

    # --- 3. Tiered matching -------------------------------------------------
    pending = list(expected.itertuples(index=False))

    passes = [
        ("matched", lambda e: by_exact[(e.location_id, e.txn_date, e.expected_cents)],
         lambda e: lambda d: d.entity_id == e.entity_id),
        ("entity_mismatch", lambda e: by_exact[(e.location_id, e.txn_date, e.expected_cents)],
         lambda e: lambda d: d.entity_id != e.entity_id),
        ("matched_timing", lambda e: by_loc_cents[(e.location_id, e.expected_cents)],
         lambda e: lambda d: d.entity_id == e.entity_id
         and abs((d.deposit_date - e.txn_date).days) <= timing_window_days),
        ("amount_variance", lambda e: by_loc_date[(e.location_id, e.txn_date)],
         lambda e: lambda d: d.entity_id == e.entity_id),
    ]
    for status, candidates, rule in passes:
        still_pending = []
        for e in pending:
            idx = claim(candidates(e), rule(e))
            if idx is None:
                still_pending.append(e)
            else:
                record(status, e, idx)
        pending = still_pending

    for e in pending:
        record("missing_in_ledger", e)

    # --- 4. Classify leftover ledger deposits ------------------------------
    claimed_keys = {
        (r["location_id"], r["ledger_date"], r["ledger_cents"])
        for r in lines if r["deposit_id"] is not None
    }
    for idx in sorted(open_deposits):
        d = ledger.loc[idx]
        if d.location_id in unmapped_locations:
            status = "unmapped_location"
        elif (d.location_id, d.deposit_date, d.cents) in claimed_keys:
            status = "duplicate_in_ledger"
        else:
            status = "unexpected_in_ledger"
        record(status, None, idx)

    lines_df = pd.DataFrame(lines)

    # --- 5. Tie-out: explain every cent of the difference -------------------
    crm_total = int(crm["cents"].sum())
    ledger_total = int(ledger["cents"].sum())
    by_status = lines_df.groupby("status")["delta_cents"].sum().to_dict()
    unmapped_net = int(unmapped_crm["cents"].sum()) + int(by_status.get("unmapped_location", 0))
    explained = unmapped_net + sum(
        int(v) for k, v in by_status.items() if k != "unmapped_location"
    )
    tie_out = {
        "crm_total_cents": crm_total,
        "ledger_total_cents": ledger_total,
        "difference_cents": crm_total - ledger_total,
        "explained_cents": explained,
        "unexplained_cents": (crm_total - ledger_total) - explained,
        "fully_explained": (crm_total - ledger_total) == explained,
    }
    return ReconResult(lines=lines_df, unmapped_crm=unmapped_crm, tie_out=tie_out)
