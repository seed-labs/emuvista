"""Startup files copied into the generated Compose deployment."""

DATABASE_START = r'''#!/bin/bash
set -euo pipefail
if [ "$(id -u)" = 0 ]; then
  mkdir -p "$PGDATA" /var/run/postgresql
  chown -R postgres:postgres "$PGDATA" /var/run/postgresql
  exec gosu postgres "$0" "$@"
fi
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  initdb --username=postgres --pwfile=<(printf '%s\n' "$POSTGRES_PASSWORD") --auth-local=trust --auth-host=scram-sha-256
  pg_ctl -D "$PGDATA" -o "-p $PGPORT -h 127.0.0.1" -w start
  trap 'pg_ctl -D "$PGDATA" -m immediate -w stop' EXIT
  /usr/local/bin/init-app-db.sh
  createdb -U postgres -O "$POSTGRES_APP_USER" "$POSTGRES_APP_USER"
  pg_ctl -D "$PGDATA" -m fast -w stop
  trap - EXIT
fi
exec postgres -D "$PGDATA" -p "$PGPORT" -h 127.0.0.1
'''

BACKEND_START = r'''#!/bin/sh
set -eu
cd /app
attempt=0
until node node_modules/prisma/build/index.js migrate deploy; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then exit 1; fi
  sleep 2
done
exec node dist/index.mjs
'''

INITIALIZE = r'''import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFile,writeFile,rename,mkdir} from 'node:fs/promises';

const state='/payment-state';
const marker=state+'/initialized.json';
const bundle='/payment-config/initial.zip';
const cli='/app/shared/cli/index.ts';
const run=args=>new Promise((resolve,reject)=>{
  const p=spawn(process.execPath,[cli,...args],{stdio:'inherit',env:process.env});
  p.once('error',reject);p.once('exit',code=>code===0?resolve():reject(new Error('Payment initialization command failed: '+code)));
});
async function main(){
  const fingerprint=process.env.INITIAL_DATA_SHA256 || '';
  let previous;
  try{previous=JSON.parse(await readFile(marker,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
  if(previous && previous.fingerprint!==fingerprint)throw new Error('Initial wallet data differs from saved state; use a new state directory');
  await run(['admin','bootstrap']);
  if(!previous && fingerprint){
    const content=await readFile(bundle);
    if(createHash('sha256').update(content).digest('hex')!==fingerprint)throw new Error('Initial bundle checksum mismatch');
    await run(['admin','migrate',bundle]);
  }
  if(previous){
    const tokenResponse=await fetch(process.env.KOMUNITIN_AUTH_URL+'/token',{
      method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({grant_type:'password',client_id:'komunitin-app',username:process.env.ADMIN_EMAIL,password:process.env.ADMIN_PASSWORD,scope:'email superadmin social:read accounting:read'})});
    if(!tokenResponse.ok)throw new Error('Saved payment administrator cannot log in');
  }
  await mkdir(state,{recursive:true});
  await writeFile(marker+'.tmp',JSON.stringify({fingerprint,initialized:new Date().toISOString()})+'\n',{mode:0o600});
  await rename(marker+'.tmp',marker);
  console.log('PaymentService initialization complete; wallet gateway may start.');
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
'''


def nginx_config(address: str, host_access: bool = False) -> str:
    servers = [f'''server {{
      listen 443 ssl;
      server_name _;
      ssl_certificate /payment-config/server.crt;
      ssl_certificate_key /payment-config/server.key;
      location = /healthz {{ default_type application/json; return 200 '{{"status":"ready"}}'; }}
      location / {{ proxy_pass http://127.0.0.1:80; proxy_set_header Host $http_host; }}
    }}''']
    for public, private in [(2026, 3026), (2028, 3028), (2025, 3025), (2023, 3023), (9191, 9090)]:
        servers.append(f'''server {{
      listen {public} ssl;
      server_name _;
      ssl_certificate /payment-config/server.crt;
      ssl_certificate_key /payment-config/server.key;
      client_max_body_size 50m;
      location / {{
        proxy_pass http://127.0.0.1:{private};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        proxy_read_timeout 600s;
      }}
    }}''')
    if host_access:
        # Rewrite browser-facing configuration and JSON links on this endpoint
        # only. Emulated clients retain the canonical IP-based API endpoints.
        routes = [('auth', 2026, 3026), ('social', 2028, 3028),
                  ('accounting', 2025, 3025), ('notifications', 2023, 3023),
                  ('files', 9191, 9090)]
        rewrites = '\n'.join(
            f"sub_filter 'https://{address}:{public}' '$scheme://$http_host/{path}';"
            for path, public, _ in routes)
        locations = '\n'.join(
            f'location /{path}/ {{ proxy_pass http://127.0.0.1:{private}/; }}'
            for path, _, private in routes)
        servers.append(f'''server {{
      listen 8443 ssl;
      server_name _;
      ssl_certificate /payment-config/server.crt;
      ssl_certificate_key /payment-config/server.key;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_set_header Accept-Encoding "";
      proxy_buffering off;
      proxy_read_timeout 600s;
      client_max_body_size 50m;
      sub_filter_types application/javascript text/javascript application/json application/vnd.api+json text/css application/manifest+json;
      sub_filter_once off;
      {rewrites}
      sub_filter 'https://{address}/' '$scheme://$http_host/';
      sub_filter 'https://{address}"' '$scheme://$http_host"';
      {locations}
      location = /healthz {{ default_type application/json; return 200 '{{"status":"ready"}}'; }}
      location / {{ proxy_pass http://127.0.0.1:80; }}
    }}''')
    return 'events {}\nhttp {\nmap $http_upgrade $connection_upgrade { default upgrade; \'\' close; }\n' + '\n'.join(servers) + '\n}\n'
