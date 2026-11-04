"""Provision Fineract accounts and register customers using real IMAP OTPs."""

import base64
import datetime
import email.policy
import hashlib
import imaplib
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from email.parser import BytesParser
from decimal import Decimal
from pathlib import Path

CONFIG = json.loads(Path('/bank/config.json').read_text())
RECORD = Path('/bank-state/initialization.json')
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DATE_FIELDS = {'locale': 'en', 'dateFormat': 'yyyy-MM-dd'}
TLS = ssl.create_default_context(cafile='/bank/mail-ca.pem')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def request(url, body=None, headers=None, method=None):
    req = urllib.request.Request(url,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
    try:
        with HTTP.open(req, timeout=90) as response:
            data = response.read()
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Bank API rejected {req.method} {req.selector} (HTTP {error.code})') from None


def core(path, body=None, operation=None, method=None):
    token = base64.b64encode((CONFIG['coreUsername']+':'+CONFIG['corePassword']).encode()).decode()
    headers = {'Authorization': 'Basic '+token, 'Fineract-Platform-TenantId': 'default'}
    if operation:
        headers['Idempotency-Key'] = operation
    return request(CONFIG['coreURL']+path, body, headers, method)


progress = json.loads(RECORD.read_text()) if RECORD.exists() else {
    'steps': {}, 'customers': {}, 'accounts': {}, 'loans': {}}
fingerprint = digest(CONFIG['initial'])
if progress.get('fingerprint', fingerprint) != fingerprint:
    raise RuntimeError('Initial configuration differs from saved bank state')
progress['fingerprint'] = fingerprint


def save():
    temporary = RECORD.with_suffix('.tmp')
    temporary.write_text(json.dumps(progress, indent=2)+'\n')
    temporary.replace(RECORD)


def once(key, action):
    if key not in progress['steps']:
        value = action('initialize-'+digest(key)[:32])
        progress['steps'][key] = True if value is None else value
        save()
    return progress['steps'][key]


def wait(action):
    for _ in range(180):
        try:
            return action()
        except (OSError, RuntimeError, imaplib.IMAP4.error):
            time.sleep(2)
    raise RuntimeError('Bank or mailbox service did not become ready')


def mailbox(address, password):
    mail = CONFIG['mail']
    client = imaplib.IMAP4_SSL(mail['host'], mail['imapPort'], ssl_context=TLS, timeout=15)
    try:
        client.login(address, password)
        client.select('INBOX', readonly=True)
        return client
    except Exception:
        client.logout()
        raise


def last_uid(address, password):
    with mailbox(address, password) as client:
        data = client.uid('search', None, 'ALL')[1][0].split()
        return max(map(int, data), default=0)


def otp(address, password, previous):
    for _ in range(90):
        with mailbox(address, password) as client:
            uids = client.uid('search', None, 'ALL')[1][0].split()
            for uid in reversed(uids):
                if int(uid) <= previous:
                    continue
                rows = client.uid('fetch', uid, '(BODY.PEEK[])')[1]
                raw = next(row[1] for row in rows if isinstance(row, tuple))
                message = BytesParser(policy=email.policy.default).parsebytes(raw)
                body = message.get_body(preferencelist=('plain', 'html'))
                match = re.search(r'verification code is:\s*([A-Za-z0-9]+)', body.get_content() if body else '')
                if match:
                    return match.group(1)
        time.sleep(1)
    raise RuntimeError('Registration verification email did not arrive')


def register(customer, client_id, document_key):
    address, password = customer['email'], customer['emailPassword']
    registration = once('registration:'+customer['id'], lambda _: request(
        CONFIG['bffURL']+'/api/v1/registration/submit', {
            'fineractClientId': client_id, 'email': address, 'password': customer['password'],
            'documentTypeName': 'Simulation ID', 'documentKey': document_key})['registrationId'])

    def verify(_):
        previous = wait(lambda: last_uid(address, password))
        request(CONFIG['bffURL']+'/api/v1/registration/otp/send',
                {'registrationId': registration, 'deliveryMethod': 'email'})
        request(CONFIG['bffURL']+'/api/v1/registration/otp/verify',
                {'registrationId': registration, 'token': otp(address, password, previous)})

    once('registered:'+customer['id'], verify)


def initialize():
    if progress.get('complete'):
        print('Bank state already initialized')
        return
    wait(lambda: core('/offices'))
    wait(lambda: request(CONFIG['bffURL']+'/actuator/health'))
    wait(lambda: last_uid(CONFIG['mail']['username'], CONFIG['mail']['password']))
    date = once('business-date', lambda _: datetime.datetime.now(datetime.timezone.utc).date().isoformat())
    currencies = sorted({product['currency'] for product in CONFIG['initial']['savingsProducts']}
                        | {loan['currency'] for c in CONFIG['initial']['customers'] for loan in c.get('loans', [])})
    once('currencies', lambda key: core('/currencies', {'currencies': currencies}, key, 'PUT'))

    def payment_type(key):
        existing = next((p for p in core('/paymenttypes') if p['name'] == 'Simulation'), None)
        return existing['id'] if existing else core('/paymenttypes', {
            'name': 'Simulation', 'description': 'Simulation cash transactions',
            'isCashPayment': True, 'position': 1}, key)['resourceId']

    payment = once('payment-type', payment_type)

    def identifier_type(key):
        code = next(c for c in core('/codes') if c['name'] == 'Customer Identifier')['id']
        values = core(f'/codes/{code}/codevalues')
        if not any(v['name'] == 'Simulation ID' for v in values):
            core(f'/codes/{code}/codevalues', {'name': 'Simulation ID', 'position': 1}, key)
        return next(v for v in core(f'/codes/{code}/codevalues') if v['name'] == 'Simulation ID')['id']

    document = once('identifier-type', identifier_type)
    for product in CONFIG['initial']['savingsProducts']:
        once('product:'+product['id'], lambda key: core('/savingsproducts', {
            'name': product['name'], 'shortName': product['id'], 'currencyCode': product['currency'],
            'digitsAfterDecimal': 2, 'inMultiplesOf': 0,
            'nominalAnnualInterestRate': product.get('interestRate', 0),
            'interestCompoundingPeriodType': 1, 'interestPostingPeriodType': 4,
            'interestCalculationType': 1, 'interestCalculationDaysInYearType': 365,
            'accountingRule': 1, 'locale': 'en'}, key)['resourceId'])

    for customer in CONFIG['initial']['customers']:
        client = once('client:'+customer['id'], lambda key: core('/clients', {
            'officeId': 1, 'firstname': customer['firstName'], 'lastname': customer['lastName'],
            'externalId': customer['id'], 'legalFormId': 1, 'active': True,
            'activationDate': date, **DATE_FIELDS}, key)['resourceId'])
        progress['customers'][customer['id']] = client
        document_key = 'SIM-'+digest(customer['id'])[:24]
        once('identifier:'+customer['id'], lambda key: core(f'/clients/{client}/identifiers', {
            'documentTypeId': document, 'documentKey': document_key, 'status': 'Active'}, key))
        for account in customer['accounts']:
            account_id = once('account:'+account['id'], lambda key: core('/savingsaccounts', {
                'clientId': client, 'productId': progress['steps']['product:'+account['product']],
                'externalId': account['id'], 'submittedOnDate': date, **DATE_FIELDS}, key)['resourceId'])
            once('approve:'+account['id'], lambda key: core(f'/savingsaccounts/{account_id}?command=approve',
                 {'approvedOnDate': date, **DATE_FIELDS}, key))
            once('activate:'+account['id'], lambda key: core(f'/savingsaccounts/{account_id}?command=activate',
                 {'activatedOnDate': date, **DATE_FIELDS}, key))
            if Decimal(str(account['balance'])) > 0:
                once('deposit:'+account['id'], lambda key: core(f'/savingsaccounts/{account_id}/transactions?command=deposit', {
                    'transactionDate': date, 'transactionAmount': str(account['balance']),
                    'paymentTypeId': payment, **DATE_FIELDS}, key))
            product = next(p for p in CONFIG['initial']['savingsProducts'] if p['id'] == account['product'])
            progress['accounts'][account['id']] = {'id': account_id, 'clientId': client,
                'currency': product['currency'], 'label': account['name'], 'customer': customer['id']}
            save()
        if customer.get('email'):
            register(customer, client, document_key)
        for loan in customer.get('loans', []):
            product_id = once('loan-product:'+loan['currency'], lambda key: core('/loanproducts', {
                'name': 'Simulation loan '+loan['currency'], 'shortName': 'L'+loan['currency'],
                'currencyCode': loan['currency'], 'digitsAfterDecimal': 2, 'inMultiplesOf': 0,
                'principal': loan['principal'], 'numberOfRepayments': 12, 'repaymentEvery': 1,
                'repaymentFrequencyType': 2, 'interestRatePerPeriod': 1, 'interestRateFrequencyType': 2,
                'amortizationType': 1, 'interestType': 0, 'interestCalculationPeriodType': 1,
                'transactionProcessingStrategyCode': 'mifos-standard-strategy', 'accountingRule': 1,
                'daysInYearType': 1, 'daysInMonthType': 1, 'isInterestRecalculationEnabled': False,
                'locale': 'en'}, key)['resourceId'])
            loan_id = once('loan:'+loan['id'], lambda key: core('/loans', {
                'clientId': client, 'productId': product_id, 'loanType': 'individual',
                'principal': loan['principal'], 'loanTermFrequency': 12, 'loanTermFrequencyType': 2,
                'numberOfRepayments': 12, 'repaymentEvery': 1, 'repaymentFrequencyType': 2,
                'interestRatePerPeriod': 1, 'amortizationType': 1, 'interestType': 0,
                'interestCalculationPeriodType': 1, 'transactionProcessingStrategyCode': 'mifos-standard-strategy',
                'expectedDisbursementDate': date, 'submittedOnDate': date, **DATE_FIELDS}, key)['resourceId'])
            once('loan-approve:'+loan['id'], lambda key: core(f'/loans/{loan_id}?command=approve',
                 {'approvedOnDate': date, **DATE_FIELDS}, key))
            once('loan-disburse:'+loan['id'], lambda key: core(f'/loans/{loan_id}?command=disburse',
                 {'actualDisbursementDate': date, 'transactionAmount': loan['principal'], **DATE_FIELDS}, key))
            progress['loans'][loan['id']] = {'id': loan_id, 'clientId': client, 'currency': loan['currency']}
            save()
    progress['complete'] = True
    save()
    print('Bank customers, accounts and loans initialized; email registration verified through IMAP')


if __name__ == '__main__':
    initialize()
