"""Synchronize actual messages and return the next durable inbox batch."""


def receive_messages(session, arguments, deadline):
    target = arguments.get("target")
    limit = arguments.get("limit", 50)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ChatError("收件数量应在 1 到 100 之间。")
    if target:
        session.fetch_history(target, deadline)
    else:
        session.discover(deadline)
        for topic in sorted(session.topics):
            try:
                session.fetch_history(topic, deadline)
            except Rejected:
                session.topics.discard(topic)
        if time.monotonic() >= deadline:
            raise ChatError("消息仍在同步，请稍后再次收取。")
    return session.inbox(arguments)
