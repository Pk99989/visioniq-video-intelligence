FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json ./
# Slow-network resilience: npm's default fetch timeout is too short on a
# slow connection (it failed after ~23 min on thenify-3.3.1.tgz).
# npm ci is deterministic from the lockfile; retries + a 10 min timeout
# let it survive transient FETCH_ERRORs instead of failing the build.
RUN npm ci --fetch-timeout=600000 --fetch-retries=5 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]
