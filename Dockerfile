FROM python:3.9-alpine

WORKDIR /app

RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    openssl-dev \
    make \
    freetype-dev \
    libpng-dev \
    g++

COPY requirements.txt .

RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p outputs

ENTRYPOINT ["python3", "graphs.py"]

# Default command-line arguments (can be overridden)
# CMD ["--output"]
