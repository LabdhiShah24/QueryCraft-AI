"""Unit tests for the Database layer of QueryCraft AI."""

import unittest
from pathlib import Path

from database import (
    DatabaseExecutionError,
    DatabaseManager,
    DatabaseSecurityError,
    MAX_DISPLAY_ROWS,
    sanitize_and_validate_sql,
)


class TestDatabaseManager(unittest.TestCase):
    """Test suite for safe database operations and security controls."""

    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()

    def test_database_file_exists(self):
        """Verify the database file exists and is accessible."""
        self.assertTrue(self.db.db_path.exists())

    def test_schema_summary(self):
        """Verify schema inspection returns all expected tables and columns."""
        schema = self.db.get_schema_summary()
        expected_tables = {
            "Album", "Artist", "Customer", "Employee", "Genre",
            "Invoice", "InvoiceLine", "MediaType", "Playlist",
            "PlaylistTrack", "Track"
        }
        self.assertTrue(expected_tables.issubset(set(schema.keys())))
        self.assertGreater(schema["Track"]["row_count"], 3000)
        self.assertEqual(schema["Genre"]["row_count"], 25)

    def test_valid_select_query(self):
        """Test executing a standard valid SELECT query."""
        res = self.db.execute_query("SELECT ArtistId, Name FROM Artist LIMIT 5;")
        self.assertEqual(res.row_count, 5)
        self.assertEqual(list(res.data.columns), ["ArtistId", "Name"])
        self.assertFalse(res.is_truncated)
        self.assertGreaterEqual(res.execution_time_ms, 0)

    def test_parameterized_query(self):
        """Test executing parameterized query safely."""
        res = self.db.execute_query(
            "SELECT CustomerId, FirstName, LastName FROM Customer WHERE Country = ? LIMIT 10",
            params=("Brazil",),
        )
        self.assertGreater(res.row_count, 0)
        self.assertTrue(all(res.data["CustomerId"] > 0))

    def test_row_limit_enforcement(self):
        """Verify queries exceeding MAX_DISPLAY_ROWS are safely capped and flagged."""
        # Track table has 3503 rows
        res = self.db.execute_query("SELECT * FROM Track;")
        self.assertEqual(res.row_count, MAX_DISPLAY_ROWS)
        self.assertTrue(res.is_truncated)

    def test_cte_query_supported(self):
        """Verify read-only Common Table Expressions (WITH ... SELECT) are permitted."""
        cte_sql = (
            "WITH TrackCounts AS ("
            "  SELECT AlbumId, COUNT(*) AS TrackCount FROM Track GROUP BY AlbumId"
            ") "
            "SELECT a.Title, tc.TrackCount "
            "FROM TrackCounts tc "
            "JOIN Album a ON tc.AlbumId = a.AlbumId "
            "ORDER BY tc.TrackCount DESC "
            "LIMIT 3;"
        )
        res = self.db.execute_query(cte_sql)
        self.assertEqual(res.row_count, 3)
        self.assertIn("Title", res.data.columns)

    def test_reject_write_and_ddl_operations(self):
        """Verify all destructive, modification, and administrative queries are blocked."""
        dangerous_queries = [
            "DROP TABLE Artist;",
            "DELETE FROM Customer WHERE CustomerId = 1;",
            "INSERT INTO Artist (Name) VALUES ('Malicious Artist');",
            "UPDATE Customer SET FirstName = 'Hacked' WHERE CustomerId = 1;",
            "ALTER TABLE Customer ADD COLUMN Hacked TEXT;",
            "CREATE TABLE NewTable (id INT);",
            "ATTACH DATABASE ':memory:' AS evil;",
            "PRAGMA table_info(Customer);",
            "VACUUM;",
        ]
        for query in dangerous_queries:
            with self.subTest(query=query):
                with self.assertRaises(DatabaseSecurityError):
                    self.db.execute_query(query)

    def test_reject_multistatement_injection(self):
        """Verify semicolon multi-statement injection attempts are rejected."""
        injections = [
            "SELECT * FROM Artist; DROP TABLE Album;",
            "SELECT 1; SELECT 2;",
            "SELECT * FROM Customer; DELETE FROM Invoice;",
        ]
        for query in injections:
            with self.subTest(query=query):
                with self.assertRaises(DatabaseSecurityError):
                    self.db.execute_query(query)

    def test_reject_sql_comments(self):
        """Verify SQL comments used for evasion are blocked."""
        comment_queries = [
            "SELECT * FROM Artist -- this is a comment",
            "SELECT * FROM Customer /* block comment */ WHERE CustomerId = 1",
        ]
        for query in comment_queries:
            with self.subTest(query=query):
                with self.assertRaises(DatabaseSecurityError):
                    self.db.execute_query(query)

    def test_reject_empty_query(self):
        """Verify empty or whitespace query is rejected."""
        with self.assertRaises(DatabaseSecurityError):
            self.db.execute_query("   ")

    def test_invalid_sql_syntax_handling(self):
        """Verify syntax or column errors raise friendly DatabaseExecutionError without raw crashes."""
        with self.assertRaises(DatabaseExecutionError) as ctx:
            self.db.execute_query("SELECT NonExistentColumn FROM Artist;")
        self.assertIn("no such column", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
