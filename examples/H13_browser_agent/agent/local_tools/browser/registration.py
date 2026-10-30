"""Register browser capabilities as model-callable tools."""

from local_tools.browser.models import BrowserArguments
from local_tools.registry import ToolDefinition


def register_browser_tool(registry, session):
    registry.register(
        ToolDefinition(
            "browser.action",
            "browser",
            "Operate the connected real Chromium browser. Start with observe or open(url). "
            "Results contain page text and element refs. click/fill/select/check/press require "
            "an exact ref from the latest observation. Never invent refs or endpoints. "
            "fill uses value; select uses option value. press supports "
            "Enter/Tab/Escape/ArrowDown/ArrowUp. switch_tab uses a returned tab index. "
            "Observe again if loading. Browser keeps cookies and executes JavaScript. "
            "No action is retried. After a failure observe the page before submitting again.",
        ),
        session.invoke,
        BrowserArguments,
    )
