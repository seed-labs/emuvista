"""Mirror canonical employee attributes into a real read-only LDAP catalog."""

import ldap
from ldap.dn import escape_dn_chars
from ldap.modlist import addModlist, modifyModlist


def connect(settings):
    connection = ldap.initialize('ldap://' + settings['host'] + ':' + str(settings['port']))
    connection.set_option(ldap.OPT_NETWORK_TIMEOUT, 10)
    connection.simple_bind_s(settings['bind_dn'], settings['password'])
    return connection


def provision(person, settings):
    connection = connect(settings)
    try:
        base = 'ou=people,' + settings['base_dn']
        dn = 'uid=' + escape_dn_chars(person['id'].lower()) + ',' + base
        fields = {
            'objectClass': [b'top', b'person', b'organizationalPerson', b'inetOrgPerson'],
            'uid': [person['id'].lower().encode()], 'employeeNumber': [person['id'].encode()],
            'cn': [(person['firstName'] + ' ' + person['lastName']).encode()],
            'givenName': [person['firstName'].encode()], 'sn': [person['lastName'].encode()],
            'mail': [person['email'].encode()],
            'employeeType': [b'active' if person.get('active', True) else b'inactive'],
            'departmentNumber': [person['department'].encode()] if person.get('department') else [],
        }
        try:
            current = connection.search_s(dn, ldap.SCOPE_BASE, attrlist=list(fields))[0][1]
            changes = modifyModlist(current, fields)
            if changes:
                connection.modify_s(dn, changes)
        except ldap.NO_SUCH_OBJECT:
            connection.add_s(dn, addModlist({key: value for key, value in fields.items() if value}))
    finally:
        connection.unbind_s()
