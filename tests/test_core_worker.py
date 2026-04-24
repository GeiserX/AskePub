"""Tests for AskePub core_worker module."""

import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, patch, call

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

    def test_notes_sorted_by_index(self):
        from core_worker import _build_notes_html
        questions = ["Q1", "Q2", "Q3"]
        notes = {2: "A3", 0: "A1", 1: "A2"}
        result = _build_notes_html(questions, notes)
        pos_a1 = result.index("A1")
        pos_a2 = result.index("A2")
        pos_a3 = result.index("A3")
        assert pos_a1 < pos_a2 < pos_a3

    def test_output_is_valid_html_div(self):
        from core_worker import _build_notes_html
        result = _build_notes_html(["Q"], {0: "A"})
        assert result.startswith("<div")
        assert result.endswith("</div>")


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

    def test_fallback_strips_leading_number(self):
        from core_worker import _parse_numbered_answers
        # Text without proper newline-based numbering triggers fallback
        text = "1. Answer A\n\n2. Answer B"
        result = _parse_numbered_answers(text, 2)
        assert 0 in result
        assert 1 in result

    def test_more_questions_than_answers(self):
        from core_worker import _parse_numbered_answers
        text = "1. Only one answer."
        result = _parse_numbered_answers(text, 3)
        assert 0 in result
        assert result[0] == "Only one answer."

    def test_no_numbered_no_double_newline(self):
        from core_worker import _parse_numbered_answers
        text = "Just a single block of text with no structure."
        result = _parse_numbered_answers(text, 1)
        assert 0 in result


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

    def test_empty_inputs(self):
        from core_worker import _cache_key
        key = _cache_key("", [])
        assert len(key) == 64

    def test_order_matters(self):
        from core_worker import _cache_key
        key1 = _cache_key("text", ["q1", "q2"])
        key2 = _cache_key("text", ["q2", "q1"])
        assert key1 != key2


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

    def test_tuple_without_href(self):
        from core_worker import _walk_toc
        section = MagicMock(spec=[])  # no href/title attrs
        child = MagicMock(href="child.xhtml", title="Child")
        title_map = {}
        _walk_toc([(section, [child])], title_map)
        assert "child.xhtml" in title_map
        assert len(title_map) == 1  # section was skipped

    def test_item_without_href(self):
        from core_worker import _walk_toc
        item = MagicMock(spec=[])  # no href/title attrs
        title_map = {}
        _walk_toc([item], title_map)
        assert title_map == {}

    def test_deeply_nested_toc(self):
        from core_worker import _walk_toc
        leaf = MagicMock(href="leaf.xhtml", title="Leaf")
        mid = MagicMock(href="mid.xhtml", title="Mid")
        top = MagicMock(href="top.xhtml", title="Top")
        title_map = {}
        _walk_toc([(top, [(mid, [leaf])])], title_map)
        assert len(title_map) == 3


# ---------------------------------------------------------------------------
# _init_cache_db
# ---------------------------------------------------------------------------

class TestInitCacheDb:
    def test_creates_db_and_table(self, tmp_path):
        from core_worker import _init_cache_db
        cache_path = str(tmp_path / "sub" / "cache.db")
        with patch('core_worker.CACHE_DB_PATH', cache_path):
            _init_cache_db()
            assert os.path.isfile(cache_path)
            conn = sqlite3.connect(cache_path)
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache'")
            assert cur.fetchone() is not None
            conn.close()

    def test_idempotent(self, tmp_path):
        from core_worker import _init_cache_db
        cache_path = str(tmp_path / "cache.db")
        with patch('core_worker.CACHE_DB_PATH', cache_path):
            _init_cache_db()
            _init_cache_db()  # should not raise
            assert os.path.isfile(cache_path)


# ---------------------------------------------------------------------------
# parse_epub (mocked ebooklib)
# ---------------------------------------------------------------------------

class TestParseEpub:
    @patch('core_worker.epub')
    def test_filters_short_chapters(self, mock_epub):
        from core_worker import parse_epub

        mock_book = MagicMock()
        mock_book.toc = []

        short_item = MagicMock()
        short_item.get_content.return_value = b"<html><body><p>Short</p></body></html>"
        short_item.get_name.return_value = "short.xhtml"

        long_text = "A " * 200
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

    @patch('core_worker.epub')
    def test_uses_toc_title(self, mock_epub):
        from core_worker import parse_epub

        toc_item = MagicMock(href="ch1.xhtml", title="TOC Title")
        mock_book = MagicMock()
        mock_book.toc = [toc_item]

        long_text = "X " * 200
        item = MagicMock()
        item.get_content.return_value = f"<html><body><p>{long_text}</p></body></html>".encode()
        item.get_name.return_value = "ch1.xhtml"

        mock_book.get_items_of_type.return_value = [item]
        mock_epub.read_epub.return_value = mock_book

        chapters = parse_epub("test.epub")
        assert chapters[0]["title"] == "TOC Title"

    @patch('core_worker.epub')
    def test_falls_back_to_heading(self, mock_epub):
        from core_worker import parse_epub

        mock_book = MagicMock()
        mock_book.toc = []

        long_text = "Z " * 200
        item = MagicMock()
        item.get_content.return_value = f"<html><body><h2>Heading Title</h2><p>{long_text}</p></body></html>".encode()
        item.get_name.return_value = "ch2.xhtml"

        mock_book.get_items_of_type.return_value = [item]
        mock_epub.read_epub.return_value = mock_book

        chapters = parse_epub("test.epub")
        assert chapters[0]["title"] == "Heading Title"

    @patch('core_worker.epub')
    def test_falls_back_to_href_id(self, mock_epub):
        from core_worker import parse_epub

        mock_book = MagicMock()
        mock_book.toc = []

        long_text = "W " * 200
        item = MagicMock()
        item.get_content.return_value = f"<html><body><p>{long_text}</p></body></html>".encode()
        item.get_name.return_value = "no_heading.xhtml"

        mock_book.get_items_of_type.return_value = [item]
        mock_epub.read_epub.return_value = mock_book

        chapters = parse_epub("test.epub")
        assert chapters[0]["title"] == "no_heading.xhtml"

    @patch('core_worker.epub')
    def test_content_text_and_html_populated(self, mock_epub):
        from core_worker import parse_epub

        mock_book = MagicMock()
        mock_book.toc = []

        long_text = "Content " * 50
        html = f"<html><body><h1>Ch</h1><p>{long_text}</p></body></html>"
        item = MagicMock()
        item.get_content.return_value = html.encode()
        item.get_name.return_value = "ch.xhtml"

        mock_book.get_items_of_type.return_value = [item]
        mock_epub.read_epub.return_value = mock_book

        chapters = parse_epub("test.epub")
        assert chapters[0]["content_html"] == html
        assert "Content" in chapters[0]["content_text"]


# ---------------------------------------------------------------------------
# query_openai (mocked OpenAI + cache)
# ---------------------------------------------------------------------------

class TestQueryOpenai:
    @patch('core_worker.OpenAI')
    def test_calls_openai_and_caches(self, mock_openai_cls, tmp_path):
        from core_worker import query_openai

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

            # Verify it was stored in cache
            conn = sqlite3.connect(cache_path)
            row = conn.execute("SELECT COUNT(*) FROM cache").fetchone()
            conn.close()
            assert row[0] == 1

    @patch('core_worker.OpenAI')
    def test_cache_hit_skips_api(self, mock_openai_cls, tmp_path):
        from core_worker import query_openai, _cache_key

        cache_path = str(tmp_path / "cache.db")
        with patch('core_worker.CACHE_DB_PATH', cache_path):
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

    @patch('core_worker.OpenAI')
    def test_prompt_contains_book_and_chapter(self, mock_openai_cls, tmp_path):
        from core_worker import query_openai

        cache_path = str(tmp_path / "cache.db")
        with patch('core_worker.CACHE_DB_PATH', cache_path):
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "1. Answer."
            mock_client.chat.completions.create.return_value = mock_response

            query_openai("My Book", "Chapter X", "text", ["Q1"], "fr")

            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs["messages"]
            system_msg = messages[0]["content"]
            user_msg = messages[1]["content"]
            assert "My Book" in system_msg
            assert "Chapter X" in system_msg
            assert "'fr'" in system_msg
            assert "text" in user_msg
            assert "Q1" in user_msg


# ---------------------------------------------------------------------------
# write_annotated_epub
# ---------------------------------------------------------------------------

class TestWriteAnnotatedEpub:
    @patch('core_worker.epub')
    def test_appends_notes_before_body_close(self, mock_epub):
        from core_worker import write_annotated_epub

        mock_book = MagicMock()
        item = MagicMock()
        item.get_name.return_value = "ch1.xhtml"
        item.get_content.return_value = b"<html><body><p>Text</p></body></html>"
        mock_book.get_items_of_type.return_value = [item]
        mock_epub.read_epub.return_value = mock_book

        chapters_with_notes = [{
            "id": "ch1.xhtml",
            "questions": ["Q1?"],
            "notes": {0: "A1"},
        }]

        result = write_annotated_epub("input.epub", chapters_with_notes, "/tmp/out.epub")
        assert result == "/tmp/out.epub"

        # Verify set_content was called with notes injected
        set_content_call = item.set_content.call_args[0][0]
        content_str = set_content_call.decode("utf-8") if isinstance(set_content_call, bytes) else set_content_call
        assert "Study Notes - AskePub" in content_str
        assert "Q1?" in content_str
        mock_epub.write_epub.assert_called_once()

    @patch('core_worker.epub')
    def test_appends_notes_without_body_tag(self, mock_epub):
        from core_worker import write_annotated_epub

        mock_book = MagicMock()
        item = MagicMock()
        item.get_name.return_value = "ch1.xhtml"
        item.get_content.return_value = b"<html><p>No body tag</p></html>"
        mock_book.get_items_of_type.return_value = [item]
        mock_epub.read_epub.return_value = mock_book

        chapters_with_notes = [{
            "id": "ch1.xhtml",
            "questions": ["Q1?"],
            "notes": {0: "A1"},
        }]

        write_annotated_epub("input.epub", chapters_with_notes, "/tmp/out.epub")

        set_content_call = item.set_content.call_args[0][0]
        content_str = set_content_call.decode("utf-8") if isinstance(set_content_call, bytes) else set_content_call
        assert "Study Notes - AskePub" in content_str

    @patch('core_worker.epub')
    def test_skips_chapters_without_notes(self, mock_epub):
        from core_worker import write_annotated_epub

        mock_book = MagicMock()
        item1 = MagicMock()
        item1.get_name.return_value = "ch1.xhtml"
        item2 = MagicMock()
        item2.get_name.return_value = "ch2.xhtml"
        mock_book.get_items_of_type.return_value = [item1, item2]
        mock_epub.read_epub.return_value = mock_book

        chapters_with_notes = [{
            "id": "ch1.xhtml",
            "questions": ["Q1?"],
            "notes": {0: "A1"},
        }]

        write_annotated_epub("input.epub", chapters_with_notes, "/tmp/out.epub")
        item1.get_content.assert_called()
        item2.get_content.assert_not_called()

    @patch('core_worker.epub')
    def test_skips_chapter_with_empty_notes(self, mock_epub):
        from core_worker import write_annotated_epub

        mock_book = MagicMock()
        item = MagicMock()
        item.get_name.return_value = "ch1.xhtml"
        mock_book.get_items_of_type.return_value = [item]
        mock_epub.read_epub.return_value = mock_book

        chapters_with_notes = [{
            "id": "ch1.xhtml",
            "questions": ["Q1?"],
            "notes": {},
        }]

        write_annotated_epub("input.epub", chapters_with_notes, "/tmp/out.epub")
        item.set_content.assert_not_called()

    @patch('core_worker.epub')
    def test_returns_output_path(self, mock_epub):
        from core_worker import write_annotated_epub

        mock_book = MagicMock()
        mock_book.get_items_of_type.return_value = []
        mock_epub.read_epub.return_value = mock_book

        result = write_annotated_epub("in.epub", [], "/tmp/result.epub")
        assert result == "/tmp/result.epub"


# ---------------------------------------------------------------------------
# write_docx_pdf
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
        mock_run.assert_called_once()

        if os.path.isfile(docx_path):
            os.remove(docx_path)

    @patch('core_worker.subprocess.run')
    def test_multiple_chapters(self, mock_run):
        from core_worker import write_docx_pdf

        chapters_data = [
            {"title": "Ch1", "questions": ["Q1"], "notes": {0: "A1"}},
            {"title": "Ch2", "questions": ["Q2", "Q3"], "notes": {0: "A2", 1: "A3"}},
        ]

        docx_path, pdf_path = write_docx_pdf("Multi Book", chapters_data, "testuser2")
        assert os.path.isfile(docx_path)

        if os.path.isfile(docx_path):
            os.remove(docx_path)

    @patch('core_worker.subprocess.run', side_effect=subprocess.CalledProcessError(1, "abiword"))
    def test_pdf_conversion_failure_called_process_error(self, mock_run):
        from core_worker import write_docx_pdf

        chapters_data = [{
            "title": "Ch1",
            "questions": ["Q1"],
            "notes": {0: "A1"},
        }]

        # Should not raise - error is caught and logged
        docx_path, pdf_path = write_docx_pdf("Book", chapters_data, "testuser3")
        assert docx_path.endswith(".docx")

        if os.path.isfile(docx_path):
            os.remove(docx_path)

    @patch('core_worker.subprocess.run', side_effect=subprocess.TimeoutExpired("abiword", 120))
    def test_pdf_conversion_failure_timeout(self, mock_run):
        from core_worker import write_docx_pdf

        chapters_data = [{
            "title": "Ch1",
            "questions": ["Q1"],
            "notes": {0: "A1"},
        }]

        docx_path, pdf_path = write_docx_pdf("Book", chapters_data, "testuser4")
        assert docx_path.endswith(".docx")

        if os.path.isfile(docx_path):
            os.remove(docx_path)

    @patch('core_worker.subprocess.run')
    def test_sanitizes_title(self, mock_run):
        from core_worker import write_docx_pdf

        chapters_data = [{"title": "Ch", "questions": ["Q"], "notes": {0: "A"}}]

        docx_path, pdf_path = write_docx_pdf("Book/With:Special<Chars>", chapters_data, "testuser5")
        assert ":" not in os.path.basename(docx_path)
        assert "<" not in os.path.basename(docx_path)

        if os.path.isfile(docx_path):
            os.remove(docx_path)

    @patch('core_worker.subprocess.run')
    def test_note_index_beyond_questions_fallback(self, mock_run):
        from core_worker import write_docx_pdf

        chapters_data = [{
            "title": "Ch1",
            "questions": ["Q1"],
            "notes": {0: "A1", 5: "A6"},  # index 5 > len(questions)
        }]

        docx_path, pdf_path = write_docx_pdf("Book", chapters_data, "testuser6")
        assert os.path.isfile(docx_path)

        if os.path.isfile(docx_path):
            os.remove(docx_path)


# ---------------------------------------------------------------------------
# main (orchestrator)
# ---------------------------------------------------------------------------

class TestMain:
    @patch('core_worker.write_docx_pdf')
    @patch('core_worker.write_annotated_epub')
    @patch('core_worker.query_openai')
    @patch('core_worker.epub')
    @patch('core_worker.parse_epub')
    def test_full_workflow(self, mock_parse, mock_epub_mod, mock_query, mock_write_epub, mock_write_docx):
        from core_worker import main

        mock_parse.return_value = [
            {"id": "ch1.xhtml", "title": "Ch1", "content_html": "<p>text</p>", "content_text": "text"},
            {"id": "ch2.xhtml", "title": "Ch2", "content_html": "<p>text2</p>", "content_text": "text2"},
        ]

        mock_book = MagicMock()
        mock_book.get_metadata.return_value = [("Test Book",)]
        mock_epub_mod.read_epub.return_value = mock_book

        mock_query.return_value = {0: "Answer"}
        mock_write_epub.return_value = "/tmp/out.epub"
        mock_write_docx.return_value = ("/tmp/out.docx", "/tmp/out.pdf")

        result = main("test.epub", "user1", ["ch1.xhtml"], ["Q1"], "en")

        assert len(result) == 3
        mock_parse.assert_called_once_with("test.epub")
        mock_query.assert_called_once()
        mock_write_epub.assert_called_once()
        mock_write_docx.assert_called_once()

    @patch('core_worker.write_docx_pdf')
    @patch('core_worker.write_annotated_epub')
    @patch('core_worker.query_openai')
    @patch('core_worker.epub')
    @patch('core_worker.parse_epub')
    def test_no_matching_chapters_uses_all(self, mock_parse, mock_epub_mod, mock_query, mock_write_epub, mock_write_docx):
        from core_worker import main

        mock_parse.return_value = [
            {"id": "ch1.xhtml", "title": "Ch1", "content_html": "<p>t</p>", "content_text": "t"},
        ]

        mock_book = MagicMock()
        mock_book.get_metadata.return_value = [("Book",)]
        mock_epub_mod.read_epub.return_value = mock_book

        mock_query.return_value = {0: "A"}
        mock_write_epub.return_value = "/tmp/out.epub"
        mock_write_docx.return_value = ("/tmp/out.docx", "/tmp/out.pdf")

        result = main("test.epub", "user1", ["nonexistent.xhtml"], ["Q1"], "en")

        # Should have queried all chapters since none matched
        mock_query.assert_called_once()
        args = mock_query.call_args
        assert args.kwargs["chapter_title"] == "Ch1"

    @patch('core_worker.write_docx_pdf')
    @patch('core_worker.write_annotated_epub')
    @patch('core_worker.query_openai')
    @patch('core_worker.epub')
    @patch('core_worker.parse_epub')
    def test_no_metadata_title_uses_unknown(self, mock_parse, mock_epub_mod, mock_query, mock_write_epub, mock_write_docx):
        from core_worker import main

        mock_parse.return_value = [
            {"id": "ch1.xhtml", "title": "Ch1", "content_html": "<p>t</p>", "content_text": "t"},
        ]

        mock_book = MagicMock()
        mock_book.get_metadata.return_value = []  # no title
        mock_epub_mod.read_epub.return_value = mock_book

        mock_query.return_value = {0: "A"}
        mock_write_epub.return_value = "/tmp/out.epub"
        mock_write_docx.return_value = ("/tmp/out.docx", "/tmp/out.pdf")

        result = main("test.epub", "user1", ["ch1.xhtml"], ["Q1"], "en")

        # query_openai should have been called with "Unknown" as book title
        call_kwargs = mock_query.call_args.kwargs
        assert call_kwargs["book_title"] == "Unknown"

    @patch('core_worker.write_docx_pdf')
    @patch('core_worker.write_annotated_epub')
    @patch('core_worker.query_openai')
    @patch('core_worker.epub')
    @patch('core_worker.parse_epub')
    def test_multiple_chapters_queried(self, mock_parse, mock_epub_mod, mock_query, mock_write_epub, mock_write_docx):
        from core_worker import main

        mock_parse.return_value = [
            {"id": "ch1.xhtml", "title": "Ch1", "content_html": "<p>t</p>", "content_text": "t1"},
            {"id": "ch2.xhtml", "title": "Ch2", "content_html": "<p>t</p>", "content_text": "t2"},
            {"id": "ch3.xhtml", "title": "Ch3", "content_html": "<p>t</p>", "content_text": "t3"},
        ]

        mock_book = MagicMock()
        mock_book.get_metadata.return_value = [("Book",)]
        mock_epub_mod.read_epub.return_value = mock_book

        mock_query.return_value = {0: "A"}
        mock_write_epub.return_value = "/tmp/out.epub"
        mock_write_docx.return_value = ("/tmp/out.docx", "/tmp/out.pdf")

        main("test.epub", "user1", ["ch1.xhtml", "ch3.xhtml"], ["Q1"], "en")

        assert mock_query.call_count == 2
