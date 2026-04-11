"""Tests for AskePub core_worker module."""

import hashlib
import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Add src to path so we can import core_worker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ---------------------------------------------------------------------------
# _escape_html
# ---------------------------------------------------------------------------

class TestEscapeHtml:
    def test_escapes_ampersand(self):
        from core_worker import _escape_html
        assert _escape_html("Tom & Jerry") == "Tom &amp; Jerry"

    def test_escapes_angle_brackets(self):
        from core_worker import _escape_html
        assert _escape_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_escapes_quotes(self):
        from core_worker import _escape_html
        assert _escape_html('He said "hello"') == 'He said &quot;hello&quot;'

    def test_empty_string(self):
        from core_worker import _escape_html
        assert _escape_html("") == ""

    def test_no_special_chars(self):
        from core_worker import _escape_html
        assert _escape_html("plain text") == "plain text"

    def test_all_special_chars_combined(self):
        from core_worker import _escape_html
        assert _escape_html('&<>"') == "&amp;&lt;&gt;&quot;"


# ---------------------------------------------------------------------------
# _build_notes_html
# ---------------------------------------------------------------------------

class TestBuildNotesHtml:
    def test_single_note(self):
        from core_worker import _build_notes_html
        questions = ["What is the main idea?"]
        notes = {0: "The main idea is X."}
        result = _build_notes_html(questions, notes)
        assert "Study Notes - AskePub" in result
        assert "What is the main idea?" in result
        assert "The main idea is X." in result

    def test_multiple_notes(self):
        from core_worker import _build_notes_html
        questions = ["Q1?", "Q2?", "Q3?"]
        notes = {0: "A1", 1: "A2", 2: "A3"}
        result = _build_notes_html(questions, notes)
        assert "Q1?" in result
        assert "Q2?" in result
        assert "Q3?" in result

    def test_notes_with_missing_question_index(self):
        from core_worker import _build_notes_html
        questions = ["Only one question"]
        notes = {0: "Answer zero", 5: "Answer five"}
        result = _build_notes_html(questions, notes)
        assert "Only one question" in result
        assert "Question 6" in result  # fallback for missing index
        assert "Answer five" in result

    def test_empty_notes(self):
        from core_worker import _build_notes_html
        result = _build_notes_html([], {})
        assert "Study Notes - AskePub" in result

    def test_html_escaping_in_notes(self):
        from core_worker import _build_notes_html
        questions = ["What about <tags>?"]
        notes = {0: "Use &amp; entities"}
        result = _build_notes_html(questions, notes)
        assert "&lt;tags&gt;" in result


# ---------------------------------------------------------------------------
# _parse_numbered_answers
# ---------------------------------------------------------------------------

class TestParseNumberedAnswers:
    def test_standard_numbered_response(self):
        from core_worker import _parse_numbered_answers
        text = "1. First answer here.\n2. Second answer here.\n3. Third answer."
        result = _parse_numbered_answers(text, 3)
        assert result[0] == "First answer here."
        assert result[1] == "Second answer here."
        assert result[2] == "Third answer."

    def test_multiline_answers(self):
        from core_worker import _parse_numbered_answers
        text = "1. First answer\nwith continuation.\n2. Second answer."
        result = _parse_numbered_answers(text, 2)
        assert "First answer\nwith continuation." in result[0]
        assert result[1] == "Second answer."

    def test_fallback_double_newline_split(self):
        from core_worker import _parse_numbered_answers
        text = "First block of text.\n\nSecond block of text."
        result = _parse_numbered_answers(text, 2)
        assert 0 in result
        assert 1 in result

    def test_single_answer(self):
        from core_worker import _parse_numbered_answers
        text = "1. The only answer."
        result = _parse_numbered_answers(text, 1)
        assert result[0] == "The only answer."

    def test_empty_text(self):
        from core_worker import _parse_numbered_answers
        result = _parse_numbered_answers("", 0)
        assert result == {}


# ---------------------------------------------------------------------------
# _cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_deterministic(self):
        from core_worker import _cache_key
        key1 = _cache_key("chapter text", ["q1", "q2"])
        key2 = _cache_key("chapter text", ["q1", "q2"])
        assert key1 == key2

    def test_different_text_different_key(self):
        from core_worker import _cache_key
        key1 = _cache_key("text A", ["q1"])
        key2 = _cache_key("text B", ["q1"])
        assert key1 != key2

    def test_different_questions_different_key(self):
        from core_worker import _cache_key
        key1 = _cache_key("text", ["q1"])
        key2 = _cache_key("text", ["q2"])
        assert key1 != key2

    def test_returns_sha256_hex(self):
        from core_worker import _cache_key
        key = _cache_key("hello", ["world"])
        assert len(key) == 64  # SHA-256 hex digest length


# ---------------------------------------------------------------------------
# _walk_toc
# ---------------------------------------------------------------------------

class TestWalkToc:
    def test_flat_toc(self):
        from core_worker import _walk_toc
        item1 = MagicMock(href="chapter1.xhtml#sec1", title="Chapter 1")
        item2 = MagicMock(href="chapter2.xhtml", title="Chapter 2")
        title_map = {}
        _walk_toc([item1, item2], title_map)
        assert title_map["chapter1.xhtml"] == "Chapter 1"
        assert title_map["chapter2.xhtml"] == "Chapter 2"

    def test_nested_toc(self):
        from core_worker import _walk_toc
        child = MagicMock(href="child.xhtml", title="Child Chapter")
        section = MagicMock(href="section.xhtml", title="Section")
        nested = (section, [child])
        title_map = {}
        _walk_toc([nested], title_map)
        assert title_map["section.xhtml"] == "Section"
        assert title_map["child.xhtml"] == "Child Chapter"

    def test_empty_toc(self):
        from core_worker import _walk_toc
        title_map = {}
        _walk_toc([], title_map)
        assert title_map == {}

    def test_href_fragment_stripped(self):
        from core_worker import _walk_toc
        item = MagicMock(href="ch1.xhtml#part2", title="Part 2")
        title_map = {}
        _walk_toc([item], title_map)
        assert "ch1.xhtml" in title_map
        assert "ch1.xhtml#part2" not in title_map


# ---------------------------------------------------------------------------
# parse_epub (mocked ebooklib)
# ---------------------------------------------------------------------------

class TestParseEpub:
    @patch('core_worker.epub')
    def test_filters_short_chapters(self, mock_epub):
        from core_worker import parse_epub

        # Create a mock book with one short and one long item
        mock_book = MagicMock()
        mock_book.toc = []

        short_item = MagicMock()
        short_item.get_content.return_value = b"<html><body><p>Short</p></body></html>"
        short_item.get_name.return_value = "short.xhtml"

        long_text = "A " * 200  # well over MIN_CHAPTER_TEXT_LENGTH
        long_item = MagicMock()
        long_item.get_content.return_value = f"<html><body><h1>Title</h1><p>{long_text}</p></body></html>".encode()
        long_item.get_name.return_value = "long.xhtml"

        mock_book.get_items_of_type.return_value = [short_item, long_item]
        mock_epub.read_epub.return_value = mock_book

        chapters = parse_epub("fake.epub")
        assert len(chapters) == 1
        assert chapters[0]["id"] == "long.xhtml"
        assert chapters[0]["title"] == "Title"

    @patch('core_worker.epub')
    def test_returns_empty_for_no_content(self, mock_epub):
        from core_worker import parse_epub
        mock_book = MagicMock()
        mock_book.toc = []
        mock_book.get_items_of_type.return_value = []
        mock_epub.read_epub.return_value = mock_book

        chapters = parse_epub("empty.epub")
        assert chapters == []


# ---------------------------------------------------------------------------
# query_openai (mocked OpenAI + cache)
# ---------------------------------------------------------------------------

class TestQueryOpenai:
    @patch('core_worker.OpenAI')
    @patch('core_worker.CACHE_DB_PATH')
    def test_calls_openai_and_caches(self, mock_cache_path, mock_openai_cls, tmp_path):
        from core_worker import query_openai, CACHE_DB_PATH

        # Point cache to temp dir
        cache_path = str(tmp_path / "cache.db")
        with patch('core_worker.CACHE_DB_PATH', cache_path):
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "1. Answer one.\n2. Answer two."
            mock_client.chat.completions.create.return_value = mock_response

            result = query_openai("Book", "Ch1", "Chapter text here", ["Q1", "Q2"], "en")

            assert 0 in result
            assert 1 in result
            mock_client.chat.completions.create.assert_called_once()

    @patch('core_worker.OpenAI')
    def test_cache_hit_skips_api(self, mock_openai_cls, tmp_path):
        from core_worker import query_openai, _cache_key

        cache_path = str(tmp_path / "cache.db")
        with patch('core_worker.CACHE_DB_PATH', cache_path):
            # Pre-populate cache
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            conn = sqlite3.connect(cache_path)
            conn.execute("CREATE TABLE IF NOT EXISTS cache (hash TEXT PRIMARY KEY, response TEXT)")
            key = _cache_key("Chapter text", ["Q1"])
            conn.execute("INSERT INTO cache (hash, response) VALUES (?, ?)", (key, "1. Cached answer."))
            conn.commit()
            conn.close()

            result = query_openai("Book", "Ch1", "Chapter text", ["Q1"], "en")
            assert result[0] == "Cached answer."
            mock_openai_cls.assert_not_called()


# ---------------------------------------------------------------------------
# write_docx_pdf (mocked subprocess)
# ---------------------------------------------------------------------------

class TestWriteDocxPdf:
    @patch('core_worker.subprocess.run')
    def test_creates_docx(self, mock_run):
        from core_worker import write_docx_pdf

        chapters_data = [{
            "title": "Chapter 1",
            "questions": ["Q1?"],
            "notes": {0: "Answer 1"},
        }]

        docx_path, pdf_path = write_docx_pdf("Test Book", chapters_data, "testuser")

        assert docx_path.endswith(".docx")
        assert pdf_path.endswith(".pdf")
        assert os.path.isfile(docx_path)

        # Cleanup
        if os.path.isfile(docx_path):
            os.remove(docx_path)
        if os.path.isfile(pdf_path):
            os.remove(pdf_path)


# ---------------------------------------------------------------------------
# bot.py: parse_chapter_selection
# ---------------------------------------------------------------------------

class TestParseChapterSelection:
    def test_all_keyword(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("all", 5)
        assert result == [0, 1, 2, 3, 4]

    def test_todos_keyword(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("todos", 5)
        assert result == [0, 1, 2, 3, 4]

    def test_custom_all_word(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("tout", 3, all_word="tout")
        assert result == [0, 1, 2]

    def test_single_number(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("3", 5)
        assert result == [2]

    def test_comma_separated(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("1,3,5", 5)
        assert result == [0, 2, 4]

    def test_range(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("2-4", 5)
        assert result == [1, 2, 3]

    def test_mixed_range_and_numbers(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("1,3-5", 5)
        assert result == [0, 2, 3, 4]

    def test_out_of_bounds_returns_none(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("10", 5)
        assert result is None

    def test_zero_returns_none(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("0", 5)
        assert result is None

    def test_invalid_text_returns_none(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("abc", 5)
        assert result is None

    def test_empty_returns_none(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("", 5)
        assert result is None

    def test_reversed_range_returns_none(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("5-2", 5)
        assert result is None

    def test_semicolon_separator(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("1;3", 5)
        assert result == [0, 2]

    def test_whitespace_handling(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("  1 , 3 ", 5)
        assert result == [0, 2]

    def test_deduplication(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("1,1,1", 5)
        assert result == [0]


# ---------------------------------------------------------------------------
# bot.py: get_default_questions
# ---------------------------------------------------------------------------

class TestGetDefaultQuestions:
    def test_returns_three_questions(self):
        from bot import get_default_questions
        trans = lambda x: x  # identity
        result = get_default_questions(trans)
        assert len(result) == 3
        assert all(isinstance(q, str) for q in result)

    def test_translation_applied(self):
        from bot import get_default_questions
        trans = lambda x: x.upper()
        result = get_default_questions(trans)
        for q in result:
            assert q == q.upper()


# ---------------------------------------------------------------------------
# bot.py: LANGUAGES constant
# ---------------------------------------------------------------------------

class TestLanguagesConstant:
    def test_languages_not_empty(self):
        from bot import LANGUAGES
        assert len(LANGUAGES) > 0

    def test_all_languages_have_two_elements(self):
        from bot import LANGUAGES
        for name, code in LANGUAGES:
            assert isinstance(name, str)
            assert isinstance(code, str)
            assert len(name) > 0
            assert len(code) > 0

    def test_contains_english_and_spanish(self):
        from bot import LANGUAGES
        codes = [code for _, code in LANGUAGES]
        assert "en" in codes
        assert "es" in codes
