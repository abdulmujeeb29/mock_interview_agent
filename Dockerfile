# Single deployable: builds the Next.js frontend AND runs the LiveKit agent
# worker in ONE container. The frontend is the web process that binds $PORT
# (so a platform health-check sees a healthy service); the agent runs alongside
# it and only needs outbound network (it dials out to LiveKit, no port of its own).
#
# ThalesOps / Nixpacks-style platforms use this Dockerfile when it's present,
# instead of auto-detecting. Provide the env vars from .env.example at runtime.

FROM python:3.12-slim-bookworm

# Node 20 (for the Next.js frontend) + pnpm via corepack.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && corepack enable

WORKDIR /app

# --- Python deps (own layer so it caches unless requirements change) ---
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- Frontend deps (own layer, cached on the lockfile) ---
COPY web/package.json web/pnpm-lock.yaml ./web/
RUN cd web && pnpm install --frozen-lockfile

# --- Frontend source + build, from web/ ONLY ---
# Copying just web/ here (before the Python source) means a change to the Python
# agent does NOT invalidate this layer, so `next build` is skipped on Python-only
# redeploys. node_modules/.next are excluded via .dockerignore, so this copy keeps
# the installed deps above and doesn't drag in local build output.
COPY web/ ./web/
RUN cd web && pnpm build

# --- Python / agent source LAST ---
# Changes here (the part we iterate on most) bust only this cheap copy layer, not
# the frontend build above.
COPY . .

ENV PORT=3000
EXPOSE 3000

# Supervise both processes; if either dies, the container exits so the platform restarts it.
CMD ["./docker-start.sh"]
