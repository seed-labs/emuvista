# Social network service

Mastodon's development version provides a social network on the shared [H00 mini Internet](../H00_mini_internet/). It runs the setup from Mastodon's `.devcontainer` (Ruby, Node.js, PostgreSQL 14 and Redis, `RAILS_ENV=development`), with web, streaming and Sidekiq as separate emulated hosts.

Build the Mastodon image once from your checkout, then compile and start:

```sh
# From the repository root; the checkout defaults to ../mastodon
docker compose -f docker_images/social/compose.yml build
cd examples/H24_social_network_service
python3 social_network.py
cd output
DOCKER_BUILDKIT=0 docker compose build
docker compose up -d
```

The emulation needs the legacy builder (`DOCKER_BUILDKIT=0`), because SEED builds its router and host images from local base images that Compose's default builder cannot see. The Mastodon image is the opposite: build it with BuildKit, Docker's default, so do not export `DOCKER_BUILDKIT=0` in your shell.

Or run `python3 social_network.py --start`: it builds the Mastodon image if it is missing, builds and starts the emulation with the right builder for each, and waits until the five accounts exist. The first start loads the database schema and takes a few minutes.

| Interface | Address |
| --- | --- |
| Mastodon | http://localhost:8450 |
| Development mail | http://localhost:8450/letter_opener |
| Internet Map | http://localhost:8080 |

Run one mini Internet example at a time.

| Account | Sign-in email | Password | Role |
| --- | --- | --- | --- |
| `@admin` | `admin@social.com` | `mastodonadmin` | Built-in Owner from Mastodon's development seed |
| `@alice` | `alice@mail.com` | `SocialDemo123!` | User |
| `@bob` | `bob@mail.com` | `SocialDemo123!` | User |
| `@carol` | `carol@mail.com` | `SocialDemo123!` | Moderator |
| `@dave` | `dave@mail.com` | `SocialDemo123!` | User |
| `@erin` | `erin@mail.com` | `SocialDemo123!` | User |

The five people match the E99 residents. Each account is confirmed and approved, has a display name and bio, follows some of the others and has published one `#introductions` post, so home timelines are not empty. Sign in as Alice and write a post, then sign in as Bob in a private window: Bob follows Alice, so the post appears in his home timeline. Carol's Moderator role opens the reports dashboard at `/admin/reports`.

Edit [accounts.json](accounts.json) to change the site title, registration mode (`open`, `approved` or `none`) and users. Users define `username`, `email` and `password`, plus optional `display_name`, `note`, `role` (`Moderator`, `Admin` or `Owner`), `follows` and `posts`. Registrations are open: new people sign up at http://localhost:8450/auth/sign_up, and their confirmation email appears at `/letter_opener` because development Mastodon keeps outgoing mail.

Emulated hosts use http://social.com, which resolves to the gateway at `10.162.0.10`. The browser endpoint binds to localhost and rewrites Mastodon's `social.com` links for the browser; the web app then streams updates over HTTP instead of WebSockets.

| Component | Address |
| --- | --- |
| Gateway (nginx) | `10.162.0.10` |
| Web (Puma) | `10.162.0.11:3000` |
| Streaming | `10.162.0.12:4000` |
| Sidekiq | `10.162.0.13` |
| PostgreSQL | `10.162.0.14:5432` |
| Redis | `10.162.0.15:6379` |
| Initializer | `10.162.0.16` |

Without `--state`, recompilation creates fresh storage outside `output`. Stop the current stack before recompiling. To save and resume accounts, posts and media, use `python3 social_network.py --state ./social-state` with the same configuration and network. Keep the state directory outside `output`.

After changing the Mastodon checkout, rebuild the image, then run `DOCKER_BUILDKIT=0 docker compose build` and `docker compose up -d` in `output`. Pending migrations run when the initializer starts.

See [the bundle API](../../bundles/SocialNetworkBundle/README.md).
