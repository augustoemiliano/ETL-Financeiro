FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# Somente dependências de runtime (ferramentas de teste/lint ficam fora da imagem).
COPY requirements.txt .
RUN pip install -r requirements.txt

# Usuário sem privilégios. UID 1000 casa com o usuário padrão da maioria dos hosts Linux,
# permitindo escrever nos bind mounts ./logs e ./reports (sobrescreva com --build-arg).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --no-create-home --shell /usr/sbin/nologin app

COPY alembic alembic
COPY alembic.ini alembic.ini
COPY scripts scripts
COPY docker docker
COPY app app
COPY data data
COPY main.py main.py
COPY pyproject.toml pyproject.toml

# Remove CR caso o script tenha vindo de um checkout Windows sem .gitattributes.
RUN sed -i 's/\r$//' docker/backend-entry.sh \
    && chmod +x docker/backend-entry.sh \
    && mkdir -p logs reports \
    && chown -R app:app logs reports

USER app

EXPOSE 8000

ENTRYPOINT ["bash", "docker/backend-entry.sh"]
CMD ["api"]
