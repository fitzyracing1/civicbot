# civicbot hosted: one image, two processes (web + worker). See docs/DEPLOY.md.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY civicbot ./civicbot
RUN pip install ".[web,postgres]" \
 && useradd --create-home --uid 10001 civicbot \
 && mkdir -p /data && chown civicbot /data
USER civicbot
ENV CIVICBOT_DATA_DIR=/data DATABASE_URL=sqlite:////data/civicbot.db HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz',timeout=4)" || exit 1
CMD ["python", "-m", "civicbot.web"]
