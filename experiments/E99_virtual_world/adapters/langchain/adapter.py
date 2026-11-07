"""LangChain adapter. AgentService and tool packages do not import this framework."""
import json
import os
import time


def run(context):
    from langchain.agents import create_agent
    from langchain_core.tools import StructuredTool
    from langchain_openai import ChatOpenAI
    key=os.environ.get('LLM_API_KEY','')
    model=os.environ.get('LLM_MODEL','')
    if not key or not model:
        raise RuntimeError('Set LLM_API_KEY and LLM_MODEL in the experiment .env, then restart the agent')
    tools=[]
    aliases=set()
    for definition in context.tools.list():
        name=definition['name']
        alias=name.replace('.','__')
        if alias in aliases:raise ValueError('tool name alias collision')
        aliases.add(alias)
        def bind(actual):
            def dispatch(**arguments):
                try:
                    value=context.tools.invoke(actual,arguments)
                    return json.dumps(value)
                except Exception as error:
                    return json.dumps({'error':str(error)})
            return dispatch
        tools.append(StructuredTool.from_function(func=bind(name),name=alias,
            description=definition['description'],args_schema=definition['input_schema']))
    options={'model':model,'api_key':key,'base_url':os.environ.get('LLM_BASE_URL') or None,'timeout':45,'max_retries':2}
    llm=ChatOpenAI(**options)
    profile=context.service('persona')
    agent=create_agent(llm,tools=tools,system_prompt=profile['system'])
    rounds=int(os.environ.get('AGENT_ROUNDS','3'))
    steps=int(os.environ.get('AGENT_MAX_STEPS','20'))
    if not 1<=rounds<=100 or not 2<=steps<=100:raise ValueError('agent limits are outside allowed ranges')
    interval=float(os.environ.get('AGENT_INTERVAL_SECONDS','20'))
    if not 0<=interval<=3600:raise ValueError('invalid agent interval')
    delay=float(os.environ.get('AGENT_START_DELAY_SECONDS','30'))
    context.emit('starting', seconds=delay)
    time.sleep(delay)
    timeout=float(os.environ.get('AGENT_READY_TIMEOUT_SECONDS','600'))
    if not 0<=timeout<=3600:raise ValueError('invalid readiness timeout')
    pending=set(profile.get('requiredServices',[]))
    deadline=time.monotonic()+timeout
    while pending and time.monotonic()<deadline:
        for name in list(pending):
            if context.tools.invoke('world.probe',{'service':name},source='readiness').get('ready'):
                pending.remove(name)
        if pending:
            context.emit('waiting', services=sorted(pending))
            time.sleep(5)
    if pending and timeout:
        context.emit('readiness_timeout', services=sorted(pending))
    messages=[]
    completed=0
    for index in range(rounds):
        try:
            context.emit('round_started', round=index+1)
            messages.append({'role':'user','content':profile['task']})
            result=agent.invoke({'messages':messages},config={'recursion_limit':steps})
            messages=result['messages']
            context.emit('round_completed', round=index+1, message=messages[-1].content)
            completed+=1
        except Exception as error:
            text=str(error).replace(key,'[redacted]')
            context.emit('round_failed', round=index+1, error=text)
        if index+1<rounds:
            context.emit('paused', seconds=interval)
            time.sleep(interval)
    if not completed:raise RuntimeError('No agent round completed; inspect the agent log and LLM configuration')
    return {'rounds':completed,'identity':context.identity}
