# DomainRegistryBundle

Namingo Registry, EPP registrar access and parent-zone delegation.

Configuration lives in `server.py` and `templates/`; application images live in
`../../docker_images/`. Configure `bundle.server` before rendering, attach internal
networks after `emu.render()`, then call `compiler.addContainerBundle(bundle)`.
