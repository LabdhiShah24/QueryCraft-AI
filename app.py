"""QueryCraft AI — Natural Language to SQL Query Generator.

A ChatGPT-inspired interface enabling users to query a digital music store
database in plain English, with multi-conversation session history, safe
read-only query generation, execution inspection, and CSV export.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Optional

import pandas as pd
import streamlit as st

from database import (
    DatabaseExecutionError,
    DatabaseManager,
    DatabaseSecurityError,
    MAX_DISPLAY_ROWS,
    QueryResult,
)
from query_generator import GeneratedQuery, generate_query


# Initialize Database Manager singleton
@st.cache_resource
def get_db_manager() -> DatabaseManager:
    """Provides a cached singleton DatabaseManager instance."""
    return DatabaseManager()


# Fetch schema statistics dynamically
@st.cache_data(ttl=3600)
def get_catalog_stats() -> dict:
    """Fetches real table and record counts from the database."""
    try:
        db = get_db_manager()
        summary = db.get_schema_summary()
        return {
            "total_tables": len(summary),
            "tracks": summary.get("Track", {}).get("row_count", 0),
            "albums": summary.get("Album", {}).get("row_count", 0),
            "artists": summary.get("Artist", {}).get("row_count", 0),
            "customers": summary.get("Customer", {}).get("row_count", 0),
            "invoices": summary.get("Invoice", {}).get("row_count", 0),
        }
    except Exception:
        return {
            "total_tables": 11,
            "tracks": 3503,
            "albums": 347,
            "artists": 275,
            "customers": 59,
            "invoices": 412,
        }


# Page setup — ChatGPT-inspired sidebar navigation
st.set_page_config(
    page_title="QueryCraft AI — Natural Language to SQL",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for dark ChatGPT-like aesthetic, high-contrast headings, and hidden deploy button
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Main Container sizing */
    .block-container {
        max-width: 1050px;
        padding-top: 1.75rem;
        padding-bottom: 3.5rem;
        margin-left: auto;
        margin-right: auto;
    }

    /* Reliably hide Streamlit Deploy button */
    [data-testid="stDeployButton"], .stAppDeployButton, .stDeployButton {
        display: none !important;
    }

    /* Sidebar ChatGPT-style styling */
    section[data-testid="stSidebar"] {
        background-color: #0B0F19;
        border-right: 1px solid #1E293B;
    }
    section[data-testid="stSidebar"] div.stButton > button {
        border-radius: 8px;
        border: 1px solid #334155;
        background-color: #1E293B;
        color: #E2E8F0;
        font-size: 0.875rem;
        font-weight: 500;
        text-align: left;
        padding: 0.5rem 0.75rem;
        transition: all 0.15s ease-in-out;
    }
    section[data-testid="stSidebar"] div.stButton > button:hover {
        background-color: #2D3748;
        border-color: #3B82F6;
        color: #FFFFFF;
    }

    /* Brand Header in Sidebar */
    .sidebar-brand {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 1.15rem;
        font-weight: 700;
        color: #FFFFFF;
        margin-bottom: 1rem;
        padding: 0.25rem 0;
    }
    .sidebar-section-title {
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #64748B;
        margin: 1.25rem 0 0.5rem 0.25rem;
    }

    /* Main Header: White High Contrast */
    .app-title {
        font-size: 2.35rem;
        font-weight: 700;
        color: #FFFFFF !important;
        letter-spacing: -0.025em;
        margin-bottom: 0.35rem;
    }
    .app-subtitle {
        font-size: 1.05rem;
        color: #CBD5E1 !important;
        margin-bottom: 0.85rem;
        font-weight: 400;
    }

    /* Database info badge */
    .meta-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        background-color: #1E293B;
        border: 1px solid #334155;
        color: #94A3B8;
        padding: 0.3rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 500;
        margin-bottom: 1.5rem;
    }

    /* Headings */
    h1, h2, h3, h4, [data-testid="stMarkdownContainer"] h3 {
        color: #F8FAFC !important;
        font-weight: 600;
    }

    /* Suggested question pill buttons */
    div[data-testid="stHorizontalBlock"] .stButton > button {
        border-radius: 9999px;
        border: 1px solid #334155;
        background-color: #1E293B;
        color: #F1F5F9;
        font-size: 0.85rem;
        font-weight: 500;
        padding: 0.4rem 0.85rem;
        transition: all 0.15s ease-in-out;
        white-space: nowrap;
        text-align: left;
    }
    div[data-testid="stHorizontalBlock"] .stButton > button:hover {
        border-color: #3B82F6;
        color: #FFFFFF;
        background-color: rgba(37, 99, 235, 0.2);
    }

    /* Primary buttons */
    button[kind="primary"] {
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        padding: 0.5rem 1.25rem !important;
    }
    button[kind="primary"]:hover {
        background-color: #1D4ED8 !important;
    }

    /* Explanation box */
    .explanation-box {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-left: 4px solid #3B82F6;
        border-radius: 6px;
        padding: 1rem 1.25rem;
        margin: 1rem 0;
        color: #F8FAFC !important;
        font-size: 0.95rem;
        line-height: 1.5;
    }

    /* Active conversation pill highlight */
    .active-chat-btn {
        background-color: #1E40AF !important;
        border-color: #3B82F6 !important;
        color: #FFFFFF !important;
    }

    /* Footer */
    .app-footer {
        margin-top: 3.5rem;
        padding-top: 1.25rem;
        border-top: 1px solid #334155;
        color: #94A3B8;
        font-size: 0.825rem;
        text-align: center;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# =====================================================================
# Conversation Management (ChatGPT-inspired session state)
# =====================================================================
def make_conversation(title: str = "New Chat") -> dict:
    """Creates a new conversation record."""
    conv_id = str(uuid.uuid4())[:8]
    return {
        "id": conv_id,
        "title": title,
        "question": "",
        "question_for_query": "",
        "generated_query": None,
        "query_result": None,
        "error": None,
        "created_at": time.time(),
    }


def derive_title(question: str) -> str:
    """Derives a short, descriptive conversation title from a question."""
    cleaned = question.strip()
    if not cleaned:
        return "New Chat"

    # Specific friendly mappings for canonical queries
    q_lower = cleaned.lower()
    if "most albums" in q_lower or "artists with most albums" in q_lower:
        return "Artists by Albums"
    if "longest tracks" in q_lower or "longest song" in q_lower:
        return "Top Longest Tracks"
    if "sales by country" in q_lower or "revenue by country" in q_lower:
        return "Sales by Country"
    if "customers" in q_lower and ("spent" in q_lower or "spending" in q_lower):
        return "Top Customers by Spend"
    if "rock tracks" in q_lower and "5 minutes" in q_lower:
        return "Rock Tracks > 5 Mins"
    if "each artist" in q_lower and "album" in q_lower:
        return "Albums per Artist"

    # Clean filler prefixes
    for prefix in [
        "show the ", "show me the ", "show me ", "show ",
        "what are the ", "what is the ", "what ",
        "which are the ", "which ",
        "can you show ", "can you find ", "can you ",
        "list all ", "list ", "find ", "how many "
    ]:
        if q_lower.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break

    cleaned = cleaned.rstrip("?").strip()
    if not cleaned:
        return "New Chat"

    title = cleaned[0].upper() + cleaned[1:]
    if len(title) > 28:
        truncated = title[:26].rsplit(" ", 1)[0]
        title = (truncated if truncated else title[:26]) + "..."
    return title


def init_chat_history():
    """Initializes multi-conversation session state and backfills titles."""
    if "conversations" not in st.session_state:
        initial_conv = make_conversation()
        st.session_state.conversations = {initial_conv["id"]: initial_conv}
        st.session_state.active_conv_id = initial_conv["id"]
    elif not st.session_state.conversations:
        initial_conv = make_conversation()
        st.session_state.conversations[initial_conv["id"]] = initial_conv
        st.session_state.active_conv_id = initial_conv["id"]

    # Backfill missing or default titles from saved question
    for conv in st.session_state.conversations.values():
        curr_title = conv.get("title", "")
        q = conv.get("question", "").strip()
        if (curr_title in ("New Chat", "Chat", "Untitled", "", None)) and q:
            conv["title"] = derive_title(q)


init_chat_history()


def get_active_conv() -> dict:
    """Returns the currently active conversation dictionary."""
    active_id = st.session_state.active_conv_id
    if active_id not in st.session_state.conversations:
        first_id = next(iter(st.session_state.conversations.keys()))
        st.session_state.active_conv_id = first_id
    return st.session_state.conversations[st.session_state.active_conv_id]


def create_new_chat():
    """Starts a fresh new conversation, setting active conversation and blanking inputs."""
    new_conv = make_conversation()
    st.session_state.conversations[new_conv["id"]] = new_conv
    st.session_state.active_conv_id = new_conv["id"]
    # Ensure fresh input area is blank and does not inherit prior question
    st.session_state[f"input_area_{new_conv['id']}"] = ""


def delete_chat(conv_id: str):
    """Deletes a conversation by ID."""
    if conv_id in st.session_state.conversations:
        del st.session_state.conversations[conv_id]
    if not st.session_state.conversations:
        create_new_chat()
    elif st.session_state.active_conv_id == conv_id:
        st.session_state.active_conv_id = next(iter(st.session_state.conversations.keys()))


# =====================================================================
# Sidebar: ChatGPT-inspired Conversation History
# =====================================================================
with st.sidebar:
    st.markdown('<div class="sidebar-brand">🎵 QueryCraft AI</div>', unsafe_allow_html=True)

    # + New Chat Button
    if st.button("➕ New Chat", key="btn_new_chat", use_container_width=True, type="primary"):
        create_new_chat()
        st.rerun()

    st.markdown('<div class="sidebar-section-title">Recents</div>', unsafe_allow_html=True)

    # Render list of previous conversations
    # Sort chronologically descending
    sorted_convs = sorted(
        st.session_state.conversations.values(),
        key=lambda c: c.get("created_at", 0),
        reverse=True,
    )

    for conv in sorted_convs:
        cid = conv["id"]
        is_active = (cid == st.session_state.active_conv_id)
        icon = "💬" if is_active else "🗨️"
        display_label = f"{icon} {conv['title']}"

        col_select, col_del = st.columns([0.82, 0.18])
        with col_select:
            # Highlighting active conversation
            btn_type = "primary" if is_active else "secondary"
            if st.button(display_label, key=f"select_conv_{cid}", use_container_width=True):
                st.session_state.active_conv_id = cid
                st.rerun()
        with col_del:
            if st.button("✕", key=f"del_conv_{cid}", help="Delete this conversation", use_container_width=True):
                delete_chat(cid)
                st.rerun()

    st.markdown("---")
    st.caption("💾 History is saved in current session. Resets on browser reload.")


# =====================================================================
# Main Application Interface
# =====================================================================
active_conv = get_active_conv()

# Main Title & Subtitle
st.markdown('<div class="app-title">QueryCraft AI</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle">Ask questions about your music data. Get answers without writing SQL.</div>',
    unsafe_allow_html=True,
)

# Dataset overview badge
stats = get_catalog_stats()
st.markdown(
    f'<div class="meta-badge">'
    f'🎵 Chinook Database &bull; {stats["total_tables"]} Tables &bull; '
    f'{stats["tracks"]:,} Tracks &bull; {stats["artists"]:,} Artists &bull; '
    f'{stats["customers"]:,} Customers &bull; Read-Only Safe'
    f'</div>',
    unsafe_allow_html=True,
)

# Clickable Example Questions
st.markdown("**Suggested questions to try:**")
example_questions = [
    "Show the top 5 artists with the most albums",
    "Which are the 10 longest tracks?",
    "Show total sales by country",
    "Which 5 customers have spent the most?",
    "Find Rock tracks longer than 5 minutes",
    "How many albums does each artist have?",
]


def handle_example_click(example_text: str):
    """Populates question input and invalidates old results in active conversation."""
    input_key = f"input_area_{active_conv['id']}"
    st.session_state[input_key] = example_text
    active_conv["question"] = example_text
    active_conv["question_for_query"] = ""
    active_conv["generated_query"] = None
    active_conv["query_result"] = None
    active_conv["error"] = None


row1_col1, row1_col2, row1_col3 = st.columns(3)
with row1_col1:
    if st.button(example_questions[0], key="btn_ex_1", use_container_width=True):
        handle_example_click(example_questions[0])
        st.rerun()
with row1_col2:
    if st.button(example_questions[1], key="btn_ex_2", use_container_width=True):
        handle_example_click(example_questions[1])
        st.rerun()
with row1_col3:
    if st.button(example_questions[2], key="btn_ex_3", use_container_width=True):
        handle_example_click(example_questions[2])
        st.rerun()

row2_col1, row2_col2, row2_col3 = st.columns(3)
with row2_col1:
    if st.button(example_questions[3], key="btn_ex_4", use_container_width=True):
        handle_example_click(example_questions[3])
        st.rerun()
with row2_col2:
    if st.button(example_questions[4], key="btn_ex_5", use_container_width=True):
        handle_example_click(example_questions[4])
        st.rerun()
with row2_col3:
    if st.button(example_questions[5], key="btn_ex_6", use_container_width=True):
        handle_example_click(example_questions[5])
        st.rerun()

st.write("")

# Question Input Area bound to active conversation
input_key = f"input_area_{active_conv['id']}"
user_question = st.text_area(
    "Your Question",
    value=active_conv.get("question", ""),
    placeholder="e.g., Show the top 5 artists with the most albums",
    height=90,
    label_visibility="collapsed",
    key=input_key,
)

# Detect if the user edited the text manually after a query was already generated
if user_question != active_conv.get("question_for_query", "") and active_conv.get("generated_query") is not None:
    # Invalidate stale generated query and results to prevent user confusion
    active_conv["generated_query"] = None
    active_conv["query_result"] = None
    active_conv["error"] = None

active_conv["question"] = user_question

# Action buttons
btn_col1, btn_col2, btn_spacer = st.columns([1.5, 1.5, 5])
with btn_col1:
    generate_clicked = st.button("Generate Query", type="primary", use_container_width=True, key=f"btn_gen_{active_conv['id']}")
with btn_col2:
    clear_clicked = st.button("Clear", use_container_width=True, key=f"btn_clear_{active_conv['id']}")

if clear_clicked:
    input_key = f"input_area_{active_conv['id']}"
    st.session_state[input_key] = ""
    active_conv["question"] = ""
    active_conv["question_for_query"] = ""
    active_conv["generated_query"] = None
    active_conv["query_result"] = None
    active_conv["error"] = None
    st.rerun()

# Generation step
if generate_clicked:
    trimmed_question = user_question.strip()
    if not trimmed_question:
        st.warning("Please enter a question or select one of the suggested examples above.")
        active_conv["generated_query"] = None
        active_conv["query_result"] = None
    else:
        with st.spinner("Analyzing question and generating safe SQL..."):
            gen_result = generate_query(trimmed_question)
            active_conv["generated_query"] = gen_result
            active_conv["question_for_query"] = trimmed_question
            active_conv["query_result"] = None
            active_conv["error"] = None

            # Update conversation title if it is still default or missing
            if active_conv.get("title") in ("New Chat", "Chat", "Untitled", "", None):
                active_conv["title"] = derive_title(trimmed_question)

# Render Generation Results if available for active conversation
gq: Optional[GeneratedQuery] = active_conv.get("generated_query")

if gq:
    if not gq.is_supported:
        st.warning(gq.explanation)
        if gq.suggested_questions:
            st.markdown("**Click any supported question below to try it:**")
            sugg_col1, sugg_col2 = st.columns(2)
            for idx, sugg in enumerate(gq.suggested_questions[:6]):
                target_col = sugg_col1 if idx % 2 == 0 else sugg_col2
                with target_col:
                    if st.button(f"👉 {sugg}", key=f"sugg_{idx}_{active_conv['id']}", use_container_width=True):
                        handle_example_click(sugg)
                        st.rerun()
    else:
        st.markdown("### Generated Query")

        # Plain English Explanation
        st.markdown(
            f'<div class="explanation-box"><strong>Explanation:</strong> {gq.explanation}</div>',
            unsafe_allow_html=True,
        )

        # Collapsible SQL View
        with st.expander("View SQL query", expanded=True):
            display_query = gq.display_sql if gq.display_sql else gq.sql
            st.code(display_query, language="sql")
            st.caption(f"Engine: {gq.engine_used} | Mode: Read-Only parameterized SQLite")

        # Action: Run Query Button
        run_col1, run_col2, run_spacer = st.columns([1.5, 2, 4.5])
        with run_col1:
            run_clicked = st.button("Run Query", type="primary", use_container_width=True, key=f"btn_run_{active_conv['id']}")

        if run_clicked:
            db = get_db_manager()
            with st.spinner("Executing safe read-only query..."):
                try:
                    result: QueryResult = db.execute_query(gq.sql, gq.params)
                    active_conv["query_result"] = result
                    active_conv["error"] = None
                except DatabaseSecurityError as sec_err:
                    active_conv["error"] = f"Security Violation: {sec_err}"
                    active_conv["query_result"] = None
                except DatabaseExecutionError as exec_err:
                    active_conv["error"] = f"Query Execution Error: {exec_err}"
                    active_conv["query_result"] = None
                except Exception as ex:
                    active_conv["error"] = f"An unexpected error occurred: {ex}"
                    active_conv["query_result"] = None

# Render Database Errors if present
if active_conv.get("error"):
    st.error(active_conv["error"])

# Render Database Execution Results
res: Optional[QueryResult] = active_conv.get("query_result")
if res is not None:
    st.markdown("---")
    st.markdown("### Query Results")

    # Metadata bar: Rows count, execution time, truncation status
    meta_cols = st.columns([2, 2, 2, 4])
    with meta_cols[0]:
        st.metric("Rows Returned", f"{res.row_count:,}")
    with meta_cols[1]:
        st.metric("Execution Time", f"{res.execution_time_ms:.1f} ms")
    with meta_cols[2]:
        status_label = "Truncated (capped)" if res.is_truncated else "Complete"
        st.metric("Dataset Status", status_label)

    if res.is_truncated:
        st.warning(
            f"Results exceeded the maximum display limit of {MAX_DISPLAY_ROWS} rows. "
            "Displaying the top rows for safety."
        )

    # Display Data Table
    if res.row_count == 0:
        st.info("The query executed successfully, but no matching records were found in the database.")
    else:
        st.dataframe(
            res.data,
            use_container_width=True,
            hide_index=True,
        )

        # CSV Download button
        csv_data = res.data.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Results as CSV",
            data=csv_data,
            file_name="querycraft_results.csv",
            mime="text/csv",
            help="Download the displayed query result table in CSV format.",
            key=f"btn_csv_{active_conv['id']}",
        )

# Footer
st.markdown(
    '<div class="app-footer">'
    'QueryCraft AI &bull; Built with Streamlit, Python &amp; SQLite &bull; '
    'Sample database: <a href="https://github.com/lerocha/chinook-database" target="_blank" style="color: #94A3B8;">Chinook Database</a>'
    '</div>',
    unsafe_allow_html=True,
)
