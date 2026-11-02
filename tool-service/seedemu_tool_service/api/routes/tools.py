"""Tool discovery and invocation endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from seedemu_tool_service.api.dependencies import get_tool_registry
from seedemu_tool_service.auth.authorization import AccessContext, AccessDenied
from seedemu_tool_service.auth.http import get_access_context
from seedemu_tool_service.models.tool import ToolListResponse
from seedemu_tool_service.registry.registry import ToolRegistry

router = APIRouter(tags=["tools"])


@router.get("", response_model=ToolListResponse)
def list_tools(
    registry: Annotated[ToolRegistry, Depends(get_tool_registry)],
    access: Annotated[AccessContext, Depends(get_access_context)],
) -> ToolListResponse:
    """List tools currently registered with the service."""

    tools = registry.list_tools(access=access)
    return ToolListResponse(tools=tools, count=len(tools))


@router.post("/{tool_name}/invoke", response_model=None)
async def invoke_tool(
    tool_name: str,
    arguments: Annotated[dict[str, Any], Body()],
    registry: Annotated[ToolRegistry, Depends(get_tool_registry)],
    access: Annotated[AccessContext, Depends(get_access_context)],
) -> Any:
    """Invoke a registered tool with its normal JSON argument object."""
    try:
        result = await registry.invoke(tool_name, arguments, access=access)
    except AccessDenied as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error.args[0])) from error
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return jsonable_encoder(result)
