# Pinned by digest so builds are reproducible; Dependabot keeps it current
FROM python:3.11-slim@sha256:bab1b7ef4b450c81002278d035eff85ebe394ae94df904f7a3ba14f7e16e487b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # No display in a container: render off-screen
    MPLBACKEND=Agg \
    # A writable config dir for any user ID, including one passed with --user
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# Every dependency ships a prebuilt wheel, so no compiler is needed.
# requirements.txt carries hashes, so pip refuses anything unexpected.
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

# Run as an unprivileged user. The directories it writes are open to any user
# ID, so `--user "$(id -u):$(id -g)"` works too, even on a cache volume that
# another user ID wrote to: every cache file is replaced by renaming a new
# file over it, which needs only write access to the directory. A new cache
# volume copies these permissions when Docker creates it.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p outputs .cache \
    && chown app:app outputs .cache \
    && chmod 0777 outputs .cache

COPY graphs.py .
COPY spacex_graphs/ ./spacex_graphs/

USER app

ENTRYPOINT ["python3", "graphs.py"]
CMD ["--output"]
