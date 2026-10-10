# RideWise Assist

Conversational assistant for bike and EV rental customer support, using a
Streamlit chat UI, a read-only SQLite database, policy PDF retrieval, and a
NeoStats OpenAI-compatible endpoint.

## Run locally

1. Use Python 3.10 or newer.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set the NeoStats base URL, API key, and
   model. Keep `.env` private; credentials are read from environment variables
   through `python-dotenv`.
4. Keep the supplied database and dictionary in `data/` (the database is
   opened read-only).
5. Start the UI with `streamlit run app.py`.

The agent uses bounded function calls (or JSON tool calls when function calling
is rejected) for scoped SQL, policy retrieval, and deterministic calculations.
Policy ingestion and retrieval helpers in `src/policy/retrieval.py` extract
chunks from the five numbered policy
PDFs with document/version/section/page/effective-date metadata. Retrieval
uses BM25 by default. Setting `NEOSTATS_EMBEDDING_MODEL` enables embeddings
through the same NeoStats-compatible endpoint and credentials. Cancellation
or refund retrieval requires the booking creation date so it can select the
applicable cancellation-policy version. Retrieved `PolicyChunk` objects
provide citation metadata via `.citation()` for later display in Sources.
Extracted PDF text is untrusted reference data and is never treated as
instructions.

Database, model, and tool exceptions are logged for diagnostics but translated
by the UI boundary into short, plain-language replies; raw SQL, SQLite, or
Python error text is not shown to users.

Deterministic calculations are available in `src/calculators/`. Cancellation
refunds select v1/v2 using the booking time in IST, use only successful booking
payments as paid amounts, and account for completed refunds. Late-return,
damage, GST, tier grace-period, and EV low-battery calculations return their
inputs, formula, result, and policy citations. Policy constants and citations
are centralized in `src/calculators/config.py`.

The database helper is available in `src/db/safe_sql.py`; it opens SQLite in read-only mode,
allows only one SELECT statement, applies an SQLite authorizer and timeout,
and caps returned rows. Per-connection customer views scope profile data by
customer ID and scope bookings, payments, and damage reports through the
booking relationship. Customer payment and damage views expose only structured
fields; they omit free-text remarks and descriptions. Support sessions use
temporary views; free-text fields have phone numbers, email addresses, and
customer-name tokens redacted before exposure. Those fields remain untrusted
data, never instructions: the answering agent must not follow or quote personal
information from them. The sample wrapper
in `data/` is excluded from Git because it contains an embedded credential;
the application client instead reads `NEOSTATS_BASE_URL`, `NEOSTATS_API_KEY`,
and `NEOSTATS_MODEL` from the environment or `.env`.

Run the tests with `python -m unittest discover -s tests`.
