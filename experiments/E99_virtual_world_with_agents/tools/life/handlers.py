"""Return a resident's requested wait; the framework checkpoints the schedule."""

from datetime import datetime, timezone


def rest(arguments, context):
    now = context.clock.now().timestamp()
    seconds = arguments['seconds']
    wake_at = now + seconds
    context.emit('rest_scheduled', seconds=seconds, reason=arguments['reason'], intention=arguments['reason'],
                 wake_at=datetime.fromtimestamp(wake_at, timezone.utc).isoformat())
    return {'resting': True, 'seconds': seconds, 'reason': arguments['reason'],
            'setAt': now, 'wakeAt': wake_at}
