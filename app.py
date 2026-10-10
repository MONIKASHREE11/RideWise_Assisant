import uuid

import streamlit as st

from src.agent.agent import respond_safely


def _reset_conversation() -> None:
    st.session_state["messages"] = []
    st.session_state["conversation_id"] = str(uuid.uuid4())


st.set_page_config(page_title="RideWise Assist", page_icon="🚲")

if "messages" not in st.session_state:
    st.session_state["messages"] = []
if "conversation_id" not in st.session_state:
    st.session_state["conversation_id"] = str(uuid.uuid4())

st.title("RideWise Assist")
st.caption("A conversational assistant for RideWise bike and EV rentals.")

with st.sidebar:
    st.header("Session")
    role = st.selectbox("Role", ["Customer", "Support Agent"], key="role")

    if st.session_state.get("_active_role") != role:
        st.session_state["_active_role"] = role
        _reset_conversation()

    customer_id = None
    if role == "Customer":
        customer_id = st.text_input("Customer ID", key="customer_id").strip()

    if st.button("New conversation", use_container_width=True):
        _reset_conversation()

for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            with st.expander("Sources"):
                sources = message.get("sources", {})
                sql = sources.get("sql")
                policy_chunks = sources.get("policy_chunks", [])
                if sql:
                    for statement in sql:
                        st.code(statement, language="sql")
                else:
                    st.caption("No SQL was run.")
                if policy_chunks:
                    for chunk in policy_chunks:
                        citation = chunk.get("metadata", {})
                        title = " · ".join(
                            str(value)
                            for value in (
                                citation.get("doc"),
                                citation.get("version"),
                                citation.get("section"),
                                f"p. {citation.get('page')}"
                                if citation.get("page") is not None
                                else None,
                            )
                            if value
                        )
                        with st.expander(title or "Policy source"):
                            st.caption(
                                f"Effective date: "
                                f"{citation.get('effective_date') or 'Not stated'}"
                            )
                            if citation.get("transcription_note"):
                                st.caption(citation["transcription_note"])
                            st.write(chunk.get("text", ""))
                else:
                    st.caption("No policy chunks were cited.")

prompt = st.chat_input("Ask RideWise Assist")
if prompt:
    if role == "Customer" and not customer_id:
        st.warning("Enter your customer ID in the sidebar before sending a message.")
    else:
        st.session_state["messages"].append({"role": "user", "content": prompt})
        history = st.session_state["messages"][:-1]
        result = respond_safely(
            prompt,
            history=history,
            role=role,
            customer_id=customer_id,
        )
        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": result["answer"],
                "sources": result["sources"],
            }
        )
        st.rerun()
