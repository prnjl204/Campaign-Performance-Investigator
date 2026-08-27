#!/bin/sh
# Entrypoint: ensures the database exists before the app starts.
#
# WHY THIS CHECK MATTERS: a container should be able to start from a
# completely empty /data volume (e.g. on a fresh deploy, or after someone
# clears the volume) and bootstrap itself -- it shouldn't silently depend
# on a database file that happened to already exist on your laptop. This
# is a small thing, but it's exactly the kind of "does this actually work
# from a clean slate" check a production deployment needs and a local dev
# environment lets you skip without noticing.
set -e

if [ ! -f "data/campaigns.db" ]; then
    echo "No database found -- generating seed data..."
    python src/generate_seed_data.py
else
    echo "Existing database found at data/campaigns.db -- skipping seed generation."
fi

exec streamlit run src/dashboard.py \
    --server.address=0.0.0.0 \
    --server.port=8501 \
    --server.headless=true
