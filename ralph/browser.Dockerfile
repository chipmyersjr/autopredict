FROM node:24-bookworm-slim AS node
FROM autopredict-backend:dev
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s /opt/venv /app/backend/.venv
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci && npx playwright install --with-deps chromium
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
