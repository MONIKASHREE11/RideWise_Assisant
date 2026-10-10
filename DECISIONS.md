# Decisions

- Keep phase one limited to the Streamlit shell, a deterministic echo agent,
  and a small standard-library SQLite safety layer.
- Open SQLite with `mode=ro`; customer and support views are temporary and
  created independently for each connection, never persisted to the database.
- Validate customer IDs as `CUST` followed by four digits and verify their
  existence before creating customer views.
- For customer access, expose only `my_profile`, `my_bookings`, `my_payments`,
  and `my_damage_reports`. Payment and damage ownership is derived through
  `bookings.customer_id`.
- For support access, expose only `agent_*` temporary views. The customer view
  omits driving-license numbers and masks phone/email; direct base-table,
  schema-metadata, and pragma reads are denied.
- Require one SELECT, install an SQLite authorizer and execution timeout, and
  cap returned rows. The authorizer also blocks attempts to reach base tables
  through UNIONs or subqueries.
- Validate a single SELECT, wrap it with a row cap, and install a SQLite
  progress handler for a bounded execution time.
- Keep role and customer identity in Streamlit session state. Switching roles
  or starting a new conversation clears conversation history; changing the
  role does not carry messages into the new role.
- Keep NeoStats credentials in environment variables; `.env` and the supplied
  wrapper containing an embedded credential are ignored by Git. The LLM
  client loads endpoint, key, and model from environment variables.
