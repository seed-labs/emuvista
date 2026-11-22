"""Initialize a company through the installed Frappe and ERPNext document APIs."""

from datetime import date, timedelta
import json
from base64 import b64encode
import os
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.desk.page.setup_wizard.setup_wizard import setup_complete
from frappe.utils.password import update_password
from business import initialize as initialize_business

SITE = os.environ['ERP_SITE']
SITES = Path('/home/frappe/frappe-bench/sites')


def create(doctype, values, filters):
    name = frappe.db.exists(doctype, filters)
    if name:
        return frappe.get_doc(doctype, name)
    return frappe.get_doc({'doctype': doctype, **values}).insert(ignore_permissions=True)


def configure_identity():
    settings = frappe.get_single('System Settings')
    settings.allow_login_using_user_name = 1
    settings.enable_onboarding = 0
    settings.save()
    settings = frappe.get_single('HR Settings')
    settings.emp_created_by = 'Employee Number'
    settings.send_leave_notification = 0
    settings.send_birthday_reminders = 0
    settings.send_work_anniversary_reminders = 0
    settings.leave_approver_mandatory_in_leave_application = 1
    settings.prevent_self_leave_approval = 1
    settings.save()
    make_property_setter('Employee', 'employee_number', 'reqd', '1', 'Check')
    make_property_setter('Employee', None, 'allow_rename', '0', 'Check', for_doctype=True)
    create_custom_fields({'User': [{
        'fieldname': 'custom_employee_id', 'label': 'Employee ID',
        'fieldtype': 'Data', 'read_only': 1, 'insert_after': 'username',
    }]})


def configure_company(configuration):
    data = configuration['company']
    year = date.today().year
    setup_complete({
        'language': 'English', 'country': data['country'],
        'currency': data['currency'], 'timezone': data['timezone'],
        'company_name': data['name'], 'company_abbr': data['abbreviation'],
        'chart_of_accounts': 'Standard',
        'fy_start_date': f'{year}-01-01', 'fy_end_date': f'{year}-12-31',
    })
    company = frappe.get_doc('Company', data['name'])
    defaults = frappe.get_single('Global Defaults')
    defaults.default_company = company.name
    defaults.default_currency = data['currency']
    defaults.country = data['country']
    defaults.current_fiscal_year = str(year)
    defaults.save()
    departments = {}
    for name in configuration['departments']:
        department = create('Department', {'department_name': name, 'company': company.name},
                            {'department_name': name, 'company': company.name})
        departments[name] = department.name
    return company, departments


def configure_employees(configuration, company, departments):
    people = {person['id']: person for person in configuration['employees']}
    for person in people.values():
        user = create('User', {
            'email': person['email'], 'username': person['id'].lower(),
            'first_name': person['firstName'], 'last_name': person['lastName'],
            'custom_employee_id': person['id'], 'enabled': 1,
            'user_type': 'System User', 'send_welcome_email': 0,
            'roles': [{'role': role} for role in person['roles']],
        }, person['email'])
        update_password(user.name, person['password'])
        create('Employee', {
            'employee_number': person['id'], 'first_name': person['firstName'],
            'last_name': person['lastName'], 'gender': person['gender'],
            'date_of_birth': person['dateOfBirth'], 'date_of_joining': person['dateOfJoining'],
            'company': company.name, 'department': departments[person['department']],
            'status': 'Active', 'user_id': user.name, 'company_email': person['email'],
            'prefered_contact_email': 'Company Email',
            'create_user_permission': int(person['roles'] == ['Employee']),
        }, person['id'])
    for person in people.values():
        if person.get('reportsTo'):
            employee = frappe.get_doc('Employee', person['id'])
            employee.reports_to = person['reportsTo']
            employee.leave_approver = people[person['reportsTo']]['email']
            employee.save()


def configure_leave(configuration, company):
    year = date.today().year
    start, end = date(year, 1, 1), date(year, 12, 31)
    holidays = []
    day = start
    while day <= end:
        if day.weekday() >= 5:
            holidays.append({'holiday_date': day.isoformat(), 'description': day.strftime('%A'),
                             'weekly_off': 1})
        day += timedelta(days=1)
    holiday_list = create('Holiday List', {
        'holiday_list_name': f'Company Holidays {year}',
        'from_date': start.isoformat(), 'to_date': end.isoformat(),
        'holidays': holidays,
    }, f'Company Holidays {year}')
    company.default_holiday_list = holiday_list.name
    company.save()
    leave = configuration['leave']
    create('Leave Type', {'leave_type_name': leave['type'],
                          'max_leaves_allowed': leave['days'], 'include_holiday': 0}, leave['type'])
    create('Leave Period', {'from_date': start.isoformat(), 'to_date': end.isoformat(),
                            'company': company.name},
           {'from_date': start.isoformat(), 'to_date': end.isoformat(), 'company': company.name})
    for person in configuration['employees']:
        allocation = create('Leave Allocation', {
            'employee': person['id'], 'leave_type': leave['type'],
            'from_date': start.isoformat(), 'to_date': end.isoformat(),
            'new_leaves_allocated': leave['days'],
        }, {'employee': person['id'], 'leave_type': leave['type'], 'from_date': start.isoformat()})
        if allocation.docstatus == 0:
            allocation.submit()


def configure_profile_consistency():
    # Employee is the master for linked account names and employee identifiers.
    make_property_setter('Employee', 'company_email', 'read_only', '0', 'Check')
    make_property_setter('Employee', 'company_email', 'read_only_depends_on',
                        'eval:doc.user_id', 'Data')
    scripts = [
        ('Company Employee Identifier', 'Employee', 'Before Validate',
         "if not doc.is_new() and doc.employee_number != doc.name:\n"
         "    frappe.throw('Employee ID cannot be changed after creation.')\n"
         "if doc.user_id:\n"
         "    doc.company_email = doc.user_id\n"),
        ('Company Employee Profile', 'Employee', 'After Save',
         "if doc.user_id:\n"
         "    frappe.db.set_value('User', doc.user_id, {\n"
         "        'first_name': doc.first_name, 'middle_name': doc.middle_name,\n"
         "        'last_name': doc.last_name, 'username': doc.employee_number.lower(),\n"
         "        'full_name': doc.employee_name,\n"
         "        'birth_date': doc.date_of_birth, 'gender': doc.gender,\n"
         "        'mobile_no': doc.cell_number,\n"
         "        'custom_employee_id': doc.employee_number,\n"
         "    })\n"),
        ('Company User Profile', 'User', 'Before Validate',
         "employee = frappe.db.get_value('Employee', {'user_id': doc.name},\n"
         "    ['employee_number', 'first_name', 'middle_name', 'last_name',\n"
         "     'date_of_birth', 'gender', 'cell_number'], as_dict=True)\n"
         "if employee:\n"
         "    doc.first_name = employee.first_name\n"
         "    doc.middle_name = employee.middle_name\n"
         "    doc.last_name = employee.last_name\n"
         "    doc.username = employee.employee_number.lower()\n"
         "    doc.birth_date = employee.date_of_birth\n"
         "    doc.gender = employee.gender\n"
         "    doc.mobile_no = employee.cell_number\n"
         "    doc.custom_employee_id = employee.employee_number\n"),
        ('Company Employee Onboarding', 'Employee', 'After Save',
         "if doc.job_applicant:\n"
         "    onboarding = frappe.db.get_value('Employee Onboarding',\n"
         "        {'job_applicant': doc.job_applicant, 'docstatus': 1},\n"
         "        ['name', 'employee'], as_dict=True)\n"
         "    if onboarding and not onboarding.employee:\n"
         "        frappe.db.set_value('Employee Onboarding', onboarding.name, 'employee', doc.name)\n"),
        ('Company Account Email', 'User', 'After Rename',
         "employee = frappe.db.get_value('Employee', {'user_id': doc.name}, 'name')\n"
         "if employee:\n"
         "    frappe.db.set_value('Employee', employee, 'company_email', doc.name)\n"),
    ]
    for name, doctype, event, script in scripts:
        values = {'name': name, 'script_type': 'DocType Event',
                  'reference_doctype': doctype, 'doctype_event': event,
                  'script': script, 'disabled': 0}
        rule = create('Server Script', values, name)
        rule.update(values)
        rule.save()


def configure_single_sign_on(configuration):
    identity = configuration.get('identity')
    if not identity:
        return
    administrator = frappe.get_doc('User', 'Administrator')
    administrator.email = 'administrator@company.com'
    administrator.save()
    # The reserved Administrator name cannot be used by Frappe's email-based
    # OAuth lookup. Give the shared login a normal native management account.
    manager = create('User', {'email': 'admin@company.com', 'username': 'admin',
                              'first_name': 'Company', 'last_name': 'Administrator',
                              'enabled': 1, 'user_type': 'System User', 'send_welcome_email': 0,
                              'new_password': frappe.generate_hash(length=32)}, 'admin@company.com')
    manager.append_roles('System Manager', 'HR Manager', 'HR User', 'Accounts Manager',
                         'Accounts User', 'Purchase Manager', 'Stock Manager',
                         'Sales Manager', 'Projects Manager', 'Leave Approver', 'Expense Approver')
    manager.save()
    values = {
        'provider_name': 'Company', 'social_login_provider': 'Custom',
        'enable_social_login': 1, 'custom_base_url': 1,
        'base_url': identity['internal_issuer'],
        'authorize_url': identity['authorize_url'],
        'access_token_url': identity['token_url'],
        'api_endpoint': identity['userinfo_url'],
        'redirect_url': '/api/method/frappe.integrations.oauth2_logins.custom/company',
        'client_id': identity['client_id'], 'client_secret': identity['client_secret'],
        'auth_url_data': json.dumps({'response_type': 'code', 'scope': 'openid profile email'}),
        'user_id_property': 'employee_id', 'sign_ups': 'Deny', 'icon': 'fa fa-building',
    }
    provider = create('Social Login Key', values, 'company')
    provider.update(values)
    provider.save()


def configure_notifications(configuration):
    chat = configuration.get('chat')
    if not chat:
        return
    authorization = b64encode((chat['email'] + ':' + chat['api_key']).encode()).decode()
    script = (
        "try:\n"
        "    frappe.make_post_request(" + repr(chat['url'] + '/api/v1/messages') + ",\n"
        "        headers=" + repr({'Authorization': 'Basic ' + authorization, 'Host': chat['host']}) + ",\n"
        "        data={'type': 'stream', 'to': 'finance', 'topic': 'Expense approvals',\n"
        "              'content': doc.employee_name + ' expense ' + doc.name + ': ' + str(doc.total_sanctioned_amount) + ' ' + doc.company})\n"
        "except Exception:\n"
        "    frappe.log_error(title='Company chat notification failed')\n"
    )
    values = {'name': 'Company Expense Notification',
              'script_type': 'DocType Event', 'reference_doctype': 'Expense Claim',
              'doctype_event': 'After Submit', 'script': script, 'disabled': 0}
    notification = create('Server Script', values, 'Company Expense Notification')
    notification.update(values)
    notification.save()


def main():
    marker = SITES / SITE / '.company-initialized'
    configuration = json.loads(Path('/opt/emuvista-erp/company.json').read_text())
    os.chdir(SITES)
    frappe.init(site=SITE, sites_path=str(SITES))
    frappe.connect()
    frappe.set_user('Administrator')
    try:
        if not marker.exists():
            company, departments = configure_company(configuration)
            configure_identity()
            configure_employees(configuration, company, departments)
            configure_leave(configuration, company)
        configure_profile_consistency()
        configure_single_sign_on(configuration)
        configure_notifications(configuration)
        business_marker = SITES / SITE / '.company-business-initialized'
        if not business_marker.exists():
            initialize_business(configuration, create)
        frappe.db.set_single_value('System Settings', 'setup_complete', 1)
        frappe.db.set_single_value('System Settings', 'enable_onboarding', 0)
        frappe.clear_cache()
        frappe.db.commit()
        marker.write_text('Company initialized.\n')
        business_marker.write_text('Company operations initialized.\n')
        print('Company employees, shared accounts, and leave allocations are ready.')
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()


if __name__ == '__main__':
    main()
