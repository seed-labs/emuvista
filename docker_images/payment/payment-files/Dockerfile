FROM node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54

RUN npm install --prefix /s3 --omit=dev --no-audit --no-fund --save-exact s3rver@3.7.1

ENTRYPOINT ["node", "/s3/node_modules/s3rver/bin/s3rver.js"]
CMD ["-d", "/data", "-a", "0.0.0.0", "-p", "9090"]
