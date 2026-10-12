"""Database layer for QueryCraft AI.

Provides safe, read-only SQLite connectivity, strict SQL query sanitization,
query execution with timeouts and row limits, and database schema introspection.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import sqlparse
from sqlparse.sql import Comment, Statement
from sqlparse.tokens import DDL, DML, Keyword


DEFAULT_DB_PATH = Path(__file__).parent / "Chinook_Sqlite.sqlite"
MAX_DISPLAY_ROWS = 500
QUERY_TIMEOUT_SECONDS = 5.0


class DatabaseSecurityError(ValueError):
    """Raised when a query violates safety and read-only policies."""


class DatabaseExecutionError(RuntimeError):
    """Raised when query execution encounters a database or operational error."""


@dataclass
class QueryResult:
    """Represents the outcome of a database query execution."""
    data: pd.DataFrame
    row_count: int
    execution_time_ms: float
    is_truncated: bool = False
    columns: List[str] = field(default_factory=list)
    sql: str = ""


# Disallowed SQL keywords for security
DISALLOWED_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE",
    "ATTACH", "DETACH", "PRAGMA", "REINDEX", "VACUUM", "REPLACE",
    "GRANT", "REVOKE", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE",
    "LOCK", "UNLOCK", "EXEC", "EXECUTE", "UPSERT"
}


def sanitize_and_validate_sql(sql: str) -> str:
    """Validates that the provided SQL is a single, safe, read-only SELECT or CTE query.

    Args:
        sql: The raw SQL query string to validate.

    Returns:
        Cleaned and normalized SQL query string.

    Raises:
        DatabaseSecurityError: If query is empty, multi-statement, contains comments,
                               writes data, alters schema, or uses unsafe constructs.
    """
    if not sql or not sql.strip():
        raise DatabaseSecurityError("SQL query cannot be empty.")

    cleaned_sql = sql.strip().rstrip(";")

    # Check for dangerous characters or semicolons inside the body (multi-statement injection)
    # Parse with sqlparse
    parsed_statements = sqlparse.parse(cleaned_sql)
    # Filter out empty or whitespace-only tokens
    real_statements = [stmt for stmt in parsed_statements if str(stmt).strip()]

    if len(real_statements) == 0:
        raise DatabaseSecurityError("No valid SQL statement found.")

    if len(real_statements) > 1:
        raise DatabaseSecurityError(
            "Multiple statements detected. Only a single read-only query is permitted."
        )

    statement: Statement = real_statements[0]

    # Reject inline comments (-- or /* */) to prevent comment-based evasion
    for token in statement.flatten():
        if isinstance(token, Comment) or token.ttype in sqlparse.tokens.Comment:
            raise DatabaseSecurityError("SQL comments are not allowed.")

    # Flatten tokens and inspect keywords
    tokens = [t for t in statement.flatten() if not t.is_whitespace]
    if not tokens:
        raise DatabaseSecurityError("Statement contains no executable tokens.")

    # First significant token must be SELECT or WITH (for CTEs)
    first_token_val = tokens[0].value.upper()
    if first_token_val not in ("SELECT", "WITH"):
        raise DatabaseSecurityError(
            f"Only SELECT queries or read-only WITH (CTE) queries are permitted. "
            f"Found leading token: '{first_token_val}'."
        )

    # Check for disallowed keywords across all tokens
    token_values = [t.value.upper() for t in tokens]
    for val in token_values:
        # Check exact keyword or word boundary match
        cleaned_val = re.sub(r"[^A-Z]", "", val)
        if cleaned_val in DISALLOWED_KEYWORDS:
            raise DatabaseSecurityError(
                f"Forbidden SQL keyword detected: '{val}'. Write and administrative operations are blocked."
            )

    # If it's a CTE (starts with WITH), ensure it terminates in a SELECT statement
    if first_token_val == "WITH":
        has_select = any(t == "SELECT" for t in token_values)
        if not has_select:
            raise DatabaseSecurityError("CTE query must conclude with a SELECT statement.")

    # Check for sqlite internal functions or schema writing attempts
    upper_sql = cleaned_sql.upper()
    if "SQLITE_MASTER" in upper_sql and any(act in upper_sql for act in ("INSERT", "UPDATE", "DELETE")):
        raise DatabaseSecurityError("Access to sqlite_master modification is strictly forbidden.")

    return cleaned_sql


class DatabaseManager:
    """Manages read-only connections and safe query execution against SQLite."""

    def __init__(self, db_path: Optional[str | Path] = None):
        """Initializes database manager.

        Args:
            db_path: Path to the SQLite database file. Defaults to Chinook_Sqlite.sqlite.
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found at: {self.db_path.resolve()}")

    def get_connection(self) -> sqlite3.Connection:
        """Returns a strict read-only SQLite connection.

        Uses URI mode ('mode=ro') and applies PRAGMA query_only = ON to ensure
        the underlying database cannot be modified under any circumstance.
        """
        # Convert path to absolute URI
        abs_path = self.db_path.resolve().as_posix()
        uri = f"file:{abs_path}?mode=ro"

        try:
            conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
            # Enforce read-only at SQLite engine level as defense in depth
            conn.execute("PRAGMA query_only = ON;")
            return conn
        except sqlite3.Error as e:
            raise DatabaseExecutionError(f"Failed to open database in read-only mode: {e}") from e

    def execute_query(
        self,
        sql: str,
        params: Optional[Tuple[Any, ...] | Dict[str, Any]] = None,
        max_rows: int = MAX_DISPLAY_ROWS,
        timeout_seconds: float = QUERY_TIMEOUT_SECONDS,
    ) -> QueryResult:
        """Sanitizes and executes a read-only SQL query, returning a QueryResult.

        Args:
            sql: The SQL query to execute.
            params: Optional query parameters for safe parameterized execution.
            max_rows: Maximum rows to return before truncating (default 500).
            timeout_seconds: Query execution deadline in seconds.

        Returns:
            QueryResult containing DataFrame, row counts, and timing.

        Raises:
            DatabaseSecurityError: If query fails safety checks.
            DatabaseExecutionError: If execution fails or times out.
        """
        sanitized_sql = sanitize_and_validate_sql(sql)
        params = params or ()

        start_time = time.perf_counter()
        conn = None

        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Set a progress handler to prevent runaway queries (interrupt after N instructions)
            start_clock = time.time()

            def progress_callback():
                if time.time() - start_clock > timeout_seconds:
                    return 1  # 1 interrupts the query execution
                return 0

            # Interrupt check every 10,000 SQLite VM opcodes
            conn.set_progress_handler(progress_callback, 10000)

            cursor.execute(sanitized_sql, params)

            # Fetch up to max_rows + 1 to detect truncation without reading entire huge tables
            rows = cursor.fetchmany(max_rows + 1)
            column_names = [d[0] for d in cursor.description] if cursor.description else []

            is_truncated = len(rows) > max_rows
            if is_truncated:
                display_rows = rows[:max_rows]
            else:
                display_rows = rows

            df = pd.DataFrame(display_rows, columns=column_names)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return QueryResult(
                data=df,
                row_count=len(df),
                execution_time_ms=round(elapsed_ms, 2),
                is_truncated=is_truncated,
                columns=column_names,
                sql=sanitized_sql,
            )

        except sqlite3.OperationalError as e:
            err_msg = str(e)
            if "interrupted" in err_msg.lower():
                raise DatabaseExecutionError(
                    f"Query execution timed out after {timeout_seconds} seconds."
                ) from e
            raise DatabaseExecutionError(f"Database query error: {err_msg}") from e
        except sqlite3.Error as e:
            raise DatabaseExecutionError(f"SQLite error: {e}") from e
        except DatabaseSecurityError:
            raise
        except Exception as e:
            raise DatabaseExecutionError(f"Unexpected execution error: {e}") from e
        finally:
            if conn:
                try:
                    conn.set_progress_handler(None, 0)
                    conn.close()
                except Exception:
                    pass

    def get_schema_summary(self) -> Dict[str, Dict[str, Any]]:
        """Retrieves and returns the full verified database schema metadata."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
            tables = [r[0] for r in cursor.fetchall()]

            schema: Dict[str, Dict[str, Any]] = {}
            for table in tables:
                cursor.execute(f"PRAGMA table_info('{table}');")
                cols = [
                    {"name": c[1], "type": c[2], "notnull": bool(c[3]), "pk": bool(c[5])}
                    for c in cursor.fetchall()
                ]

                cursor.execute(f"PRAGMA foreign_key_list('{table}');")
                fks = [
                    {"from": fk[3], "table": fk[2], "to": fk[4]}
                    for fk in cursor.fetchall()
                ]

                cursor.execute(f'SELECT COUNT(*) FROM "{table}";')
                row_count = cursor.fetchone()[0]

                schema[table] = {
                    "columns": cols,
                    "foreign_keys": fks,
                    "row_count": row_count,
                }
            return schema
        finally:
            conn.close()
