#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export PATH=/opt/ruby/bin:/usr/local/bin:$PATH

# 固定版本，使用 SeedEmu 基础镜像 / Pinned sources inside the SeedEmu base image.
MASTODON_VERSION=4.7.3
RUBY_VERSION=4.0.6
NODE_VERSION=24.19.0
curl --retry 3 -fsSL "https://cache.ruby-lang.org/pub/ruby/4.0/ruby-${RUBY_VERSION}.tar.gz" -o /tmp/ruby.tar.gz
mkdir -p /tmp/ruby-build
tar -xzf /tmp/ruby.tar.gz -C /tmp/ruby-build --strip-components=1
cd /tmp/ruby-build
./configure --prefix=/opt/ruby --disable-install-doc --disable-yjit
make -j2
make install
case "$(uname -m)" in
    x86_64) node_arch=x64 ;;
    aarch64) node_arch=arm64 ;;
    *) echo 'Unsupported architecture' >&2; exit 1 ;;
esac
curl --retry 3 -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.xz" -o /tmp/node.tar.xz
tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1
npm install --global corepack@0.34.6
corepack enable

useradd --system --create-home --home-dir /opt/mastodon --shell /bin/bash mastodon
curl --retry 3 -fsSL "https://github.com/mastodon/mastodon/archive/refs/tags/v${MASTODON_VERSION}.tar.gz" -o /tmp/mastodon.tar.gz
tar -xzf /tmp/mastodon.tar.gz -C /opt/mastodon --strip-components=1
cd /opt/mastodon
gem install bundler -v 4.0.18 --no-document
bundle config set --local without 'development test'
bundle config set --local frozen true
bundle install --jobs 2
yarn install --immutable
RAILS_ENV=production NODE_ENV=production SECRET_KEY_BASE_DUMMY=1 bundle exec rails assets:precompile
mkdir -p /var/lib/mastodon /opt/mastodon/public/system
chown -R mastodon:mastodon /opt/mastodon /var/lib/mastodon
chmod 700 /var/lib/mastodon
chmod 755 /opt/mastodon-service/run.sh
rm -f /etc/nginx/sites-enabled/default
rm -rf /tmp/ruby-build /tmp/ruby.tar.gz /tmp/node.tar.xz /tmp/mastodon.tar.gz
