import pandas as pd
import pytest

from recon import generate, reconcile
from recon.report import entity_summary

ISSUE_TO_STATUS = {
    "timing": "matched_timing",
    "missing": "missing_in_ledger",
    "duplicate": "duplicate_in_ledger",
    "variance": "amount_variance",
    "entity_mismatch": "entity_mismatch",
}


@pytest.fixture(scope="module")
def run():
    data = generate(days=60, seed=7)
    return data, reconcile(data.crm, data.ledger, data.location_map)


def test_tie_out_is_exact(run):
    _, result = run
    assert result.tie_out["fully_explained"]
    assert result.tie_out["unexplained_cents"] == 0


def test_every_injected_issue_is_found_and_classified(run):
    data, result = run
    key = data.answer_key.dropna(subset=["txn_date"])
    for issue, status in ISSUE_TO_STATUS.items():
        expected = {(r.location_id, str(r.txn_date)) for r in key[key.issue == issue].itertuples()}
        found = result.lines[result.lines.status == status]
        date_col = "ledger_date" if status == "duplicate_in_ledger" else "crm_date"
        got = {(r.location_id, str(getattr(r, date_col))) for r in found.itertuples()}
        assert got == expected, f"{issue}: missed {expected - got}, false positives {got - expected}"


def test_no_unexplained_exceptions(run):
    _, result = run
    assert (result.lines.status == "unexpected_in_ledger").sum() == 0


def test_unmapped_location_is_isolated(run):
    data, result = run
    unmapped = data.answer_key.loc[data.answer_key.issue == "unmapped_location", "location_id"].item()
    assert set(result.unmapped_crm.location_id) == {unmapped}
    summary = entity_summary(result)
    assert "UNMAPPED" in set(summary.entity_id)


def _tiny(ledger_rows):
    crm = pd.DataFrame([
        {"txn_id": "T1", "location_id": "L1", "txn_date": "2026-01-01", "amount": 100.00},
        {"txn_id": "T2", "location_id": "L1", "txn_date": "2026-01-01", "amount": 50.25},
    ])
    ledger = pd.DataFrame(ledger_rows)
    loc_map = pd.DataFrame([{"location_id": "L1", "entity_id": "E1"}])
    return reconcile(crm, ledger, loc_map, timing_window_days=3)


def test_exact_match_uses_cents():
    r = _tiny([{"deposit_id": "D1", "entity_id": "E1", "location_id": "L1",
                "deposit_date": "2026-01-01", "amount": 150.25}])
    assert r.lines.status.tolist() == ["matched"]


def test_late_deposit_outside_window_is_not_a_match():
    r = _tiny([{"deposit_id": "D1", "entity_id": "E1", "location_id": "L1",
                "deposit_date": "2026-01-09", "amount": 150.25}])
    assert sorted(r.lines.status) == ["missing_in_ledger", "unexpected_in_ledger"]
    assert r.tie_out["fully_explained"]
