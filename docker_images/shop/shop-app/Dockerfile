FROM mysql:8.0-debian AS database
RUN mkdir -p /mysql-runtime/usr/sbin /mysql-runtime/usr/lib/x86_64-linux-gnu /mysql-runtime/usr/share \
    && cp /usr/sbin/mysqld /mysql-runtime/usr/sbin/ \
    && cp -a /usr/lib/mysql /mysql-runtime/usr/lib/ \
    && cp -a /usr/share/mysql* /mysql-runtime/usr/share/ \
    && cp -a /usr/lib/x86_64-linux-gnu/libaio.so.1* /mysql-runtime/usr/lib/x86_64-linux-gnu/

FROM wordpress:7.1.4-php8.3-apache@sha256:8b64037bb2a3bdc41bebccb165f20ad5e4c786b684ae4a2bd5981f98aa1eb107
COPY --from=database /mysql-runtime/ /
RUN export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y --no-install-recommends \
        libmecab2 libnuma1 libtirpc3 libssl3 libstdc++6 libzstd1 liblz4-1 \
        iproute2 iputils-ping python3 tini zsh nano vim-nox mtr-tiny tcpdump termshark dnsutils jq ipcalc netcat-openbsd \
    && ! ldd /usr/sbin/mysqld | grep 'not found' \
    && groupadd --system mysql && useradd --system --gid mysql --home-dir /var/lib/mysql mysql \
    && rm -rf /var/lib/apt/lists/*
ADD https://downloads.wordpress.org/plugin/woocommerce.11.3.0.zip /tmp/woocommerce.zip
ADD https://downloads.wordpress.org/plugin/dc-woocommerce-multi-vendor.5.0.22.zip /tmp/multivendor.zip
ADD https://downloads.wordpress.org/theme/storefront.4.6.2.zip /tmp/storefront.zip
ADD https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar /usr/local/bin/wp
RUN printf '%s\n' 'd9eb1e46df8309eb37b6f7f3fba51480f2a9a00e7feb10b1487592fde39accc6  /tmp/woocommerce.zip' '1dcc921e31e76dfc61d75a3bf26593f4f9d105a9ea35947965b5229226bdeb2b  /tmp/multivendor.zip' '163b5bf217dad76a823432d8c01598ab3dc3f15cbdd69067b98f5a6ddf05c1c4  /tmp/storefront.zip' 'ce34ddd838f7351d6759068d09793f26755463b4a4610a5a5c0a97b68220d85c  /usr/local/bin/wp' | sha256sum --check -
RUN php -r 'foreach (["woocommerce", "multivendor", "storefront"] as $name) { $zip = new ZipArchive; $zip->open("/tmp/$name.zip"); $zip->extractTo("/usr/src/wordpress/wp-content/" . ($name === "storefront" ? "themes" : "plugins")); $zip->close(); }' \
    && rm /tmp/*.zip && chmod 755 /usr/local/bin/wp
COPY src/ /opt/emuvista-shop/
RUN mkdir -p /usr/src/wordpress/wp-content/mu-plugins \
    && cp /opt/emuvista-shop/loader.php /usr/src/wordpress/wp-content/mu-plugins/emuvista.php \
    && cp /opt/emuvista-shop/htaccess /usr/src/wordpress/.htaccess

WORKDIR /
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["/bin/bash"]
