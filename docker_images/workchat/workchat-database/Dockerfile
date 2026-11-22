FROM zulip/zulip-postgresql:14 AS upstream
FROM postgres:17-bookworm
COPY --from=upstream /docker-entrypoint-initdb.d/zulip-create-db.sql /docker-entrypoint-initdb.d/10-company-database.sql
COPY --from=upstream /usr/local/share/postgresql/tsearch_data/en_us.affix /usr/share/postgresql/17/tsearch_data/en_us.affix
COPY --from=upstream /usr/local/share/postgresql/tsearch_data/en_us.dict /usr/share/postgresql/17/tsearch_data/en_us.dict
