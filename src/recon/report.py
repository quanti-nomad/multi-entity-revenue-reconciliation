"""Turn a ReconResult into files a finance team can act on."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .reconcile import MATCHED, ReconResult

STATUS_NOTES = {
    "matched": "Exact match",
    "matched_timing": "Posted late but within the timing window",
    "entity_mismatch": "Booked to the wrong legal entity; reclass needed",
    "amount_variance": "Amount differs from CRM; investigate",
    "missing_in_ledger": "CRM revenue with no deposit; post or explain",
    "duplicate_in_ledger": "Deposit posted twice; reverse one",
    "unexpected_in_ledger": "Deposit with no CRM revenue; investigate",
    "unmapped_location": "Location missing from entity map; add mapping",
}


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def entity_summary(result: ReconResult) -> pd.DataFrame:
    """Per-entity totals. Unmapped-location activity gets its own row so it
    does not distort the entity it is actually booked to."""
    lines = result.lines[result.lines["status"] != "unmapped_location"]
    exp = lines.groupby("entity_id")["expected_cents"].sum()
    led = lines.dropna(subset=["ledger_entity_id"]).groupby("ledger_entity_id")["ledger_cents"].sum()
    exc = lines[~lines["status"].isin(MATCHED)].groupby("entity_id").size()
    df = pd.DataFrame({"crm_cents": exp, "ledger_cents": led, "exceptions": exc}).fillna(0)
    df = df.astype("int64")
    df.index.name = "entity_id"
    df = df.reset_index().sort_values("entity_id")

    unmapped = result.lines[result.lines["status"] == "unmapped_location"]
    if len(unmapped) or len(result.unmapped_crm):
        df.loc[len(df)] = {
            "entity_id": "UNMAPPED",
            "crm_cents": int(result.unmapped_crm["cents"].sum()),
            "ledger_cents": int(unmapped["ledger_cents"].sum()),
            "exceptions": len(unmapped),
        }
    df["difference_cents"] = df["crm_cents"] - df["ledger_cents"]
    return df


def write_outputs(result: ReconResult, folder: str | Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    result.lines.to_csv(folder / "all_lines.csv", index=False)
    result.exceptions.to_csv(folder / "exceptions.csv", index=False)
    summary = entity_summary(result)
    summary.to_csv(folder / "entity_summary.csv", index=False)

    t = result.tie_out
    counts = result.lines["status"].value_counts()
    status_rows = "\n".join(
        f"| {s} | {int(counts.get(s, 0)):,} | {STATUS_NOTES[s]} |" for s in STATUS_NOTES
    )
    entity_rows = "\n".join(
        f"| {r.entity_id} | {_money(r.crm_cents)} | {_money(r.ledger_cents)} | "
        f"{_money(r.difference_cents)} | {r.exceptions} |"
        for r in summary.itertuples()
    )
    md = f"""# Reconciliation summary

## Tie-out

| | Amount |
| --- | --- |
| CRM revenue | {_money(t['crm_total_cents'])} |
| Ledger deposits | {_money(t['ledger_total_cents'])} |
| Difference | {_money(t['difference_cents'])} |
| Explained by exceptions | {_money(t['explained_cents'])} |
| Unexplained | {_money(t['unexplained_cents'])} |

**Fully explained to the cent: {"yes" if t['fully_explained'] else "NO"}**

## Lines by status

| Status | Lines | Action |
| --- | --- | --- |
{status_rows}

## By entity

| Entity | CRM | Ledger | Difference | Exceptions |
| --- | --- | --- | --- | --- |
{entity_rows}
"""
    path = folder / "summary.md"
    path.write_text(md)
    return path
