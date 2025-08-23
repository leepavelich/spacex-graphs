FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required for matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY graphs.py .

# Create outputs directory
RUN mkdir -p outputs

# Set the entrypoint to the Python script
ENTRYPOINT ["python3", "graphs.py"]

# Default: no arguments (displays graphs)
# Override with --output to save as SVG files
CMD []
