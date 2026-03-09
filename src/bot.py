import logging
import gettext
import os
import re
import sys
import sqlite3
from datetime import datetime, timedelta

import pytz
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
    CallbackQueryHandler, ConversationHandler
)

import core_worker

# Conversation states
(
    LANG_SELECT,
    RECEIVE_EPUB_FILE,
    SELECT_CHAPTERS,
    CUSTOMIZE_QUESTIONS_YES_NO,
    CHOOSE_EDIT_OR_DELETE,
    RECEIVE_QUESTION_NUMBER,
    RECEIVE_QUESTION_TEXT,
    ASK_FOR_MORE_ACTIONS,
    EPUB_PREPARE,
    AFTER_PREPARATION,
    RECEIVE_KEEP_QUESTIONS_RESPONSE,
) = range(11)

# Logging
logger = logging.getLogger("askepub")
logger.setLevel(logging.INFO)
_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_formatter)
logger.addHandler(_handler)

# Environment
admin_id = int(os.environ["ADMIN_ID"])
user_ids_env = os.environ.get("USER_IDS")
if user_ids_env:
    allowed_user_ids = {int(uid.strip()) for uid in user_ids_env.split(",") if uid.strip()}
else:
    allowed_user_ids = set()
allowed_user_ids.add(admin_id)

TIMEZONE = pytz.timezone("Europe/Madrid")

# Translation cache
_translations_cache: dict = {}


def get_translation(context):
    lang_code = context.user_data.get("language", "es")
    if lang_code in _translations_cache:
        return _translations_cache[lang_code]
    localedir = os.path.join(os.path.dirname(__file__), "../locales")
    try:
        translation = gettext.translation(domain="askepub", localedir=localedir, languages=[lang_code])
    except FileNotFoundError:
        logger.warning("Translation not found for '%s', falling back to 'es'.", lang_code)
        translation = gettext.translation(domain="askepub", localedir=localedir, languages=["es"], fallback=True)
    _translations_cache[lang_code] = translation
    return translation


def get_default_questions(trans):
    q1 = trans("Resume los puntos clave y argumentos principales de esta sección")
    q2 = trans("¿Cuáles son los conceptos o términos más importantes introducidos?")
    q3 = trans("¿Qué preguntas plantea o deja sin responder esta sección?")
    return [q1, q2, q3]


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def startup_message(application: Application):
    try:
        await application.bot.send_message(chat_id=admin_id, text="AskePub booted up")
    except Exception as e:
        logger.error("Failed to send startup message: %s", e)


async def check_if_user_exists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM Main WHERE UserId = ?", (user.id,))
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO Main (UserId, UserName, FirstName, LastName, LangCodeTelegram, IsBot) VALUES (?, ?, ?, ?, ?, ?)",
            (user.id, user.username, user.first_name, user.last_name, user.language_code, user.is_bot),
        )
    else:
        cur.execute(
            "UPDATE Main SET UserName=?, FirstName=?, LastName=?, LangCodeTelegram=?, IsBot=? WHERE UserId=?",
            (user.username, user.first_name, user.last_name, user.language_code, user.is_bot, user.id),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    await check_if_user_exists(update, context)
    logger.info("START - User %s (%s)", user.id, user.username)

    context.user_data["command"] = "start"

    if user.is_bot:
        await update.message.reply_text("Bots are not allowed.")
        return ConversationHandler.END

    if user.id not in allowed_user_ids:
        await update.message.reply_text("You are not authorized to use this bot.")
        return ConversationHandler.END

    # Rate limit (non-admin)
    if user.id != admin_id:
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute("SELECT LastRun, LangSelected FROM Main WHERE UserId = ?", (user.id,))
        row = cur.fetchone()
        conn.close()
        last_run_str = row[0] if row else None
        lang_selected = row[1] if row else None

        if last_run_str:
            now = datetime.now(TIMEZONE)
            last_run = datetime.fromisoformat(last_run_str)
            diff = now - last_run
            if diff < timedelta(hours=1):
                remaining = int((timedelta(hours=1) - diff).total_seconds() // 60)
                trans = get_translation(context).gettext
                await update.message.reply_text(
                    trans("Has alcanzado el límite. Intenta de nuevo en {minutes} minutos.").format(minutes=remaining)
                )
                return ConversationHandler.END
    else:
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute("SELECT LangSelected FROM Main WHERE UserId = ?", (user.id,))
        row = cur.fetchone()
        conn.close()
        lang_selected = row[0] if row else None

    # Set language in context
    if lang_selected:
        context.user_data["language"] = lang_selected
        context.user_data["translation"] = get_translation(context)
    else:
        context.user_data["language"] = None

    if not context.user_data["language"]:
        return await language_select(update, context)

    trans = context.user_data["translation"].gettext

    # Ensure default questions
    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("SELECT Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8,Q9,Q10 FROM Main WHERE UserId = ?", (user.id,))
    data = cur.fetchone()
    conn.close()
    if not any(data):
        defaults = get_default_questions(trans)
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute("UPDATE Main SET Q1=?, Q2=?, Q3=? WHERE UserId=?", (*defaults, user.id))
        conn.commit()
        conn.close()

    await update.message.reply_text(
        trans("Idioma seleccionado: {lang}. Envíame un archivo .epub para comenzar.").format(lang=lang_selected)
    )
    return RECEIVE_EPUB_FILE


# ---------------------------------------------------------------------------
# /change_language
# ---------------------------------------------------------------------------

async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id not in allowed_user_ids:
        await update.message.reply_text("You are not authorized to use this bot.")
        return ConversationHandler.END
    logger.info("CHANGE_LANGUAGE - User %s", user.id)
    context.user_data["command"] = "change_language"
    return await language_select(update, context)


# ---------------------------------------------------------------------------
# Language selection
# ---------------------------------------------------------------------------

LANGUAGES = [
    ("English", "en"),
    ("Español", "es"),
    ("Italiano", "it"),
    ("Français", "fr"),
    ("Português (Portugal)", "pt-A"),
    ("Português (Brasil)", "pt-B"),
    ("Deutsch", "de"),
    ("Български", "bg"),
]


async def language_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton(name, callback_data=f"lang_{code}")] for name, code in LANGUAGES]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Please select your language / Por favor selecciona tu idioma"
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    return LANG_SELECT


async def language_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    lang_code = query.data.replace("lang_", "")
    logger.info("LANGUAGE_SELECTED - User %s - Lang %s", user.id, lang_code)

    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("SELECT LangSelected FROM Main WHERE UserId = ?", (user.id,))
    row = cur.fetchone()
    old_lang = row[0] if row else None
    cur.execute("UPDATE Main SET LangSelected = ? WHERE UserId = ?", (lang_code, user.id))
    conn.commit()
    conn.close()

    context.user_data["language"] = lang_code
    context.user_data["translation"] = get_translation(context)
    trans = context.user_data["translation"].gettext

    if old_lang and old_lang != lang_code:
        keyboard = [
            [InlineKeyboardButton(trans("Mantener preguntas"), callback_data="keep_questions")],
            [InlineKeyboardButton(trans("Usar predeterminadas"), callback_data="reset_questions")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            trans("¿Quieres mantener tus preguntas anteriores o usar las predeterminadas?"),
            reply_markup=reply_markup,
        )
        return RECEIVE_KEEP_QUESTIONS_RESPONSE

    await query.edit_message_text(
        trans("Idioma seleccionado: {lang}. Envíame un archivo .epub para comenzar.").format(lang=lang_code)
    )
    return RECEIVE_EPUB_FILE


async def receive_keep_questions_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    trans = context.user_data["translation"].gettext

    if query.data == "reset_questions":
        defaults = get_default_questions(trans)
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute(
            "UPDATE Main SET Q1=?, Q2=?, Q3=?, Q4=NULL, Q5=NULL, Q6=NULL, Q7=NULL, Q8=NULL, Q9=NULL, Q10=NULL WHERE UserId=?",
            (*defaults, user.id),
        )
        conn.commit()
        conn.close()

    await query.edit_message_text(
        trans("Idioma seleccionado: {lang}. Envíame un archivo .epub para comenzar.").format(
            lang=context.user_data["language"]
        )
    )
    return RECEIVE_EPUB_FILE


# ---------------------------------------------------------------------------
# Receive ePub file
# ---------------------------------------------------------------------------

async def receive_epub_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    trans = context.user_data["translation"].gettext
    doc = update.message.document

    if not doc or not doc.file_name or not doc.file_name.lower().endswith(".epub"):
        await update.message.reply_text(trans("Por favor, envía un archivo .epub válido."))
        return RECEIVE_EPUB_FILE

    logger.info("RECEIVE_EPUB - User %s - File %s", user.id, doc.file_name)

    await update.message.reply_text(trans("Archivo recibido. Analizando..."))

    # Download the file
    os.makedirs("userBackups", exist_ok=True)
    epub_path = f"userBackups/{user.id}.epub"
    tg_file = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(epub_path)
    context.user_data["epub_path"] = epub_path

    # Parse chapters
    try:
        chapters = core_worker.parse_epub(epub_path)
    except Exception as e:
        logger.error("Error parsing ePub: %s", e)
        await update.message.reply_text(trans("Error al procesar el archivo. Por favor, intenta con otro .epub."))
        return RECEIVE_EPUB_FILE

    if not chapters:
        await update.message.reply_text(trans("Error al procesar el archivo. Por favor, intenta con otro .epub."))
        return RECEIVE_EPUB_FILE

    context.user_data["chapters"] = chapters

    # Build chapter list text
    chapter_lines = []
    for i, ch in enumerate(chapters, 1):
        title = ch["title"][:80]
        chapter_lines.append(f"{i}. {title}")
    chapters_text = "\n".join(chapter_lines)

    all_word = trans("todos")
    msg = trans(
        "He encontrado {count} capítulos en este libro:\n\n{chapters}\n\nEscribe los números de los capítulos que quieres estudiar (ej: 1,3,5 o 1-5 o '{all_word}')."
    ).format(count=len(chapters), chapters=chapters_text, all_word=all_word)

    # Telegram has a 4096 char limit; truncate if needed
    if len(msg) > 4000:
        msg = msg[:3990] + "\n..."

    await update.message.reply_text(msg)
    return SELECT_CHAPTERS


async def receive_epub_text_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trans = context.user_data.get("translation", get_translation(context)).gettext
    await update.message.reply_text(trans("Por favor, envía un archivo .epub válido."))
    return RECEIVE_EPUB_FILE


# ---------------------------------------------------------------------------
# Chapter selection
# ---------------------------------------------------------------------------

def parse_chapter_selection(text: str, total: int, all_word: str = "todos") -> list[int] | None:
    """Parse user input like '1,3,5', '1-5', 'all'/'todos' into 0-based indices."""
    text = text.strip().lower()
    if text in ("all", all_word.lower(), "todos"):
        return list(range(total))

    indices = set()
    for part in re.split(r"[,;\s]+", text):
        part = part.strip()
        if not part:
            continue
        range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start < 1 or end > total or start > end:
                return None
            indices.update(range(start - 1, end))
        elif part.isdigit():
            num = int(part)
            if num < 1 or num > total:
                return None
            indices.add(num - 1)
        else:
            return None

    return sorted(indices) if indices else None


async def select_chapters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    trans = context.user_data["translation"].gettext
    chapters = context.user_data.get("chapters", [])
    all_word = trans("todos")

    selection = parse_chapter_selection(update.message.text, len(chapters), all_word)
    if selection is None:
        await update.message.reply_text(
            trans("Selección no válida. Por favor, usa números separados por comas (1,3,5), rangos (1-5), o escribe '{all_word}'.").format(
                all_word=all_word
            )
        )
        return SELECT_CHAPTERS

    context.user_data["selected_chapter_indices"] = selection
    logger.info("SELECT_CHAPTERS - User %s - Selected %d chapters", user.id, len(selection))

    # Show current questions
    return await show_questions(update, context)


# ---------------------------------------------------------------------------
# Question management
# ---------------------------------------------------------------------------

async def show_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trans = context.user_data["translation"].gettext
    user = update.effective_user
    selected_count = len(context.user_data.get("selected_chapter_indices", []))

    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("SELECT Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8,Q9,Q10 FROM Main WHERE UserId = ?", (user.id,))
    data = cur.fetchone()
    conn.close()

    # Initialize defaults if empty
    if not any(data):
        defaults = get_default_questions(trans)
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute("UPDATE Main SET Q1=?, Q2=?, Q3=? WHERE UserId=?", (*defaults, user.id))
        conn.commit()
        conn.close()
        data = tuple(defaults) + (None,) * 7

    questions_lines = []
    for i in range(10):
        if data[i]:
            questions_lines.append(f"{i + 1}. {data[i]}")
    questions_text = "\n".join(questions_lines)

    msg = trans(
        "Has seleccionado {count} capítulo(s). Tus preguntas actuales:\n\n{questions}\n\n¿Quieres personalizar las preguntas?"
    ).format(count=selected_count, questions=questions_text)

    keyboard = [
        [InlineKeyboardButton(trans("Sí, personalizar"), callback_data="yes")],
        [InlineKeyboardButton(trans("No, continuar"), callback_data="no")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=reply_markup)
    return CUSTOMIZE_QUESTIONS_YES_NO


async def customize_questions_yes_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "yes":
        return await ask_edit_or_delete(update, context)
    else:
        return await epub_prepare(update, context)


async def ask_edit_or_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trans = context.user_data["translation"].gettext
    keyboard = [
        [InlineKeyboardButton(trans("Editar pregunta"), callback_data="edit")],
        [InlineKeyboardButton(trans("Eliminar pregunta"), callback_data="delete")],
        [InlineKeyboardButton(trans("Añadir pregunta"), callback_data="add")],
        [InlineKeyboardButton(trans("Continuar con la preparación"), callback_data="continue")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = trans("¿Qué deseas hacer?")
    if update.callback_query:
        await update.callback_query.message.reply_text(msg, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup)
    return CHOOSE_EDIT_OR_DELETE


async def choose_edit_or_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data
    context.user_data["action"] = action
    trans = context.user_data["translation"].gettext

    if action == "continue":
        return await epub_prepare(update, context)

    if action == "add":
        # Find first empty slot
        user = update.effective_user
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute("SELECT Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8,Q9,Q10 FROM Main WHERE UserId = ?", (user.id,))
        data = cur.fetchone()
        conn.close()
        empty_slot = None
        for i in range(10):
            if not data[i]:
                empty_slot = i + 1
                break
        if empty_slot is None:
            await query.message.reply_text(trans("¿Qué deseas hacer?").replace(trans("¿Qué deseas hacer?"), "Maximum 10 questions reached."))
            return await ask_edit_or_delete(update, context)
        context.user_data["question_number"] = empty_slot
        await query.edit_message_text(trans("Escribe el texto de la nueva pregunta:"))
        return RECEIVE_QUESTION_TEXT

    # edit or delete
    return await ask_for_question_number(update, context)


async def ask_for_question_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trans = context.user_data["translation"].gettext
    action = context.user_data["action"]
    user = update.effective_user

    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("SELECT Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8,Q9,Q10 FROM Main WHERE UserId = ?", (user.id,))
    data = cur.fetchone()
    conn.close()

    keyboard = []
    if action == "edit":
        for i in range(10):
            if data[i]:
                keyboard.append([InlineKeyboardButton(f"Q{i + 1}: {data[i][:40]}", callback_data=str(i + 1))])
        text = trans("Escribe el número de la pregunta a editar:")
    else:  # delete
        for i in range(10):
            if data[i]:
                keyboard.append([InlineKeyboardButton(f"Q{i + 1}: {data[i][:40]}", callback_data=str(i + 1))])
        text = trans("Escribe el número de la pregunta a eliminar:")

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    return RECEIVE_QUESTION_NUMBER


async def receive_question_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    qnum = int(query.data)
    action = context.user_data["action"]
    user = update.effective_user
    trans = context.user_data["translation"].gettext
    context.user_data["question_number"] = qnum

    if action == "edit":
        await query.edit_message_text(
            trans("Escribe el nuevo texto para la pregunta {num}:").format(num=qnum)
        )
        return RECEIVE_QUESTION_TEXT
    elif action == "delete":
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute("SELECT Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8,Q9,Q10 FROM Main WHERE UserId = ?", (user.id,))
        data = cur.fetchone()
        non_empty = sum(1 for q in data if q)
        if non_empty <= 1:
            await query.message.reply_text(trans("No puedes eliminar la última pregunta."))
            return await ask_edit_or_delete(update, context)
        cur.execute(f"UPDATE Main SET Q{qnum} = NULL WHERE UserId = ?", (user.id,))
        conn.commit()
        conn.close()
        await query.message.reply_text(trans("Pregunta eliminada."))
        return await ask_edit_or_delete(update, context)


async def receive_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    user = update.effective_user
    qnum = context.user_data["question_number"]
    trans = context.user_data["translation"].gettext

    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute(f"UPDATE Main SET Q{qnum} = ? WHERE UserId = ?", (text, user.id))
    conn.commit()
    conn.close()

    if context.user_data.get("action") == "add":
        await update.message.reply_text(trans("Pregunta añadida."))
    else:
        await update.message.reply_text(trans("Pregunta actualizada."))

    return await ask_edit_or_delete(update, context)


# ---------------------------------------------------------------------------
# Preparation
# ---------------------------------------------------------------------------

async def epub_prepare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    trans = context.user_data["translation"].gettext

    # Determine message target
    if update.callback_query:
        message = update.callback_query.message
    elif update.message:
        message = update.message
    else:
        return ConversationHandler.END

    await message.reply_text(trans("Preparando tus notas de estudio. Esto puede tardar unos minutos..."))
    await context.bot.send_chat_action(chat_id=message.chat_id, action=telegram.constants.ChatAction.TYPING)

    # Fetch questions from DB
    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("SELECT Q1,Q2,Q3,Q4,Q5,Q6,Q7,Q8,Q9,Q10 FROM Main WHERE UserId = ?", (user.id,))
    qs_data = cur.fetchone()
    conn.close()

    questions = [q for q in qs_data if q]
    if not questions:
        await message.reply_text("No questions configured.")
        return ConversationHandler.END

    epub_path = context.user_data.get("epub_path")
    chapters = context.user_data.get("chapters", [])
    selected_indices = context.user_data.get("selected_chapter_indices", [])
    language = context.user_data.get("language", "es")

    if not epub_path or not chapters:
        await message.reply_text(trans("Error al procesar el archivo. Por favor, intenta con otro .epub."))
        return ConversationHandler.END

    selected_chapter_ids = [chapters[i]["id"] for i in selected_indices if i < len(chapters)]

    # Update LastRun
    now_iso = datetime.now(TIMEZONE).isoformat("T", "seconds")
    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("UPDATE Main SET LastRun = ? WHERE UserId = ?", (now_iso, user.id))
    conn.commit()
    conn.close()

    # Send admin notification
    try:
        token_notify = os.environ.get("TOKEN_NOTIFY")
        if token_notify:
            notify_bot = telegram.Bot(token=token_notify)
            notify_msg = (
                f"AskePub - User Started Preparation:\n"
                f"UserId: {user.id}\n"
                f"UserName: {user.username}\n"
                f"Language: {language}\n"
                f"Chapters: {len(selected_chapter_ids)}\n"
                f"Questions: {len(questions)}\n"
            )
            await notify_bot.send_message(chat_id=admin_id, text=notify_msg)
    except Exception as e:
        logger.error("Error sending notification: %s", e)

    # Run the core worker
    try:
        epub_out, docx_out, pdf_out = core_worker.main(
            epub_path=epub_path,
            telegram_user=str(user.id),
            selected_chapter_ids=selected_chapter_ids,
            questions=questions,
            language=language,
        )

        await message.reply_text(trans("Aquí tienes tus archivos:"))

        # Send annotated ePub
        if os.path.isfile(epub_out):
            await message.reply_document(
                document=open(epub_out, "rb"),
                caption=trans("ePub anotado con tus notas de estudio"),
            )
            os.remove(epub_out)

        # Send DOCX
        if os.path.isfile(docx_out):
            await message.reply_document(
                document=open(docx_out, "rb"),
                caption=trans("Documento Word con las notas"),
            )
            os.remove(docx_out)

        # Send PDF
        if os.path.isfile(pdf_out):
            await message.reply_document(
                document=open(pdf_out, "rb"),
                caption=trans("Documento PDF con las notas"),
            )
            os.remove(pdf_out)

    except Exception as e:
        logger.error("Error in core_worker.main: %s", e)
        await message.reply_text(trans("Error al procesar el archivo. Por favor, intenta con otro .epub."))
        return ConversationHandler.END

    # Clean up uploaded epub
    if epub_path and os.path.isfile(epub_path):
        os.remove(epub_path)

    # Ask if they want to study another book
    keyboard = [
        [InlineKeyboardButton(trans("Sí"), callback_data="yes")],
        [InlineKeyboardButton(trans("No"), callback_data="no")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(
        trans("¿Deseas estudiar otro libro o más capítulos?"), reply_markup=reply_markup
    )
    return AFTER_PREPARATION


# ---------------------------------------------------------------------------
# After preparation
# ---------------------------------------------------------------------------

async def after_preparation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    trans = context.user_data["translation"].gettext

    # Rate limit check for non-admin
    if user.id != admin_id:
        conn = sqlite3.connect("dbs/main.db")
        cur = conn.cursor()
        cur.execute("SELECT LastRun FROM Main WHERE UserId = ?", (user.id,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            now = datetime.now(TIMEZONE)
            last_run = datetime.fromisoformat(row[0])
            diff = now - last_run
            if diff < timedelta(hours=1):
                remaining = int((timedelta(hours=1) - diff).total_seconds() // 60)
                await query.message.reply_text(
                    trans("Has alcanzado el límite. Intenta de nuevo en {minutes} minutos.").format(minutes=remaining)
                )
                return ConversationHandler.END

    if query.data == "yes":
        await query.message.reply_text(
            trans("Idioma seleccionado: {lang}. Envíame un archivo .epub para comenzar.").format(
                lang=context.user_data.get("language", "es")
            )
        )
        return RECEIVE_EPUB_FILE
    else:
        await query.message.reply_text(trans("Gracias por usar AskePub. Usa /start para comenzar de nuevo."))
        return ConversationHandler.END


# ---------------------------------------------------------------------------
# Cancel & Admin
# ---------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trans_obj = context.user_data.get("translation")
    if trans_obj:
        trans = trans_obj.gettext
    else:
        trans = lambda x: x
    await update.message.reply_text(trans("Operación cancelada."))
    return ConversationHandler.END


async def admin_broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != admin_id:
        await update.message.reply_text("Not authorized.")
        return
    msg_text = update.message.text.partition(" ")[2]
    if not msg_text:
        await update.message.reply_text("Provide a message to broadcast.")
        return
    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("SELECT UserId FROM Main")
    rows = cur.fetchall()
    conn.close()
    ok = 0
    for (uid,) in rows:
        try:
            await context.bot.send_message(chat_id=uid, text=msg_text)
            ok += 1
        except Exception as e:
            logger.error("Failed to send to %s: %s", uid, e)
    await update.message.reply_text(f"Message sent to {ok} users.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    application = Application.builder().token(os.environ["TOKEN"]).post_init(startup_message).build()

    os.makedirs("dbs", exist_ok=True)

    # Create DB table
    conn = sqlite3.connect("dbs/main.db")
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS "Main" (
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

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("change_language", change_language),
        ],
        states={
            LANG_SELECT: [
                CallbackQueryHandler(language_selected, pattern="^lang_"),
                CommandHandler("cancel", cancel),
            ],
            RECEIVE_KEEP_QUESTIONS_RESPONSE: [
                CallbackQueryHandler(receive_keep_questions_response),
                CommandHandler("cancel", cancel),
            ],
            RECEIVE_EPUB_FILE: [
                MessageHandler(filters.Document.ALL, receive_epub_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_epub_text_reject),
                CommandHandler("cancel", cancel),
            ],
            SELECT_CHAPTERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_chapters),
                CommandHandler("cancel", cancel),
            ],
            CUSTOMIZE_QUESTIONS_YES_NO: [
                CallbackQueryHandler(customize_questions_yes_no),
                CommandHandler("cancel", cancel),
            ],
            CHOOSE_EDIT_OR_DELETE: [
                CallbackQueryHandler(choose_edit_or_delete),
                CommandHandler("cancel", cancel),
            ],
            RECEIVE_QUESTION_NUMBER: [
                CallbackQueryHandler(receive_question_number),
                CommandHandler("cancel", cancel),
            ],
            RECEIVE_QUESTION_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question_text),
                CommandHandler("cancel", cancel),
            ],
            ASK_FOR_MORE_ACTIONS: [
                CallbackQueryHandler(choose_edit_or_delete),
                CommandHandler("cancel", cancel),
            ],
            AFTER_PREPARATION: [
                CallbackQueryHandler(after_preparation),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("admin_broadcast_msg", admin_broadcast_msg))
    application.run_polling()


if __name__ == "__main__":
    main()
