#!/usr/bin/env bash
# Run from the repo root:
#   bash cvat_worker/setup_cvat.sh
set -e

# Verify we're at the repo root
if [ ! -f "docker-compose.yaml" ]; then
    echo "Error: run this script from the repo root"
    exit 1
fi

# Load credentials from .env
if [ ! -f ".env" ]; then
    echo "Error: .env not found. Copy .example_env and fill in CVAT_USERNAME and CVAT_PASSWORD."
    exit 1
fi
set -a; source .env; set +a

if [ -z "${CVAT_EMAIL}" ] || [ -z "${CVAT_PASSWORD}" ]; then
    echo "Error: CVAT_EMAIL and CVAT_PASSWORD must be set in .env"
    exit 1
fi

CVAT_USERNAME="${CVAT_EMAIL%%@*}"

# Ensure cvat_share/ exists for the shared volume
if [ ! -d "cvat_share" ]; then
    echo "Creating cvat_share/ directory..."
    mkdir -p cvat_share
fi

# Clone CVAT once
if [ ! -d "cvat" ]; then
    echo "Cloning CVAT..."
    git clone https://github.com/cvat-ai/cvat
fi

# Create the external Docker network that connects CVAT to cvat_worker
docker network create cvat_network 2>/dev/null \
    && echo "Created cvat_network" \
    || echo "cvat_network already exists, skipping"

# Start CVAT — PWD is exported so docker-compose.cvat.yml can resolve ${PWD}/cvat_share
export PWD="$(pwd)"
docker compose \
    -f cvat/docker-compose.yml \
    -f docker-compose.cvat.yml \
    up -d

# Wait for Django to be ready (checks DB connection too)
echo "Waiting for CVAT to be ready..."
until [ "$(docker exec cvat_server python manage.py showmigrations --plan 2>/dev/null | grep -c '^\[ \]')" = "0" ]; do
    printf "."
    sleep 3
done

# Create superuser using credentials from .env
# --no-input reads DJANGO_SUPERUSER_* env vars instead of prompting
# Silently skips if the user already exists
echo "Creating CVAT superuser..."
docker exec \
    -e DJANGO_SUPERUSER_USERNAME="${CVAT_USERNAME}" \
    -e DJANGO_SUPERUSER_EMAIL="${CVAT_EMAIL}" \
    -e DJANGO_SUPERUSER_PASSWORD="${CVAT_PASSWORD}" \
    cvat_server \
    python manage.py createsuperuser --no-input 2>/dev/null \
    && echo "Superuser created." \
    || echo "Superuser already exists, skipping."

echo ""
echo "CVAT is running at http://localhost:8080"
echo "Login: ${CVAT_USERNAME} / (password from .env)"
