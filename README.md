# QueryCraft AI — Natural Language to SQL Query Generator

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/frontend-Streamlit-red.svg)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/database-SQLite-green.svg)](https://www.sqlite.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**QueryCraft AI** is a full-stack, schema-aware application that allows non-technical users to ask questions about a digital music store in plain English and receive safe, read-only SQL queries and verified database results.

---

## 📌 Project Overview

Traditional relational databases require knowledge of SQL syntax, table schemas, join paths, and primary/foreign key relationships. QueryCraft AI bridges this gap by translating conversational English questions into validated SQLite queries against the Chinook digital music store database.

Users do not need prior knowledge of SQL, schemas, or database administration. The application features a ChatGPT-inspired web interface with conversation history, execution inspection, and one-click CSV export.

---

## 🚀 Key Features

* **Natural Language to SQL Translation**: Schema-aware translation mapping plain-English questions to verified tables and columns.
* **Deterministic Local Pattern Engine**: 100% offline, zero-API-key functionality covering rankings, aggregations, joins, and filters.
* **Optional LLM Integration**: Clean plug-and-play support for OpenAI or Google Gemini via environment variables for open-ended queries, with automatic local fallback.
* **Strict Security Sandbox**:
  * SQLite URI read-only connection mode (`file:...path...?mode=ro`).
  * Engine-level enforcement via `PRAGMA query_only = ON;`.
  * AST token inspection powered by `sqlparse` to block DDL (`DROP`, `ALTER`, `CREATE`), DML (`INSERT`, `UPDATE`, `DELETE`), administrative queries (`PRAGMA`, `ATTACH`, `VACUUM`), multi-statement semicolons, and SQL comments.
  * Only single read-only `SELECT` and `WITH` (CTE) statements are permitted.
  * Query execution timeout protection and 500-row display cap.
* **Revenue Accuracy (Anti-Double-Counting)**: Aggregates line-item revenue via `InvoiceLine.UnitPrice * InvoiceLine.Quantity` rather than summing redundant invoice totals across line joins.
* **Unit Conversion**: Automatically converts natural song duration constraints (minutes) to database storage units (milliseconds: $1\text{ min} = 60,000\text{ ms}$).
* **ChatGPT-Inspired Interface**:
  * Multi-conversation session history in the left sidebar.
  * Auto-generated, descriptive conversation titles (e.g., *"Top Longest Tracks"*, *"Artists by Albums"*).
  * Independent conversation state preservation (switching chats restores questions, SQL, and results).
  * Collapsible SQL query inspection with native copy controls.
  * Direct execution controls ("Run Query") so users inspect before running.
  * One-click CSV export of result sets.

---

## 🏗️ Architecture

```
QueryCraft-AI/
│
├── app.py                     # Streamlit frontend with ChatGPT-style conversation state
├── database.py                # Read-only SQLite layer, security sanitizer, and query runner
├── query_generator.py         # Schema-aware natural language to SQL pattern engine
├── query_generator_llm.py     # Optional OpenAI/Gemini translation pipeline with local fallback
├── requirements.txt           # Python package dependencies
├── .env.example               # Template for optional external LLM API keys
├── .gitignore                 # Git ignore rules for caches, venvs, and secrets
├── .streamlit/
│   └── config.toml            # Streamlit theme and toolbar configuration
├── tests/
│   ├── test_database.py       # Security, CTE, parameterization, and execution tests
│   └── test_query_generator.py# Pattern translation, revenue calculation, and conversion tests
└── Chinook_Sqlite.sqlite      # SQLite sample music store database (11 tables)
```

---

## 📊 Dataset Attribution

This project uses the open-source **Chinook Database** created by [Luis Rocha](https://github.com/lerocha/chinook-database) under the MIT License.

The database models a digital media store with **11 relational tables**:
* `Artist` (275 records) & `Album` (347 records)
* `Track` (3,503 records), `Genre` (25 records), `MediaType` (5 records)
* `Customer` (59 records) & `Employee` (8 records)
* `Invoice` (412 records) & `InvoiceLine` (2,240 line items)
* `Playlist` (18 records) & `PlaylistTrack` (8,715 records)

---

## 🛠️ Installation & Setup

### Prerequisites
* Python 3.10 or higher
* Git

### 1. Clone the Repository
```bash
git clone <YOUR_REPOSITORY_URL>
cd QueryCraft-AI
```

### 2. Create and Activate a Virtual Environment
```bash
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Optional: Configure External LLM (Not required for offline use)
Copy `.env.example` to `.env` and configure your API key if you want open-ended LLM translation:
```bash
cp .env.example .env
```
*(Leave empty or omitted to use the built-in local pattern engine)*

---

## 💻 Running the Application

Launch the Streamlit web application:

```bash
python -m streamlit run app.py
```

The application will be accessible at `http://localhost:8501` (or your configured port).

---

## 🧪 Supported Query Patterns

The deterministic local engine supports a wide range of natural language patterns:

| Category | Example Question | Generated SQL Logic |
| :--- | :--- | :--- |
| **Artist / Album Rankings** | *"Show the top 5 artists with the most albums"* | `JOIN Artist, Album GROUP BY ArtistId ORDER BY COUNT(*) DESC LIMIT 5` |
| **Catalog Exploration** | *"List all albums by AC/DC"* | `SELECT Title FROM Album JOIN Artist ON ... WHERE Name LIKE '%AC/DC%'` |
| **Audio Duration Filter** | *"Find Rock tracks longer than 5 minutes"* | `JOIN Genre WHERE Genre = 'Rock' AND Milliseconds > 300000` |
| **Track Rankings** | *"Which are the 10 longest tracks?"* | `SELECT ... FROM Track ORDER BY Milliseconds DESC LIMIT 10` |
| **Customer Spending** | *"Which 5 customers have spent the most?"* | `JOIN Customer, Invoice GROUP BY CustomerId ORDER BY SUM(Total) DESC LIMIT 5` |
| **Regional Sales** | *"Show total sales by country"* | `SELECT BillingCountry, SUM(Total) FROM Invoice GROUP BY BillingCountry` |
| **Best-Selling Items** | *"What are the top 5 best-selling tracks?"* | `JOIN InvoiceLine, Track GROUP BY TrackId ORDER BY SUM(Quantity) DESC` |
| **Store Financials** | *"What is the total revenue of the store?"* | `SELECT SUM(Total), AVG(Total) FROM Invoice` |
| **Track Search** | *"Find tracks with name containing Love"* | `SELECT Name FROM Track WHERE Name LIKE '%Love%'` |
| **Genre Breakdown** | *"Show track count by genre"* | `JOIN Genre, Track GROUP BY GenreId ORDER BY COUNT(*) DESC` |

---

## 🔒 Database Safety & Security

QueryCraft AI implements defense-in-depth database security:

1. **Read-Only SQLite Engine**: Connections are opened strictly with SQLite URI parameter `?mode=ro`.
2. **Engine Pragma Lock**: `PRAGMA query_only = ON;` is executed on every connection.
3. **AST Token Inspection**: `sqlparse` tokenizes every query before execution:
   * Rejects multi-statement queries (prevents `; DROP TABLE` injection).
   * Verifies the leading token is strictly `SELECT` or `WITH`.
   * Blacklists destructive keywords (`DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `ATTACH`, `DETACH`, `PRAGMA`, etc.).
   * Rejects SQL comments (`--`, `/* */`) commonly used for filter evasion.
4. **Execution Timeout**: Enforces a 5-second deadline via SQLite progress handlers.
5. **Row Capping**: Limits output to 500 rows with truncation feedback.

---

## 🧪 Running Tests

The test suite covers database safety, parameterization, Common Table Expressions (CTEs), pattern translation, duration conversions, and revenue calculations.

Run the test suite:

```bash
python -m unittest discover tests
```

Expected output:
```text
Ran 24 tests in ~0.1s
OK
```

---

## ⚠️ Limitations & Future Work

* **Local Engine Phrasing**: The local generator matches deterministic patterns and keywords tailored to the Chinook schema; highly irregular phrasing will prompt an informative suggestion unless an optional LLM API key is provided.
* **Session History Scope**: Conversation history is maintained within the active browser session (`st.session_state`) and resets upon full browser reload. Future improvements could include optional SQLite persistence for chat sessions.
* **Schema Scalability**: Current pattern mappings are customized for Chinook. Future iterations could incorporate dynamic vector-based schema indexing.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).  
Chinook Sample Database © Luis Rocha (MIT License).
