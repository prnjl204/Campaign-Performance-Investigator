# Using slim, not full python:3.11 -- cuts image size roughly in half by
# excluding build tools and libraries this project doesn't need at runtime.
FROM python:3.11-slim

WORKDIR /app

# Copy requirements.txt BEFORE the rest of the code, and install here as a
# separate layer. This is a deliberate Docker layer-caching optimization:
# as long as requirements.txt doesn't change, Docker reuses this layer on
# rebuilds instead of re-running pip install every time you edit a .py
# file -- meaningfully faster iteration once the project has real dependencies.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the actual application code (changes often, so it comes after
# the rarely-changing dependency layer above).
COPY src/ ./src/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# data/ is intentionally NOT baked into the image. The entrypoint script
# generates it on first run if missing -- this is what lets you mount an
# external volume at /app/data for persistence across container restarts
# (see docker-compose.yml) without ever needing to rebuild the image just
# because the underlying data changed.
RUN mkdir -p data

EXPOSE 8501

ENTRYPOINT ["./entrypoint.sh"]
