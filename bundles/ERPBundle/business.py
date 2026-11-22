"""Configure native company operations without replacing upstream workflows."""

from datetime import date

import frappe


def initialize(configuration, create):
    data = configuration.get('business')
    if not data:
        return
    company = frappe.get_doc('Company', configuration['company']['name'])
    year = date.today().year
    for person in configuration['employees']:
        user = frappe.get_doc('User', person['email'])
        user.append_roles(*person['roles'])
        user.save()
        if person.get('reportsTo'):
            approver = next(row['email'] for row in configuration['employees'] if row['id'] == person['reportsTo'])
            frappe.db.set_value('Employee', person['id'], 'expense_approver', approver)
    travel = frappe.db.get_value('Account', {'company': company.name, 'account_name': 'Travel Expenses'})
    company.default_expense_claim_payable_account = company.default_payable_account
    company.save()
    expense_type = create('Expense Claim Type', {'expense_type': 'Travel', 'accounts': [
        {'company': company.name, 'default_account': travel},
    ]}, 'Travel')
    if not any(row.company == company.name for row in expense_type.accounts):
        expense_type.append('accounts', {'company': company.name, 'default_account': travel})
        expense_type.save()
    create('Project Type', {'project_type': 'Internal'}, 'Internal')
    create('Project', {'project_name': data['project'], 'project_type': 'Internal',
                       'company': company.name, 'status': 'Open'}, {'project_name': data['project']})
    create('Supplier', {'supplier_name': data['supplier'], 'supplier_type': 'Company',
                        'supplier_group': 'All Supplier Groups'}, {'supplier_name': data['supplier']})
    create('Customer', {'customer_name': data['customer'], 'customer_type': 'Company',
                        'customer_group': 'Commercial', 'territory': 'Rest Of The World'},
           {'customer_name': data['customer']})
    item = data['item']
    create('Item', {'item_code': item['code'], 'item_name': item['name'], 'item_group': 'Products',
                    'stock_uom': 'Nos', 'is_stock_item': 1}, item['code'])
    for price_list in ('Standard Buying', 'Standard Selling'):
        create('Item Price', {'item_code': item['code'], 'price_list': price_list,
                              'price_list_rate': item['price'], 'currency': company.default_currency},
               {'item_code': item['code'], 'price_list': price_list})

    salary_account = frappe.db.get_value('Account', {'company': company.name, 'account_name': 'Salary'})
    create('Salary Component', {'salary_component': 'Basic Salary', 'salary_component_abbr': 'BASIC',
                                'type': 'Earning', 'accounts': [
                                    {'company': company.name, 'default_account': salary_account},
                                ]}, 'Basic Salary')
    structure = create('Salary Structure', {
        'name': 'Company Monthly Salary', 'company': company.name, 'currency': company.default_currency,
        'is_active': 'Yes', 'payroll_frequency': 'Monthly',
        'earnings': [{'salary_component': 'Basic Salary', 'amount_based_on_formula': 1, 'formula': 'base'}],
    }, 'Company Monthly Salary')
    if structure.docstatus == 0:
        structure.submit()
    for person in configuration['employees']:
        assignment = create('Salary Structure Assignment', {
            'employee': person['id'], 'company': company.name, 'salary_structure': structure.name,
            'from_date': f'{year}-01-01', 'base': data['monthlySalary'], 'currency': company.default_currency,
        }, {'employee': person['id'], 'salary_structure': structure.name})
        if assignment.docstatus == 0:
            assignment.submit()
    create('Designation', {'designation_name': 'Software Engineer'}, 'Software Engineer')
    create('Job Opening', {'job_title': 'Software Engineer', 'designation': 'Software Engineer',
                           'company': company.name, 'status': 'Open'}, {'job_title': 'Software Engineer'})
    create('Appraisal Cycle', {'cycle_name': f'Company Review {year}', 'company': company.name,
                               'start_date': f'{year}-01-01', 'end_date': f'{year}-12-31'},
           {'cycle_name': f'Company Review {year}'})

    cash = frappe.db.get_value('Account', {'company': company.name, 'account_type': 'Cash', 'is_group': 0})
    equity = frappe.db.get_value('Account', {'company': company.name, 'root_type': 'Equity', 'is_group': 0})
    if not frappe.db.exists('Journal Entry', {'user_remark': 'Company opening capital'}):
        journal = frappe.get_doc({'doctype': 'Journal Entry', 'company': company.name,
                                  'voucher_type': 'Opening Entry', 'is_opening': 'Yes',
                                  'posting_date': f'{year}-01-01', 'user_remark': 'Company opening capital',
                                  'accounts': [
                                      {'account': cash, 'debit_in_account_currency': data['openingCash']},
                                      {'account': equity, 'credit_in_account_currency': data['openingCash']},
                                  ]}).insert()
        journal.submit()
