"""IMAP transport used by service-owned tools."""
import imaplib
from email.parser import BytesParser
from email import policy
import re
import time


def configuration(context):
    """Resolve mailbox transport from installed tools and personal credentials."""
    account = context.accounts['email']
    providers = context.tool_config['email']
    if account.get('instance'):
        provider = providers[account['instance']]
    else:
        domain = account['email'].rsplit('@', 1)[1].lower()
        provider = next(provider for provider in providers.values()
                        if domain in provider['domains'])
    return {**provider, **account}


def messages(config, limit=5, folder='INBOX'):
    with imaplib.IMAP4(config['hostname'], config.get('imapPort', 143), timeout=15) as client:
        client.login(config['email'], config['password'])
        status, _ = client.select(folder, readonly=True)
        if status != 'OK':
            raise RuntimeError('Mailbox could not be opened')
        uids = client.uid('search', None, 'ALL')[1][0].split()
        result = []
        for uid in uids[-limit:]:
            rows = client.uid('fetch', uid, '(BODY.PEEK[])')[1]
            raw = next(row[1] for row in rows if isinstance(row, tuple))
            message = BytesParser(policy=policy.default).parsebytes(raw)
            body = message.get_body(preferencelist=('plain', 'html'))
            result.append({'uid': int(uid), 'from': str(message.get('From', '')), 'to': str(message.get('To', '')),
                           'subject': str(message.get('Subject', '')), 'date': str(message.get('Date', '')),
                           'messageId': str(message.get('Message-ID', '')),
                           'inReplyTo': str(message.get('In-Reply-To', '')),
                           'body': body.get_content() if body else ''})
        return result


def save_sent(config, message):
    """SMTP acceptance and IMAP filing are separate operations; never resend here."""
    def quoted(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

    with imaplib.IMAP4(config['hostname'], config.get('imapPort', 143), timeout=15) as client:
        client.login(config['email'], config['password'])
        status, rows = client.list()
        if status != 'OK':
            raise RuntimeError('Mailbox folders could not be listed')
        folder = None
        for row in rows:
            if not isinstance(row, bytes):
                continue
            match = re.fullmatch(rb'\((.*?)\)\s+(?:"[^"]*"|NIL)\s+(.+)', row)
            if match and b'\\sent' in match[1].lower().split():
                name = match[2].decode()
                folder = name[1:-1].replace('\\"', '"').replace('\\\\',
                                                                '\\') if name.startswith('"') else name
                break
        if folder is None:
            folder = 'Sent'
            status, _ = client.select(quoted(folder), readonly=True)
            if status != 'OK':
                status, _ = client.create(quoted(folder))
                if status != 'OK':
                    # Another client may have created it at the same time.
                    status, _ = client.select(quoted(folder), readonly=True)
                    if status != 'OK':
                        raise RuntimeError('Sent folder could not be created')
        status, _ = client.select(quoted(folder), readonly=True)
        if status != 'OK':
            raise RuntimeError('Sent folder could not be opened')
        status, existing = client.uid('search', None, 'HEADER',
                                      'Message-ID', quoted(str(message['Message-ID'])))
        if status != 'OK':
            raise RuntimeError('Sent folder could not be searched')
        if not existing or not existing[0]:
            status, _ = client.append(quoted(folder), r'(\Seen)', imaplib.Time2Internaldate(time.time()),
                                      message.as_bytes(policy=policy.SMTP))
            if status != 'OK':
                raise RuntimeError('Sent copy was not accepted')
        return folder
