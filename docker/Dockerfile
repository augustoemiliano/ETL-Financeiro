FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic alembic
COPY alembic.ini alembic.ini

COPY scripts scripts
COPY docker docker
COPY app app
COPY data data
COPY main.py main.py
COPY pyproject.toml pyproject.toml
COPY README.md README.md

RUN chmod +x docker/backend-entry.sh

EXPOSE 8000

ENTRYPOINT ["bash", "docker/backend-entry.sh"]
CMD ["api"]
