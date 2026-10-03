# Pinned by digest so builds are reproducible; Dependabot keeps it current
FROM python:3.11-slim@sha256:bab1b7ef4b450c81002278d035eff85ebe394ae94df904f7a3ba14f7e16e487b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # No display in a container: render off-screen
    MPLBACKEND=Agg

WORKDIR /app

# Every dependency ships a prebuilt wheel, so no compiler is needed.
# requirements.txt carries hashes, so pip refuses anything unexpected.
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

# Run as an unprivileged user that owns only the directories it writes
RUN useradd --create-home --uid 1000 app \
    && mkdir -p outputs .cache \
    && chown app:app outputs .cache

COPY graphs.py .
COPY spacex_graphs/ ./spacex_graphs/

USER app

ENTRYPOINT ["python3", "graphs.py"]
CMD ["--output"]
