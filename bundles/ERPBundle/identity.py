"""Expose canonical employee profiles through the ERP's native document API."""

from http.cookiejar import CookieJar
import json
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


def people(configuration):
    client = build_opener(HTTPCookieProcessor(CookieJar()))
    url = configuration['url']
    login = urlencode({'usr': 'Administrator', 'pwd': configuration['password']}).encode()
    client.open(Request(url + '/api/method/login', data=login), timeout=20).read()
    fields = ['employee_number', 'first_name', 'last_name', 'user_id', 'department', 'reports_to', 'status']
    path = '/api/resource/Employee?' + urlencode({'fields': json.dumps(fields), 'limit_page_length': 10000})
    employees = json.load(client.open(url + path, timeout=20))['data']
    fields = json.dumps(['name', 'department_name'])
    path = '/api/resource/Department?' + urlencode({'fields': fields, 'limit_page_length': 10000})
    departments = {row['name']: row['department_name']
                   for row in json.load(client.open(url + path, timeout=20))['data']}
    return [{'id': employee['employee_number'], 'firstName': employee['first_name'],
             'lastName': employee['last_name'] or '', 'email': employee['user_id'],
             'department': departments.get(employee['department'], ''),
             'reportsTo': employee['reports_to'] or '', 'active': employee['status'] == 'Active'}
            for employee in employees if employee['user_id']]
