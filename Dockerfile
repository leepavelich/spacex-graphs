# Pinned by digest so builds are reproducible; Dependabot keeps it current
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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

# Run as an unprivileged user. Any UID can write to fresh output and cache
# directories, so `--user "$(id -u):$(id -g)"` works too. The sticky bit keeps
# other non-owner UIDs from deleting or replacing files in these directories.
# A new cache volume inherits these permissions. Reuse it with the same UID.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p outputs .cache \
    && chown app:app outputs .cache \
    && chmod 1777 outputs .cache

COPY graphs.py .
COPY spacex_graphs/ ./spacex_graphs/

USER 1000

ENTRYPOINT ["python3", "graphs.py"]
CMD ["--output"]
