FROM komunitin/komunitin-social@sha256:e1fd74796abb524faf054d3124ee239399d024174ba07e5995192ca4e3f5b0ba AS social
FROM node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54

ARG SOURCE_REVISION=124a87b639c37952dc9a029fc7056e523a10de5b
WORKDIR /app
COPY --from=social /app /app/social
ADD https://codeload.github.com/community-exchange-network/komunitin/tar.gz/${SOURCE_REVISION} /tmp/source.tar.gz
RUN tar -xzf /tmp/source.tar.gz --strip-components=1 -C /app \
       komunitin-${SOURCE_REVISION}/shared/cli \
       komunitin-${SOURCE_REVISION}/accounting/src/migration/format.ts \
    && rm /tmp/source.tar.gz
RUN corepack enable && corepack prepare pnpm@10.26.1 --activate \
    && pnpm --dir shared/cli install --frozen-lockfile

ENTRYPOINT ["node", "/app/shared/cli/index.ts"]
