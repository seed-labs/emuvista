"""IMAP transport used by service-owned tools."""
import imaplib
from email.parser import BytesParser
from email import policy
from .http import tls


def messages(config,limit=5):
    with imaplib.IMAP4_SSL(config['hostname'],993,ssl_context=tls(config),timeout=15) as client:
        client.login(config['email'],config['password'])
        client.select('INBOX',readonly=True)
        uids=client.uid('search',None,'ALL')[1][0].split()
        result=[]
        for uid in uids[-limit:]:
            rows=client.uid('fetch',uid,'(BODY.PEEK[])')[1]
            raw=next(row[1] for row in rows if isinstance(row,tuple))
            message=BytesParser(policy=policy.default).parsebytes(raw)
            body=message.get_body(preferencelist=('plain','html'))
            result.append({'uid':int(uid),'from':str(message.get('From','')),'subject':str(message.get('Subject','')),
                           'body':body.get_content()[:4000] if body else ''})
        return result
