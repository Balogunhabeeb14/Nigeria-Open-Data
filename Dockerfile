# ==========================================
# Production Dockerfile: Unified Web Application
# ==========================================

# Stage 1: Build the Next.js Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY src/ ./src
COPY public/ ./public
COPY next.config.ts tsconfig.json eslint.config.mjs postcss.config.mjs ./
# We set dummy env vars for build time if Next.js requires them
ENV NEXT_PUBLIC_CKAN_URL=http://localhost:5000
RUN npm run build

# Stage 2: Final Runtime Environment
FROM python:3.11-slim
LABEL maintainer="Naija Open Data <support@nigeriaopendata.gov.ng>"
LABEL description="Nigeria Open Data — Unified App Portal"

# Install System Dependencies (Postgres client, etc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    gcc \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js from the frontend-builder stage so we don't have to download it via slow apt mirrors!
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/
COPY --from=frontend-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /app

# Create log directories for supervisor
RUN mkdir -p /var/log/supervisor

# Copy Python Requirements & Install
COPY pipeline/requirements.txt ./pipeline/requirements.txt
RUN pip install --retries 10 --timeout 100 --no-cache-dir -r pipeline/requirements.txt

# Copy Built Standalone Frontend from Stage 1
COPY --from=frontend-builder /app/.next/standalone ./
COPY --from=frontend-builder /app/.next/static ./.next/static
COPY --from=frontend-builder /app/public ./public

# Copy application source code (FastAPI/pipeline backend)
COPY pipeline/ ./pipeline/

# Set environment
ENV PYTHONPATH="/app"
ENV PREFECT_API_URL="http://prefect-server:4200/api"
ENV LANDING_ROOT="/app/data/raw"

# Expose ports for Next.js (3000) and FastAPI (8000)
EXPOSE 3000 8000

# Copy supervisord configuration
COPY pipeline/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy and set up the entrypoint script
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Run the database-waiting and migration entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
