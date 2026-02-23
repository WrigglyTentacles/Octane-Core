# Octane-Core - Discord bot for Rocket League tournaments
# Stage 1: Build frontend
FROM node:20-alpine AS frontend
WORKDIR /app
COPY web/frontend/package*.json ./
RUN npm install
COPY web/frontend/ ./
RUN npm run build

# Stage 2: Python app
FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py run.py ./
COPY bot/ ./bot/
COPY web/ ./web/

# Copy built frontend from stage 1
COPY --from=frontend /app/dist ./web/frontend/dist

# Default: run the Discord bot
# Pass DISCORD_TOKEN via -e or --env-file
CMD ["python", "run.py"]
