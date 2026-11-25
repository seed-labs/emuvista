#!/usr/bin/env python3
"""Run BankBundle initialization with H24's Mailu folder handling."""

from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import re
import time

import initialize as bank


FOLDERS = ("INBOX", "Junk")


def mailbox_uids(client, folder):
    status, _ = client.select(folder, readonly=True)
    if status != "OK":
        return []
    status, rows = client.uid("search", None, "ALL")
    return sorted(map(int, rows[0].split())) if status == "OK" and rows and rows[0] else []


def last_uids(address, password):
    with bank.mailbox(address, password) as client:
        return {folder: max(mailbox_uids(client, folder), default=0) for folder in FOLDERS}


def registration_otp(address, password, previous):
    sender = bank.CONFIG["mail"]["username"].lower()
    for _ in range(90):
        with bank.mailbox(address, password) as client:
            for folder in FOLDERS:
                for uid in reversed(mailbox_uids(client, folder)):
                    if uid <= previous[folder]:
                        break
                    status, parts = client.uid("fetch", str(uid), "(BODY.PEEK[])")
                    if status != "OK":
                        continue
                    raw = next((part[1] for part in parts if isinstance(part, tuple)), None)
                    if raw is None:
                        continue
                    message = BytesParser(policy=policy.default).parsebytes(raw)
                    if parseaddr(str(message.get("From", "")))[1].lower() != sender:
                        continue
                    body = message.get_body(preferencelist=("plain", "html"))
                    match = re.search(r"verification code is:\s*([A-Za-z0-9]+)", body.get_content() if body else "")
                    if match:
                        return match.group(1)
        time.sleep(1)
    raise RuntimeError("Registration verification email did not arrive in Inbox or Junk")


if __name__ == "__main__":
    bank.last_uid = last_uids
    bank.otp = registration_otp
    bank.initialize()
