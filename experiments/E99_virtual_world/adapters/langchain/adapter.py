"""Continuous resident life using LangChain, independent of AgentService core."""

from datetime import datetime, timezone
import json
import math
import os
import random
import signal
import threading
import time

from memory import Experience, bounded


def pause(stop, seconds):
    """Wait without delaying shutdown signals."""
    return stop.wait(max(0, seconds))


def number(name, default, minimum, maximum, integer=False):
    value = int(os.environ.get(name, default)) if integer else float(os.environ.get(name, default))
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(name+' is outside its allowed range')
    return value


def run(context):
    from langchain.agents import create_agent
    from langchain.agents.middleware import wrap_model_call
    from langchain_core.messages import AIMessage, HumanMessage, messages_from_dict, messages_to_dict
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI

    key = os.environ.get('LLM_API_KEY', '')
    model = os.environ.get('LLM_MODEL', '')
    if not key or not model:
        raise RuntimeError('Set LLM_API_KEY and LLM_MODEL in the experiment .env, then restart the agent')
    steps = number('AGENT_MAX_STEPS', 20, 4, 100, integer=True)
    # Each decision can take a model node and a tool node. Reserve a final model
    # node for a local pause response, without another LLM request or tool call.
    model_limit = (steps-2)//2
    model_calls, budget_reached = 0, False
    maximum = number('AGENT_MAX_CYCLES', 0, 0, 1000000, integer=True)
    default_rest = number('AGENT_DEFAULT_REST_SECONDS', 120, 30, 1800)
    startup_delay = number('AGENT_START_DELAY_SECONDS', 10, 0, 3600)
    experience = Experience(context.service('life')['directory'])
    stop = threading.Event()
    previous_signals = {}

    def recall():
        return context.tools.invoke('life.recall', {}, source='lifecycle')

    tools, aliases = [], set()
    for definition in context.tools.list():
        name = definition['name']
        alias = name.replace('.', '__')
        if alias in aliases:
            raise ValueError('tool name alias collision')
        aliases.add(alias)

        def bind(actual):
            def dispatch(**arguments):
                if stop.is_set():
                    return json.dumps({'error': 'Resident is stopping'})
                identifier = None
                if not actual.startswith('life.'):
                    identifier = experience.pending(actual, arguments)
                try:
                    value = context.tools.invoke(actual, arguments)
                    if identifier:
                        experience.finish(identifier, 'returned', value)
                    # Full observations are available to the handler; model context is bounded.
                    return json.dumps(bounded(value, 12000), ensure_ascii=False)
                except Exception as error:
                    message = str(error).replace(key, '[redacted]')
                    if identifier:
                        experience.finish(identifier, 'error', {'error': message})
                    return json.dumps({'error': message})
            return dispatch

        tools.append(StructuredTool.from_function(
            func=bind(name), name=alias, description=definition['description'],
            args_schema=definition['input_schema'], return_direct=name == 'life.rest',
        ))
    llm = ChatOpenAI(
        model=model, api_key=key, base_url=os.environ.get('LLM_BASE_URL') or None,
        timeout=45, max_retries=2,
    )
    profile = context.service('persona')

    @wrap_model_call
    def moment_budget(request, handler):
        nonlocal model_calls, budget_reached
        if model_calls >= model_limit:
            budget_reached = True
            return AIMessage(
                content='This moment has reached its activity budget. Completed tool '
                        'observations are retained. Rest, then revisit unfinished intentions '
                        'without repeating confirmed actions.',
                additional_kwargs={'emuvista': {'source': 'runtime', 'reason': 'activity_budget'}},
            )
        model_calls += 1
        return handler(request)

    agent = create_agent(llm, tools=tools, system_prompt=profile['system'], middleware=[moment_budget])
    cycles, completed, failures = 0, 0, 0
    if threading.current_thread() is threading.main_thread():
        for name in (signal.SIGINT, signal.SIGTERM):
            previous_signals[name] = signal.signal(name, lambda *_: stop.set())
    try:
        context.emit('resident_started', mode='continuous', remembered_moments=experience.data['cycles'])
        initial = recall()
        remaining = max(0, initial.get('rest', {}).get('wake_at', 0)-time.time())
        if remaining:
            context.emit('resting', seconds=round(remaining),
                         reason=initial['rest'].get('reason', ''),
                         wake_at=datetime.fromtimestamp(time.time()+remaining, timezone.utc).isoformat())
        else:
            remaining = random.uniform(0, startup_delay)
            context.emit('starting', seconds=round(remaining, 1))
        pause(stop, remaining)
        while not stop.is_set() and (not maximum or cycles < maximum):
            cycles += 1
            cycle = experience.begin()
            started = time.time()
            personal = recall()
            context.emit('waking', cycle=cycle, intention=personal.get('intention', ''))
            # This is an internal waking observation, never a repeated external task.
            observation = {
                'kind': 'resident_wakeup', 'time': datetime.now(timezone.utc).isoformat(),
                'personal_memory': {**personal, 'notes': personal['notes'][-12:]},
                'recent_activity': experience.recent(),
            }
            messages = [message for moment in experience.data['history']
                        for message in messages_from_dict(moment)]
            prefix = len(messages)
            messages.append(HumanMessage(content=json.dumps(observation, ensure_ascii=False)))
            try:
                model_calls, budget_reached = 0, False
                result = agent.invoke({'messages': messages}, config={'recursion_limit': steps})
                experience.complete(messages_to_dict(result['messages'][prefix:]))
                personal = recall()
                resting = personal.get('rest', {})
                selected_rest = resting.get('set_at', 0) >= started
                reflection = resting['reason'] if selected_rest else result['messages'][-1].content
                context.emit('moment_completed', cycle=cycle, message=reflection,
                             intention=personal.get('intention', ''), model_calls=model_calls,
                             outcome='activity_budget' if budget_reached else 'finished')
                completed += 1
                failures = 0
                seconds = max(0, resting['wake_at']-time.time()) if selected_rest else default_rest
                reason = (resting['reason'] if selected_rest else
                          'Activity budget reached; continue after resting' if budget_reached else
                          'Time between moments')
                phase = 'resting'
            except Exception as error:
                failures += 1
                # Preserve attempted calls even when the graph cannot return its transcript.
                seconds = min(1800, default_rest*2**min(failures-1, 4))
                reason = 'A moment was interrupted; memories and attempted actions are retained'
                phase = 'recovering'
                context.emit('moment_failed', cycle=cycle, error=str(error).replace(key, '[redacted]'))
            if stop.is_set() or (maximum and cycles >= maximum):
                break
            context.emit(phase, cycle=cycle, seconds=round(seconds, 1), reason=reason,
                         wake_at=datetime.fromtimestamp(time.time()+seconds, timezone.utc).isoformat())
            pause(stop, seconds)
        context.emit('resident_stopped', cycles=cycles, completed_moments=completed,
                     reason='Signal received' if stop.is_set() else 'Optional cycle limit reached')
        return {'cycles': cycles, 'completed_moments': completed, 'identity': context.identity}
    finally:
        for name, handler in previous_signals.items():
            signal.signal(name, handler)
