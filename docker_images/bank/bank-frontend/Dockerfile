ARG BASE_IMAGE=nginx:stable-alpine
FROM eclipse-temurin:25-jdk@sha256:83f4a7fc27df94dcc7b8de04d14cbbba8da14406f921e966969c3b09000aa507 AS client
ADD https://repo.maven.apache.org/maven2/org/openapitools/openapi-generator-cli/7.14.0/openapi-generator-cli-7.14.0.jar /generator.jar
COPY openapi.json /openapi.json
RUN java -jar /generator.jar generate -i /openapi.json -g typescript-angular -o /client \
    --additional-properties=ngVersion=22.0.0,providedInRoot=true,withInterfaces=true
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS build
ARG SOURCE_REVISION=ce2621c0fe76c28f58de5cf5627c49f20f5980ca
WORKDIR /app
ADD https://codeload.github.com/apache/fineract-consumer-facing/tar.gz/${SOURCE_REVISION} /tmp/source.tar.gz
RUN tar -xzf /tmp/source.tar.gz --strip-components=2 -C /app fineract-consumer-facing-${SOURCE_REVISION}/frontend \
    && rm /tmp/source.tar.gz
RUN npm ci
COPY --from=client /client src/openapi-client
COPY src/ src/
COPY public/ public/
RUN npm run build -- --configuration production
FROM ${BASE_IMAGE}
COPY --from=build /app/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
