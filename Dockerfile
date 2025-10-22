# Build stage: Install dependencies that require compilation
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Runtime stage: Create minimal final image
FROM python:3.11-slim

WORKDIR /app

# Copy only the installed Python packages from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy application code
COPY graphs.py .

# Create outputs directory
RUN mkdir -p outputs

# Set the entrypoint to the Python script
ENTRYPOINT ["python3", "graphs.py"]

# Default: no arguments (displays graphs)
# Override with --output to save as SVG files
CMD []
