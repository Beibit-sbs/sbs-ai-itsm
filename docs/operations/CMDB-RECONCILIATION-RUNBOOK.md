# CMDB reconciliation runbook

## Operating model

Every automated or file-based CMDB feed must use a registered CMDB source.
Do not write discovered data directly to `assets`.

Source priority uses ascending trust:

- `1` is strongest;
- `1000` is weakest;
- a source can always update fields it already owns;
- a stronger source can take ownership from a weaker source;
- a weaker source cannot overwrite a stronger-owned field;
- nonempty manual/unowned values are preserved unless the source explicitly
  has `claim_unowned_fields=true`.

Use `claim_unowned_fields` sparingly. It is appropriate for an authoritative
discovery or ERP feed after its scope and mapping are approved.

## Safe ingestion sequence

1. Register and activate the source.
2. Configure ordered identification rules. Prefer stable identifiers:
   `serial_number`, `inventory_number`, and `asset_tag`. Use `name` only as a
   low-trust fallback.
3. Configure only the fields for which the source is authoritative.
4. Send 1-500 records to preview with a unique idempotency key.
5. Review create/update/protected/invalid/ambiguous counts and record details.
6. Correct invalid source data and create a new preview.
7. Resolve duplicate candidates. After a merge, create a new preview for the
   affected payload.
8. Apply only a clean preview.
9. Confirm source health, run status, CI history, and field ownership.

The same idempotency key with the same payload returns the existing run. The
same key with a different payload fails with a conflict.

## Apply safety

Apply fails closed when:

- the source is inactive;
- the run is not in `PREVIEWED`;
- any invalid record remains;
- any ambiguous record remains;
- a source identity conflicts with a different identified CI;
- a class/schema/owner reference is unavailable.

Runtime apply rechecks field ownership. A field that became protected after
preview is not overwritten.

## Duplicate decisions

`Dismiss` records that two CIs are intentionally separate.

`Merge` requires the current candidate version and both current CI versions.
It:

- keeps the primary CI;
- fills only empty primary values from the duplicate;
- rewires supported operational references;
- preserves relationship constraints;
- transfers source identities and the strongest field ownership;
- retires, but does not delete, the duplicate;
- writes histories on both CIs and a tamper-evident audit event.

Review the merge summary and histories after every merge. If the wrong CI was
chosen as primary, do not delete either CI; restore references through a
reviewed corrective change.

## Built-in Excel import

Excel upload uses source `EXCEL_ASSET_IMPORT` with priority `300`.

- Preview parses the workbook and creates one or more CMDB reconciliation
  runs in chunks of 500 valid records.
- Duplicate rows inside the file are skipped deterministically.
- Invalid or ambiguous CMDB rows block commit.
- Commit applies clean runs and stores their IDs in the import summary.
- Imported CIs retain `source=excel_import` for compatibility while their
  source identity and per-field ownership are governed by CMDB.

## Freshness response

An active source is stale when it has never completed successfully or its last
success exceeds `stale_after_hours`.

For a stale source:

1. inspect the last run and its record errors;
2. confirm upstream credentials/connectivity outside CMDB;
3. do not weaken priority or enable `claim_unowned_fields` as a workaround;
4. rerun preview with a new idempotency key;
5. escalate if freshness cannot be restored within the source owner's SLO.
