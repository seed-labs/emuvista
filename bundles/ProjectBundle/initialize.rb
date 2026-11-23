# Use the installed backend's own models and validation rules.
require 'json'

configuration = JSON.parse(File.read('/project-config/company.json'))
directory = configuration.fetch('ldap')
source = LdapAuthSource.find_or_initialize_by(name: 'Company employee directory')
source.assign_attributes(host: directory.fetch('host'), port: directory.fetch('port'),
                         tls_mode: :plain_ldap,
                         account: directory.fetch('bind_dn'), base_dn: 'ou=people,' + directory.fetch('base_dn'),
                         attr_login: 'uid', attr_firstname: 'givenName', attr_lastname: 'sn', attr_mail: 'mail',
                         onthefly_register: true, filter_string: '(employeeType=active)')
source.account_password = directory.fetch('password')
source.save!
Setting.api_tokens_enabled = true
admin = User.find_by!(login: 'admin')
admin.password = 'ProjectAdminDemo123!'
admin.password_confirmation = admin.password
admin.force_password_change = false
admin.ldap_auth_source = source
admin.save!
token = Token::API.for_user(admin).find { |row| row.token_name == 'Company directory' }
token ||= Token::API.new(user: admin, token_name: 'Company directory')
token.value = Token::API.hash_function(ENV.fetch('DIRECTORY_API_TOKEN'))
token.save!

configuration.fetch('employees').each do |person|
  user = User.find_or_initialize_by(login: person.fetch('id').downcase)
  user.ldap_auth_source = source
  if user.new_record?
    user.firstname = person.fetch('firstName')
    user.lastname = person.fetch('lastName')
    user.mail = person.fetch('email')
    user.status = :active
    user.force_password_change = false
  end
  user.save!
end

project = Project.find_or_initialize_by(identifier: 'company-operations')
project.workspace_type = 'project' if project.new_record?
project.name = configuration.fetch('business', {}).fetch('project', 'Company Operations')
project.public = false
project.enabled_module_names = ['work_package_tracking', 'wiki', 'time_tracking', 'calendar', 'news']
project.save!
if project.project_types.empty?
  Type.find_each { |type| project.project_types.create!(type: type) }
end
role = Role.find_by(name: 'Member') || Role.where(builtin: 0).first
configuration.fetch('employees').each do |person|
  user = User.find_by!(login: person.fetch('id').downcase)
  member = Member.find_or_initialize_by(project: project, principal: user)
  if member.new_record?
    member.roles = [role]
    member.save!
  end
end
puts 'Company projects, shared employee accounts and directory API are ready.'
