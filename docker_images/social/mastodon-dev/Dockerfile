# syntax=docker/dockerfile:1

# Mastodon development image for EmuVista's SocialNetworkBundle. The Mastodon
# checkout is the named build context "mastodon"; see ../compose.yml.
#
# The base image, Node.js setup and OS packages are merged from the checkout's
# .devcontainer/Dockerfile. The devcontainer installs gems and JavaScript
# packages after it starts (bin/setup). Emulated hosts cannot reach public
# package registries, so this image installs them, and builds the development
# frontend assets, at build time instead.
ARG DEVCONTAINER_IMAGE=mcr.microsoft.com/devcontainers/ruby:4.0-trixie
FROM ${DEVCONTAINER_IMAGE}

USER root
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install node version from .nvmrc, as the devcontainer does, and expose it
# to non-login shells such as container commands.
WORKDIR /app
COPY --from=mastodon .nvmrc .
RUN /bin/bash --login -i -c "nvm install" \
 && /bin/bash --login -i -c 'nvm alias default "$(cat .nvmrc)" && ln -sfn "$(dirname "$(dirname "$(nvm which "$(cat .nvmrc)")")")" /usr/local/emuvista-node'
ENV PATH=/usr/local/emuvista-node/bin:${PATH}
RUN test "$(node --version | cut -d. -f1)" = "v$(cut -d. -f1 .nvmrc)"

# Install additional OS packages from the devcontainer; iproute2 lets SEED set
# each container's default route.
RUN apt-get update && \
    export DEBIAN_FRONTEND=noninteractive && \
    apt-get -y install --no-install-recommends libicu-dev libidn11-dev ffmpeg libvips42 libpam-dev iproute2 && \
    rm -rf /var/lib/apt/lists/*

# Disable download prompt for Corepack, and use Mastodon's development mode.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    RAILS_ENV=development \
    NODE_ENV=development \
    BOOTSNAP_CACHE_DIR=/tmp \
    HUSKY=0

WORKDIR /workspaces/mastodon

# bin/setup: Installing Ruby dependencies.
COPY --chmod=755 emuvista-align-ruby /usr/local/bin/
COPY --from=mastodon Gemfile Gemfile.lock .ruby-version ./
RUN --mount=type=cache,id=emuvista-mastodon-gems,target=/usr/local/bundle/cache \
    emuvista-align-ruby \
 && gem install bundler --conservative \
 && bundle install --jobs "$(nproc)" \
 && mkdir -p /usr/local/share/emuvista \
 && cp Gemfile.lock .ruby-version /usr/local/share/emuvista/

# bin/setup: Installing JS dependencies.
COPY --from=mastodon package.json yarn.lock .yarnrc.yml ./
COPY --from=mastodon .yarn/ .yarn/
COPY --from=mastodon streaming/package.json streaming/
RUN --mount=type=cache,id=emuvista-mastodon-yarn,target=/root/.yarn/berry/cache \
    npm i -g corepack \
 && yarn install --immutable

# Application source. Without a running Vite dev server, development pages
# load the assets listed in public/packs-dev's manifest.
COPY --from=mastodon . .
RUN cp /usr/local/share/emuvista/Gemfile.lock /usr/local/share/emuvista/.ruby-version ./ \
 && bundle check \
 && rm -rf tmp log/*.log public/packs-dev \
 && mkdir -p tmp/pids tmp/cache tmp/letter_opener public/system \
 && yarn build:development
