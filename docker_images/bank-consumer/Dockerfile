ARG BASE_IMAGE=eclipse-temurin:25-jre@sha256:ecdc0adb37bde1a281c4d245a3cd535004b1fc8322d560f5b09463b248c81df0
FROM eclipse-temurin:25-jdk@sha256:83f4a7fc27df94dcc7b8de04d14cbbba8da14406f921e966969c3b09000aa507 AS build
ARG SOURCE_REVISION=ce2621c0fe76c28f58de5cf5627c49f20f5980ca
WORKDIR /workspace
ADD https://codeload.github.com/apache/fineract-consumer-facing/tar.gz/${SOURCE_REVISION} /tmp/source.tar.gz
RUN tar -xzf /tmp/source.tar.gz --strip-components=2 -C /workspace fineract-consumer-facing-${SOURCE_REVISION}/consumer \
    && rm /tmp/source.tar.gz
COPY src/ src/
RUN --mount=type=cache,target=/root/.gradle chmod +x gradlew && ./gradlew --no-daemon bootJar
FROM ${BASE_IMAGE}
WORKDIR /app
COPY --from=build /workspace/build/libs/*.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=60", "-XX:+ExitOnOutOfMemoryError", "-jar", "/app/app.jar"]
