"""Generate synthetic CRM transactions and accounting deposits.

The data mimics a multi-location, multi-entity business: every location belongs
to one legal entity, the CRM records individual sales, and the accounting system
records one deposit per location per day. A small share of deposits is
deliberately corrupted (late, missing, duplicated, wrong amount, wrong entity)
and every corruption is written to an answer key, so the engine's accuracy can
be measured instead of assumed.

No real company, patient or financial data is used anywhere in this project.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CATEGORIES = ["membership", "iv_therapy", "diagnostics", "aesthetics", "retail"]
METHODS = ["card", "ach", "cash"]

# Share of daily deposits that receive each injected issue.
ISSUE_RATES = {
    "timing": 0.020,          # posted 1-3 days late
    "missing": 0.005,         # never posted
    "duplicate": 0.003,       # posted twice
    "variance": 0.005,        # posted with the wrong amount
    "entity_mismatch": 0.003, # posted to the wrong legal entity
}


@dataclass
class SyntheticData:
    crm: pd.DataFrame
    ledger: pd.DataFrame
    location_map: pd.DataFrame
    answer_key: pd.DataFrame

    def save(self, folder: str | Path) -> None:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.crm.to_csv(folder / "crm_transactions.csv", index=False)
        self.ledger.to_csv(folder / "ledger_deposits.csv", index=False)
        self.location_map.to_csv(folder / "location_entity_map.csv", index=False)
        self.answer_key.to_csv(folder / "answer_key.csv", index=False)


def generate(
    n_entities: int = 11,
    n_locations: int = 58,
    days: int = 90,
    start: str = "2026-01-01",
    seed: int = 42,
) -> SyntheticData:
    rng = np.random.default_rng(seed)
    entities = [f"ENT-{i:02d}" for i in range(1, n_entities + 1)]
    locations = [f"LOC-{i:03d}" for i in range(1, n_locations + 1)]
    true_entity = {loc: entities[i % n_entities] for i, loc in enumerate(locations)}

    # One location is left out of the mapping table on purpose: a new site
    # that accounting knows about but the data team has not mapped yet.
    unmapped = locations[-1]
    location_map = pd.DataFrame(
        [{"location_id": l, "entity_id": e} for l, e in true_entity.items() if l != unmapped]
    )

    # --- CRM: individual transactions -------------------------------------
    dates = pd.date_range(start, periods=days, freq="D").date
    rows = []
    txn = 0
    for d in dates:
        for loc in locations:
            for _ in range(rng.poisson(6)):
                txn += 1
                amount = round(float(rng.lognormal(mean=5.0, sigma=0.6)), 2)
                rows.append(
                    (f"TXN-{txn:07d}", loc, d, amount, rng.choice(METHODS), rng.choice(CATEGORIES))
                )
    crm = pd.DataFrame(
        rows,
        columns=["txn_id", "location_id", "txn_date", "amount", "payment_method", "service_category"],
    )

    # --- Ledger: one clean deposit per location per day --------------------
    crm["_cents"] = (crm["amount"] * 100).round().astype("int64")
    daily = crm.groupby(["location_id", "txn_date"], as_index=False)["_cents"].sum()
    crm = crm.drop(columns="_cents")
    daily["entity_id"] = daily["location_id"].map(true_entity)
    daily["deposit_date"] = daily["txn_date"]

    # --- Inject issues on disjoint rows ------------------------------------
    # Issues are only injected on mapped locations so each one has a single,
    # unambiguous expected classification.
    eligible = daily.index[daily["location_id"] != unmapped].to_numpy()
    order = rng.permutation(eligible)
    cursor = 0
    picked: dict[str, np.ndarray] = {}
    for issue, rate in ISSUE_RATES.items():
        n = max(1, int(round(rate * len(eligible))))
        picked[issue] = order[cursor : cursor + n]
        cursor += n

    key_rows = []

    def log(issue: str, idx: int, detail: str) -> None:
        r = daily.loc[idx]
        key_rows.append(
            {"issue": issue, "location_id": r.location_id, "txn_date": r.txn_date, "detail": detail}
        )

    for idx in picked["timing"]:
        lag = int(rng.integers(1, 4))
        daily.loc[idx, "deposit_date"] = daily.loc[idx, "txn_date"] + pd.Timedelta(days=lag)
        log("timing", idx, f"posted {lag} day(s) late")
    for idx in picked["variance"]:
        delta = int(rng.integers(-5000, 5000)) or 137
        daily.loc[idx, "_cents"] += delta
        log("variance", idx, f"amount off by {delta / 100:+.2f}")
    for idx in picked["entity_mismatch"]:
        right = daily.loc[idx, "entity_id"]
        wrong = rng.choice([e for e in entities if e != right])
        daily.loc[idx, "entity_id"] = wrong
        log("entity_mismatch", idx, f"posted to {wrong} instead of {right}")
    for idx in picked["missing"]:
        log("missing", idx, "never posted")
    for idx in picked["duplicate"]:
        log("duplicate", idx, "posted twice")

    ledger = daily.drop(index=picked["missing"])
    ledger = pd.concat([ledger, daily.loc[picked["duplicate"]]], ignore_index=True)
    ledger = ledger.sample(frac=1, random_state=seed).reset_index(drop=True)
    ledger["deposit_id"] = [f"DEP-{i:06d}" for i in range(1, len(ledger) + 1)]
    ledger["amount"] = ledger["_cents"] / 100
    ledger["memo"] = "Daily revenue " + ledger["location_id"]
    ledger = ledger[["deposit_id", "entity_id", "location_id", "deposit_date", "amount", "memo"]]

    # The unmapped location's deposits show up in the ledger with no CRM
    # counterpart the engine can place, so they are part of the answer key too.
    key_rows.append(
        {"issue": "unmapped_location", "location_id": unmapped, "txn_date": None,
         "detail": "location missing from mapping table"}
    )
    answer_key = pd.DataFrame(key_rows)
    return SyntheticData(crm=crm, ledger=ledger, location_map=location_map, answer_key=answer_key)
