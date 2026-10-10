# Project Decisions

## 1) Three most important design decisions

1. **Enforce access control in the database layer, not in the prompt.** SQLite
   is opened read-only. Each request can run only one `SELECT`, and an SQLite
   authorizer controls reads. Customer sessions receive per-connection,
   customer-scoped temporary views; support sessions receive operational
   views with contact details masked and free-text remarks/descriptions
   redacted. The model's instructions help it use these views, but are not the
   security boundary.
2. **Keep money and date calculations deterministic.** Python calculators
   compute rentals, refunds, penalties, GST, and related benefits using
   explicit date/time handling. Answers can show each calculation's inputs,
   formula, result, and policy citations. The LLM selects and explains facts;
   it does not perform the arithmetic.
3. **Select cancellation rules from the booking time.** The cancellation
   policy version is chosen using `booked_at`, with the v2 cutover at
   **1 July 2026, 00:00 IST**. Scanned annexure tables that could not be
   extracted as text were transcribed by hand and explicitly flagged as
   transcriptions in their policy-chunk metadata.

## 2) Alternatives rejected

- Unrestricted SQL written by the LLM: it could reach data outside a
  customer's entitlement, so SQL is restricted by read-only connections,
  scoped views, validation, and the authorizer.
- Having the LLM do arithmetic: money and time rules need reproducible,
  testable results, so calculations stay in Python.
- OCR for scanned tables: for this short build, checking and transcribing the
  small number of scanned annexures was faster; those chunks are flagged.
- Showing free-text payment remarks or damage descriptions to customers:
  these can contain personal or untrusted content, so customer views omit
  them.

## 3) Where it currently fails

- The live model can still write SQL against disallowed tables. Role-specific
  schema guidance and retries help, but a denied query can still require a
  retry.
- Name redaction relies on names already present in the customer database;
  unknown names in free text may not be caught.
- Support-agent SQL results are capped at 10 rows per query.
- Completeness checks have not been run for late returns with no penalty row
  or `CNL_S` bookings with no refund row.
- There are 35 penalty rows not reconciled against damage claims.
- The app has no login; the customer ID entered in the session is not proof of
  identity.
- The database authorizer rejects `COUNT(*)` on views, so the agent is told to
  count with `COUNT(<id column>)` instead.
- Live testing against the NeoStats model covered a small set of questions
  (customer bookings, cancellation refund, cross-customer refusal, towing
  charge, and three support queries), not a large adversarial set.

Read-only reconciliation results: rental calculations matched **1,795 of
1,800** bookings; the five unmatched rental payments were still pending.
Calculated late fees matched **435 of 435** rows, and battery fees matched
**47 of 47** rows. Refund calculations matched **104 of 107** rows; the three
remaining differences were **₹0.01** rounding differences.

The project has 45 automated tests covering SQL safety, calculators, policy
retrieval, agent routing, and error handling.

## 4) Next week

- Add authentication and bind customer identity to the authenticated session.
- Expand adversarial tests for SQL, role boundaries, untrusted text, and
  ambiguous requests.
- Run the missing completeness checks for late-return penalties and
  RideWise-initiated cancellations/refunds.
- Improve personal-information detection with fuzzy redaction beyond known
  customer names.
- Build an evaluation harness with hidden-style questions and measurable
  expected answers, citations, and access-control outcomes.
