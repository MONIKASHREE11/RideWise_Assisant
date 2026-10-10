# RideWise Assist

Conversational assistant for bike and EV rental customer support. It uses
Streamlit, a read-only SQLite database, versioned policy-PDF retrieval,
deterministic Python calculators, and a NeoStats OpenAI-compatible endpoint.

## Setup and run

1. Install Python 3.10 or newer, then install the project dependencies:
   `python -m pip install -r requirements.txt`.
2. Copy the provided `ridewise.db` into the project's `data/` directory. The
   database is git-ignored and opened read-only by the app. Keep
   `data_dictionary.md` and the five policy PDFs in `data/` as well.
3. Copy `.env.example` to `.env` and fill in `NEOSTATS_BASE_URL`,
   `NEOSTATS_API_KEY`, `NEOSTATS_MODEL` (the deployed model name), and
   `NEOSTATS_EMBEDDING_MODEL`. Keep `.env` private; it is git-ignored.
4. Start the application with `streamlit run app.py`.
5. Run the tests with `python -m unittest discover -s tests`.

## Architecture

```text
User -> Streamlit UI -> Agent (tool loop with NeoStats LLM)
                        |- run_sql -> safe read-only DB layer (role-scoped views)
                        |- search_policy -> PDF chunks (versioned, cited)
                        |- calculators -> refunds, late fees, GST (cited)
```

The agent gives the model only the columns of the temporary views available to
the current role; a read-only SQLite authorizer, one-`SELECT` validation, and
scoped views enforce access independently of the prompt. Policy and calculation
citations, and only successful SQL statements, are shown in the expandable
Sources panel.

## Data, policies, and calculations

Policy ingestion in `src/policy/retrieval.py` chunks the five policy PDFs with
document, version, section, page, and effective-date metadata. Retrieval uses
BM25 by default; setting `NEOSTATS_EMBEDDING_MODEL` enables embeddings through
the same NeoStats endpoint. Cancellation/refund retrieval requires the
booking's `booked_at` timestamp to select the applicable policy version.
Extracted PDF text is untrusted reference data, never instructions.

Calculators in `src/calculators/` compute rental charges, cancellation refunds,
late-return penalties, damage charges, GST, tier benefits, and EV battery
charges. They return inputs, formulas, results, and policy citations; the LLM
does not perform arithmetic. Policy constants and citations are centralized
in `src/calculators/config.py`.

## Data access and privacy

The database layer in `src/db/safe_sql.py` opens SQLite in read-only mode,
validates a single `SELECT`, applies an authorizer and timeout, and caps rows.
Customer temporary views scope profile data to the session customer and scope
bookings, payments, and damage reports through their booking relationship.
Customer payment/damage views omit free text. Support sessions use temporary
operational views; contact fields are masked and names, phone numbers, and
email addresses in remarks/descriptions are redacted where recognized. Database
text and policy text are untrusted data, never instructions.

The agent uses bounded function calling, with a JSON tool-call fallback if the
endpoint rejects function calling. Role-specific schema guidance and retries
help correct denied SQL; failed statements are logged for diagnostics, not
shown in Sources. Tool, database, and model failures receive plain-language
fallback replies rather than raw errors.

## Configuration

The application reads `NEOSTATS_BASE_URL`, `NEOSTATS_API_KEY`,
`NEOSTATS_MODEL`, and optional embedding configuration from environment
variables or `.env` through `python-dotenv`. Never commit `.env` or put
credentials in source code.
