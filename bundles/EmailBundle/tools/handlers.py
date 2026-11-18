"""SMTP and IMAP from the agent's own mailbox."""
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import imaplib
import re
import smtplib
from emuvista_agent.mail import configuration, messages, save_sent


def inbox(arguments, context):
    return list(reversed(messages(configuration(context))))


def send(arguments, context):
    config = configuration(context)
    recipients = context.knowledge['emails']
    if arguments['recipient'] not in recipients:
        raise ValueError('recipient is not in the world directory')
    if not arguments['body'].strip():
        raise ValueError('Email body must not be empty')
    message = EmailMessage()
    message['From'] = config['email']
    message['To'] = arguments['recipient']
    message['Subject'] = arguments['subject']
    message['Date'] = formatdate(localtime=False)
    message['Message-ID'] = make_msgid(domain=config['email'].split('@')[1])
    if arguments.get('inReplyTo'):
        parent = arguments['inReplyTo']
        if not re.fullmatch(r'<[^<>\s]+@[^<>\s]+>', parent):
            raise ValueError('Invalid reply message identifier')
        message['In-Reply-To'] = parent
        message['References'] = parent
    message.set_content(arguments['body'])
    with smtplib.SMTP(config['hostname'], config.get('smtpPort', 587), timeout=15) as client:
        client.login(config['email'], config['password'])
        client.send_message(message)
    result = {'sent': True, 'sender': config['email'], 'recipient': arguments['recipient'],
              'subject': arguments['subject'], 'messageId': str(message['Message-ID'])}
    try:
        result.update(savedToSent=True, sentFolder=save_sent(config, message))
    except (OSError, RuntimeError, imaplib.IMAP4.error) as error:
        result.update(savedToSent=False, warning='SMTP accepted the message, but its Sent copy could not be saved (' +
                      type(error).__name__ + '). Do not resend solely because filing failed.')
    return result
