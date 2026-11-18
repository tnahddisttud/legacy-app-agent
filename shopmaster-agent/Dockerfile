# The agent's browser UI (Streamlit). Same code, same locked dependencies (uv.lock) on every machine.
FROM python:3.12.10-slim

# uv, pinned to the version the lockfile was made with
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Do not run as root. The user owns /app, so run_agent.py can write its agent_state.db there.
# (Create the user BEFORE copying files: a later `chown -R` would store every file a second time.)
RUN useradd --create-home --uid 1000 app && mkdir /app && chown app:app /app
USER app
WORKDIR /app

# 1. Dependencies first: this layer is rebuilt only when pyproject.toml or uv.lock change.
COPY --chown=app:app pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

# 2. Then the code (see .dockerignore: no .env, no tests, no local venv)
COPY --chown=app:app . .

EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2)"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
