"""Supervise the persistent bot and optional AgentService LLM loop."""
import os
from pathlib import Path
import pwd
import signal
import subprocess
import time
from urllib.request import urlopen
import json
from emuvista_agent.launch import read_environment


def main():
    os.environ.update(read_environment('/run/minecraft-logging-trade.env', ('MC_', 'LLM_', 'AGENT_')))
    # E16 residents use doors; breaking obstacles requires an explicit dig_blocks call.
    os.environ['MC_PATHFINDER_CAN_DIG'] = 'false'
    # Accept older hostnames; simulated DNS resolves minecraft.com.
    if os.environ.get('MC_HOST', 'minecraft') in ('minecraft', 'minecraft.e16.test', 'minecraft.e16.com'):
        os.environ['MC_HOST'] = 'minecraft.com'
    identity = os.environ.get('MC_AGENT_NAME')
    config = json.loads(Path('/etc/emuvista-agent/config.json').read_text())
    if not identity or identity != config['identity']:
        raise ValueError('Container identity does not match its agent configuration')
    # Per-agent overrides prevent both clients from joining under the same name.
    prefix = 'MC_' + identity.upper() + '_'
    if not os.environ.get(prefix + 'USERNAME', '').strip():
        raise ValueError(f'Set {prefix}USERNAME in E16 .env')
    os.environ['MC_AUTH'] = os.environ.get(prefix + 'AUTH') or os.environ.get('MC_AUTH', 'offline')
    port = os.environ.get('MC_PORT', '')
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError('Set MC_PORT in E16 .env to the Compose server port (25565), then restart the agent')
    if os.environ.get('MC_AUTH', 'offline') not in ('offline', 'microsoft'):
        raise ValueError('MC_AUTH must be offline or microsoft')
    timeout = float(os.environ.get('MC_READY_TIMEOUT_SECONDS', '180'))
    if not 1 <= timeout <= 3600:
        raise ValueError('MC_READY_TIMEOUT_SECONDS must be between 1 and 3600')
    user = pwd.getpwnam('emuvista-agent')
    os.initgroups(user.pw_name, user.pw_gid)
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    os.environ['HOME'] = user.pw_dir
    os.chdir(user.pw_dir)
    children = []
    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        bot = subprocess.Popen(['node', '/opt/minecraft-bridge/server.js'])
        children.append(bot)
        if os.environ.get('LLM_API_KEY') and os.environ.get('LLM_MODEL'):
            deadline = time.monotonic() + timeout
            while True:
                if bot.poll() is not None:
                    raise RuntimeError('Minecraft bridge exited before joining')
                try:
                    with urlopen('http://127.0.0.1:8765/observe', timeout=2) as response:
                        if json.load(response)['connected']:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    print('MC join timed out; starting agent with actual offline status. Bridge will retry.', flush=True)
                    break
                time.sleep(2)
            log = open(Path(user.pw_dir) / 'agent.log', 'a', buffering=1)
            agent = subprocess.Popen(['/usr/local/bin/agentctl', 'run'], stdout=log, stderr=subprocess.STDOUT)
            children.append(agent)
            print(f'{identity} LLM started; log: /home/emuvista-agent/agent.log', flush=True)
        else:
            agent = None
            print('LLM_API_KEY/LLM_MODEL unset: bot-only mode; agentctl tools remain available.', flush=True)
        reported = False
        while bot.poll() is None:
            if agent is not None and agent.poll() is not None and not reported:
                print(f'{identity} LLM loop exited with code {agent.returncode}; bot remains connected for manual tools.', flush=True)
                reported = True
            time.sleep(1)
        raise RuntimeError(f'Minecraft bridge exited with code {bot.returncode}')
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    main()
