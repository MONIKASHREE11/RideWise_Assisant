import uuid

import streamlit as st

from src.agent.agent import respond


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
                    st.code(sql, language="sql")
                else:
                    st.caption("No SQL was run.")
                if policy_chunks:
                    st.write(policy_chunks)
                else:
                    st.caption("No policy chunks were cited.")

prompt = st.chat_input("Ask RideWise Assist")
if prompt:
    if role == "Customer" and not customer_id:
        st.warning("Enter your customer ID in the sidebar before sending a message.")
    else:
        st.session_state["messages"].append({"role": "user", "content": prompt})
        history = st.session_state["messages"][:-1]
        result = respond(prompt, history=history)
        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": result["answer"],
                "sources": result["sources"],
            }
        )
        st.rerun()
