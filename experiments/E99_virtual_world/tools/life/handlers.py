"""Personal memory and self-selected wake times, local to each resident."""

from datetime import datetime, timezone
import json
from pathlib import Path
import os
import tempfile
import threading
import time

_lock = threading.RLock()


def _path(context):
    directory = Path(context.service('life')['directory'])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory/'personal.json'


def _load(path):
    if not path.exists():
        return {'notes': [], 'intention': '', 'rest': {}}
    try:
        state = json.loads(path.read_text())
        if not isinstance(state, dict) or not isinstance(state.get('notes'), list):
            raise ValueError('Invalid personal memory')
        return state
    except (ValueError, OSError):
        raise RuntimeError('Personal memory could not be read; inspect the resident memory directory') from None


def _save(path, state):
    descriptor, temporary = tempfile.mkstemp(prefix='.personal-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(state, output)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def recall(arguments, context):
    with _lock:
        return _load(_path(context))


def remember(arguments, context):
    with _lock:
        path = _path(context)
        state = _load(path)
        note = arguments['note']
        if not state['notes'] or state['notes'][-1]['note'] != note:
            state['notes'].append({'time': datetime.now(timezone.utc).isoformat(), 'note': note})
        state['notes'] = state['notes'][-40:]
        if 'intention' in arguments:
            state['intention'] = arguments['intention']
        _save(path, state)
    context.emit('memory_updated', intention=state['intention'], entries=len(state['notes']))
    return {'remembered': True, 'intention': state['intention']}


def rest(arguments, context):
    now = time.time()
    seconds = arguments['seconds']
    wake_at = now + seconds
    with _lock:
        path = _path(context)
        state = _load(path)
        state['rest'] = {'set_at': now, 'wake_at': wake_at, 'reason': arguments['reason']}
        _save(path, state)
    wake_time = datetime.fromtimestamp(wake_at, timezone.utc).isoformat()
    context.emit('rest_scheduled', seconds=seconds, reason=arguments['reason'], wake_at=wake_time)
    return {'resting': True, 'seconds': seconds, 'wakeAt': wake_time, 'reason': arguments['reason']}
