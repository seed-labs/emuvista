FROM postgres:16-bookworm@sha256:a49f7438ba03589f9b1ca062f2da82e899b48ea1dc50d2449fa09a70be83ebca

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-16-postgis-3 postgresql-16-postgis-3-scripts postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

COPY init-app-db.sh /usr/local/bin/init-app-db.sh
RUN chmod +x /usr/local/bin/init-app-db.sh
