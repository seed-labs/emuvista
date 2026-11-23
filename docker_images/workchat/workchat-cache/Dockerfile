FROM handsonsecurity/seedemu-base:2.0
RUN apt-get update && apt-get install -y --no-install-recommends memcached sasl2-bin libsasl2-modules && rm -rf /var/lib/apt/lists/*
COPY cache-start /usr/local/bin/cache-start
RUN chmod +x /usr/local/bin/cache-start
CMD ["/usr/local/bin/cache-start"]
