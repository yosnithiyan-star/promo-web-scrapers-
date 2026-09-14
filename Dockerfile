# Umbrella Actor for promo-web-scrapers
FROM python:3.12-slim

WORKDIR /app

# Debian slim needs git for `git describe` in some Apify tooling; install quietly.
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt apify

# Copy the whole project (scrapers + shared + actor).
COPY . .

# Run the Actor wrapper.
CMD ["python", "-m", "actor.main"]
