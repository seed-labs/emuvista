"""Mastodon development startup, account initialization and gateway templates."""

SOURCE = '/workspaces/mastodon'

# Each Mastodon container starts in the checkout, as the devcontainer's app does.
APPLICATION_START = f'''#!/bin/sh
cd {SOURCE} || exit 1
exec "$@"
'''

# The devcontainer runs bin/setup (bundle, yarn, db:prepare) after it starts.
# Dependencies are part of the image, so only the database step remains here.
INITIALIZE_SH = f'''#!/bin/sh
set -eu
cd {SOURCE}
bin/rails db:prepare
exec bin/rails runner /social-config/initialize.rb
'''

# Account creation follows mastodon/example/create_user.rb.
INITIALIZE = r'''# frozen_string_literal: true

require 'json'
require 'pathname'

cfg = JSON.parse(File.read('/social-config/initial.json'))
record = Pathname.new('/social-state/initialized.json')

if record.exist?
  saved = JSON.parse(record.read)
  abort('Initial social network configuration differs from saved state') unless saved['fingerprint'] == cfg['fingerprint']
  puts 'Social network state already initialized'
  exit 0
end

configuration = cfg['configuration']

Chewy.strategy(:bypass) do
  # db:prepare seeds a new development database, including the built-in Owner.
  Rails.application.load_seed if Account.find_local(cfg['admin']).nil?

  Setting.site_title = configuration['title'] if configuration['title']
  Setting.registrations_mode = configuration['registrations'] if configuration['registrations']

  accounts = {}
  configuration['users'].each do |entry|
    username = entry['username']
    account = Account.find_local(username)

    if account
      puts "Account already exists: #{username}"
    else
      account = Account.new(username: username)

      user = User.new(
        email: entry['email'],
        password: entry['password'],
        password_confirmation: entry['password'],
        agreement: true,
        confirmed_at: Time.current,
        bypass_registration_checks: true,
        role: entry['role'] && UserRole.find_by!(name: entry['role'])
      )

      user.account = account

      user.save!

      user.mark_email_as_confirmed!
      user.approve! unless user.approved?

      puts "Created #{username}"
    end

    profile = entry.slice('display_name', 'note')
    account.update!(profile) if profile.any?
    accounts[username] = account
  end

  configuration['users'].each do |entry|
    account = accounts.fetch(entry['username'])

    entry.fetch('follows', []).each do |name|
      target = accounts[name] || Account.find_local!(name)
      FollowService.new.call(account, target) unless account.following?(target)
    end

    entry.fetch('posts', []).each do |text|
      PostStatusService.new.call(account, text: text, visibility: 'public') unless account.statuses.exists?(text: text)
    end
  end
end

record.dirname.mkpath
temporary = record.sub_ext('.tmp')
temporary.write("#{JSON.generate(fingerprint: cfg['fingerprint'])}\n")
temporary.rename(record)
puts 'Mastodon accounts, follows and posts initialized'
'''

_GATEWAY = r'''worker_processes 2;
events { worker_connections 1024; }

http {
  include /etc/nginx/mime.types;
  sendfile on;
  keepalive_timeout 70;
  client_max_body_size 99m;
  proxy_read_timeout 300s;

  map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
  }
@SERVERS@}
'''

_SERVER = r'''
  server {
    listen @PORT@;
    server_name _;

    location = /healthz {
      access_log off;
      default_type text/plain;
      return 200 "OK\n";
    }

    location ^~ /api/v1/streaming {
      proxy_pass http://@STREAMING@:4000;
@PROXY@      proxy_buffering off;
@STREAM_REWRITE@    }

    location / {
      proxy_pass http://@WEB@:3000;
@PROXY@@WEB_REWRITE@    }
  }
'''

_PROXY = r'''      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto http;
      proxy_set_header Proxy "";
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      tcp_nodelay on;
'''

# Mastodon writes absolute URLs for LOCAL_DOMAIN. The localhost server rewrites
# them, and points the web app at HTTP streaming (server-sent events), whose
# responses can be rewritten in the same way as pages and API results.
_REWRITE = r'''      proxy_set_header Accept-Encoding "";
      proxy_redirect http://@HOST@/ http://$http_host/;
      sub_filter_once off;
      sub_filter_types @TYPES@;
      sub_filter 'http://@HOST@/' 'http://$http_host/';
      sub_filter 'http:\\/\\/@HOST@\\/' 'http:\\/\\/$http_host\\/';
'''

_STREAMING_URL = r'''      sub_filter 'ws://@HOST@' 'http://$http_host';
      sub_filter 'ws:\\/\\/@HOST@' 'http:\\/\\/$http_host';
'''

_API_TYPES = ('application/json application/activity+json application/ld+json application/jrd+json '
              'application/manifest+json application/xrd+xml')


def gateway_config(addresses, hostname, host_port=None):
    """Serve emulated clients on port 80 and, optionally, the host browser."""
    def server(port, rewrite):
        if rewrite:
            stream = _REWRITE.replace('@TYPES@', 'text/event-stream application/json')
            web = _REWRITE.replace('@TYPES@', _API_TYPES) + _STREAMING_URL
        else:
            stream = web = '      proxy_redirect off;\n'
        return (_SERVER.replace('@PROXY@', _PROXY).replace('@STREAM_REWRITE@', stream)
                .replace('@WEB_REWRITE@', web).replace('@PORT@', str(port)))

    servers = server(80, False) + (server(host_port, True) if host_port else '')
    return (_GATEWAY.replace('@SERVERS@', servers).replace('@HOST@', hostname)
            .replace('@WEB@', addresses['web']).replace('@STREAMING@', addresses['streaming']))
