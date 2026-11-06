# Phase 12: multi-stage build — the runner image has no dev
# dependencies and no source beyond the built app, and it runs as the
# built-in non-root `node` user.
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Slow-network resilience: npm's default fetch timeout is too short on a
# slow connection (it failed after ~23 min on thenify-3.3.1.tgz).
# npm ci is deterministic from the lockfile; retries + a 10 min timeout
# let it survive transient FETCH_ERRORs instead of failing the build.
RUN npm ci --fetch-timeout=600000 --fetch-retries=5 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_API_URL is inlined at build time: the compose files set
# it (http://localhost:8000 for the laptop/full stack). A build made
# without it points at the wrong API port — see the Phase 11 e2e note.
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/public ./public
# Phase 12: the runner owns nothing writable except the Next.js cache.
RUN mkdir -p .next/cache && chown -R node:node /app
USER node
EXPOSE 3000
# Phase 12: healthy when the login page answers (alpine has wget).
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD wget -q -O /dev/null http://localhost:3000/login || exit 1
CMD ["node", "node_modules/.bin/next", "start"]
