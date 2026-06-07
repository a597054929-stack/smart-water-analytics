FROM python:3.12-slim

WORKDIR /app

# System deps:
# - build-essential: pandera + scipy may need a C compiler for some wheels.
#   (Most have prebuilt wheels, but a build fallback is cheap insurance.)
# - curl: needed by the HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate mock data inside the image so `docker run` works out of the
# box. The output dir is gitignored — the image bakes a fresh copy in.
RUN python scripts/mock_data_generator.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Liveness probe — Docker / Kubernetes polls this to decide if the
# container is healthy. The endpoint is served by agent/server.py and
# returns {"status": "ok", ...}; a non-200 marks the container unhealthy
# and triggers a restart.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

# Default: run the AI agent service. Override with `command:` to run
# the data pipeline, tests, etc.
CMD ["python", "agent/server.py"]
