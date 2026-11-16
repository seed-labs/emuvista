"""E16 entrypoint using current AgentService context and tool authorization."""
from emuvista_agent.events import JsonEvents
from emuvista_agent.runtime import AgentContext
from adapter import run


def main():
    context = AgentContext.load()
    context.observer = JsonEvents(context.identity, context.config)
    context.emit('run_started', framework='e16_langchain')
    try:
        result = run(context)
    except Exception as error:
        context.emit('run_failed', status='failed', error=str(error))
        return 1
    context.emit('run_completed', result=result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
