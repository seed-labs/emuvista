"""Generate a native LangChain/LangGraph application during Service installation."""

from pathlib import Path

REQUIREMENTS = ('langchain==1.4.9', 'langchain-openai==1.7.4',
                'langgraph-checkpoint-sqlite==3.1.3')


def install(node, root, data_directory):
    entrypoint = root + '/framework/main.py'
    node.setFile(entrypoint, Path(__file__).with_name('application.py').read_text())
    return {'name': 'langchain', 'entrypoint': entrypoint,
            'state_directory': data_directory, 'checkpoint': data_directory + '/langgraph.sqlite'}
