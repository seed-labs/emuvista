# Custom images

Images are grouped by Bundle. Each group has a build-only `compose.yml`, with
one subdirectory per custom image containing its Dockerfile and build inputs.
Source builds fetch a fixed upstream revision; no upstream checkout is stored.

Images use public upstream bases. Bank images compile from source and use the
public Java and nginx runtime images. No build depends on an earlier example's
local image. Licenses accompany copied or modified upstream source.

From the repository root, build all custom images for a Bundle:

```sh
docker compose -f docker_images/payment/compose.yml build
docker compose -f docker_images/bank/compose.yml build
docker compose -f docker_images/erp/compose.yml build
```

Alternatively, enter a group directory and run `docker compose build`. Append
an image service name, such as `payment-app`, to rebuild only that image.
Use `DOCKER_BUILDKIT=0 docker compose build` for the legacy builder.

| Bundle | Build configuration | Custom images |
| --- | --- | --- |
| PaymentBundle | [payment/compose.yml](payment/compose.yml) | payment-app, payment-accounting, payment-database, payment-cli, payment-files |
| BankBundle | [bank/compose.yml](bank/compose.yml) | bank-consumer, bank-frontend |
| ShopService | [shop/compose.yml](shop/compose.yml) | shop-app |
| ERPBundle | [erp/compose.yml](erp/compose.yml) | erp-app |
| IdentityBundle | [identity/compose.yml](identity/compose.yml) | identity-server, identity-directory, auth-gateway |
| WorkChatBundle | [workchat/compose.yml](workchat/compose.yml) | workchat-cache, workchat-database |
| ProjectBundle | [project/compose.yml](project/compose.yml) | project-app, auth-gateway |
| KnowledgeBundle | [knowledge/compose.yml](knowledge/compose.yml) | knowledge-app |
| HelpdeskBundle | [helpdesk/compose.yml](helpdesk/compose.yml) | helpdesk-app, auth-gateway |
| SocialNetworkBundle | [social/compose.yml](social/compose.yml) | mastodon-dev |

These files prepare images. Runtime configuration and startup remain in each
example's generated `output/docker-compose.yml`, which also pulls unmodified
upstream images. Bundles that use only upstream images need no build group.

| Payment image | Changes or packaging |
| --- | --- |
| `payment-app` | Wallet UI changes; upstream nginx configuration on a Debian nginx runtime |
| `payment-accounting` | Accounting API changes, including bank-funded payments |
| `payment-database` | PostgreSQL 16 with PostGIS, pgvector and the upstream application-user initialization script |
| `payment-cli` | Upstream initialization CLI and its dependencies; imports the upstream Social files it uses |
| `payment-files` | Node with S3rver 3.7.1 for the simulated file store |

The payment source revision is `124a87b639c37952dc9a029fc7056e523a10de5b`.
The database initialization script comes from that revision's
`shared/docker/db/init-app-db.sh`. Application and infrastructure bases are
recorded directly in each Dockerfile. Debian runtimes support the current SEED
ContainerBundle compiler's network-package installation.

After a source change, rebuild that image and recreate its example container.
Bundles reference these image names. Unmodified payment components use upstream
image references directly; they do not require a local build or image archive.

To use your Docker Hub account, change the image tag and the matching Bundle
image reference. Publishing with `docker push` is separate from local builds.

Build the marketplace and refresh Payment checkout support from the repository root:

```sh
DOCKER_BUILDKIT=0 docker compose -f docker_images/shop/compose.yml build
DOCKER_BUILDKIT=0 docker compose -f docker_images/payment/compose.yml build payment-accounting payment-app
```

The single-container shop image packages MySQL, WooCommerce 11.3.0, MultiVendorX
5.0.22 and Storefront 4.6.2. Release archives are checked with SHA-256. A local
WordPress plugin connects orders to Payment; upstream application sources are
not stored in this repository.

The social image is the exception to fixed upstream revisions: it builds the
development version from a local Mastodon checkout, so source changes can be
tried in the emulation. Build it from the repository root with BuildKit:

```sh
docker compose -f docker_images/social/compose.yml build
```

The checkout defaults to `mastodon` beside this repository; set `MASTODON_SOURCE`
to an absolute path to use another one. It is passed as the named build context
`mastodon`, filtered by the checkout's `.dockerignore`.
The Dockerfile merges the checkout's `.devcontainer/Dockerfile` (base image,
Node.js from `.nvmrc`, OS packages, plus `iproute2`) and runs `bin/setup`'s gem
and JavaScript installation at build time. It then builds `public/packs-dev`.
A newer Ruby patch release in the devcontainer base replaces the exact
`.ruby-version` inside the image only. Set `MASTODON_DEVCONTAINER_IMAGE` when the
checkout's devcontainer changes its base image.
