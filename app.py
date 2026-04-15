# app.py
import os
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from tools.state import read_state
from tools.profile import read_profile
from agents.orchestrator import run_turn

st.set_page_config(page_title="Meal Planner (Agentic)", layout="wide")
st.title("Meal Planner")

if not os.getenv("ANTHROPIC_API_KEY"):
    st.error("ANTHROPIC_API_KEY not set. Add it to .env and restart.")
    st.stop()

# --- Session state ---
if "history" not in st.session_state:
    st.session_state.history = []  # list[{"role": "user"|"assistant", "content": ...}]
if "chat_display" not in st.session_state:
    st.session_state.chat_display = []  # list[{"role", "text"}] for rendering


def _render_plan_table():
    s = read_state()
    if not s.meal_plan:
        st.info("No meal plan yet. Ask the agent to plan next week.")
        return
    rows = [{
        "Day": slot.day,
        "Recipe": slot.recipe_title,
        "Protein": slot.key_ingredients[0] if slot.key_ingredients else "",
        "Key ingredients": ", ".join(slot.key_ingredients),
        "Why": slot.rationale,
    } for slot in s.meal_plan]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_sidebar():
    with st.sidebar:
        st.subheader("Profile")
        p = read_profile()
        if p is None:
            st.caption("No profile yet. The agent will onboard you.")
        else:
            st.caption(f"Household of {p.household_size}")
            st.caption("Members: " + ", ".join(m.name for m in p.members))
            if p.household_dislikes:
                st.caption("Dislikes: " + ", ".join(p.household_dislikes))

        st.subheader("Pantry")
        s = read_state()
        if s.pantry:
            st.write(" · ".join(s.pantry))
        else:
            st.caption("(empty)")

        with st.expander("Recent ratings"):
            if not s.ratings:
                st.caption("(none)")
            else:
                for r in s.ratings[-10:]:
                    st.caption(f"{r.cooked_at.date()} · {r.rater}: {r.recipe_title} → {r.rating}")


# --- Layout ---
_render_sidebar()
st.subheader("This week")
_render_plan_table()
st.divider()
st.subheader("Chat")

for msg in st.session_state.chat_display:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

user_input = st.chat_input("Tell the agent what you want…")
if user_input:
    st.session_state.chat_display.append({"role": "user", "text": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            reply, new_history = run_turn(user_input, st.session_state.history)
        st.session_state.history = new_history
        st.session_state.chat_display.append({"role": "assistant", "text": reply})
        st.markdown(reply)
    st.rerun()  # refresh table + sidebar to reflect any state changes
