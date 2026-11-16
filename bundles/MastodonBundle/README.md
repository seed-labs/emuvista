# MastodonBundle

Mastodon, persistent PostgreSQL/Redis state and per-agent token exports.

Configuration lives in `server.py` and `templates/`; application images live in
`../../docker_images/`. Configure `bundle.server` before rendering, attach internal
networks after `emu.render()`, then call `compiler.addContainerBundle(bundle)`.

Agent tools are owned by [tools](tools/README.md). Register them with
`ToolPackage(**MastodonBundle.getAgentTools())` (with `requirements=("pydantic>=2,<3",)` on ToolPackage).

The default is HTTP on port 18084. H16 calls `server.setHttps(18443)`,
`server.setAcmeUrl(...)`, and `bundle.trustCA(...)` for CA-issued HTTPS.
Call `registerVolumes(compiler)` before compilation.

For standalone Docker Compose deployments, use `generate_mastodon_compose` from
this package. It writes the startup configuration, token-sharing mounts, health
check and image build context, and returns the service definition. The caller
configures accounts on `SocialMediaServer` and declares the returned service's
named volumes at Compose top level. This path currently supports HTTP.

`site_title` and `bootstrap_email_domains` are passed as JSON data. The email
allowlist applies only to the Rails account-initialization process. E16 supplies
its experiment-specific accounts, title, domain, port and token-volume mapping;
application installation remains in `docker_images/mastodon`.
