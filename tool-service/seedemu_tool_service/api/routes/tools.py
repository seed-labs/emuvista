"""Tool discovery and invocation endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from seedemu_tool_service.api.dependencies import get_tool_registry
from seedemu_tool_service.models.tool import ToolListResponse
from seedemu_tool_service.registry.registry import ToolRegistry

router = APIRouter(tags=["tools"])


@router.get("", response_model=ToolListResponse)
def list_tools(
    registry: Annotated[ToolRegistry, Depends(get_tool_registry)],
) -> ToolListResponse:
    """List tools currently registered with the service."""

    tools = registry.list_tools()
    return ToolListResponse(tools=tools, count=len(tools))


@router.post("/{tool_name}/invoke", response_model=None)
async def invoke_tool(
    tool_name: str,
    arguments: Annotated[dict[str, Any], Body()],
    registry: Annotated[ToolRegistry, Depends(get_tool_registry)],
) -> Any:
    """Invoke a registered tool with its normal JSON argument object."""
    try:
        result = await registry.invoke(tool_name, arguments)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return jsonable_encoder(result)
