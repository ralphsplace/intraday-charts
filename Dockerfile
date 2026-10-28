FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/New_York DATA_DIR=/app/data HOME=/tmp
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tools ./tools
COPY config.json start.sh LICENSE NOTICE ./
RUN chmod 0755 start.sh && chmod -R a+rX,go-w /app

EXPOSE 8050
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8050/api/meta')" || exit 1
# start.sh hands the data folder to the app user (uid 1000 unless APP_UID is set) and then drops root
ENTRYPOINT ["./start.sh"]
