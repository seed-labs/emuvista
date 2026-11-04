"""Publish using the already authenticated session, with no automatic resend."""


def send_message(session, arguments, deadline):
    target = arguments.get("target")
    content = arguments.get("content")
    if not target or not isinstance(content, str) or not content.strip() or len(content) > 4000:
        raise ChatError("请提供接收对象和有效的消息正文。")
    session.attach(target, deadline)
    try:
        reply = session.command("pub", {"topic": target, "content": {"txt": content}, "noecho": True}, deadline)
    except Rejected:
        raise
    except (ChatError, TimeoutError):
        # Once pub was attempted, never retry automatically: the server may have accepted it.
        raise ChatError("尚未确认发送结果，请先检查聊天记录，避免重复发送。", unknown=True) from None
    seq = reply.get("params", {}).get("seq")
    message_id = str(reply.get("topic", target)) + ":" + str(seq) if type(seq) is int else None
    return dict(successful=True, message="消息已提交给聊天服务。", status="sent", message_id=message_id)
