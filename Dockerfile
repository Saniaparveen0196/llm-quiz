FROM python:3.10

# Set working directory
WORKDIR /app

# Install system dependencies including XML libraries for lxml and Playwright dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libxml2-dev \
    libxslt1-dev \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libxshmfence1 \
    fonts-liberation \
    libappindicator3-1 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create user (ONLY ONCE!)
RUN useradd -m -u 1000 user

# Copy application code with user ownership
COPY --chown=user:user . .

# Switch to non-root user
USER user

# Set Playwright browser path
ENV PLAYWRIGHT_BROWSERS_PATH=/home/user/.cache/ms-playwright

# Install Chromium as user
RUN playwright install chromium

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV HOST=0.0.0.0

# Expose port
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:7860/health', timeout=5)"

# Run the application using uvicorn
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]