# Synthetos web SPA — multi-stage build then nginx serve.
#
# Build: docker build -t synthetos-web:latest -f apps/web/Dockerfile apps/web

# ---------- build ----------
FROM node:22-alpine AS build

WORKDIR /app

# Install deps first; isolating this layer keeps the cache warm across
# source-only changes.
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the web source. The TanStack Router plugin will
# regenerate src/routeTree.gen.ts during `npm run build`.
COPY index.html tsconfig.json vite.config.ts postcss.config.js eslint.config.js ./
COPY src ./src

RUN npm run build

# ---------- serve ----------
FROM nginx:alpine AS serve

# Drop the stock default site; ours proxies /api to the api service.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
