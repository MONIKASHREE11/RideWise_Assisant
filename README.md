# RideWise Assist

A phase-one scaffold for a conversational assistant for bike and EV rentals.
The current chat agent is an echo stub; database retrieval, policy retrieval,
and NeoStats calls are not wired into the conversation yet.

## Run locally

1. Use Python 3.10 or newer.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set the NeoStats base URL, API key, and
   model. Keep `.env` private; credentials are read from environment variables
   through `python-dotenv` when the LLM client is implemented.
4. Keep the supplied database and dictionary in `data/` (the database is
   opened read-only).
5. Start the UI with `streamlit run app.py`.

The app does not currently call an LLM or attach retrieved policy context to
answers. Policy ingestion and retrieval helpers are available in
`src/policy/retrieval.py`; they extract chunks from the five numbered policy
PDFs with document/version/section/page/effective-date metadata. Retrieval
uses BM25 by default. Setting `NEOSTATS_EMBEDDING_MODEL` enables embeddings
through the same NeoStats-compatible endpoint and credentials. Cancellation
or refund retrieval requires the booking creation date so it can select the
applicable cancellation-policy version. Retrieved `PolicyChunk` objects
provide citation metadata via `.citation()` for later display in Sources.
Extracted PDF text is untrusted reference data; it must not be treated as
instructions by any future answering agent.

The database helper is available in `src/db/safe_sql.py`; it opens SQLite in read-only mode,
allows only one SELECT statement, applies an SQLite authorizer and timeout,
and caps returned rows. Per-connection customer views scope profile data by
customer ID and scope bookings, payments, and damage reports through the
booking relationship. Support sessions use temporary views; the customer view
masks phone and email and omits driving-license numbers. The sample wrapper
in `data/` is excluded from Git because it contains an embedded credential;
the application client instead reads `NEOSTATS_BASE_URL`, `NEOSTATS_API_KEY`,
and `NEOSTATS_MODEL` from the environment or `.env`.

Run the scaffold tests with `python -m unittest discover -s tests`.
