#!/usr/bin/env python3
"""Read-only, host-side observer for the E99 agent containers."""

import argparse
import errno
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import inspect
import math
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent

def scrub(value, secrets=()):
    """Keep complete business observations while removing authentication material."""
    if isinstance(value, dict):
        return {key: '[redacted]' if re.search(r'password|secret|token|api.?key|otp|^authorization$|authorization.?code', key, re.I)
                else scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, '[redacted]')
        value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[redacted]', value)
        value = re.sub(r'(?i)\b(Bearer|Basic)\s+\S+', r'\1 [redacted]', value)
        return re.sub(r'(?i)(\b(?:verification|security|login|one[- ]time)\s+code\s*(?:is\s*)?[:：]?\s*)([a-z0-9]{4,12})\b',
                      r'\1[redacted]', value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# Only read local logs, public metadata and recent resident observations.
# Credentials are used for redaction inside the container and never exported.
COLLECT = 'import math,re\n' + inspect.getsource(scrub) + r'''

import fcntl,glob,json,pathlib,socket,struct
p=pathlib.Path('/home/emuvista-agent/agent.log')
text='';modified=None
if p.is_file():
    modified=p.stat().st_mtime
    with p.open('rb') as f:
        offset=max(0,p.stat().st_size-2097152);f.seek(offset)
        if offset:f.readline()
        text=f.read(2097152).decode(errors='replace')
running=False
for path in glob.glob('/proc/[0-9]*/cmdline'):
    try:
        parts=pathlib.Path(path).read_bytes().split(b'\0')
        if b'emuvista_agent' in parts and b'run' in parts:
            running=True;break
    except (OSError,PermissionError):pass
address=None
for _,interface in socket.if_nameindex():
    if interface=='lo':continue
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            address=socket.inet_ntoa(fcntl.ioctl(s.fileno(),0x8915,struct.pack('256s',interface.encode()[:15]))[20:24])
        break
    except OSError:pass
configuration={}
profile={}
try:
    configuration=json.loads(pathlib.Path('/etc/emuvista-agent/config.json').read_text())
    persona=configuration.get('services',{}).get('persona',{})
    profile={'name':configuration['identity'],'tools':configuration.get('allowed_tools',[]),
             'description':persona.get('background',persona.get('task','')),
             'mode':persona.get('mode','legacy')}
except (OSError,ValueError,KeyError):pass
secrets=set()
def find_secrets(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if re.search(r'password|secret|token|api.?key',key,re.I) and isinstance(item,str) and item:
                secrets.add(item)
            else:find_secrets(item)
    elif isinstance(value,list):
        for item in value:find_secrets(item)
find_secrets(configuration.get('services',{}))
activities=[]
sales=[]
try:
    directory=configuration.get('services',{}).get('life',{}).get('directory')
    path=pathlib.Path(directory)/'experience.json' if directory else None
    if path and path.is_file() and path.stat().st_size<=2097152:
        saved=json.loads(path.read_text()).get('activities',[])
        activities=[{key:item[key] for key in ('id','time','tool','arguments','status','observation') if key in item}
                    for item in saved[-40:] if isinstance(item,dict)]
except (OSError,ValueError,TypeError):pass
try:
    directory=configuration.get('services',{}).get('shop',{}).get('directory')
    path=pathlib.Path(directory)/'orders.json' if directory else None
    if path and path.is_file() and path.stat().st_size<=2097152:
        orders=json.loads(path.read_text()).values()
        sales=[item for item in orders if item.get('status')=='delivered']
        sales=sorted(sales,key=lambda item:item.get('created',''),reverse=True)[:30]
except (OSError,ValueError,TypeError,AttributeError):pass
for secret in sorted(secrets,key=len,reverse=True):text=text.replace(secret,'[redacted]')
print(json.dumps({'log':text,'activities':scrub(activities,secrets),'modified':modified,
                  'sales':scrub(sales,secrets),'process_running':running,'address':address,'profile':profile}))
'''


def discover(output):
    """Read only public metadata from compiler-staged agent configuration."""
    agents = []
    for folder in sorted(output.glob('hnode_*_agent_*')):
        dockerfile = folder/'Dockerfile'
        if not dockerfile.is_file():
            continue
        match = re.search(r'^COPY ([a-f0-9]{32}) /etc/emuvista-agent/config\.json$',
                          dockerfile.read_text(), re.M)
        if not match:
            continue
        configuration = json.loads((folder/match[1]).read_text())
        persona = configuration.get('services', {}).get('persona', {})
        agents.append({'name': configuration['identity'], 'service': folder.name,
                       'description': persona.get('background', persona.get('task', '')),
                       'mode': persona.get('mode', 'legacy'),
                       'tools': configuration.get('allowed_tools', [])})
    return agents


def parse_events(log):
    events = []
    for line in log.splitlines()[-1200:]:
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict):
            events.append(scrub(event))
    # Retain only the current process run when a log contains multiple runs.
    run = next((event['run_id'] for event in reversed(events) if event.get('run_id')), None)
    if run:
        events = [event for event in events if event.get('run_id') == run]
    return events[-500:]


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def _compatible(recorded, visible):
    if visible == '[redacted]':
        return True
    if isinstance(visible, dict) and isinstance(recorded, dict):
        return all(key in recorded and _compatible(recorded[key], item) for key, item in visible.items())
    if isinstance(visible, list) and isinstance(recorded, list):
        return len(visible) == len(recorded) and all(_compatible(a,b) for a,b in zip(recorded,visible))
    return recorded == visible


def enrich_calls(calls, activities):
    """Recover older details only when one memory record matches time/tool/arguments."""
    for call in calls.values():
        if call.get('detail_version') == 2:
            continue
        started = _time(call.get('timestamp'))
        if not started:
            continue
        candidates = []
        for activity in activities:
            observed = _time(activity.get('time'))
            arguments = activity.get('arguments')
            if (activity.get('tool') == call.get('tool') and observed
                    and abs((observed-started).total_seconds()) <= 2
                    and isinstance(arguments,dict) and not arguments.get('truncated')
                    and _compatible(arguments,call.get('arguments',{}))):
                candidates.append(activity)
        if len(candidates) != 1:
            continue
        activity = candidates[0]
        call['arguments'] = activity['arguments']
        call['arguments_source'] = 'resident_memory'
        if 'observation' in activity:
            call['result'] = activity['observation']
            call['result_source'] = 'resident_memory'


def summarize(metadata, container, observation=None, error=None):
    observation = observation or {}
    metadata = {**metadata, **scrub(observation.get('profile', {}))}
    events = parse_events(observation.get('log', ''))
    calls, active = {}, {}
    phase, terminal, last_error, reply, round_number = 'starting', None, None, '', None
    cycle, intention, rest_reason, wake_at = None, '', '', None
    for index, event in enumerate(events):
        kind = event.get('event')
        if 'round' in event:
            round_number = event['round']
        if 'cycle' in event:
            cycle = event['cycle']
        if 'intention' in event:
            intention = event['intention']
        if kind == 'run_started':
            calls.clear(); active.clear(); terminal = None
        if kind in ('starting', 'waiting', 'paused', 'round_started', 'round_completed', 'readiness_timeout'):
            phase = {'round_started': 'running', 'round_completed': 'running',
                     'readiness_timeout': 'running'}.get(kind, kind)
        if kind in ('waking', 'moment_completed'):
            phase, wake_at, rest_reason = 'running', None, ''
            if kind == 'moment_completed':
                last_error = None
        if kind in ('resting', 'recovering'):
            phase = kind
            rest_reason, wake_at = event.get('reason', ''), event.get('wake_at')
        if event.get('message'):
            reply = event['message']
        if kind in ('round_failed', 'moment_failed', 'run_failed') or event.get('error'):
            last_error = event.get('error', 'Agent execution failed')
        if kind == 'run_failed' or event.get('status') == 'failed':
            terminal = 'failed'
        if event.get('status') == 'complete':
            terminal = 'completed'
        if kind == 'tool_started':
            identifier = event.get('call_id', str(index))
            call = {'id': identifier, 'tool': event.get('tool'), 'status': 'running',
                    'timestamp': event.get('timestamp'), 'arguments': event.get('arguments', {}),
                    'detail_version': event.get('detail_version', 1), 'arguments_source': 'event',
                    'source': event.get('source', 'agent')}
            calls[identifier] = active[identifier] = call
        elif kind in ('tool_finished', 'tool_failed'):
            identifier = event.get('call_id', str(index))
            call = calls.setdefault(identifier, {'id': identifier, 'tool': event.get('tool')})
            timestamp = call.get('timestamp')
            if not timestamp:
                finished = _time(event.get('timestamp'))
                timestamp = (finished-timedelta(milliseconds=event.get('duration_ms') or 0)).isoformat() if finished else None
            call.update(status=event.get('status', 'error' if kind == 'tool_failed' else 'success'),
                        source=event.get('source', call.get('source', 'agent')),
                        timestamp=timestamp,
                        duration_ms=event.get('duration_ms'), result=event.get('result'),
                        summary=event.get('summary'), result_source='event' if event.get('detail_version') == 2 else 'summary',
                        detail_version=event.get('detail_version', call.get('detail_version',1)),
                        error=event.get('error'))
            active.pop(identifier, None)
        elif kind == 'tool':  # Existing E99 images report completion only.
            phase = 'running'
            calls['legacy-'+str(index)] = {'id': 'legacy-'+str(index), 'tool': event.get('tool'),
                                           'status': event.get('status', 'success'),
                                           'timestamp': event.get('timestamp'), 'error': event.get('error')}
    enrich_calls(calls, scrub(observation.get('activities', [])))
    container_state = container.get('State', 'not_created')
    if error:
        status = 'unavailable'
    elif container_state != 'running':
        status = {'not_created':'not_started', 'created':'not_started',
                  'restarting':'starting', 'paused':'container_paused'}.get(container_state, 'stopped')
    elif observation.get('process_running'):
        status = 'calling_tool' if active else phase
    elif terminal:
        status = terminal
    elif observation.get('log'):
        status = 'failed'
        last_error = last_error or 'Process ended before emitting a completion event. Inspect the local startup log.'
    else:
        status = 'starting'
    if container_state != 'running' or status in ('failed', 'stopped', 'completed', 'not_started', 'unavailable'):
        for call in active.values():
            call['status'] = 'unknown' if status == 'unavailable' else 'suspended' if container_state == 'paused' else 'interrupted'
        active = {}
    address = observation.get('address')
    if not address:
        match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', container.get('Name', ''))
        address = match[0] if match else None
    latest = events[-1] if events else {}
    return {**metadata, 'status': status, 'container_state': container_state, 'address': address,
            'sales':scrub(observation.get('sales',[])),
            'round': round_number, 'last_update': latest.get('timestamp'),
            'cycle': cycle, 'intention': intention, 'rest_reason': rest_reason, 'wake_at': wake_at,
            'run_id': latest.get('run_id'), 'detailed_events': any(e.get('run_id') for e in events),
            'active_tools': list(active.values()), 'calls': list(calls.values())[-150:],
            'events': events[-150:], 'reply': reply, 'error': error or last_error,
            'waiting_for': latest.get('services', []) if phase == 'waiting' else [],
            'tool_count': len(calls),
            'failure_count': sum(c['status'] in ('error', 'denied', 'interrupted') for c in calls.values())}


class Observer:
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.agents = discover(self.output)
        if not self.agents:
            raise ValueError('No compiled agents found. Run python3 experiment.py first, or specify --output.')
        self.lock = threading.Lock()
        self.observations = {}
        self.stop = threading.Event()
        self.snapshot = {'updated': None, 'error': None,
                         'agents': [summarize(a, {}) for a in self.agents]}

    def command(self, *args):
        command = ['docker', 'compose', *args]
        result = subprocess.run(command, cwd=self.output, text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise RuntimeError(scrub(result.stderr.strip()[-350:]) or 'Docker observation command failed')
        return result.stdout

    def refresh(self):
        try:
            current = discover(self.output)
            if current:
                self.agents = current
            raw = self.command('ps', '--all', '--format', 'json')
            try:
                entries = json.loads(raw or '[]')
                if isinstance(entries, dict): entries = [entries]
            except ValueError:
                entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
            containers = {item['Service']: item for item in entries}

            def collect(agent):
                container = containers.get(agent['service'], {})
                if container.get('State') != 'running':
                    return summarize(agent, container, self.observations.get(agent['service']))
                try:
                    raw = self.command('exec', '-T', '--user', 'emuvista-agent', agent['service'],
                                       'python3', '-c', COLLECT)
                    observation = json.loads(raw)
                    self.observations[agent['service']] = observation
                    return summarize(agent, container, observation)
                except subprocess.TimeoutExpired:
                    return summarize(agent, container, self.observations.get(agent['service']),
                                     error='Timed out reading agent status. Observation will retry.')
                except (OSError, ValueError, RuntimeError) as error:
                    return summarize(agent, container, self.observations.get(agent['service']), error=str(error))

            with ThreadPoolExecutor(max_workers=min(8, len(self.agents))) as pool:
                agents = list(pool.map(collect, self.agents))
            error = None
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exception:
            error = 'Docker status lookup timed out. Observation will retry.' if isinstance(exception, subprocess.TimeoutExpired) else str(exception)
            agents = [summarize(agent, {}, self.observations.get(agent['service']),
                                error='Docker status unavailable') for agent in self.agents]
        with self.lock:
            self.snapshot = {'updated': datetime.now(timezone.utc).isoformat(),
                             'error': error, 'agents': agents}

    def watch(self):
        while not self.stop.is_set():
            self.refresh()
            self.stop.wait(2)

    def state(self):
        with self.lock:
            return self.snapshot


def make_handler(observer):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                host = urlsplit('http://'+self.headers.get('Host', '')).hostname
            except ValueError:
                host = None
            if host not in ('127.0.0.1', 'localhost', '::1'):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path == '/api/state':
                data = json.dumps(observer.state(), allow_nan=False).encode()
                content_type = 'application/json'
            elif path in ('/', '/app.js', '/style.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
                data = (HERE/'dashboard'/name).read_bytes()
                content_type = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[path]
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type+'; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE/'output')
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('port must be between 1 and 65535')
    try:
        observer = Observer(args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(observer))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            parser.error(f'Port {args.port} is already in use. Stop the existing listener or choose another port with --port, for example --port 8091.')
        parser.error(str(error))
    worker = threading.Thread(target=observer.watch, daemon=True)
    worker.start()
    print(f'Agent dashboard: http://localhost:{args.port}', flush=True)
    print('Read-only observation. Press Ctrl+C to close the dashboard; agents keep running.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop.set()
        server.server_close()
        worker.join(timeout=12)


if __name__ == '__main__':
    main()
