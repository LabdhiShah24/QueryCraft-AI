"""Natural-language query generation pipeline for QueryCraft AI.

Translates plain-English questions into safe, schema-aware SQL queries targeting
the Chinook digital music store database.

Features:
- Deterministic, schema-aware local pattern engine supporting top-N rankings,
  artist/album aggregations, duration filtering with minute-to-millisecond conversion,
  customer spending, non-double-counted revenue calculations, and relational joins.
- Parameterized SQL generation to prevent injection.
- Plain-English explanations for every generated query.
- Helpful, informative rejection messages for ambiguous or unsupported requests.
- Optional external LLM provider integration with graceful local fallback.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


SUPPORTED_GENRES = [
    "Rock", "Jazz", "Metal", "Alternative & Punk", "Rock And Roll", "Blues",
    "Latin", "Reggae", "Pop", "Soundtrack", "Bossa Nova", "Easy Listening",
    "Heavy Metal", "R&B/Soul", "Electronica/Dance", "World", "Hip Hop/Rap",
    "Science Fiction", "TV Shows", "Sci Fi & Fantasy", "Drama", "Comedy",
    "Alternative", "Classical", "Opera"
]

SUPPORTED_COUNTRIES = [
    "USA", "Canada", "France", "Brazil", "Germany", "United Kingdom",
    "Portugal", "India", "Czech Republic", "Sweden", "Spain", "Poland",
    "Norway", "Netherlands", "Italy", "Ireland", "Hungary", "Finland",
    "Denmark", "Chile", "Belgium", "Austria", "Australia", "Argentina"
]


@dataclass
class GeneratedQuery:
    """Encapsulates the result of natural language to SQL translation."""
    user_question: str
    sql: str
    params: Tuple[Any, ...] = field(default_factory=tuple)
    display_sql: str = ""
    explanation: str = ""
    is_supported: bool = True
    confidence: float = 1.0
    category: str = "general"
    engine_used: str = "Local Pattern Engine (Rule-based)"
    suggested_questions: List[str] = field(default_factory=list)


def extract_limit(text: str, default: int = 5) -> int:
    """Extracts top-N or limit count from natural language text."""
    match = re.search(r"\b(?:top|first|best|limit)\s+(\d+)\b", text, re.IGNORECASE)
    if match:
        val = int(match.group(1))
        return min(max(val, 1), 500)
    match = re.search(r"\b(\d+)\s+(?:top|best|longest|shortest|most|highest)\b", text, re.IGNORECASE)
    if match:
        val = int(match.group(1))
        return min(max(val, 1), 500)
    return default


def extract_duration_minutes(text: str) -> Optional[float]:
    """Extracts duration in minutes from text and returns float minutes."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes)\b", text, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def extract_genre(text: str) -> Optional[str]:
    """Finds matching genre from known database genres."""
    for genre in sorted(SUPPORTED_GENRES, key=len, reverse=True):
        # Word boundary match or simple case-insensitive substring
        pattern = r"\b" + re.escape(genre) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return genre
    # Common short aliases
    if re.search(r"\bhip hop\b|\brap\b", text, re.IGNORECASE):
        return "Hip Hop/Rap"
    if re.search(r"\bdance\b|\belectronic\b", text, re.IGNORECASE):
        return "Electronica/Dance"
    if re.search(r"\bpunk\b", text, re.IGNORECASE):
        return "Alternative & Punk"
    return None


def extract_country(text: str) -> Optional[str]:
    """Finds matching country name from supported database countries."""
    for country in sorted(SUPPORTED_COUNTRIES, key=len, reverse=True):
        pattern = r"\b" + re.escape(country) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return country
    # Common aliases
    if re.search(r"\b(united states|us|america)\b", text, re.IGNORECASE):
        return "USA"
    if re.search(r"\b(uk|britain|england)\b", text, re.IGNORECASE):
        return "United Kingdom"
    return None


def extract_year(text: str) -> Optional[str]:
    """Extracts 4-digit invoice year between 2000 and 2099."""
    match = re.search(r"\b(20\d{2})\b", text)
    if match:
        return match.group(1)
    return None


def extract_quoted_entity(text: str) -> Optional[str]:
    """Extracts quoted entity name like 'AC/DC' or "Queen" if provided."""
    match = re.search(r"['\"]([^'\"]+)['\"]", text)
    if match:
        return match.group(1).strip()
    return None


class LocalQueryGenerator:
    """Deterministic, schema-aware natural language to SQL pattern generator."""

    def __init__(self):
        self.example_questions = [
            "Show the top 5 artists with the most albums",
            "Which are the 10 longest tracks?",
            "Show total sales by country",
            "Which 5 customers have spent the most?",
            "Find Rock tracks longer than 5 minutes",
            "How many albums does each artist have?",
        ]

    def generate(self, question: str) -> GeneratedQuery:
        """Parses user question and returns a schema-aligned GeneratedQuery."""
        q_raw = question.strip()
        q = q_raw.lower()

        if not q:
            return GeneratedQuery(
                user_question=question,
                sql="",
                explanation="Please enter a question about the music store database.",
                is_supported=False,
                suggested_questions=self.example_questions[:4],
            )

        # -------------------------------------------------------------
        # 1. Total Store Revenue & Average Order Value
        # -------------------------------------------------------------
        if any(kw in q for kw in ["total revenue", "overall revenue", "total sales", "how much revenue", "store revenue"]) and not any(kw in q for kw in ["by country", "by artist", "by genre", "by customer", "by employee", "per country", "per artist"]):
            sql = (
                "SELECT "
                "  ROUND(SUM(Total), 2) AS TotalRevenue, "
                "  COUNT(InvoiceId) AS TotalInvoices, "
                "  ROUND(AVG(Total), 2) AS AverageInvoiceAmount "
                "FROM Invoice;"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Calculates the overall revenue, invoice volume, and average order value across all recorded transactions in the Invoice table.",
                category="sales",
            )

        if any(kw in q for kw in ["average invoice", "average order", "avg invoice", "mean invoice"]):
            sql = (
                "SELECT "
                "  ROUND(AVG(Total), 2) AS AverageInvoiceAmount, "
                "  ROUND(MIN(Total), 2) AS MinInvoice, "
                "  ROUND(MAX(Total), 2) AS MaxInvoice, "
                "  COUNT(InvoiceId) AS TotalInvoices "
                "FROM Invoice;"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Computes the average, minimum, maximum transaction amounts and total transaction count from the Invoice table.",
                category="sales",
            )

        # -------------------------------------------------------------
        # 2. Sales by Year / Invoices by Year
        # -------------------------------------------------------------
        year = extract_year(q_raw)
        if year and any(kw in q for kw in ["invoice", "sales", "revenue", "orders", "spent"]):
            limit = extract_limit(q_raw, default=20)
            sql = (
                "SELECT "
                "  InvoiceId, CustomerId, InvoiceDate, BillingCountry, Total "
                "FROM Invoice "
                "WHERE strftime('%Y', InvoiceDate) = ? "
                "ORDER BY InvoiceDate DESC "
                f"LIMIT {limit};"
            )
            display_sql = sql.replace("?", f"'{year}'")
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                params=(year,),
                display_sql=display_sql,
                explanation=f"Filters invoices recorded in calendar year {year}, sorted chronologically descending up to {limit} records.",
                category="sales",
            )

        if any(kw in q for kw in ["sales by year", "revenue by year", "annual sales", "annual revenue", "yearly sales", "yearly revenue"]):
            sql = (
                "SELECT "
                "  strftime('%Y', InvoiceDate) AS SalesYear, "
                "  ROUND(SUM(Total), 2) AS AnnualRevenue, "
                "  COUNT(InvoiceId) AS TotalInvoices "
                "FROM Invoice "
                "GROUP BY SalesYear "
                "ORDER BY SalesYear ASC;"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Groups store sales chronologically by calendar year using strftime, computing annual revenue and invoice counts.",
                category="sales",
            )

        # -------------------------------------------------------------
        # 3. Sales / Revenue by Country
        # -------------------------------------------------------------
        if any(kw in q for kw in ["sales by country", "revenue by country", "top countries by", "sales per country", "revenue per country", "country by sales"]):
            limit = extract_limit(q_raw, default=10)
            sql = (
                "SELECT "
                "  BillingCountry AS Country, "
                "  ROUND(SUM(Total), 2) AS TotalSales, "
                "  COUNT(InvoiceId) AS InvoiceCount, "
                "  ROUND(AVG(Total), 2) AS AverageInvoiceValue "
                "FROM Invoice "
                "GROUP BY BillingCountry "
                "ORDER BY TotalSales DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Aggregates total customer purchases and average invoice sizes grouped by billing country, ranking the top {limit} countries by revenue.",
                category="sales",
            )

        # -------------------------------------------------------------
        # 4. Best Selling Artists & Best Selling Tracks (Line-item Revenue, NO double counting)
        # -------------------------------------------------------------
        if any(kw in q for kw in ["best-selling artist", "best selling artist", "top selling artist", "artists by revenue", "artists with most sales", "artist revenue", "artists made the most"]):
            limit = extract_limit(q_raw, default=5)
            sql = (
                "SELECT "
                "  a.Name AS ArtistName, "
                "  SUM(il.Quantity) AS TracksSold, "
                "  ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS TotalRevenue "
                "FROM InvoiceLine il "
                "JOIN Track t ON il.TrackId = t.TrackId "
                "JOIN Album al ON t.AlbumId = al.AlbumId "
                "JOIN Artist a ON al.ArtistId = a.ArtistId "
                "GROUP BY a.ArtistId, a.Name "
                "ORDER BY TotalRevenue DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=(
                    f"Ranks the top {limit} commercial artists by joining InvoiceLine, Track, Album, and Artist. "
                    "Revenue is calculated strictly as SUM(UnitPrice * Quantity) to prevent duplicate invoice counting."
                ),
                category="artists",
            )

        if any(kw in q for kw in ["best-selling track", "best selling track", "most purchased track", "most popular track", "top selling track", "most sold song", "best-selling song", "best selling song"]):
            limit = extract_limit(q_raw, default=10)
            sql = (
                "SELECT "
                "  t.Name AS TrackName, "
                "  a.Name AS ArtistName, "
                "  al.Title AS AlbumTitle, "
                "  SUM(il.Quantity) AS UnitsSold, "
                "  ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS TotalRevenue "
                "FROM InvoiceLine il "
                "JOIN Track t ON il.TrackId = t.TrackId "
                "JOIN Album al ON t.AlbumId = al.AlbumId "
                "JOIN Artist a ON al.ArtistId = a.ArtistId "
                "GROUP BY t.TrackId, t.Name, a.Name, al.Title "
                "ORDER BY UnitsSold DESC, TotalRevenue DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Calculates track popularity by summing units purchased in InvoiceLine, returning the top {limit} tracks with their artist and album info.",
                category="tracks",
            )

        # -------------------------------------------------------------
        # 5. Customer Spending & Demographics
        # -------------------------------------------------------------
        if any(kw in q for kw in ["customer", "customers", "client", "clients"]) and any(kw in q for kw in ["spending", "spent", "highest", "top", "most", "revenue", "best"]):
            limit = extract_limit(q_raw, default=5)
            sql = (
                "SELECT "
                "  c.CustomerId, "
                "  c.FirstName || ' ' || c.LastName AS CustomerName, "
                "  c.Country, "
                "  ROUND(SUM(i.Total), 2) AS TotalSpent, "
                "  COUNT(i.InvoiceId) AS OrderCount "
                "FROM Customer c "
                "JOIN Invoice i ON c.CustomerId = i.CustomerId "
                "GROUP BY c.CustomerId, c.FirstName, c.LastName, c.Country "
                "ORDER BY TotalSpent DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Joins Customer and Invoice tables to aggregate historical spending per individual, ordering by total expenditures to identify the top {limit} customers.",
                category="customers",
            )

        country = extract_country(q_raw)
        if country and any(kw in q for kw in ["customer", "customers", "who lives in", "clients"]):
            limit = extract_limit(q_raw, default=50)
            sql = (
                "SELECT "
                "  CustomerId, "
                "  FirstName || ' ' || LastName AS CustomerName, "
                "  Company, "
                "  City, "
                "  State, "
                "  Country, "
                "  Email "
                "FROM Customer "
                "WHERE Country = ? "
                "ORDER BY LastName, FirstName "
                f"LIMIT {limit};"
            )
            display_sql = sql.replace("?", f"'{country}'")
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                params=(country,),
                display_sql=display_sql,
                explanation=f"Retrieves verified customers registered in {country}, sorted alphabetically by surname.",
                category="customers",
            )

        if any(kw in q for kw in ["customers by country", "customers per country", "count customers by country", "how many customers in each country"]):
            limit = extract_limit(q_raw, default=15)
            sql = (
                "SELECT "
                "  Country, "
                "  COUNT(CustomerId) AS CustomerCount "
                "FROM Customer "
                "GROUP BY Country "
                "ORDER BY CustomerCount DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Groups the Customer directory by country and sorts by customer headcount in descending order (top {limit}).",
                category="customers",
            )

        # -------------------------------------------------------------
        # 6. Artists & Albums
        # -------------------------------------------------------------
        if any(kw in q for kw in ["artist", "artists"]) and any(kw in q for kw in ["most albums", "highest albums", "album count", "number of albums", "albums with most", "each artist", "per artist"]):
            limit = extract_limit(q_raw, default=25 if ("each artist" in q or "per artist" in q) else 5)
            sql = (
                "SELECT "
                "  a.Name AS ArtistName, "
                "  COUNT(al.AlbumId) AS AlbumCount "
                "FROM Artist a "
                "JOIN Album al ON a.ArtistId = al.ArtistId "
                "GROUP BY a.ArtistId, a.Name "
                "ORDER BY AlbumCount DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Joins Artist and Album tables, groups by artist identity, and ranks artists by total album releases (showing top {limit}).",
                category="artists",
            )

        # "List albums by {Artist}" / "Albums for {Artist}"
        quoted = extract_quoted_entity(q_raw)
        artist_name = None
        if quoted:
            artist_name = quoted
        else:
            match = re.search(r"\b(?:by|for|of)\s+([A-Za-z0-9&/\s\-]+?)(?:\s+(?:band|group|artist|music))?$", q_raw, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if candidate.lower() not in ["genre", "country", "date", "album", "artist", "track", "minutes"]:
                    artist_name = candidate

        if artist_name and any(kw in q for kw in ["album", "albums"]) and not any(kw in q for kw in ["most albums", "longest"]):
            param_val = f"%{artist_name}%"
            sql = (
                "SELECT "
                "  al.Title AS AlbumTitle, "
                "  a.Name AS ArtistName "
                "FROM Album al "
                "JOIN Artist a ON al.ArtistId = a.ArtistId "
                "WHERE a.Name LIKE ? "
                "ORDER BY al.Title;"
            )
            display_sql = sql.replace("?", f"'{param_val}'")
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                params=(param_val,),
                display_sql=display_sql,
                explanation=f"Queries albums associated with artists matching '{artist_name}', sorting catalog titles alphabetically.",
                category="albums",
            )

        # -------------------------------------------------------------
        # 7. Tracks by Genre and Duration (Minutes -> Milliseconds conversion)
        # -------------------------------------------------------------
        duration_mins = extract_duration_minutes(q_raw)
        genre = extract_genre(q_raw)

        is_longer = any(kw in q for kw in ["longer than", "more than", "greater than", "over", "above", "exceeding"])
        is_shorter = any(kw in q for kw in ["shorter than", "less than", "under", "below"])

        if duration_mins is not None:
            ms_threshold = int(duration_mins * 60 * 1000)
            limit = extract_limit(q_raw, default=25)
            comp_op = ">" if is_longer else ("<" if is_shorter else ">")
            order_dir = "DESC" if comp_op == ">" else "ASC"
            label = "longer" if comp_op == ">" else "shorter"

            if genre:
                sql = (
                    "SELECT "
                    "  t.Name AS TrackName, "
                    "  g.Name AS GenreName, "
                    "  a.Name AS ArtistName, "
                    "  al.Title AS AlbumTitle, "
                    "  ROUND(t.Milliseconds / 60000.0, 2) AS DurationMinutes "
                    "FROM Track t "
                    "JOIN Genre g ON t.GenreId = g.GenreId "
                    "JOIN Album al ON t.AlbumId = al.AlbumId "
                    "JOIN Artist a ON al.ArtistId = a.ArtistId "
                    f"WHERE g.Name = ? AND t.Milliseconds {comp_op} ? "
                    f"ORDER BY t.Milliseconds {order_dir} "
                    f"LIMIT {limit};"
                )
                display_sql = sql.replace("g.Name = ?", f"g.Name = '{genre}'").replace(f"Milliseconds {comp_op} ?", f"Milliseconds {comp_op} {ms_threshold}")
                return GeneratedQuery(
                    user_question=question,
                    sql=sql,
                    params=(genre, ms_threshold),
                    display_sql=display_sql,
                    explanation=(
                        f"Filters tracks in the '{genre}' genre with duration {label} than {duration_mins} minutes "
                        f"(converted internally to {ms_threshold:,} milliseconds), joining Genre, Album, and Artist tables."
                    ),
                    category="tracks",
                )
            else:
                sql = (
                    "SELECT "
                    "  t.Name AS TrackName, "
                    "  g.Name AS GenreName, "
                    "  a.Name AS ArtistName, "
                    "  al.Title AS AlbumTitle, "
                    "  ROUND(t.Milliseconds / 60000.0, 2) AS DurationMinutes "
                    "FROM Track t "
                    "JOIN Genre g ON t.GenreId = g.GenreId "
                    "JOIN Album al ON t.AlbumId = al.AlbumId "
                    "JOIN Artist a ON al.ArtistId = a.ArtistId "
                    f"WHERE t.Milliseconds {comp_op} ? "
                    f"ORDER BY t.Milliseconds {order_dir} "
                    f"LIMIT {limit};"
                )
                display_sql = sql.replace(f"Milliseconds {comp_op} ?", f"Milliseconds {comp_op} {ms_threshold}")
                return GeneratedQuery(
                    user_question=question,
                    sql=sql,
                    params=(ms_threshold,),
                    display_sql=display_sql,
                    explanation=(
                        f"Retrieves tracks {label} than {duration_mins} minutes ({ms_threshold:,} milliseconds), "
                        f"returning track title, genre, artist, and duration in minutes."
                    ),
                    category="tracks",
                )

        # Genre track counts
        if any(kw in q for kw in ["tracks by genre", "track count by genre", "songs by genre", "genres by track count", "popular genres"]):
            limit = extract_limit(q_raw, default=15)
            sql = (
                "SELECT "
                "  g.Name AS GenreName, "
                "  COUNT(t.TrackId) AS TrackCount "
                "FROM Genre g "
                "JOIN Track t ON g.GenreId = t.GenreId "
                "GROUP BY g.GenreId, g.Name "
                "ORDER BY TrackCount DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Aggregates total track inventory per musical genre and presents the top {limit} genres.",
                category="genres",
            )

        # Tracks in a specific genre without duration
        if genre and any(kw in q for kw in ["track", "tracks", "song", "songs", "list", "show"]):
            limit = extract_limit(q_raw, default=20)
            sql = (
                "SELECT "
                "  t.Name AS TrackName, "
                "  a.Name AS ArtistName, "
                "  al.Title AS AlbumTitle, "
                "  ROUND(t.Milliseconds / 60000.0, 2) AS DurationMinutes, "
                "  t.UnitPrice "
                "FROM Track t "
                "JOIN Genre g ON t.GenreId = g.GenreId "
                "JOIN Album al ON t.AlbumId = al.AlbumId "
                "JOIN Artist a ON al.ArtistId = a.ArtistId "
                "WHERE g.Name = ? "
                "ORDER BY t.Name "
                f"LIMIT {limit};"
            )
            display_sql = sql.replace("?", f"'{genre}'")
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                params=(genre,),
                display_sql=display_sql,
                explanation=f"Lists songs cataloged under the '{genre}' genre, linking Track, Album, and Artist metadata.",
                category="genres",
            )

        # -------------------------------------------------------------
        # 8. Track Length Rankings (Longest / Shortest)
        # -------------------------------------------------------------
        if any(kw in q for kw in ["longest track", "longest tracks", "longest song", "longest songs"]):
            limit = extract_limit(q_raw, default=10)
            sql = (
                "SELECT "
                "  t.Name AS TrackName, "
                "  a.Name AS ArtistName, "
                "  al.Title AS AlbumTitle, "
                "  g.Name AS GenreName, "
                "  ROUND(t.Milliseconds / 60000.0, 2) AS DurationMinutes "
                "FROM Track t "
                "JOIN Album al ON t.AlbumId = al.AlbumId "
                "JOIN Artist a ON al.ArtistId = a.ArtistId "
                "JOIN Genre g ON t.GenreId = g.GenreId "
                "ORDER BY t.Milliseconds DESC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Queries the top {limit} longest audio tracks by Milliseconds descending, converting play duration to minutes for user readability.",
                category="tracks",
            )

        if any(kw in q for kw in ["shortest track", "shortest tracks", "shortest song", "shortest songs"]):
            limit = extract_limit(q_raw, default=10)
            sql = (
                "SELECT "
                "  t.Name AS TrackName, "
                "  a.Name AS ArtistName, "
                "  al.Title AS AlbumTitle, "
                "  g.Name AS GenreName, "
                "  ROUND(t.Milliseconds / 60000.0, 2) AS DurationMinutes "
                "FROM Track t "
                "JOIN Album al ON t.AlbumId = al.AlbumId "
                "JOIN Artist a ON al.ArtistId = a.ArtistId "
                "JOIN Genre g ON t.GenreId = g.GenreId "
                "ORDER BY t.Milliseconds ASC "
                f"LIMIT {limit};"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation=f"Queries the top {limit} shortest audio tracks by Milliseconds ascending, converting duration to decimal minutes.",
                category="tracks",
            )

        # -------------------------------------------------------------
        # 9. Track Search by Name / Keyword
        # -------------------------------------------------------------
        search_keyword = None
        quoted_kw = extract_quoted_entity(q_raw)
        if quoted_kw and any(kw in q for kw in ["track", "song", "title", "find", "search"]):
            search_keyword = quoted_kw
        else:
            for pat in [
                r"(?:with\s+name\s+containing|name\s+containing|containing)\s+['\"]?([A-Za-z0-9\s]+)['\"]?",
                r"(?:with\s+title|named|called)\s+['\"]?([A-Za-z0-9\s]+)['\"]?",
                r"(?:tracks?\s+with|songs?\s+with)\s+['\"]?([A-Za-z0-9\s]+)['\"]?\s+(?:in\s+the\s+title|in\s+title)",
                r"(?:search\s+for\s+tracks?|search\s+for\s+songs?|search\s+for)\s+['\"]?([A-Za-z0-9\s]+)['\"]?",
                r"(?:find\s+tracks?|find\s+songs?)\s+named\s+['\"]?([A-Za-z0-9\s]+)['\"]?",
            ]:
                match = re.search(pat, q_raw, re.IGNORECASE)
                if match:
                    candidate = match.group(1).strip()
                    candidate = re.sub(r"\b(in the title|in title|in name)\b", "", candidate, flags=re.IGNORECASE).strip()
                    if candidate.lower() not in ["the", "a", "an", "all", "tracks", "songs"]:
                        search_keyword = candidate
                        break

        if search_keyword and any(kw in q for kw in ["track", "song", "title", "name", "find", "search"]):
            limit = extract_limit(q_raw, default=20)
            param_val = f"%{search_keyword}%"
            sql = (
                "SELECT "
                "  t.Name AS TrackName, "
                "  al.Title AS AlbumTitle, "
                "  a.Name AS ArtistName, "
                "  g.Name AS GenreName, "
                "  ROUND(t.Milliseconds / 60000.0, 2) AS DurationMinutes "
                "FROM Track t "
                "JOIN Album al ON t.AlbumId = al.AlbumId "
                "JOIN Artist a ON al.ArtistId = a.ArtistId "
                "JOIN Genre g ON t.GenreId = g.GenreId "
                "WHERE t.Name LIKE ? "
                "ORDER BY t.Name "
                f"LIMIT {limit};"
            )
            display_sql = sql.replace("?", f"'{param_val}'")
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                params=(param_val,),
                display_sql=display_sql,
                explanation=f"Executes case-insensitive pattern matching on track names matching '{search_keyword}', returning song metadata and durations.",
                category="tracks",
            )

        # -------------------------------------------------------------
        # 10. Employees / Sales Representatives Performance
        # -------------------------------------------------------------
        if any(kw in q for kw in ["employee", "employees", "sales rep", "support rep", "staff"]) and any(kw in q for kw in ["sales", "performance", "revenue", "most", "top"]):
            sql = (
                "SELECT "
                "  e.EmployeeId, "
                "  e.FirstName || ' ' || e.LastName AS EmployeeName, "
                "  e.Title, "
                "  ROUND(SUM(i.Total), 2) AS TotalSalesAssisted, "
                "  COUNT(DISTINCT c.CustomerId) AS ClientsSupported "
                "FROM Employee e "
                "JOIN Customer c ON e.EmployeeId = c.SupportRepId "
                "JOIN Invoice i ON c.CustomerId = i.CustomerId "
                "GROUP BY e.EmployeeId, e.FirstName, e.LastName, e.Title "
                "ORDER BY TotalSalesAssisted DESC;"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Joins Employee, Customer, and Invoice tables on SupportRepId to calculate total revenue supported and distinct customers handled per sales rep.",
                category="employees",
            )

        if any(kw in q for kw in ["list employees", "all employees", "show employees", "who works here"]):
            sql = (
                "SELECT "
                "  EmployeeId, "
                "  FirstName || ' ' || LastName AS FullName, "
                "  Title, "
                "  City, "
                "  Country, "
                "  Email, "
                "  HireDate "
                "FROM Employee "
                "ORDER BY LastName, FirstName;"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Retrieves the staff roster from the Employee table, showing positions, locations, contact info, and hiring dates.",
                category="employees",
            )

        # -------------------------------------------------------------
        # 11. Playlists & Media Types
        # -------------------------------------------------------------
        if any(kw in q for kw in ["playlist", "playlists"]):
            sql = (
                "SELECT "
                "  p.Name AS PlaylistName, "
                "  COUNT(pt.TrackId) AS TrackCount "
                "FROM Playlist p "
                "LEFT JOIN PlaylistTrack pt ON p.PlaylistId = pt.PlaylistId "
                "GROUP BY p.PlaylistId, p.Name "
                "ORDER BY TrackCount DESC;"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Computes the number of tracks attached to each playlist using a LEFT JOIN on Playlist and PlaylistTrack.",
                category="playlists",
            )

        if any(kw in q for kw in ["media type", "media types", "audio format", "file format"]):
            sql = (
                "SELECT "
                "  m.Name AS MediaTypeName, "
                "  COUNT(t.TrackId) AS TrackCount "
                "FROM MediaType m "
                "JOIN Track t ON m.MediaTypeId = t.MediaTypeId "
                "GROUP BY m.MediaTypeId, m.Name "
                "ORDER BY TrackCount DESC;"
            )
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Breaks down track inventory by audio/video encoding format using the MediaType catalog.",
                category="media",
            )

        # -------------------------------------------------------------
        # 12. General Table Record Counts
        # -------------------------------------------------------------
        if any(kw in q for kw in ["how many artists", "number of artists", "count of artists", "total artists"]):
            sql = "SELECT COUNT(*) AS TotalArtists FROM Artist;"
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Counts total artist records in the database.",
                category="artists",
            )

        if any(kw in q for kw in ["how many albums", "number of albums", "count of albums", "total albums"]):
            sql = "SELECT COUNT(*) AS TotalAlbums FROM Album;"
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Counts total album catalog entries in the database.",
                category="albums",
            )

        if any(kw in q for kw in ["how many tracks", "number of tracks", "how many songs", "count of tracks", "total tracks"]):
            sql = "SELECT COUNT(*) AS TotalTracks FROM Track;"
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Counts total available tracks in the database.",
                category="tracks",
            )

        if any(kw in q for kw in ["how many customers", "number of customers", "total customers"]):
            sql = "SELECT COUNT(*) AS TotalCustomers FROM Customer;"
            return GeneratedQuery(
                user_question=question,
                sql=sql,
                display_sql=sql,
                explanation="Counts registered customers in the database.",
                category="customers",
            )

        # -------------------------------------------------------------
        # Unsupported or Ambiguous Query Handling
        # -------------------------------------------------------------
        return GeneratedQuery(
            user_question=question,
            sql="",
            display_sql="",
            explanation=(
                f"I could not map \"{question}\" to a music store query. "
                "QueryCraft AI answers questions about songs, artists, albums, sales, and customers in the Chinook database. "
                "Try selecting one of the suggested questions below or rephrasing your question."
            ),
            is_supported=False,
            confidence=0.0,
            category="unsupported",
            suggested_questions=self.example_questions,
        )


def generate_query(
    user_question: str,
    use_llm_if_available: bool = True,
) -> GeneratedQuery:
    """Primary pipeline entry point to translate natural language into SQL.

    Attempts optional LLM translation if API key is provided and requested,
    otherwise uses the robust schema-aware local pattern engine.

    Args:
        user_question: The user's question in plain English.
        use_llm_if_available: Flag to permit LLM when credentials exist.

    Returns:
        GeneratedQuery containing SQL, explanation, parameters, and metadata.
    """
    local_gen = LocalQueryGenerator()

    # Optional external LLM integration via environment variable
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    if use_llm_if_available and (openai_key or gemini_key):
        try:
            # We will attempt LLM generation if configured
            from query_generator_llm import generate_query_with_llm  # type: ignore
            llm_result = generate_query_with_llm(user_question)
            if llm_result and llm_result.is_supported:
                return llm_result
        except Exception:
            # Fall back safely to local engine without crashing
            pass

    # Use deterministic local generator
    return local_gen.generate(user_question)
