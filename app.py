# app.py
import os

# AVG / Avast point SSLKEYLOGFILE at a kernel filter-driver device path
# (e.g. \\.\avgMonFltPro), which crashes Python's SSL stack with
# "OPENSSL_Uplink ... no OPENSSL_Applink" via System32's LibreSSL. Drop
# only AV-style paths; a real file path stays untouched.
_keylog = os.environ.get("SSLKEYLOGFILE", "")
if _keylog.startswith("\\\\.\\") or "avgMon" in _keylog or "avast" in _keylog.lower():
    os.environ.pop("SSLKEYLOGFILE", None)

from datetime import date, timedelta
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from tools.state import read_state
from tools.profile import read_profile
from agents.orchestrator import run_turn, get_bg_jobs

st.set_page_config(page_title="Meal Planner (Agentic)", layout="wide")
st.title("Meal Planner")

if not os.getenv("OPENROUTER_API_KEY"):
    st.error("OPENROUTER_API_KEY not set. Add it to .env and restart.")
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

    if s.week_of:
        monday = s.week_of
        friday = monday + timedelta(days=4)
        st.caption(f"Week of {monday.strftime('%d %b')} \u2013 {friday.strftime('%d %b %Y')}")

    day_offsets = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
    rows = []
    for slot in s.meal_plan:
        day_label = slot.day
        if s.week_of:
            slot_date = s.week_of + timedelta(days=day_offsets.get(slot.day, 0))
            day_label = f"{slot.day} {slot_date.strftime('%d/%m')}"
        rows.append({
            "Day": day_label,
            "Recipe": slot.recipe_title,
            "Protein": slot.main_protein,
            "Key ingredients": ", ".join(slot.key_ingredients),
            "Why": slot.rationale,
        })
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
            st.write(" · ".join(p.name for p in s.pantry))
        else:
            st.caption("(empty)")

        with st.expander("Recent ratings"):
            if not s.ratings:
                st.caption("(none)")
            else:
                for r in s.ratings[-10:]:
                    st.caption(f"{r.cooked_at.date()} · {r.rater}: {r.recipe_title} → {r.rating}")

        st.subheader("Last turn")
        import tracing
        last = tracing.last_turn_summary()
        if last is None:
            st.caption("(no traces yet)")
        else:
            tot = last.get("total_tokens", 0)
            ms = last.get("latency_ms", 0)
            n_tools = len(last.get("tool_calls", []))
            tot_str = f"{tot/1000:.1f}K" if tot >= 1000 else str(tot)
            st.caption(f"{tot_str} tokens · {ms/1000:.1f}s · {n_tools} tools")



def _render_bg_jobs():
    """Show a banner for any running background recipe searches."""
    jobs = get_bg_jobs()
    for job_id, job in jobs.items():
        if job["status"] == "running":
            cur, total, msg = job.get("progress", (0, 1, "Starting..."))
            st.info(f"\U0001f50d Background search: {msg}")
            st.progress(cur / total if total > 0 else 0)
        elif job["status"] == "done" and job.get("result"):
            count = len(job["result"])
            st.success(f"\u2705 Recipe search complete \u2014 {count} new recipe(s) added.")
        elif job["status"] == "error":
            st.error(f"Recipe search failed: {job.get('result', 'unknown error')}")


# --- Layout ---
_render_sidebar()
s_header = read_state()
if s_header.week_of:
    st.subheader(f"Meal plan \u2014 w/c {s_header.week_of.strftime('%d %b %Y')}")
else:
    st.subheader("Meal plan")
_render_plan_table()
_render_bg_jobs()
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
