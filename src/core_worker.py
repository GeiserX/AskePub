# core_worker.py

# Import necessary modules
import os
import shutil
import logging
import zipfile
import subprocess
import hashlib  # For calculating SHA-256 hash
import sqlite3
import json
import pytz
import requests
import gettext  # For translations
from datetime import datetime
from bs4 import BeautifulSoup
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.shared import Pt

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Import LangChain and OpenAI
import openai
import langchain
from langchain.cache import SQLiteCache
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.chains import LLMChain
from langchain.prompts import (
    PromptTemplate
)

# Set up caching
langchain.llm_cache = SQLiteCache(database_path="/app/dbs/langchain.db")

#########################################
### HELPER: DESCRIBE EPUBLIBRARY FILE ###
#########################################

def describe_epublibrary(telegram_user):
    logger.info("describe_epublibrary - Telegram User: {0}".format(telegram_user))
    epubfile = "userBackups/{0}.epublibrary".format(telegram_user)

    with zipfile.ZipFile(epubfile, 'r') as zip_ref:
        files = zip_ref.namelist()
        zip_ref.extractall("userBackups/{0}/".format(telegram_user))

    uploadedDb = "userBackups/{0}/{1}".format(telegram_user, [zipname for zipname in files if zipname.endswith(".db")][0])

    connection = sqlite3.connect(uploadedDb)
    cursor = connection.cursor()
    cursor.execute("SELECT Count(*) FROM Note")
    notesN = cursor.fetchone()[0]
    cursor.execute("SELECT Count(*) FROM Field")
    inputN = cursor.fetchone()[0]
    cursor.execute("SELECT Count(*) FROM TagM")
    tagMaptN = cursor.fetchone()[0]
    cursor.execute("SELECT Count(*) FROM Tag")
    tagN = cursor.fetchone()[0]
    cursor.execute("SELECT Count(*) FROM Book")
    bookmarkN = cursor.fetchone()[0]
    cursor.execute("SELECT LastModified FROM LastModified")
    lastModified = cursor.fetchone()[0]
    cursor.execute("SELECT Count(*) FROM Mark")
    userMarkN = cursor.fetchone()[0]
    connection.close()

    shutil.rmtree("userBackups/{0}/".format(telegram_user))

    return notesN, inputN, tagMaptN, tagN, bookmarkN, lastModified, userMarkN

#######################
### EXTRACTING HTML ###
#######################

def epub_extract_html(url, get_all):
    logger.info("epub_extract_html - URL: {0} - Full Run: {1}".format(url, get_all))

    html = requests.get(url).text
    soup = BeautifulSoup(html, features="html5lib")
    title = soup.find("h1").text
    classArticleId = soup.find("sontile", {"id": "sontile"}).get("class")
    articleId = next(x for x in classArticleId if x.startswith("iss"))[4:] + "00"
    articleN = soup.find("p", {"id": "p1"}).text

    if get_all:
        base_text = soup.find("p", {"id": "p4"}).text
        summary = soup.find("p", {"id": "p6"}).text
        DiD = soup.find("input", {"name": "xid"}).get("value")
        p_elements = soup.find("div", {"class": "bodyTxt"})
        questions = p_elements.find_all("p", {"class": lambda x: x and x.startswith("qu")})
        paragraphs = p_elements.find_all("p", {"class": lambda x: x and x.startswith("p")})
        textareas = soup.find_all("textarea")

        # Example q_map = {0: [q1, [p1]], 1: [q2&3, [p2, p3]]}
        q_map = {}
        i = 0
        for q in questions:
            q_map[i] = [q]
            q_map[i].append([p for p in paragraphs if p.has_attr('data-rel-pid') and p.get('data-rel-pid').strip('[]') in q.get('data-pid')])
            i += 1

        return title, base_text, summary, questions, DiD, articleId, q_map, textareas
    else:
        return title, articleId, articleN

####################
### QUERY OPENAI ###
####################

def epub_query_openai(title, base_text, summary, q_map, qs_user, trans):
    logger = logging.getLogger(__name__)
    logger.info("epub_query_openai - Title: {0}".format(title))

    questions = [f"{i+1}. {question}" for i, question in enumerate(qs_user) if question]
    questions_text = "\n".join(questions)
    logger.info("epub_query_openai - Questions Text: {0}".format(questions_text))

    # Prepare the system prompt (now incorporated into the user input)
    system_prompt_template = trans("""Eres un asistente que únicamente usa place.holder y las publicaciones de place.holder.
Yo estoy preparándome... {title}, {base_text}, resumen es el siguiente:
{summary}
Para cada pregunta y párrafo o párrafos que te vaya enviando a partir de ahora, responderás en una lista lo siguiente:
{questions_text}
No escribas estas preguntas de nuevo en la respuesta. Separa las respuestas con dos retornos de carro.""")

    system_prompt = system_prompt_template.format(
        title=title,
        base_text=base_text,
        summary=summary,
        questions_text=questions_text
    )

    # Log the system prompt
    logger.info("epub_query_openai - System Prompt:\n{0}".format(system_prompt))

    # Set up the ChatOpenAI LLM
    llm = ChatOpenAI(model_name="gpt-4o-mini")

    # Define a simple prompt that just uses the input
    prompt = PromptTemplate.from_template("{input}")

    notes = {}
    i = 0

    for idx, q in enumerate(q_map.values()):
        chain = LLMChain(llm=llm, prompt=prompt)

        # Flatten the paragraphs
        flattened_paragraph = "".join([p.text for p in q[1]])

        # Prepare the user input
        user_input_template = trans("Pregunta: {question} -- Párrafo(s): {paragraphs}")
        user_input = user_input_template.format(
            question=q[0].text,
            paragraphs=flattened_paragraph
        )

        # Combine the system prompt and user input
        full_input = system_prompt + "\n\n" + user_input

        # Log the user input
        logger.info("epub_query_openai - User Input for question {0}:\n{1}".format(idx+1, user_input))

        # Log the full input (system prompt + user input)
        logger.info("epub_query_openai - Full Input for question {0}:\n{1}".format(idx+1, full_input))

        # Call the chain to get the response
        notes[i] = chain.predict(input=full_input)

        # Log the response
        logger.info("epub_query_openai(Note) - Note for question {0}:\n{1}".format(idx+1, notes[i]))

        i += 1

    return notes

##############################
### WRITE EPUBLIBRARY FILE ###
##############################

def calculate_user_data_hash(user_data_db_path):
    sha256_hash = hashlib.sha256()
    with open(user_data_db_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    hash_digest = sha256_hash.hexdigest()
    return hash_digest

def get_last_modified_date(user_data_db_path):
    last_modified_timestamp = os.path.getmtime(user_data_db_path)
    last_modified_date = datetime.fromtimestamp(
        last_modified_timestamp,
        pytz.timezone('Europe/Madrid')
    ).isoformat()
    return last_modified_date

def write_epublibrary(DiD, articleId, title, questions, notes, telegram_user, textareas):
    logger.info("write_epublibrary - Document ID: {0} - Article ID: {1} - Title: {2}".format(DiD, articleId, title))
    uploadedEpubLibrary = 'userBackups/{0}.epublibrary'.format(telegram_user)

    os.makedirs("/app/userBackups/{0}".format(telegram_user), exist_ok=True)

    now = datetime.now(pytz.timezone('Europe/Madrid'))
    now_date = now.strftime("%Y-%m-%d")
    now_iso = now.isoformat("T", "seconds")
    now_utc = now.astimezone(pytz.UTC)
    now_utc_iso = now_utc.isoformat("T", "seconds").replace('+00:00', 'Z')
    schema_version = 140  # TODO: Upgrade when needed

    thumbnail_file = "extra/default_thumbnail.png"

    if os.path.isfile(uploadedEpubLibrary):
        logger.info("Archivo .epublibrary encontrado")
        with zipfile.ZipFile(uploadedEpubLibrary, 'r') as zip_ref:
            files = zip_ref.namelist()
            zip_ref.extractall("userBackups/{0}/".format(telegram_user))

        uploadedDb = "userBackups/{0}/{1}".format(telegram_user, [zipname for zipname in files if zipname.endswith(".db")][0])
        manifestUser = "userBackups/{0}/manifest.json".format(telegram_user)

        connection = sqlite3.connect(uploadedDb)
        cursor = connection.cursor()
        cursor.execute("SELECT LocationId FROM Location WHERE DiD=?", (DiD,))
        locationId = cursor.fetchone()
        if locationId:
            locationId = locationId[0]
        else:
            cursor.execute("SELECT max(LocationId) FROM Location")
            max_location_id = cursor.fetchone()[0]
            locationId = max_location_id + 1 if max_location_id else 1
            cursor.execute("""INSERT INTO Location (LocationId, DiD, IssueTagNumber, sym, Type)
                VALUES (?, ?, ?, "w", 0);""", (locationId, DiD, articleId))

        for i in notes:
            cursor.execute("""INSERT INTO InputField ('LocationId', 'TextTag', 'Value') VALUES (?, ?, ?)""",
                           (locationId, textareas[i].get("id"), notes[i].replace("'", '"')))

        cursor.execute("UPDATE LastModified SET LastModified = ?", (now_iso,))

        connection.commit()
        connection.close()

        # Calculate hash and last modified date
        hash_digest = calculate_user_data_hash(uploadedDb)
        last_modified_date = get_last_modified_date(uploadedDb)

        # Create manifest data
        manifest_data = {
            "type": 0,
            "name": f"askepub-backup_{now_date}",
            "userDataBackup": {
                "deviceName": "askepub",
                "hash": hash_digest,
                "lastModifiedDate": last_modified_date,
                "databaseName": "userData.db",
                "schemaVersion": schema_version
            },
            "version": 1,
            "creationDate": now.isoformat()
        }

        manifest_file = 'userBackups/{0}/manifest.json'.format(telegram_user)
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, ensure_ascii=False)

        fileName = "userBackups/{0}/askepub-{1}-{2}.epublibrary".format(telegram_user, DiD, now_date)
        with zipfile.ZipFile(fileName, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(uploadedDb, arcname="userData.db")
            zf.write(manifest_file, arcname="manifest.json")
            zf.write(thumbnail_file, arcname="default_thumbnail.png")

        os.remove(uploadedDb)
        os.remove(manifest_file)
        os.remove(uploadedEpubLibrary)
        if os.path.exists(manifestUser):
            os.remove(manifestUser)

    else:
        dbOriginal = "dbs/userData.db.original"
        dbFromUser = "userBackups/{0}/userData.db".format(telegram_user)
        shutil.copyfile(src=dbOriginal, dst=dbFromUser)

        connection = sqlite3.connect(dbFromUser)
        cursor = connection.cursor()

        cursor.execute("""INSERT INTO Location (LocationId, DiD, IssueTagNumber, sym, Type)
            VALUES (1, ?, ?, "w", 0);""", (DiD, articleId))

        for i in notes:
            cursor.execute("""INSERT INTO InputField ('LocationId', 'TextTag', 'Value') VALUES (1, ?, ?)""",
                           (textareas[i].get("id"), notes[i].replace("'", '"')))

        cursor.execute("UPDATE LastModified SET LastModified = ?", (now_iso,))

        connection.commit()
        connection.close()

        # Calculate hash and last modified date
        hash_digest = calculate_user_data_hash(dbFromUser)
        last_modified_date = get_last_modified_date(dbFromUser)

        # Create manifest data
        manifest_data = {
            "type": 0,
            "name": f"askepub-backup_{now_date}",
            "userDataBackup": {
                "deviceName": "askepub",
                "hash": hash_digest,
                "lastModifiedDate": last_modified_date,
                "databaseName": "userData.db",
                "schemaVersion": schema_version
            },
            "version": 1,
            "creationDate": now.isoformat()
        }

        manifest_file = 'userBackups/{0}/manifest.json'.format(telegram_user)
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest_data, f, ensure_ascii=False)

        fileName = "userBackups/{0}/askepub-{1}-{2}.epublibrary".format(telegram_user, DiD, now_date)
        with zipfile.ZipFile(fileName, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(dbFromUser, arcname="userData.db")
            zf.write(manifest_file, arcname="manifest.json")
            zf.write(thumbnail_file, arcname="default_thumbnail.png")

        os.remove(dbFromUser)
        os.remove(manifest_file)

    return fileName

########################
### WRITE DOCX AND PDF #
########################

def write_docx_pdf(DiD, title, questions, notes, telegram_user):
    now_date = datetime.now(pytz.timezone('Europe/Madrid')).strftime("%Y-%m-%d")
    document = Document()

    bold_style = document.styles.add_style('Bold List Number', WD_STYLE_TYPE.PARAGRAPH)
    bold_style.font.bold = True

    document.add_heading(title, 0)

    for i in range(len(questions)):
        p = document.add_paragraph(style='Bold List Number')
        p.add_run(questions[i].text).font.size = Pt(12)
        document.add_paragraph(notes[i])

    fileNameDoc = "userBackups/{0}/askepub-{1}-{2}.docx".format(telegram_user, DiD, now_date)
    document.save(fileNameDoc)

    fileNamePDF = "userBackups/{0}/askepub-{1}-{2}.pdf".format(telegram_user, DiD, now_date)
    cmd_str = "xvfb-run abiword --to=pdf --to-name='{0}' '{1}'".format(fileNamePDF, fileNameDoc)
    subprocess.run(cmd_str, shell=True)
    return fileNameDoc, fileNamePDF

################
### MAIN CODE ##
################

def main(url, telegram_user, qs_user, language):
    # Set up translation function
    domain = "askepub"
    locale_dir = os.path.join(os.path.dirname(__file__), '../locales')
    translation = gettext.translation(domain, localedir=locale_dir, languages=[language], fallback=True)
    trans = translation.gettext

    title, base_text, summary, questions, DiD, articleId, q_map, textareas = epub_extract_html(url, get_all=True)
    notes = epub_query_openai(title, base_text, summary, q_map, qs_user, trans)
    filenameepub = write_epublibrary(DiD, articleId, title, questions, notes, telegram_user, textareas)
    filenamedoc, filenamepdf = write_docx_pdf(DiD, title, questions, notes, telegram_user)
    return filenameepub, filenamedoc, filenamepdf

if __name__ == "__main__":
    # Example usage
    url = "https://www.place.holder/test/"
    telegram_user = "user_id"  # Replace with actual Telegram user ID
    qs_user = [
        "Una ilustración o ejemplo para explicar algún punto principal",
        "Una experiencia en concreto, aportando referencias exactas de place.holder, que esté muy relacionada",
        "Una explicación sobre uno de las referencias que aparezcan, que aplique."
    ]
    language = "es"  # Replace with the desired language code, e.g., "en" for English
    main(url, telegram_user, qs_user, language)