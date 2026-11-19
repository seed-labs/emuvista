"""Call the persistent local Mineflayer bridge; never reconnect for each tool."""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, ProxyHandler, build_opener


def _call(context, path, arguments=None):
    base = context.tool_config['minecraft']['local']['bridge_url']
    body = None if arguments is None else json.dumps(arguments).encode()
    request = Request(base + path, data=body, headers={'Content-Type': 'application/json'})
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            return json.load(response)
    except HTTPError as error:
        return json.loads(error.read())
    except (URLError, TimeoutError) as error:
        return {'error': str(error), 'outcome_unknown': arguments is not None,
                'guidance': 'Inspect observe/action_status before retrying an action.'}


def _start_action(context, path, arguments):
    """Wait locally for short actions while retaining the ID on polling failure."""
    result = _call(context, path, arguments)
    if result.get('status') == 'running' and result.get('id'):
        settled = action_status({'action_id': result['id'], 'wait_seconds': 10}, context)
        if 'error' in settled and 'status' not in settled:
            return {**result, 'poll_error': settled['error'],
                    'guidance': 'Action was submitted; query this action ID before retrying.'}
        return settled
    return result


def observe(arguments, context):
    return _call(context, '/observe')


def chat(arguments, context):
    return _call(context, '/chat', arguments)


def move_to(arguments, context):
    return _start_action(context, '/move', arguments)


def action_status(arguments, context):
    wait = arguments.get('wait_seconds', 3)
    if isinstance(wait, bool) or not isinstance(wait, int) or not 0 <= wait <= 10:
        raise ValueError('wait_seconds must be an integer between 0 and 10')
    deadline = time.monotonic() + wait
    path = '/actions/' + quote(arguments['action_id'], safe='')
    while True:
        result = _call(context, path)
        if result.get('status') != 'running' and not result.get('pending'):
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result
        time.sleep(min(0.5, remaining))


def stop(arguments, context):
    return _call(context, '/stop', {})


def inspect_block(arguments, context):
    return _call(context, '/block?' + urlencode(arguments))


def find_blocks(arguments, context):
    return _call(context, '/blocks?' + urlencode(arguments))


def attack(arguments, context):
    return _start_action(context, '/attack', arguments)


def hunt_entity(arguments, context):
    return _start_action(context, '/hunt', arguments)


def equip(arguments, context):
    return _start_action(context, '/equip', arguments)


def consume(arguments, context):
    return _start_action(context, '/consume', arguments)


def place_block(arguments, context):
    return _start_action(context, '/place', arguments)


def craft(arguments, context):
    return _start_action(context, '/craft', arguments)


def search_items(arguments, context):
    return _call(context, '/items/search?' + urlencode(arguments))


def get_recipes(arguments, context):
    return _call(context, '/recipes?' + urlencode(arguments))


def dig_blocks(arguments, context):
    return _start_action(context, '/dig-blocks', arguments)


def drop_item(arguments, context):
    return _start_action(context, '/drop', arguments)


def open_container(arguments, context):
    return _start_action(context, '/container/open', arguments)


def inspect_container(arguments, context):
    return _call(context, '/container')


def deposit_item(arguments, context):
    return _start_action(context, '/container/deposit', arguments)


def withdraw_item(arguments, context):
    return _start_action(context, '/container/withdraw', arguments)


def close_container(arguments, context):
    return _start_action(context, '/container/close', arguments)


def open_furnace(arguments, context):
    return _start_action(context, '/furnace/open', arguments)


def inspect_furnace(arguments, context):
    """Bounded local waiting for output, without holding an HTTP request open."""
    wait = arguments.get('wait_seconds', 0)
    if isinstance(wait, bool) or not isinstance(wait, int) or not 0 <= wait <= 10:
        raise ValueError('wait_seconds must be an integer between 0 and 10')
    deadline = time.monotonic() + wait
    window_id = None
    while True:
        result = _call(context, '/furnace')
        if 'error' in result:
            return result
        if window_id is not None and result.get('id') != window_id:
            return {'error': 'Furnace window changed while waiting; inspect again.'}
        window_id = result.get('id')
        remaining = deadline - time.monotonic()
        if result.get('output') or remaining <= 0:
            return result
        time.sleep(min(0.5, remaining))


def put_furnace_input(arguments, context):
    return _start_action(context, '/furnace/input', arguments)


def put_furnace_fuel(arguments, context):
    return _start_action(context, '/furnace/fuel', arguments)


def take_furnace_item(arguments, context):
    return _start_action(context, '/furnace/take', arguments)


def use_on_block(arguments, context):
    return _start_action(context, '/use-on-block', arguments)


def interact_entity(arguments, context):
    return _start_action(context, '/interact-entity', arguments)


def sleep(arguments, context):
    return _start_action(context, '/sleep', arguments)


def wake(arguments, context):
    return _start_action(context, '/wake', arguments)


def get_time(arguments, context):
    """Read game time immediately; no waiting or server time changes."""
    observation = observe({}, context)
    if not observation.get('connected'):
        return {'connected': False, 'error': observation.get('error', 'Minecraft is disconnected')}
    ticks = observation.get('time_of_day')
    if isinstance(ticks, bool) or not isinstance(ticks, (int, float)) or not 0 <= ticks < 24000:
        return {'connected': True, 'error': 'Game time is unavailable'}
    minutes = (int(ticks * 60 / 1000) + 6 * 60) % (24 * 60)
    return {'connected': True, 'time_of_day': ticks,
            'clock_24h': f'{minutes // 60:02d}:{minutes % 60:02d}',
            'dimension': observation.get('dimension'),
            'source': 'latest server time received by Mineflayer',
            'clock_basis': '24000 ticks per game day; tick 0 = 06:00; not real-world time'}


def open_door(arguments, context):
    return _start_action(context, '/door/open', arguments)
