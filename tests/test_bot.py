"""Tests for AskePub bot module - Telegram bot handlers."""

import os
import sqlite3
import sys
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import pytz

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# We must set env vars BEFORE importing bot, since bot reads them at module level
os.environ.setdefault("ADMIN_ID", "111111")
os.environ.setdefault("TOKEN", "fake-token")

TIMEZONE = pytz.timezone("Europe/Madrid")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with the Main table."""
    db = str(tmp_path / "main.db")
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE IF NOT EXISTS "Main" (
        "UserId" INTEGER NOT NULL PRIMARY KEY,
        "UserName" TEXT,
        "FirstName" TEXT,
        "LastName" TEXT,
        "LangCodeTelegram" TEXT,
        "LangSelected" TEXT,
        "IsBot" TEXT,
        "Q1" TEXT,
        "Q2" TEXT,
        "Q3" TEXT,
        "Q4" TEXT,
        "Q5" TEXT,
        "Q6" TEXT,
        "Q7" TEXT,
        "Q8" TEXT,
        "Q9" TEXT,
        "Q10" TEXT,
        "LastRun" TEXT
    );""")
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def mock_update():
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 111111
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.effective_user.last_name = "User"
    update.effective_user.language_code = "en"
    update.effective_user.is_bot = False
    update.message = AsyncMock()
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.chat_id = 111111
    update.callback_query = None
    return update


@pytest.fixture
def mock_context():
    """Create a mock context with user_data."""
    context = MagicMock()
    context.user_data = {}
    context.bot = AsyncMock()
    context.bot.get_file = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_chat_action = AsyncMock()
    return context


# Save real sqlite3.connect before any patching so lambdas can use it
_real_sqlite3_connect = sqlite3.connect


def _insert_user(db_path, user_id=111111, lang="es", last_run=None, q1="Q1", q2="Q2", q3="Q3"):
    """Helper to insert a user into the test DB."""
    conn = _real_sqlite3_connect(db_path)
    conn.execute(
        "INSERT INTO Main (UserId, UserName, FirstName, LastName, LangCodeTelegram, LangSelected, IsBot, Q1, Q2, Q3, LastRun) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, "testuser", "Test", "User", "en", lang, 0, q1, q2, q3, last_run),
    )
    conn.commit()
    conn.close()


def _patch_db(db_path):
    """Return a patch context manager that redirects bot.sqlite3.connect to our temp DB."""
    return patch('bot.sqlite3.connect', side_effect=lambda *a, **kw: _real_sqlite3_connect(db_path))


# ---------------------------------------------------------------------------
# get_translation
# ---------------------------------------------------------------------------

class TestGetTranslation:
    def test_returns_translation_object(self):
        from bot import get_translation
        context = MagicMock()
        context.user_data = {"language": "es"}
        result = get_translation(context)
        assert result is not None

    def test_caches_translation(self):
        from bot import get_translation, _translations_cache
        context = MagicMock()
        context.user_data = {"language": "en"}
        t1 = get_translation(context)
        t2 = get_translation(context)
        assert t1 is t2

    def test_fallback_for_unknown_language(self):
        from bot import get_translation
        context = MagicMock()
        context.user_data = {"language": "zz_UNKNOWN"}
        result = get_translation(context)
        assert result is not None

    def test_default_language_es(self):
        from bot import get_translation
        context = MagicMock()
        context.user_data = {}  # no language set
        result = get_translation(context)
        assert result is not None


# ---------------------------------------------------------------------------
# get_default_questions
# ---------------------------------------------------------------------------

class TestGetDefaultQuestions:
    def test_returns_three_questions(self):
        from bot import get_default_questions
        trans = lambda x: x
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
# LANGUAGES constant
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


# ---------------------------------------------------------------------------
# parse_chapter_selection
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

    def test_range_start_equals_end(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("3-3", 5)
        assert result == [2]

    def test_space_separated(self):
        from bot import parse_chapter_selection
        result = parse_chapter_selection("1 3 5", 5)
        assert result == [0, 2, 4]


# ---------------------------------------------------------------------------
# startup_message
# ---------------------------------------------------------------------------

class TestStartupMessage:
    @pytest.mark.asyncio
    async def test_sends_boot_message(self):
        from bot import startup_message
        app = MagicMock()
        app.bot = AsyncMock()
        app.bot.send_message = AsyncMock()
        await startup_message(app)
        app.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_send_failure(self):
        from bot import startup_message
        app = MagicMock()
        app.bot = AsyncMock()
        app.bot.send_message = AsyncMock(side_effect=Exception("Network error"))
        # Should not raise
        await startup_message(app)


# ---------------------------------------------------------------------------
# check_if_user_exists
# ---------------------------------------------------------------------------

class TestCheckIfUserExists:
    @pytest.mark.asyncio
    async def test_inserts_new_user(self, mock_update, mock_context, db_path):
        from bot import check_if_user_exists
        with _patch_db(db_path):
            await check_if_user_exists(mock_update, mock_context)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT UserName FROM Main WHERE UserId = ?", (111111,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "testuser"

    @pytest.mark.asyncio
    async def test_updates_existing_user(self, mock_update, mock_context, db_path):
        from bot import check_if_user_exists
        _insert_user(db_path)
        mock_update.effective_user.username = "newname"
        with _patch_db(db_path):
            await check_if_user_exists(mock_update, mock_context)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT UserName FROM Main WHERE UserId = ?", (111111,)).fetchone()
        conn.close()
        assert row[0] == "newname"


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------

class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_with_translation(self, mock_update, mock_context):
        from bot import cancel
        from telegram.ext import ConversationHandler
        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        result = await cancel(mock_update, mock_context)
        assert result == ConversationHandler.END
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_without_translation(self, mock_update, mock_context):
        from bot import cancel
        from telegram.ext import ConversationHandler
        result = await cancel(mock_update, mock_context)
        assert result == ConversationHandler.END
        mock_update.message.reply_text.assert_called_once()


# ---------------------------------------------------------------------------
# language_select
# ---------------------------------------------------------------------------

class TestLanguageSelect:
    @pytest.mark.asyncio
    async def test_language_select_via_message(self, mock_update, mock_context):
        from bot import language_select, LANG_SELECT
        mock_update.callback_query = None
        result = await language_select(mock_update, mock_context)
        assert result == LANG_SELECT
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_language_select_via_callback(self, mock_update, mock_context):
        from bot import language_select, LANG_SELECT
        mock_update.message = None
        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        result = await language_select(mock_update, mock_context)
        assert result == LANG_SELECT
        mock_update.callback_query.edit_message_text.assert_called_once()


# ---------------------------------------------------------------------------
# language_selected
# ---------------------------------------------------------------------------

class TestLanguageSelected:
    @pytest.mark.asyncio
    async def test_language_selected_new_user(self, mock_update, mock_context, db_path):
        from bot import language_selected, RECEIVE_EPUB_FILE
        _insert_user(db_path, lang=None)
        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "lang_en"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_user.id = 111111

        with _patch_db(db_path):
            result = await language_selected(mock_update, mock_context)

        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_language_selected_changed_language(self, mock_update, mock_context, db_path):
        from bot import language_selected, RECEIVE_KEEP_QUESTIONS_RESPONSE
        _insert_user(db_path, lang="es")
        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "lang_en"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_user.id = 111111

        with _patch_db(db_path):
            result = await language_selected(mock_update, mock_context)

        assert result == RECEIVE_KEEP_QUESTIONS_RESPONSE


# ---------------------------------------------------------------------------
# receive_keep_questions_response
# ---------------------------------------------------------------------------

class TestReceiveKeepQuestionsResponse:
    @pytest.mark.asyncio
    async def test_reset_questions(self, mock_update, mock_context, db_path):
        from bot import receive_keep_questions_response, RECEIVE_EPUB_FILE
        _insert_user(db_path, lang="en", q1="Old Q1", q2="Old Q2", q3="Old Q3")

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "reset_questions"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_user.id = 111111

        with _patch_db(db_path):
            result = await receive_keep_questions_response(mock_update, mock_context)

        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_keep_questions(self, mock_update, mock_context, db_path):
        from bot import receive_keep_questions_response, RECEIVE_EPUB_FILE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "es"

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "keep_questions"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()

        result = await receive_keep_questions_response(mock_update, mock_context)
        assert result == RECEIVE_EPUB_FILE


# ---------------------------------------------------------------------------
# receive_epub_file
# ---------------------------------------------------------------------------

class TestReceiveEpubFile:
    @pytest.mark.asyncio
    async def test_rejects_non_epub(self, mock_update, mock_context):
        from bot import receive_epub_file, RECEIVE_EPUB_FILE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.message.document = MagicMock()
        mock_update.message.document.file_name = "file.pdf"

        result = await receive_epub_file(mock_update, mock_context)
        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_rejects_no_document(self, mock_update, mock_context):
        from bot import receive_epub_file, RECEIVE_EPUB_FILE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.message.document = None

        result = await receive_epub_file(mock_update, mock_context)
        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_accepts_epub_and_parses(self, mock_update, mock_context):
        from bot import receive_epub_file, SELECT_CHAPTERS

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.message.document = MagicMock()
        mock_update.message.document.file_name = "book.epub"
        mock_update.message.document.file_id = "fileid123"

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file = AsyncMock(return_value=mock_file)

        fake_chapters = [
            {"id": "ch1.xhtml", "title": "Chapter 1", "content_html": "<p>t</p>", "content_text": "t"},
        ]

        with patch('bot.core_worker.parse_epub', return_value=fake_chapters):
            result = await receive_epub_file(mock_update, mock_context)

        assert result == SELECT_CHAPTERS
        assert mock_context.user_data["chapters"] == fake_chapters

    @pytest.mark.asyncio
    async def test_parse_error_returns_epub_state(self, mock_update, mock_context):
        from bot import receive_epub_file, RECEIVE_EPUB_FILE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.message.document = MagicMock()
        mock_update.message.document.file_name = "bad.epub"
        mock_update.message.document.file_id = "fileid456"

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file = AsyncMock(return_value=mock_file)

        with patch('bot.core_worker.parse_epub', side_effect=Exception("Parse error")):
            result = await receive_epub_file(mock_update, mock_context)

        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_empty_chapters_returns_epub_state(self, mock_update, mock_context):
        from bot import receive_epub_file, RECEIVE_EPUB_FILE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.message.document = MagicMock()
        mock_update.message.document.file_name = "empty.epub"
        mock_update.message.document.file_id = "fileid789"

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file = AsyncMock(return_value=mock_file)

        with patch('bot.core_worker.parse_epub', return_value=[]):
            result = await receive_epub_file(mock_update, mock_context)

        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_long_chapter_list_truncated(self, mock_update, mock_context):
        from bot import receive_epub_file, SELECT_CHAPTERS

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.message.document = MagicMock()
        mock_update.message.document.file_name = "big.epub"
        mock_update.message.document.file_id = "fileidBig"

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()
        mock_context.bot.get_file = AsyncMock(return_value=mock_file)

        # Create 200 chapters with long titles to exceed 4000 chars
        fake_chapters = [
            {"id": f"ch{i}.xhtml", "title": f"Very Long Chapter Title Number {i} " * 5,
             "content_html": "<p>t</p>", "content_text": "t"}
            for i in range(200)
        ]

        with patch('bot.core_worker.parse_epub', return_value=fake_chapters):
            result = await receive_epub_file(mock_update, mock_context)

        assert result == SELECT_CHAPTERS


# ---------------------------------------------------------------------------
# receive_epub_text_reject
# ---------------------------------------------------------------------------

class TestReceiveEpubTextReject:
    @pytest.mark.asyncio
    async def test_rejects_text(self, mock_update, mock_context):
        from bot import receive_epub_text_reject, RECEIVE_EPUB_FILE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        result = await receive_epub_text_reject(mock_update, mock_context)
        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_uses_fallback_translation(self, mock_update, mock_context):
        from bot import receive_epub_text_reject, RECEIVE_EPUB_FILE

        # No translation in user_data
        mock_context.user_data = {}

        with patch('bot.get_translation') as mock_get_trans:
            mock_trans_obj = MagicMock()
            mock_trans_obj.gettext = lambda x: x
            mock_get_trans.return_value = mock_trans_obj
            result = await receive_epub_text_reject(mock_update, mock_context)

        assert result == RECEIVE_EPUB_FILE


# ---------------------------------------------------------------------------
# select_chapters
# ---------------------------------------------------------------------------

class TestSelectChapters:
    @pytest.mark.asyncio
    async def test_valid_selection(self, mock_update, mock_context, db_path):
        from bot import select_chapters

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["chapters"] = [
            {"id": "ch1.xhtml", "title": "Ch1"},
            {"id": "ch2.xhtml", "title": "Ch2"},
            {"id": "ch3.xhtml", "title": "Ch3"},
        ]
        mock_update.message.text = "1,3"
        mock_update.effective_user.id = 111111

        _insert_user(db_path)

        with _patch_db(db_path):
            result = await select_chapters(mock_update, mock_context)

        assert mock_context.user_data["selected_chapter_indices"] == [0, 2]

    @pytest.mark.asyncio
    async def test_invalid_selection(self, mock_update, mock_context):
        from bot import select_chapters, SELECT_CHAPTERS

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["chapters"] = [{"id": "ch1", "title": "Ch1"}]
        mock_update.message.text = "abc"

        result = await select_chapters(mock_update, mock_context)
        assert result == SELECT_CHAPTERS


# ---------------------------------------------------------------------------
# show_questions
# ---------------------------------------------------------------------------

class TestShowQuestions:
    @pytest.mark.asyncio
    async def test_shows_existing_questions(self, mock_update, mock_context, db_path):
        from bot import show_questions, CUSTOMIZE_QUESTIONS_YES_NO

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["selected_chapter_indices"] = [0, 1]
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path)

        with _patch_db(db_path):
            result = await show_questions(mock_update, mock_context)

        assert result == CUSTOMIZE_QUESTIONS_YES_NO

    @pytest.mark.asyncio
    async def test_initializes_default_questions(self, mock_update, mock_context, db_path):
        from bot import show_questions, CUSTOMIZE_QUESTIONS_YES_NO

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["selected_chapter_indices"] = [0]
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path, q1=None, q2=None, q3=None)

        with _patch_db(db_path):
            result = await show_questions(mock_update, mock_context)

        assert result == CUSTOMIZE_QUESTIONS_YES_NO

    @pytest.mark.asyncio
    async def test_shows_via_callback_query(self, mock_update, mock_context, db_path):
        from bot import show_questions, CUSTOMIZE_QUESTIONS_YES_NO

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["selected_chapter_indices"] = [0]
        mock_update.effective_user.id = 111111
        mock_update.message = None
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        _insert_user(db_path)

        with _patch_db(db_path):
            result = await show_questions(mock_update, mock_context)

        assert result == CUSTOMIZE_QUESTIONS_YES_NO


# ---------------------------------------------------------------------------
# customize_questions_yes_no
# ---------------------------------------------------------------------------

class TestCustomizeQuestionsYesNo:
    @pytest.mark.asyncio
    async def test_yes_goes_to_edit(self, mock_update, mock_context):
        from bot import customize_questions_yes_no

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "yes"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        with patch('bot.ask_edit_or_delete', new_callable=AsyncMock, return_value=5) as mock_aed:
            result = await customize_questions_yes_no(mock_update, mock_context)
        assert result == 5  # CHOOSE_EDIT_OR_DELETE

    @pytest.mark.asyncio
    async def test_no_goes_to_prepare(self, mock_update, mock_context):
        from bot import customize_questions_yes_no

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "no"
        mock_update.callback_query.answer = AsyncMock()

        with patch('bot.epub_prepare', new_callable=AsyncMock, return_value=8) as mock_prep:
            result = await customize_questions_yes_no(mock_update, mock_context)
        assert result == 8  # EPUB_PREPARE


# ---------------------------------------------------------------------------
# ask_edit_or_delete
# ---------------------------------------------------------------------------

class TestAskEditOrDelete:
    @pytest.mark.asyncio
    async def test_via_callback(self, mock_update, mock_context):
        from bot import ask_edit_or_delete, CHOOSE_EDIT_OR_DELETE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.message = None
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        result = await ask_edit_or_delete(mock_update, mock_context)
        assert result == CHOOSE_EDIT_OR_DELETE

    @pytest.mark.asyncio
    async def test_via_message(self, mock_update, mock_context):
        from bot import ask_edit_or_delete, CHOOSE_EDIT_OR_DELETE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.callback_query = None

        result = await ask_edit_or_delete(mock_update, mock_context)
        assert result == CHOOSE_EDIT_OR_DELETE


# ---------------------------------------------------------------------------
# choose_edit_or_delete
# ---------------------------------------------------------------------------

class TestChooseEditOrDelete:
    @pytest.mark.asyncio
    async def test_continue_action(self, mock_update, mock_context):
        from bot import choose_edit_or_delete

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "continue"
        mock_update.callback_query.answer = AsyncMock()

        with patch('bot.epub_prepare', new_callable=AsyncMock, return_value=8):
            result = await choose_edit_or_delete(mock_update, mock_context)
        assert result == 8

    @pytest.mark.asyncio
    async def test_add_action_with_empty_slot(self, mock_update, mock_context, db_path):
        from bot import choose_edit_or_delete, RECEIVE_QUESTION_TEXT

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "add"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_user.id = 111111

        _insert_user(db_path)  # Q1-Q3 set, Q4-Q10 null

        with _patch_db(db_path):
            result = await choose_edit_or_delete(mock_update, mock_context)

        assert result == RECEIVE_QUESTION_TEXT
        assert mock_context.user_data["question_number"] == 4

    @pytest.mark.asyncio
    async def test_add_action_max_questions(self, mock_update, mock_context, db_path):
        from bot import choose_edit_or_delete

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "add"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 111111

        # Insert user with all 10 questions filled
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO Main (UserId, Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8,Q9,Q10) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (111111, "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10"),
        )
        conn.commit()
        conn.close()

        with _patch_db(db_path):
            with patch('bot.ask_edit_or_delete', new_callable=AsyncMock, return_value=5):
                result = await choose_edit_or_delete(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_edit_action(self, mock_update, mock_context, db_path):
        from bot import choose_edit_or_delete, RECEIVE_QUESTION_NUMBER

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "edit"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 111111

        _insert_user(db_path)

        with _patch_db(db_path):
            result = await choose_edit_or_delete(mock_update, mock_context)

        assert result == RECEIVE_QUESTION_NUMBER

    @pytest.mark.asyncio
    async def test_delete_action(self, mock_update, mock_context, db_path):
        from bot import choose_edit_or_delete, RECEIVE_QUESTION_NUMBER

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "delete"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 111111

        _insert_user(db_path)

        with _patch_db(db_path):
            result = await choose_edit_or_delete(mock_update, mock_context)

        assert result == RECEIVE_QUESTION_NUMBER


# ---------------------------------------------------------------------------
# receive_question_number
# ---------------------------------------------------------------------------

class TestReceiveQuestionNumber:
    @pytest.mark.asyncio
    async def test_edit_question(self, mock_update, mock_context):
        from bot import receive_question_number, RECEIVE_QUESTION_TEXT

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["action"] = "edit"

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "2"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()

        result = await receive_question_number(mock_update, mock_context)
        assert result == RECEIVE_QUESTION_TEXT
        assert mock_context.user_data["question_number"] == 2

    @pytest.mark.asyncio
    async def test_delete_question(self, mock_update, mock_context, db_path):
        from bot import receive_question_number

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["action"] = "delete"
        mock_update.effective_user.id = 111111

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "1"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        _insert_user(db_path, q1="Q1", q2="Q2", q3="Q3")

        with _patch_db(db_path):
            with patch('bot.ask_edit_or_delete', new_callable=AsyncMock, return_value=5):
                result = await receive_question_number(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_delete_last_question_blocked(self, mock_update, mock_context, db_path):
        from bot import receive_question_number

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["action"] = "delete"
        mock_update.effective_user.id = 111111

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "1"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        _insert_user(db_path, q1="Q1", q2=None, q3=None)

        with _patch_db(db_path):
            with patch('bot.ask_edit_or_delete', new_callable=AsyncMock, return_value=5):
                result = await receive_question_number(mock_update, mock_context)


# ---------------------------------------------------------------------------
# receive_question_text
# ---------------------------------------------------------------------------

class TestReceiveQuestionText:
    @pytest.mark.asyncio
    async def test_edit_question_text(self, mock_update, mock_context, db_path):
        from bot import receive_question_text

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["action"] = "edit"
        mock_context.user_data["question_number"] = 1
        mock_update.effective_user.id = 111111
        mock_update.message.text = "New question text"

        _insert_user(db_path)

        with _patch_db(db_path):
            with patch('bot.ask_edit_or_delete', new_callable=AsyncMock, return_value=5):
                result = await receive_question_text(mock_update, mock_context)

        mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_add_question_text(self, mock_update, mock_context, db_path):
        from bot import receive_question_text

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["action"] = "add"
        mock_context.user_data["question_number"] = 4
        mock_update.effective_user.id = 111111
        mock_update.message.text = "New added question"

        _insert_user(db_path)

        with _patch_db(db_path):
            with patch('bot.ask_edit_or_delete', new_callable=AsyncMock, return_value=5):
                result = await receive_question_text(mock_update, mock_context)


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

class TestStart:
    @pytest.mark.asyncio
    async def test_bot_user_rejected(self, mock_update, mock_context):
        from bot import start
        from telegram.ext import ConversationHandler

        mock_update.effective_user.is_bot = True

        with patch('bot.check_if_user_exists', new_callable=AsyncMock):
            result = await start(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_unauthorized_user_rejected(self, mock_update, mock_context):
        from bot import start
        from telegram.ext import ConversationHandler

        mock_update.effective_user.id = 999999
        mock_update.effective_user.is_bot = False

        with patch('bot.check_if_user_exists', new_callable=AsyncMock):
            result = await start(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_admin_with_language_set(self, mock_update, mock_context, db_path):
        from bot import start, RECEIVE_EPUB_FILE

        mock_update.effective_user.id = 111111
        mock_update.effective_user.is_bot = False

        _insert_user(db_path, lang="en")

        with patch('bot.check_if_user_exists', new_callable=AsyncMock):
            with _patch_db(db_path):
                result = await start(mock_update, mock_context)

        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_admin_without_language_goes_to_select(self, mock_update, mock_context, db_path):
        from bot import start, LANG_SELECT

        mock_update.effective_user.id = 111111
        mock_update.effective_user.is_bot = False

        _insert_user(db_path, lang=None)

        with patch('bot.check_if_user_exists', new_callable=AsyncMock):
            with _patch_db(db_path):
                result = await start(mock_update, mock_context)

        assert result == LANG_SELECT

    @pytest.mark.asyncio
    async def test_rate_limited_user(self, mock_update, mock_context, db_path):
        from bot import start
        from telegram.ext import ConversationHandler
        import bot

        # Set up a non-admin allowed user
        mock_update.effective_user.id = 222222
        mock_update.effective_user.is_bot = False
        original_allowed = bot.allowed_user_ids.copy()
        bot.allowed_user_ids.add(222222)

        recent_time = datetime.now(TIMEZONE).isoformat("T", "seconds")
        _insert_user(db_path, user_id=222222, lang="en", last_run=recent_time)

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["language"] = "en"

        try:
            with patch('bot.check_if_user_exists', new_callable=AsyncMock):
                with _patch_db(db_path):
                    result = await start(mock_update, mock_context)

            assert result == ConversationHandler.END
        finally:
            bot.allowed_user_ids = original_allowed

    @pytest.mark.asyncio
    async def test_admin_initializes_default_questions(self, mock_update, mock_context, db_path):
        from bot import start, RECEIVE_EPUB_FILE

        mock_update.effective_user.id = 111111
        mock_update.effective_user.is_bot = False

        _insert_user(db_path, lang="en", q1=None, q2=None, q3=None)

        with patch('bot.check_if_user_exists', new_callable=AsyncMock):
            with _patch_db(db_path):
                result = await start(mock_update, mock_context)

        assert result == RECEIVE_EPUB_FILE


# ---------------------------------------------------------------------------
# change_language
# ---------------------------------------------------------------------------

class TestChangeLanguage:
    @pytest.mark.asyncio
    async def test_authorized_user(self, mock_update, mock_context):
        from bot import change_language, LANG_SELECT

        mock_update.effective_user.id = 111111

        result = await change_language(mock_update, mock_context)
        assert result == LANG_SELECT
        assert mock_context.user_data["command"] == "change_language"

    @pytest.mark.asyncio
    async def test_unauthorized_user(self, mock_update, mock_context):
        from bot import change_language
        from telegram.ext import ConversationHandler

        mock_update.effective_user.id = 999999
        result = await change_language(mock_update, mock_context)
        assert result == ConversationHandler.END


# ---------------------------------------------------------------------------
# epub_prepare
# ---------------------------------------------------------------------------

class TestEpubPrepare:
    @pytest.mark.asyncio
    async def test_no_message_source(self, mock_update, mock_context):
        from bot import epub_prepare
        from telegram.ext import ConversationHandler

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_update.callback_query = None
        mock_update.message = None

        result = await epub_prepare(mock_update, mock_context)
        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_no_questions_configured(self, mock_update, mock_context, db_path):
        from bot import epub_prepare
        from telegram.ext import ConversationHandler

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path, q1=None, q2=None, q3=None)

        with _patch_db(db_path):
            result = await epub_prepare(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_no_epub_path(self, mock_update, mock_context, db_path):
        from bot import epub_prepare
        from telegram.ext import ConversationHandler

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path)

        with _patch_db(db_path):
            result = await epub_prepare(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_successful_preparation_via_callback(self, mock_update, mock_context, db_path):
        from bot import epub_prepare, AFTER_PREPARATION

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"
        mock_context.user_data["epub_path"] = "/tmp/test.epub"
        mock_context.user_data["chapters"] = [{"id": "ch1.xhtml", "title": "Ch1"}]
        mock_context.user_data["selected_chapter_indices"] = [0]
        mock_update.effective_user.id = 111111

        mock_update.message = None
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()
        mock_update.callback_query.message.reply_document = AsyncMock()
        mock_update.callback_query.message.chat_id = 111111

        _insert_user(db_path)

        mock_core_result = ("/tmp/out.epub", "/tmp/out.docx", "/tmp/out.pdf")

        with _patch_db(db_path):
            with patch('bot.core_worker.main', return_value=mock_core_result):
                with patch('bot.os.path.isfile', return_value=False):
                    with patch('bot.os.remove'):
                        with patch.dict(os.environ, {"TOKEN_NOTIFY": ""}, clear=False):
                            result = await epub_prepare(mock_update, mock_context)

        assert result == AFTER_PREPARATION

    @pytest.mark.asyncio
    async def test_core_worker_error(self, mock_update, mock_context, db_path):
        from bot import epub_prepare
        from telegram.ext import ConversationHandler

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"
        mock_context.user_data["epub_path"] = "/tmp/test.epub"
        mock_context.user_data["chapters"] = [{"id": "ch1.xhtml", "title": "Ch1"}]
        mock_context.user_data["selected_chapter_indices"] = [0]
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path)

        with _patch_db(db_path):
            with patch('bot.core_worker.main', side_effect=Exception("API error")):
                with patch.dict(os.environ, {"TOKEN_NOTIFY": ""}, clear=False):
                    result = await epub_prepare(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_sends_files_when_exist(self, mock_update, mock_context, db_path, tmp_path):
        from bot import epub_prepare, AFTER_PREPARATION

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"

        epub_file = tmp_path / "test.epub"
        epub_file.write_text("fake epub")
        mock_context.user_data["epub_path"] = str(epub_file)
        mock_context.user_data["chapters"] = [{"id": "ch1.xhtml", "title": "Ch1"}]
        mock_context.user_data["selected_chapter_indices"] = [0]
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path)

        out_epub = tmp_path / "out.epub"
        out_docx = tmp_path / "out.docx"
        out_pdf = tmp_path / "out.pdf"
        out_epub.write_text("epub")
        out_docx.write_text("docx")
        out_pdf.write_text("pdf")

        with _patch_db(db_path):
            with patch('bot.core_worker.main', return_value=(str(out_epub), str(out_docx), str(out_pdf))):
                with patch.dict(os.environ, {"TOKEN_NOTIFY": ""}, clear=False):
                    result = await epub_prepare(mock_update, mock_context)

        assert result == AFTER_PREPARATION
        assert mock_update.message.reply_document.call_count == 3

    @pytest.mark.asyncio
    async def test_notification_sent(self, mock_update, mock_context, db_path):
        from bot import epub_prepare

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"
        mock_context.user_data["epub_path"] = "/tmp/test.epub"
        mock_context.user_data["chapters"] = [{"id": "ch1.xhtml", "title": "Ch1"}]
        mock_context.user_data["selected_chapter_indices"] = [0]
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path)

        mock_notify_bot = AsyncMock()
        mock_notify_bot.send_message = AsyncMock()

        with _patch_db(db_path):
            with patch('bot.core_worker.main', return_value=("/tmp/a.epub", "/tmp/a.docx", "/tmp/a.pdf")):
                with patch('bot.os.path.isfile', return_value=False):
                    with patch.dict(os.environ, {"TOKEN_NOTIFY": "fake-notify-token"}, clear=False):
                        with patch('bot.telegram.Bot', return_value=mock_notify_bot):
                            await epub_prepare(mock_update, mock_context)

        mock_notify_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_failure_handled(self, mock_update, mock_context, db_path):
        from bot import epub_prepare

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"
        mock_context.user_data["epub_path"] = "/tmp/test.epub"
        mock_context.user_data["chapters"] = [{"id": "ch1.xhtml", "title": "Ch1"}]
        mock_context.user_data["selected_chapter_indices"] = [0]
        mock_update.effective_user.id = 111111
        mock_update.callback_query = None

        _insert_user(db_path)

        with _patch_db(db_path):
            with patch('bot.core_worker.main', return_value=("/tmp/a.epub", "/tmp/a.docx", "/tmp/a.pdf")):
                with patch('bot.os.path.isfile', return_value=False):
                    with patch.dict(os.environ, {"TOKEN_NOTIFY": "fake-token"}, clear=False):
                        with patch('bot.telegram.Bot', side_effect=Exception("Notify fail")):
                            await epub_prepare(mock_update, mock_context)
        # Should not raise


# ---------------------------------------------------------------------------
# after_preparation
# ---------------------------------------------------------------------------

class TestAfterPreparation:
    @pytest.mark.asyncio
    async def test_yes_continues(self, mock_update, mock_context):
        from bot import after_preparation, RECEIVE_EPUB_FILE

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_context.user_data["language"] = "en"
        mock_update.effective_user.id = 111111

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "yes"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        result = await after_preparation(mock_update, mock_context)
        assert result == RECEIVE_EPUB_FILE

    @pytest.mark.asyncio
    async def test_no_ends_conversation(self, mock_update, mock_context):
        from bot import after_preparation
        from telegram.ext import ConversationHandler

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_update.effective_user.id = 111111

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "no"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        result = await after_preparation(mock_update, mock_context)
        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_rate_limited_non_admin(self, mock_update, mock_context, db_path):
        from bot import after_preparation
        from telegram.ext import ConversationHandler
        import bot

        mock_trans = MagicMock()
        mock_trans.gettext = lambda x: x
        mock_context.user_data["translation"] = mock_trans
        mock_update.effective_user.id = 333333

        original_allowed = bot.allowed_user_ids.copy()
        bot.allowed_user_ids.add(333333)

        recent_time = datetime.now(TIMEZONE).isoformat("T", "seconds")
        _insert_user(db_path, user_id=333333, lang="en", last_run=recent_time)

        mock_update.callback_query = AsyncMock()
        mock_update.callback_query.data = "yes"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.message = AsyncMock()
        mock_update.callback_query.message.reply_text = AsyncMock()

        try:
            with _patch_db(db_path):
                result = await after_preparation(mock_update, mock_context)
            assert result == ConversationHandler.END
        finally:
            bot.allowed_user_ids = original_allowed


# ---------------------------------------------------------------------------
# admin_broadcast_msg
# ---------------------------------------------------------------------------

class TestAdminBroadcastMsg:
    @pytest.mark.asyncio
    async def test_non_admin_rejected(self, mock_update, mock_context):
        from bot import admin_broadcast_msg

        mock_update.effective_user.id = 999999
        await admin_broadcast_msg(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_with("Not authorized.")

    @pytest.mark.asyncio
    async def test_empty_message(self, mock_update, mock_context):
        from bot import admin_broadcast_msg

        mock_update.effective_user.id = 111111
        mock_update.message.text = "/admin_broadcast_msg"
        await admin_broadcast_msg(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_with("Provide a message to broadcast.")

    @pytest.mark.asyncio
    async def test_broadcasts_to_users(self, mock_update, mock_context, db_path):
        from bot import admin_broadcast_msg

        mock_update.effective_user.id = 111111
        mock_update.message.text = "/admin_broadcast_msg Hello everyone!"

        _insert_user(db_path, user_id=111111)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO Main (UserId, UserName) VALUES (?, ?)", (222222, "user2")
        )
        conn.commit()
        conn.close()

        with _patch_db(db_path):
            await admin_broadcast_msg(mock_update, mock_context)

        assert mock_context.bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_broadcast_handles_send_failure(self, mock_update, mock_context, db_path):
        from bot import admin_broadcast_msg

        mock_update.effective_user.id = 111111
        mock_update.message.text = "/admin_broadcast_msg Test"

        _insert_user(db_path)
        mock_context.bot.send_message = AsyncMock(side_effect=Exception("Blocked"))

        with _patch_db(db_path):
            await admin_broadcast_msg(mock_update, mock_context)

        # Should report 0 successful sends
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "0" in call_args


# ---------------------------------------------------------------------------
# main (bot entry point)
# ---------------------------------------------------------------------------

class TestBotMain:
    def test_main_builds_application(self):
        from bot import main as bot_main

        with patch('bot.Application') as mock_app_cls:
            mock_builder = MagicMock()
            mock_app = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.post_init.return_value = mock_builder
            mock_builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = mock_builder
            mock_app.run_polling = MagicMock()

            with patch('bot.sqlite3.connect') as mock_conn:
                mock_cursor = MagicMock()
                mock_conn.return_value = mock_conn
                mock_conn.cursor.return_value = mock_cursor
                mock_conn.commit = MagicMock()
                mock_conn.close = MagicMock()

                bot_main()

            mock_app.add_handler.assert_called()
            mock_app.run_polling.assert_called_once()


# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------

class TestConversationStates:
    def test_states_are_unique(self):
        from bot import (
            LANG_SELECT, RECEIVE_EPUB_FILE, SELECT_CHAPTERS,
            CUSTOMIZE_QUESTIONS_YES_NO, CHOOSE_EDIT_OR_DELETE,
            RECEIVE_QUESTION_NUMBER, RECEIVE_QUESTION_TEXT,
            ASK_FOR_MORE_ACTIONS, EPUB_PREPARE, AFTER_PREPARATION,
            RECEIVE_KEEP_QUESTIONS_RESPONSE,
        )
        states = [
            LANG_SELECT, RECEIVE_EPUB_FILE, SELECT_CHAPTERS,
            CUSTOMIZE_QUESTIONS_YES_NO, CHOOSE_EDIT_OR_DELETE,
            RECEIVE_QUESTION_NUMBER, RECEIVE_QUESTION_TEXT,
            ASK_FOR_MORE_ACTIONS, EPUB_PREPARE, AFTER_PREPARATION,
            RECEIVE_KEEP_QUESTIONS_RESPONSE,
        ]
        assert len(states) == len(set(states))

    def test_states_are_sequential(self):
        from bot import (
            LANG_SELECT, RECEIVE_EPUB_FILE, SELECT_CHAPTERS,
            CUSTOMIZE_QUESTIONS_YES_NO, CHOOSE_EDIT_OR_DELETE,
            RECEIVE_QUESTION_NUMBER, RECEIVE_QUESTION_TEXT,
            ASK_FOR_MORE_ACTIONS, EPUB_PREPARE, AFTER_PREPARATION,
            RECEIVE_KEEP_QUESTIONS_RESPONSE,
        )
        assert LANG_SELECT == 0
        assert RECEIVE_KEEP_QUESTIONS_RESPONSE == 10
