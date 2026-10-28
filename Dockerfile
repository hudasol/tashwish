# Read only Tashwish release API.
#
#   docker build -t tashwish-api .
#   docker run --rm -p 8000:8000 tashwish-api
#
# The release directory is copied into the image. To serve a different release, mount it and set the variable:
#   docker run --rm -p 8000:8000 -v /path/to/release:/data/release:ro -e TASHWISH_RELEASE_DIR=/data/release tashwish-api
# No secrets are needed or stored in the image.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin tashwish

WORKDIR /app

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install ".[api]"

COPY release ./release

ENV TASHWISH_RELEASE_DIR=/app/release \
    TASHWISH_DUCKDB_THREADS=1 \
    TASHWISH_DUCKDB_MEMORY=256MB

USER tashwish
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["uvicorn", "tashwish.api.app:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
