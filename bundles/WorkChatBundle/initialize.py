"""Seed the native organization, employee profiles and company channels."""

import json
import os
from pathlib import Path

from zerver.actions.create_realm import do_create_realm
from zerver.actions.create_user import do_create_user
from zerver.actions.streams import bulk_add_subscriptions
from zerver.lib.cache import flush_user_profile
from zerver.lib.streams import create_stream_if_needed
from zerver.models import CustomProfileField, CustomProfileFieldValue, Realm, UserProfile

configuration = json.loads(Path('/chat-config/company.json').read_text())
realm = Realm.objects.filter(string_id='').first()
if realm is None:
    realm = do_create_realm('', configuration['company']['name'], invite_required=True,
                            org_type=Realm.ORG_TYPES['business']['id'])
admin = UserProfile.objects.filter(realm=realm, delivery_email='admin@company.com').first()
if admin is None:
    admin = do_create_user('admin@company.com', 'WorkChatAdminDemo123!', realm,
                           'Company Administrator', role=UserProfile.ROLE_REALM_OWNER,
                           acting_user=None, enable_marketing_emails=False)
admin.api_key = os.environ['DIRECTORY_API_KEY']
admin.can_create_users = True
admin.save(update_fields=['api_key', 'can_create_users'])
flush_user_profile(instance=admin)
field, _ = CustomProfileField.objects.get_or_create(
    realm=realm, name='Employee ID', defaults={'field_type': CustomProfileField.SHORT_TEXT,
                                               'editable_by_user': False})
users = [admin]
for person in configuration['employees']:
    record = CustomProfileFieldValue.objects.filter(field=field, value=person['id']).select_related('user_profile').first()
    user = record.user_profile if record else UserProfile.objects.filter(
        realm=realm, delivery_email__iexact=person['email']).first()
    if user is None:
        user = do_create_user(person['email'], None, realm,
                               person['firstName'] + ' ' + person['lastName'],
                               acting_user=None, enable_marketing_emails=False)
    CustomProfileFieldValue.objects.update_or_create(
        user_profile=user, field=field, defaults={'value': person['id']})
    users.append(user)
channels = [create_stream_if_needed(realm, name, acting_user=admin)[0]
            for name in ('general', 'engineering', 'human-resources', 'finance', 'support')]
bulk_add_subscriptions(realm, channels, users, acting_user=admin)
print('Company chat organization, employee profiles and channels are ready.', flush=True)
