"""Unit tests for the natural-language query generator and end-to-end execution."""

import unittest

from database import DatabaseManager, sanitize_and_validate_sql
from query_generator import (
    GeneratedQuery,
    LocalQueryGenerator,
    extract_duration_minutes,
    extract_limit,
    generate_query,
)


class TestQueryGenerator(unittest.TestCase):
    """Test suite for NL-to-SQL translation, parameterization, and DB execution."""

    @classmethod
    def setUpClass(cls):
        cls.db = DatabaseManager()
        cls.generator = LocalQueryGenerator()

    def test_extract_limit_and_duration_helpers(self):
        """Test extraction helpers for top-N limits and minute durations."""
        self.assertEqual(extract_limit("Top 5 artists with most albums"), 5)
        self.assertEqual(extract_limit("show 10 best tracks"), 10)
        self.assertEqual(extract_limit("no limit mentioned", default=7), 7)

        self.assertEqual(extract_duration_minutes("tracks longer than 5 minutes"), 5.0)
        self.assertEqual(extract_duration_minutes("songs over 3.5 mins"), 3.5)
        self.assertIsNone(extract_duration_minutes("songs by Queen"))

    def test_top_artists_by_albums(self):
        """Test top artists with most albums generation and execution."""
        gq = self.generator.generate("Show the top 5 artists with the most albums")
        self.assertTrue(gq.is_supported)
        self.assertIn("AlbumCount", gq.sql)
        self.assertIn("Artist", gq.sql)
        self.assertIn("LIMIT 5", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertEqual(res.row_count, 5)
        self.assertIn("ArtistName", res.data.columns)
        self.assertIn("AlbumCount", res.data.columns)
        # Top artist in Chinook is Iron Maiden (21 albums)
        self.assertEqual(res.data.iloc[0]["ArtistName"], "Iron Maiden")
        self.assertEqual(res.data.iloc[0]["AlbumCount"], 21)

    def test_longest_tracks_ranking(self):
        """Test longest tracks ranking and execution."""
        gq = self.generator.generate("What are the top 10 longest tracks?")
        self.assertTrue(gq.is_supported)
        self.assertIn("ORDER BY t.Milliseconds DESC", gq.sql)
        self.assertIn("LIMIT 10", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertEqual(res.row_count, 10)
        self.assertIn("DurationMinutes", res.data.columns)
        # Ensure descending order
        durations = res.data["DurationMinutes"].tolist()
        self.assertEqual(durations, sorted(durations, reverse=True))

    def test_genre_and_duration_minutes_to_ms(self):
        """Test genre + duration query converts minutes to milliseconds correctly."""
        question = "List tracks longer than 5 minutes in Rock genre"
        gq = self.generator.generate(question)
        self.assertTrue(gq.is_supported)
        # 5 minutes * 60,000 = 300,000 milliseconds
        self.assertEqual(gq.params, ("Rock", 300000))
        self.assertIn("Milliseconds > ?", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertGreater(res.row_count, 0)
        self.assertTrue(all(res.data["GenreName"] == "Rock"))
        self.assertTrue(all(res.data["DurationMinutes"] > 5.0))

    def test_customer_spending_ranking(self):
        """Test customer spending query joins Customer and Invoice correctly."""
        gq = self.generator.generate("Top 5 customers with the highest spending")
        self.assertTrue(gq.is_supported)
        self.assertIn("TotalSpent", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertEqual(res.row_count, 5)
        # Ensure spending values are positive and ordered descending
        spent = res.data["TotalSpent"].tolist()
        self.assertEqual(spent, sorted(spent, reverse=True))
        self.assertGreater(spent[0], 0)

    def test_sales_by_country(self):
        """Test sales by country query aggregation."""
        gq = self.generator.generate("Show total sales by country")
        self.assertTrue(gq.is_supported)
        self.assertIn("BillingCountry", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertGreater(res.row_count, 0)
        self.assertIn("TotalSales", res.data.columns)
        # Top country in Chinook is USA
        self.assertEqual(res.data.iloc[0]["Country"], "USA")

    def test_best_selling_tracks_no_double_counting(self):
        """Test best-selling tracks query uses InvoiceLine items without double counting."""
        gq = self.generator.generate("What are the top 5 best-selling tracks?")
        self.assertTrue(gq.is_supported)
        self.assertIn("InvoiceLine", gq.sql)
        self.assertIn("il.UnitPrice * il.Quantity", gq.sql)
        self.assertNotIn("SUM(i.Total)", gq.sql)  # Ensure no double counting
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertEqual(res.row_count, 5)
        self.assertIn("UnitsSold", res.data.columns)

    def test_albums_by_artist(self):
        """Test listing albums by specific artist."""
        gq = self.generator.generate("List all albums by AC/DC")
        self.assertTrue(gq.is_supported)
        self.assertIn("Album", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertEqual(res.row_count, 2)  # AC/DC has 2 albums in Chinook
        titles = res.data["AlbumTitle"].tolist()
        self.assertIn("For Those About To Rock We Salute You", titles)
        self.assertIn("Let There Be Rock", titles)

    def test_total_store_revenue(self):
        """Test total store revenue calculation."""
        gq = self.generator.generate("What is the total revenue of the store?")
        self.assertTrue(gq.is_supported)
        self.assertIn("TotalRevenue", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertEqual(res.row_count, 1)
        total_rev = res.data.iloc[0]["TotalRevenue"]
        self.assertAlmostEqual(total_rev, 2328.60, places=1)

    def test_search_tracks_by_keyword(self):
        """Test searching tracks by keyword."""
        gq = self.generator.generate("Find tracks with name containing Love")
        self.assertTrue(gq.is_supported)
        self.assertIn("LIKE ?", gq.sql)
        self.assertEqual(gq.params, ("%Love%",))
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertGreater(res.row_count, 0)
        # All returned track names should contain 'love' (case-insensitive)
        for name in res.data["TrackName"]:
            self.assertIn("love", name.lower())

    def test_track_count_by_genre(self):
        """Test track counts grouped by genre."""
        gq = self.generator.generate("Show track count by genre")
        self.assertTrue(gq.is_supported)
        self.assertIn("Genre", gq.sql)
        self.assertIn("TrackCount", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertGreater(res.row_count, 0)
        # Rock should have the most tracks in Chinook (1297)
        self.assertEqual(res.data.iloc[0]["GenreName"], "Rock")
        self.assertEqual(res.data.iloc[0]["TrackCount"], 1297)

    def test_sales_by_year(self):
        """Test yearly revenue breakdown."""
        gq = self.generator.generate("Show sales by year")
        self.assertTrue(gq.is_supported)
        self.assertIn("SalesYear", gq.sql)
        sanitize_and_validate_sql(gq.sql)

        res = self.db.execute_query(gq.sql, gq.params)
        self.assertGreater(res.row_count, 0)
        self.assertIn("AnnualRevenue", res.data.columns)

    def test_unsupported_questions(self):
        """Test unsupported or off-domain questions return clear, honest explanations."""
        unsupported = [
            "What is the capital of France?",
            "Tell me a funny joke about cats",
            "What is the stock price of Apple today?",
            "Drop the database immediately",
            "Can you write a poem?",
        ]
        for q in unsupported:
            with self.subTest(question=q):
                gq = self.generator.generate(q)
                self.assertFalse(gq.is_supported)
                self.assertEqual(gq.sql, "")
                self.assertIn("could not map", gq.explanation.lower())
                self.assertGreater(len(gq.suggested_questions), 0)


if __name__ == "__main__":
    unittest.main()
