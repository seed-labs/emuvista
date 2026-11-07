ARG BASE_IMAGE=komunitin/komunitin-app@sha256:399b77d967aeaf8e0d7f4de8134f4fc6c52fdcdf033b2d4a9d6a2cd4d3472255
FROM node:24@sha256:e7add2a490bb17d97b485b8641bd88455fff7839ade0f5eba493c3508124d413 AS build
ARG SOURCE_REVISION=124a87b639c37952dc9a029fc7056e523a10de5b
WORKDIR /app
ADD https://codeload.github.com/community-exchange-network/komunitin/tar.gz/${SOURCE_REVISION} /tmp/source.tar.gz
RUN tar -xzf /tmp/source.tar.gz --strip-components=2 -C /app komunitin-${SOURCE_REVISION}/app \
    && rm /tmp/source.tar.gz
RUN corepack enable && corepack prepare pnpm@10.26.1 --activate \
    && pnpm install --frozen-lockfile \
    && pnpm --dir src-pwa install --frozen-lockfile \
    && pnpm --dir src-ssg install --frozen-lockfile
COPY src/ src/
COPY public/config.template.js public/config.template.js
RUN mkdir -p /certs && openssl req -x509 -newkey rsa:2048 -noenc -days 365 \
    -keyout /certs/localhost-key.pem -out /certs/localhost.pem -subj /CN=localhost
RUN pnpm run build
FROM ${BASE_IMAGE}
COPY --from=build /app/dist/ssg /usr/share/nginx/html
