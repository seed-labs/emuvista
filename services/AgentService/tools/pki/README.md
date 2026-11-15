# PKI tools

Certificate inspection, TLS diagnostics, ACME, certificate installation and
trust-store helpers. These are a tool package, with no tool server or proxy.

```python
agents = AgentService().addPkiTools()
agent = agents.createagent({'id': '4de4ceb9-78be-4d9b-8236-6d080b70d1f9', 'name': 'Alice', 'background': 'Alice explores local TLS services.'})
# Optional subset; otherwise all registered PKI tools are available.
agent.setTools(['pki.inspect_certificate_file', 'pki.inspect_remote_tls_certificate'])
```

The package installs OpenSSL, coreutils and Pydantic in the agent image.
Bind `agents.clock.vnode` as shown in the AgentService README.
Commands run as the agent user in its own container; `source` is injected as
`local`. File permissions still apply. A network `target` can be another node;
it does not grant access to that node's files or commands. Omit optional arguments
to use their defaults. Full Pydantic validation runs before command execution.

CA administration, Certbot and system trust-store changes require the appropriate
software, files and permissions on the execution node. They are not enabled by
installing this package. In particular, an ordinary agent cannot read another
node's CA configuration or deploy Nginx settings there.

The library retains its execution contract, `execute(source, argv)`, for callers
that supply their own backend. No remote execution backend or HTTP API is included.

See [the tool catalog](../../../../docs/agent-service/pki-tools-design.md).
