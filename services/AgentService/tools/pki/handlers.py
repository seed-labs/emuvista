"""Agent entrypoints for the PKI catalog; policy is enforced by AgentService."""

from functools import partial
import json
from pathlib import Path

from .catalog import Catalog
from .execution import LocalBackend
from .registration import register_pki_tools


def _invoke(name, arguments, context):
    catalog = Catalog()
    register_pki_tools(catalog, LocalBackend(context.identity))
    # The common entrypoint rejects any caller-provided source before import.
    local_arguments = dict(arguments)
    if 'source' in catalog._tools[name].arguments_model.model_fields:
        local_arguments['source'] = 'local'
    result = catalog.call(name, local_arguments)
    return result.model_dump(mode='json')


for _tool in json.loads(Path(__file__).with_name('tools.json').read_text()):
    globals()[_tool['name'].split('.')[1]] = partial(_invoke, _tool['name'])
