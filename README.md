# RideWise Assist

RideWise Assist is a conversational support prototype for a bike and electric
vehicle rental company. Customers can ask about their own account, bookings,
payments and rental policies. Support agents can ask operational questions
across the fleet and customer records. The app combines a Streamlit chat UI, a
read-only SQLite database, policy-PDF retrieval, deterministic Python
calculators and a NeoStats-hosted OpenAI-compatible model.

> **Prototype limitation:** Customer role selection is not authentication.
> The customer ID is entered into the session and checked for format and
> existence, but the app does not verify the user's identity.

## Features

- Customer data is constrained to temporary views scoped to the session
  customer ID. Support agents use separate operational views.
- SQLite runs read-only for app queries. A query validator and SQLite
  authorizer restrict model-generated SQL; database access control does not
  rely on the system prompt.
- The five numbered policy PDFs are split into page- and section-aware chunks.
  Retrieval uses BM25 by default and can use embeddings when an embedding model
  is configured.
- Python calculators determine refunds, rental charges, GST, late fees, damage
  charges, tier benefits and EV battery fees. The model explains their
  results; it is not the source of the arithmetic.
- Answers can include an expandable **Sources** panel with successful SQL
  statements and cited policy chunks.
- Conversation history is kept in Streamlit session state. Changing roles or
  choosing **New conversation** clears the current conversation.

## Project layout

```text
app.py
src/
  agent/          Conversation routing, prompts and tool loop
  calculators/    Deterministic calculations and centralized policy constants
  db/             Read-only SQLite views, SQL validation and authorizer
  llm/            NeoStats OpenAI-compatible client
  policy/         PDF extraction, chunking, version selection and retrieval
tests/            Unit tests for database safety, agent, retrieval and calculators
data/
  data_dictionary.md
  01_Rental_Agreement_and_Terms.pdf
  02_Cancellation_and_Refund_Policy_v1.pdf
  03_Cancellation_and_Refund_Policy_v2.pdf
  04_Late_Return_and_Damage_Penalty_Schedule.pdf
  05_EV_User_Guide_and_FAQ.pdf
  ridewise.db     Supplied separately in the hackathon pack; git-ignored
```

Key implementation files:

- `app.py` — Streamlit role selector, chat, session state and Sources display.
- `src/agent/agent.py` — `respond()` tool loop and `respond_safely()` error
  boundary.
- `src/db/safe_sql.py` — read-only connections, scoped temporary views,
  validation, authorizer, timeout and row limits.
- `src/policy/retrieval.py` — PDF extraction, chunk metadata, version
  selection, BM25 and optional embedding retrieval.
- `src/calculators/calculators.py` and `src/calculators/config.py` — calculation
  implementations, policy constants and citations.
- `src/llm/client.py` — reads model configuration and creates the NeoStats
  client.

## Data and policies

The application queries the five tables in `ridewise.db`:

| Table | Primary key | Main purpose |
|---|---|---|
| `customers` | `customer_id` | Customer profile, contact, KYC and tier |
| `vehicles` | `vehicle_id` | Vehicle types, hubs, rates and fleet status |
| `bookings` | `booking_id` | Customer/vehicle booking, scheduled and actual times, status |
| `payments` | `payment_id` | Booking, deposit, penalty and refund transactions |
| `damage_reports` | `report_id` | Damage assessment, cost and claim status |

The full column definitions and status codes are in `data/data_dictionary.md`.
The app requires the database, dictionary and five numbered PDFs under `data/`.
The database is supplied in the hackathon pack and is excluded from Git by
`.gitignore`; if it is not present locally, copy it into `data/`.

Policy documents used by the retriever:

| Document | Subject | Version/effective date read by the loader |
|---|---|---|
| `01_Rental_Agreement_and_Terms.pdf` | Rental terms, rates, deposits and customer tiers | 3.0; 1 January 2025 |
| `02_Cancellation_and_Refund_Policy_v1.pdf` | Original cancellation and refund rules | v1; 1 January 2025 |
| `03_Cancellation_and_Refund_Policy_v2.pdf` | Revised cancellation and refund rules | v2; 1 July 2026, 00:00 IST |
| `04_Late_Return_and_Damage_Penalty_Schedule.pdf` | Late returns, damage, tier grace, EV battery fee and GST | 2.1; 1 January 2025 |
| `05_EV_User_Guide_and_FAQ.pdf` | EV operation, charging and return questions | 1.4; no effective date parsed |

Cancellation policy selection uses a booking's `booked_at` timestamp: bookings
before 1 July 2026, 00:00 IST use v1; bookings at or after the cutover use v2.
The selected version is used for retrieval and by the refund calculator.

The loader currently produces 47 chunks: 44 extracted from the PDFs plus three
separately flagged, hand-transcribed chunks for the scanned v2 refund schedule,
GOLD grace table and EV battery figure. These transcriptions are marked in
Sources; they are not OCR output.

## Architecture and request flow

```text
Customer / Support Agent
          |
          v
Streamlit UI (app.py): role, session, chat and Sources
          |
          v
respond_safely() -> respond() (src/agent/agent.py)
          |
          +--> NeoStats chat completion
          |       |
          |       +--> run_sql ------> safe read-only SQLite views
          |       +--> search_policy -> version-filtered PDF chunks
          |       +--> calculator tools -> deterministic results/citations
          |
          v
Answer + successful SQL + policy chunks
          |
          v
Streamlit response and expandable Sources panel
```

`app.py` passes the current message, role, customer ID and prior conversation
messages to `respond_safely()`. `respond()` supplies the model with role-specific
view names and columns, then handles tool calls for SQL, policy retrieval and
calculations. The app renders the answer and its sources. Function calling is
used when supported by the endpoint; the agent can switch to a JSON tool-call
format if the endpoint rejects function calling.

For cancellation and refund questions, the agent resolves the booking first,
uses its actual `booked_at` value to select the policy version, and provides
the applicable policy chunks to the model. For hypothetical “cancel now”
questions, the refund tool uses the current UTC time and returns it with the
calculation inputs.

## Database safety and privacy

`src/db/safe_sql.py` opens the database with SQLite's read-only URI mode and
creates per-connection temporary views. These views do not modify the supplied
database.

- Customer sessions can query only `my_profile`, `my_bookings`, `my_payments`
  and `my_damage_reports`. Payments and damage reports are scoped through
  bookings for the session customer. Customer payment and damage views omit
  free-text remarks and descriptions.
- Support sessions can query `agent_customers`, `agent_vehicles`,
  `agent_bookings`, `agent_payments` and `agent_damage_reports`. The support
  customer view omits driving-license numbers and masks phone and email fields.
  Known customer-name tokens, phone numbers and email addresses are redacted
  from payment remarks and damage descriptions.
- `validate_select()` accepts one `SELECT` and rejects comments, stacked
  statements and forbidden SQL operations. The SQLite authorizer limits table
  reads and functions, while a progress handler enforces a query timeout.
- Queries return at most 25 rows for customers and 10 for support agents.
  Support-list totals are requested through a separate `COUNT(id)` query with
  the same filter; the model is instructed to say when only the first 10 rows
  are shown. The cap is enforced by code, but count and final wording still
  depend on the model following that guidance.

These checks limit database access even if the model generates an invalid or
overbroad query. Prompt instructions reinforce the rules; they are not the
security boundary.

## Policy retrieval and calculations

`src/policy/retrieval.py` extracts PDF text with `pypdf`, records document,
version, section, page and effective-date metadata, and splits text by detected
headings and page. The default chunk target is 1,400 characters. When
`NEOSTATS_EMBEDDING_MODEL` is blank, the in-project BM25 implementation ranks
chunks by query-term frequency and document frequency. When configured,
embeddings from the same NeoStats endpoint are ranked using cosine similarity.

`src/calculators/calculators.py` returns calculation inputs, formula, results
and policy citations. Policy values and citations are centralized in
`src/calculators/config.py`.

| Calculator | Main rules |
|---|---|
| Cancellation/refund | Chooses v1/v2 by booking date; applies the cancellation window to successful BOOKING principal and GST, then nets successful prior REFUND payments. CNL_S is 100%; NSH is 0%. |
| Rental | Uses full 24-hour blocks at the daily rate; remaining hours are hourly, capped at one daily rate. Minimum rental duration is two hours. |
| Late return | STANDARD/SILVER have no grace; GOLD has 30 minutes. If beyond grace, charges the full late period, rounded up by hour, at 1.5 times hourly rate, plus GST. |
| GST | Computes 18% on the GST-exclusive amount, rounded to cents. |
| Damage | CHARGED uses the assessed amount; OPEN, DISPUTED and WAIVED produce no charge. GST is separate. |
| EV battery | EV return below 10% incurs a ₹150 fee; exactly 10% does not. GST is separate. |
| Tier benefit | Returns the configured late-return grace for STANDARD, SILVER or GOLD. |

The LLM does not calculate monetary results itself. It is instructed to use
calculator outputs and explain them.

## Model configuration

Copy `.env.example` to `.env` and set the required values locally:

| Variable | Required? | Purpose |
|---|---|---|
| `NEOSTATS_BASE_URL` | Yes | NeoStats OpenAI-compatible endpoint |
| `NEOSTATS_API_KEY` | Yes | Credential used by the client; keep private |
| `NEOSTATS_MODEL` | Yes | NeoStats deployment name provided for this project |
| `NEOSTATS_EMBEDDING_MODEL` | No | Embedding deployment; leave blank for BM25 |

`src/llm/client.py` loads `.env` using `python-dotenv`. The chat client uses a
15-second timeout and one client retry. Do not commit `.env`, place credentials
in source code, or share them. `.env.example` contains blank values, and
`.gitignore` excludes `.env`.

## Setup and run

Use Python 3.10 or newer. In Windows PowerShell, from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Ensure the five numbered policy PDFs and `data_dictionary.md` are in `data/`.
Copy the `ridewise.db` database supplied with the hackathon pack into `data/`
if it is not already present. Then create the local environment file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally to set the NeoStats endpoint, API key and deployment name.
Leave `NEOSTATS_EMBEDDING_MODEL` blank to use BM25. Start the app:

```powershell
streamlit run app.py
```

Run the test suite in an activated environment:

```powershell
python -m unittest discover -s tests
```

The database file is git-ignored and is not distributed as part of the source
repository. Dependencies are listed by name in `requirements.txt` and are not
version-pinned.

## Tests

The `tests/` suite covers:

- `test_safe_sql.py` — view scoping, blocked base/schema access, SQL validation,
  PII masking, read-only connections and row limits.
- `test_policy_retrieval.py` — document metadata, effective-date parsing,
  cancellation version selection, BM25 and transcribed chunks.
- `test_calculators.py` — cancellation/refunds, payments, GST, rental,
  late-return, damage, tier and battery calculations.
- `test_agent_routing.py` — fake-model tool routing, refusals, role schema,
  retries, Sources and prompt regression checks.
- `test_agent_errors.py` — safe database and model error replies.

Agent routing tests use a `FakeLLM` with predefined tool calls and answers;
they test routing and prompt contents, not live-model reliability. Current
prompt regression tests check that the agent is instructed to count capped
support lists and state the cancellation policy version and booking-date rule.

## Known limitations

- There is no authentication. A typed customer ID is not identity verification.
- Name redaction relies on customer names present in the database and may miss
  unknown names or other forms of personal information.
- The 10-row support cap is enforced, but the model must execute a separate
  count query and word the response correctly.
- Prompt regression tests do not guarantee real-model compliance on unseen
  questions.
- Policy heading/date extraction uses simple patterns. The EV guide's effective
  date is not parsed.
- If embeddings are configured but the embedding service fails, retrieval does
  not automatically fall back to BM25.
- Operational completeness and reconciliation gaps documented in
  `DECISIONS.md` still need follow-up.
