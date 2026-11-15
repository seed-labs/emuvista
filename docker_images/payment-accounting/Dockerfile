# Extend the published upstream image, which includes source and dependencies.
ARG BASE_IMAGE=komunitin/komunitin-accounting@sha256:89e8a42cba503515a87b0f1e7a714123fbef093e3ec4d27684b627cfc227c4d5
FROM ${BASE_IMAGE}
WORKDIR /app
COPY src/bank/ src/bank/
COPY src/server/app.ts src/server/app.ts
COPY src/controller/external-resource-controller.ts src/controller/external-resource-controller.ts
COPY src/utils/resource-url.ts src/utils/resource-url.ts
RUN node node_modules/typescript/bin/tsc --noEmit \
    && node node_modules/unbuild/dist/cli.mjs
CMD ["node", "dist/index.mjs"]
