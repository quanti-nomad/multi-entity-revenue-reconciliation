# Case study: daily revenue reconciliation across 11 legal entities

*Company details are anonymized. The code in this repository is a clean-room rebuild on synthetic data.*

## Context

A multi-location healthcare and wellness organization operates two brands across dozens of locations. Sales are recorded in a single CRM, but the books are kept in a separate accounting company file for each of 11 legal entities. Every day, revenue from each location has to land as a deposit in the right entity's books.

## The problem

Reconciliation was manual and slow. The finance team compared CRM exports to accounting reports in spreadsheets, entity by entity. Totals were often "close," which hid real problems: deposits booked to the wrong entity, late postings that crossed month-end, duplicates, and new locations that had never been mapped to an entity after openings and an acquisition.

## What I built

- **Direct integrations** to the accounting system's API for all 11 entities and to the CRM database, replacing manual exports.
- **A tiered matching engine** that pairs each day's expected revenue per location with its deposit, strictest rule first, and classifies every leftover into an action a finance team understands: reclass, reverse, post, or investigate.
- **A cent-level tie-out** that proves the total difference is fully explained by classified exceptions, with nothing left unexplained.
- **A daily run** that surfaces exceptions in the BI layer, so issues are caught the next morning instead of at month-end.
- **A chart-of-accounts audit** run alongside the reconciliation, flagging accounts that were mis-mapped or inconsistent across entities.

## Outcome

- Year-to-date revenue across all 11 entities tied out to the cent.
- Hundreds of chart-of-accounts issues surfaced for review and cleanup.
- Reconciliation moved from a manual monthly exercise to an automated daily check.
- The same data foundation now feeds executive and board reporting, and AI-assisted finance workflows with a person approving every posting.

## What I'd do next

- Land both sources in a cloud data warehouse, so the engine is independent of any single BI tool.
- Add an AI step that drafts the explanation and journal entry for each exception for accounting to approve.
- Track exception rates per location and entity as an operational KPI.

## Skills demonstrated

Data engineering (API integrations, Python pipelines), accounting data modeling across multiple entities, data quality and certification, BI delivery, and AI-assisted finance automation.
