FROM quay.io/keycloak/keycloak:26.8.0 AS upstream
FROM handsonsecurity/seedemu-base:2.0

COPY --from=upstream /opt/keycloak /opt/keycloak
COPY --from=upstream /usr/lib/jvm /usr/lib/jvm
COPY --from=upstream /etc/java /etc/java
COPY --from=upstream /etc/crypto-policies /etc/crypto-policies
COPY --from=upstream /etc/pki /etc/pki
COPY --from=upstream /usr/share/javazi-1.8 /usr/share/javazi-1.8
RUN ln -s /usr/lib/jvm/java-21-openjdk-* /opt/java \
    && apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/opt/java
ENV PATH="/opt/java/bin:${PATH}"
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
