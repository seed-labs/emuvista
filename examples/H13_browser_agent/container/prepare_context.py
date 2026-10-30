"""Prepare the browser-agent Docker build context."""
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent


def prepare_context(output):
    """Copy agent source and model profiles, excluding caches and other local files."""
    source = HERE.parent / 'agent'
    context = Path(output) / 'browser-agent'
    context.mkdir()
    for name in ('Dockerfile', 'start.sh', 'launch_browser.js'):
        shutil.copyfile(HERE / name, context / name)
    shutil.copyfile(HERE.parent / 'egress_urls.txt', context / 'egress_urls.txt')
    target = context / 'agent'
    target.mkdir()
    # Seed profiles in the image and persist updates through the host mount.
    profiles = source / 'model_profiles.json'
    if profiles.is_file():
        shutil.copyfile(profiles, target / profiles.name)
        (target / profiles.name).chmod(0o600)
    for name in ('requirements.txt', 'agent_web.py', 'domain_agent.py', 'agent_web.html',
                 'agent_web.js', 'browser_viewer.html'):
        shutil.copyfile(source / name, target / name)
    for package in ('browser_runtime', 'local_tools'):
        for path in (source / package).rglob('*.py'):
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
