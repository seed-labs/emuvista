"""Opt-in HTTP for the isolated emulator; preserve HTTPS unless explicitly enabled."""
from pathlib import Path

root = Path('/opt/mastodon/config')
patches = {
    'environments/production.rb': (
        'config.force_ssl = true',
        "config.force_ssl = ENV['EMUVISTA_HTTP'] != 'true'"),
    'initializers/1_hosts.rb': (
        "https = Rails.env.production? || ENV['LOCAL_HTTPS'] == 'true'",
        "https = ENV['EMUVISTA_HTTP'] != 'true' && (Rails.env.production? || ENV['LOCAL_HTTPS'] == 'true')"),
}
for filename, (old, new) in patches.items():
    path = root / filename
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f'Mastodon HTTP patch no longer matches {filename}')
    path.write_text(content.replace(old, new))
