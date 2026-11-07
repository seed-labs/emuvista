"""Bank customer APIs, using native bank login and real mailbox OTP verification."""
from email.utils import parseaddr
import re
import threading
import time
from emuvista_agent.http import client,request
from emuvista_agent.mail import messages

_login_lock=threading.Lock()


def connection(context):
    # Frameworks may call accounts/cards/loans concurrently. Share one OTP
    # login so parallel requests cannot consume each other's verification code.
    with _login_lock:
        return authenticated_connection(context)


def authenticated_connection(context):
    config=context.service('bank')
    cached=getattr(context,'_bank_connection',None)
    if cached and cached[0]>time.time():return config,cached[1],cached[2]
    mail=context.service('email')
    previous=max((m['uid'] for m in messages(mail,50)),default=0)
    opener=client(config)
    headers={'X-Device-Fingerprint':'agent-'+context.identity}
    challenge=request(config,'/api/v1/authentication/login',method='POST',headers=headers,opener=opener,
                      body={'email':config['email'],'password':config['password']})['challengeToken']
    code=None
    for _ in range(30):
        for message in reversed(messages(mail,10)):
            if message['uid']<=previous or parseaddr(message['from'])[1].lower()!=config['sender'].lower():continue
            match=re.search(r'verification code is:\s*([A-Za-z0-9]+)',message['body'])
            if match:code=match.group(1);break
        if code:break
        time.sleep(2)
    if not code:raise RuntimeError('bank login email did not arrive')
    request(config,'/api/v1/authentication/2fa',method='POST',headers=headers,opener=opener,
            body={'challengeToken':challenge,'token':code})
    context._bank_connection=(time.time()+120,opener,headers)
    return config,opener,headers


def read(context,path):
    config,opener,headers=connection(context)
    return request(config,'/api/v1/'+path,opener=opener,headers=headers)


def accounts(arguments,context):return read(context,'savings')
def cards(arguments,context):return read(context,'cards')
def loans(arguments,context):return read(context,'loans')
