# EmuVista Chat Client

A DSH 0.2.0-rc.2 plugin for the Tinode server installed by [ChatService](../../services/ChatService/README.md). The agent connects to the server over the SEED network using the [Tinode WebSocket protocol](https://github.com/tinode/chat/blob/v0.25.3/docs/API.md).

Add the built package to the profile's dependencies, then add @emuvista/chat-client to the resident preset's plugins with an endpoint (ws or wss), apiKey, and username. E30 generates this configuration from its topology. A chat password is supplied to chat_login and retained in memory for that agent session. The tool results contain the user ID, never the password.

| Tool | Use |
| --- | --- |
| chat_login | Authenticate as the configured resident and return the Tinode user ID. |
| chat_inbox | List conversation topic IDs and unread counts. |
| chat_read | Retrieve a bounded set of recent messages for a topic. |
| chat_send | Send one text message to a verified Tinode user ID. |
| chat_logout | Discard the current session's login. |
