FROM python:3.11-slim

# Install required packages
RUN apt-get update && \
    apt-get install -y ffmpeg bash coreutils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make entrypoint script executable
RUN chmod +x entrypoint.sh

# Run the application
ENTRYPOINT ["./entrypoint.sh"]
