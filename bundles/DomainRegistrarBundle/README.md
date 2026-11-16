# DomainRegistrarBundle

FOSSBilling customer accounts, domain purchases, DNS hosting orders and simulated payments.

Configuration lives in `server.py` and `templates/`; application images live in
`../../docker_images/`. Configure `bundle.server` before rendering, attach internal
networks after `emu.render()`, then call `compiler.addContainerBundle(bundle)`.

Agent tools are owned by [tools](tools/README.md). Register them with
`ToolPackage(**DomainRegistrarBundle.getAgentTools())`.
