# Cloud tools

Service-owned tools copied into Agent containers by AgentService. Requests use
WebDAV and OCS directly from the Agent; no Docker socket, remote execution backend
or separate tool server is required.

| Tool | Purpose |
| --- | --- |
| `cloud.storage_find` | List drive instances present in both tool configuration and personal accounts |
| `cloud.file_upload` | Upload or replace a file, limited to 256 KiB |
| `cloud.file_download` | Read a file as base64, with its size and SHA-256 |
| `cloud.file_share` | Create a read-only share for another existing user on the same drive |

After configuring the world and resolving drive bindings, export the tools:

```python
agents.addToolsFrom(cloud)
```

The configured CloudDriveService supplies internal URLs through
`getAgentTools()`. Instance IDs are the names passed to `createDrive()`.
Each persona supplies its own WebDAV account:

```json
{
  "accounts": {
    "cloud": {
      "company_cloud": {
        "username": "EMP0002",
        "password": "cloud-application-password"
      }
    }
  }
}
```

The password must authenticate to Nextcloud WebDAV, using a local account password
or an application password. For SSO-only accounts, use a Nextcloud application
password instead of assuming that the SSO password authenticates WebDAV. Account
creation and credential delivery remain deployment responsibilities.

Handlers follow `handler(arguments, context)`: endpoints come from
`context.tool_config['cloud']`, personal credentials from `context.accounts['cloud']`.
The Agent does not supply a source container or choose another container to execute
commands in. Service discovery results contain instance IDs, not credentials or
backend addresses. AgentService applies the selected tool policy.

Use absolute file paths such as `/notes.txt`. Parent directories must already
exist. Missing files, invalid credentials and rejected shares raise tool errors.
Empty files are supported; oversized downloads are rejected. HTTP requests keep
normal certificate validation and reject redirects.
