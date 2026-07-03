FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Metadata
LABEL maintainer="ScoutAPI"
LABEL description="ScoutAPI — Lead Scraping API"

# Env
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# On installe les deps Python en root puis on bascule vers l’utilisateur Playwright
USER root
WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Code
COPY . .

# Logs dir + permissions pour l'utilisateur 'pwuser' fourni par l'image Playwright
RUN mkdir -p logs && chown -R pwuser:pwuser /app

# Utilisateur non-root recommandé par Playwright
USER pwuser

EXPOSE 8000

# Healthcheck sans dépendre de curl/wget
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
r=urllib.request.urlopen('http://localhost:8000/v1/health', timeout=5); \
sys.exit(0 if r.status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "warning", "--no-access-log"]
