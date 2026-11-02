# Web front end. Build context: the repo root (the theme reads docs/design/tokens.json).
# 1) node builds web/dist  2) nginx (unprivileged) serves it.
FROM node:24-alpine AS build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY docs/design/tokens.json docs/design/error-messages.json /app/docs/design/
COPY web/ ./
ARG VITE_APP_ENV=""
ENV VITE_APP_ENV=$VITE_APP_ENV
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY web/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY web/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/web/dist /usr/share/nginx/html
EXPOSE 8080
