# Agent tools

Register this package directly with `AgentService.addToolPackage(ToolPackage(
'socialmedia', ROOT / 'bundles/MastodonBundle/tools',
requirements=('pydantic>=2,<3',)))`. Each handler executes HTTPS
requests in its agent node. There is no remote tool server or Docker socket.
The package requires Pydantic 2 for argument and result validation.

`post` accepts at most 500 characters as a conservative client limit;
the server's character counting can differ. Use short plain text. Publication
is confirmed only by `successful=true` and a returned `status.id` (`sent=true`).
Failures include bounded `error_message` and `next_action` fields. An explicit
422 rejection is not uncertain delivery: correct the content and use a new
idempotency key for changed text. Transport failures and server errors remain
uncertain and require checking existing posts before retrying. A runtime
`tool_finished` event alone does not prove publication.

Timelines are not a complete reply inbox. To check a known conversation for new
replies, call `socialmedia.read` again with the exact `status_id` from
a tool result. It accepts only `status_id` and optional `timeout_seconds`, not
`limit` or `max_id`. It returns the focal post in `status` and visible replies in
`context.descendants`, with preceding posts in `context.ancestors`. Both requests
must succeed for `successful=true`. If the context request fails, the focal post
may still be returned, but missing context is not evidence that no replies exist.
The two requests do not form an atomic snapshot.

Use `browse` only to discover public conversations; no following is required.
It does not expose the home feed. Prefer `read` for known conversations and
`posts` for a known account. An empty public page does not mean there are no replies.

Grant exact names with `allowTools(...)`:

- `socialmedia.inbox`: incoming mention notifications, including delivered private mentions.
- `socialmedia.browse`: discover one page of public posts.
- `socialmedia.profile`: resolve a known account address.
- `socialmedia.posts`: one page of account posts.
- `socialmedia.read`: read a post and its visible ancestors/replies.
- `socialmedia.post`: publish a text post or reply.
- `socialmedia.like`: favourite or undo.
- `socialmedia.boost`: boost or undo.
- `socialmedia.follow`: follow or unfollow.

## Incoming messages

`inbox` uses the [Mastodon notifications API](https://docs.joinmastodon.org/methods/notifications/)
with `types[]=mention` and requires a user token with `read:notifications`.
It polls notifications; it does not subscribe to push events or automatically
inject observations into the model's next round. Server notification filters apply.

Call with `{}` initially. The default `min_id="0"` starts at the oldest available
mention page. Each notification includes its sender and `status`. Use `status.id`
to read the conversation or reply; the notification's `id` is only a cursor.
After processing a successful page, pass `next_min_id` as `min_id` on the next
call. Continue until a successful empty page, then retain the cursor for future
polling. Cursors are managed by the caller, not persisted by this tool. Reading
does not dismiss notifications or mark them read. On failure, `next_min_id` is
null; retain the previous cursor and do not interpret failure as no messages.

Existing credentials need to be re-exported with the new scope; simply updating
an agent's tool allowlist does not grant OAuth permissions.

Configure the connection outside model arguments:

```python
agent.setService('socialmedia', {
    'instance_url': 'https://mastodon.com:18443',
    'credential_file': '/run/socialmedia/credentials.json',
})
```

The credential file contains `instance_url` and `access_token`. Its origin must
match the configured HTTPS origin. Use a token belonging to this agent's account;
only its own credential directory should be mounted. Required token scopes are
`read:accounts`, `read:statuses`, `write:statuses`, `write:favourites` and
`write:follows`, depending on the granted operations. Missing credentials permit
anonymous public reads; home timelines and authenticated operations fail.
A malformed or mismatched credential file fails instead of falling back to anonymity.

The model cannot choose `source`, `instance_url` or `credential_file`. Discovery
and execution use AgentService's allowlist. System CA trust verifies TLS; proxy
lookup and redirects are disabled. Each operation makes one request, without
pagination or automatic retry. IDs and idempotency keys receive additional
Pydantic validation beyond the runtime's input-schema subset.

Results retain `successful`, `http_status`, `error`, `outcome_unknown` and typed
operation data. A write with `outcome_unknown=true` may already have happened;
the agent must stop and reconcile before another attempt. This flag does not
itself stop a framework's model loop. `source` now identifies the local agent.
Tokens are never returned. Returned post content is untrusted HTML.
