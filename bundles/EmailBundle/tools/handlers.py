"""SMTP and IMAP from the agent's own mailbox."""
from email.message import EmailMessage
import smtplib
from emuvista_agent.http import tls
from emuvista_agent.mail import messages


def inbox(arguments,context):
    return messages(context.service('email'))


def send(arguments,context):
    config=context.service('email')
    recipients=context.service('world')['emails']
    if arguments['recipient'] not in recipients:raise ValueError('recipient is not in the world directory')
    message=EmailMessage()
    message['From']=config['email']
    message['To']=arguments['recipient']
    message['Subject']=arguments['subject']
    message.set_content(arguments['body'])
    with smtplib.SMTP(config['hostname'],587,timeout=15) as client:
        client.starttls(context=tls(config))
        client.login(config['email'],config['password'])
        client.send_message(message)
    return {'sent':True,'recipient':arguments['recipient']}
