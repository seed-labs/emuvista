"""Authenticate once; the shared runtime keeps this connection alive in the container."""


def login(session, arguments, deadline):
    username, password = arguments.get("username"), arguments.get("password")
    if not isinstance(username, str) or not username or any(c in username for c in ":\r\n"):
        raise ChatError("请填写有效的账号。")
    if not isinstance(password, str) or not password:
        raise ChatError("请填写密码。")
    # Persist the failed-switch guard, including across host/worker restarts.
    session.account["login_required"] = True
    atomic_json(session.state_file, session.account)
    # Explicit login authenticates supplied credentials. Ordinary sends never do this.
    secret = base64.b64encode((username + ":" + password).encode()).decode()
    session.connect("basic", secret, deadline, username=username)
    return dict(successful=True, message="登录成功，后续可直接收发消息。")
