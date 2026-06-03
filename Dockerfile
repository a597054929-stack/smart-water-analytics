FROM python:3.12-slim

WORKDIR /app

# System deps: pandera + scipy need a C compiler for some wheels.
# (Most have prebuilt wheels, but a build fallback is cheap insurance.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Generate mock data inside the image so `docker run` works out of the
# box. The output dir is gitignored — the image bakes a fresh copy in.
RUN python scripts/mock_data_generator.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Default: run the AI agent service. Override with `command:` to run
# the data pipeline, tests, etc.
CMD ["python", "agent/server.py"]
