FROM python:3.14-slim-bookworm

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    locales-all abiword xvfb sqlite3 libxml2-dev libxslt-dev gcc \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p userBackups dbs

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["python", "-u", "src/bot.py"]
