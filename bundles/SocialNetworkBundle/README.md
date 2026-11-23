# SocialNetworkBundle

Deploys Mastodon's development version (the `main` branch setup in Mastodon's `.devcontainer`): Puma web, streaming, Sidekiq, PostgreSQL 14, Redis, an nginx gateway and an account initializer. Each component owns an emulated IP and uses the emulated router. DNS is provided by the example's infrastructure.

| Built-in administrator | Sign-in email | Password |
| --- | --- | --- |
| `@admin` (Owner) | `admin@social.com` | `mastodonadmin` |

```python
from bundles.SocialNetworkBundle import SocialNetworkBundle

emu.render()
social = SocialNetworkBundle(emu, resolver='10.150.0.54')
social.setHostname('social.com')
social.setInitialConfiguration('accounts.json')
social.addInternalNetwork('162', 'net0',
    [f'10.162.0.{i}' for i in range(10, 17)], '10.162.0.254')
social.enableHostAccess(8450)
# Optional: social.setSavePath('./social-state')
compiler.addContainerBundle(social)
emu.compile(compiler, './output', override=True)
```

Build the Mastodon image first, with BuildKit (Docker's default builder):

```sh
docker compose -f docker_images/social/compose.yml build
```

Then run `DOCKER_BUILDKIT=0 docker compose build` and `docker compose up -d` in `output`. SEED's router and host images need the legacy builder.

It builds `handsonsecurity/emuvista-mastodon-dev:main` from a local Mastodon checkout: `mastodon` beside this repository, or the absolute path in `MASTODON_SOURCE`. The image merges the checkout's `.devcontainer/Dockerfile` (base image, Node.js from `.nvmrc`, OS packages) and does `bin/setup`'s gem and JavaScript installation at build time, because emulated hosts cannot reach package registries. It also builds the development frontend into `public/packs-dev`, which Mastodon serves when no Vite dev server is running. Override image references using `SocialNetworkBundle(emu, images={role: reference})`; the `mastodon` key sets web, streaming, Sidekiq and the initializer together.

`setHostname(name)` sets Mastodon's `LOCAL_DOMAIN`, defaulting to `social.com`. Configure its DNS A record separately, pointing at the gateway. Accounts are `@user@<hostname>`. `getURL()` returns the internal HTTP URL and `getAdminCredentials()` the administrator above.

`setInitialConfiguration(path_or_dict)` supplies an optional `title`, an optional `registrations` mode (`open`, `approved` or `none`, Mastodon's default) and `users`. Users define `username` (lowercase letters, digits and underscores), `email` and `password` (8 to 72 characters), plus optional `display_name`, `note`, `role` (`Moderator`, `Admin` or `Owner`), `follows` (other configured usernames or `admin`) and `posts` (public statuses of up to 500 characters). `addUser(user)` adds one user before compilation. The server hostname is configured separately with `setHostname()`.

On first startup the initializer runs `bin/rails db:prepare`, which loads the schema and Mastodon's development seeds, including `admin@<hostname>` / `mastodonadmin`. It then creates the configured users the same way as Mastodon's `example/create_user.rb`: confirmed, approved and bypassing registration checks. It updates profiles, follows and posts once. Later startups apply pending migrations and keep existing accounts, passwords and data.

Mastodon components share one emulated subnet. Their ordered roles are `gateway`, `web`, `streaming`, `sidekiq`, `db`, `redis`, `initialize`. The required `resolver` argument identifies an existing DNS resolver. Call `addInternalNetwork()` once after `emu.render()`, with seven free addresses; components appear on the Internet Map as hosts of that AS.

SEED builds a derived image for every component and installs `iproute2` in it with `apt-get`, so every image must be Debian or Ubuntu based. PostgreSQL 14 and Redis 7 therefore use the Debian variants of the devcontainer's Alpine images.

| Component | Port | Notes |
| --- | --- | --- |
| `gateway` | 80 | nginx; `/api/v1/streaming` to streaming, everything else to web |
| `web` | 3000 | `bundle exec puma -C config/puma.rb` |
| `streaming` | 4000 | `node ./streaming/index.js` |
| `sidekiq` | — | `bundle exec sidekiq` |
| `db` | 5432 | `postgres:14-bookworm`, generated password |
| `redis` | 6379 | `redis:7-bookworm` |
| `initialize` | — | `db:prepare` and account initialization, then exits |

Emulated clients use `http://<hostname>`, with WebSocket streaming at `ws://<hostname>/api/v1/streaming`. Only the gateway publishes a browser port, bound to `127.0.0.1`. That endpoint rewrites Mastodon's absolute `http://<hostname>/` links in pages, API results and redirects to the browser's localhost address, and points the web app at HTTP streaming (server-sent events), which is rewritten in the same way. Internal clients receive unmodified responses.

Development mode is kept: detailed errors, development logging and the development seed. Outgoing mail is not sent; it is listed at `/letter_opener`, where new users find their confirmation links. Elasticsearch search and LibreTranslate from the devcontainer are not deployed. `ALLOWED_PRIVATE_ADDRESSES=10.0.0.0/8` lets Mastodon fetch link previews from other emulated services. The software update check is disabled.

Without `setSavePath`, recompilation uses fresh temporary state outside the output directory. Explicit saved state includes the database, Redis, uploaded media, development mail, initialization marker and generated secrets. Stop the stack before recompiling; resume with the same configuration and network.

See [H24](../../examples/H24_social_network_service/README.md) for accounts and browser use.
