"""
MCP Server Routes
Endpoints for querying registered MCP servers and their tools.
"""

from typing import Dict

from fastapi import APIRouter, HTTPException

from framework_base.mcp_servers.registry import get_mcp_registry
from framework_base.multi_server_mcp_client import multi_server_mcp_client
from logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["MCP"])


@router.get("/servers")
async def list_mcp_servers() -> Dict[str, object]:
    """List all registered MCP servers and their current configurations."""
    registry = get_mcp_registry()
    servers = registry.get_all_servers()

    result = []
    for name, cfg in servers.items():
        result.append(
            {
                "name": name,
                "enabled": bool(cfg.enabled),
                "available": bool(cfg.is_available()),
                "description": cfg.description,
            }
        )

    return {"servers": result}


@router.get("/servers/{server_name}/tools")
async def list_mcp_server_tools(server_name: str):
    """List tools exposed by a specific MCP server (safe fields only).

    Returns per-tool: `name`, `description`, and a summarized `args` schema
    (property names, whether required, and enum values where present).
    """
    registry = get_mcp_registry()
    server_cfg = registry.get_server(server_name)
    if not server_cfg:
        raise HTTPException(status_code=404, detail="MCP server not found")

    if not server_cfg.is_available():
        raise HTTPException(status_code=400, detail="MCP server is not available")

    try:
        raw_tools = await multi_server_mcp_client.get_tools(server_name=server_name)
    except Exception as exc:
        logger.error(f"Error fetching tools for {server_name}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch tools")

    safe_tools = []
    for t in raw_tools:
        tool_entry = {
            "name": getattr(t, "name", ""),
            "description": getattr(t, "description", ""),
        }

        schema = getattr(t, "args_schema", None)
        if schema:
            try:
                schema_dict = (
                    schema.model_json_schema()
                    if hasattr(schema, "model_json_schema")
                    else schema if isinstance(schema, dict) else {}
                )
                props = schema_dict.get("properties", {})
                required = set(schema_dict.get("required", []))

                args_summary = {}
                for pname, pinfo in props.items():
                    arg = {"required": pname in required}
                    enum_vals = pinfo.get("enum")
                    if enum_vals:
                        arg["enum"] = enum_vals
                    args_summary[pname] = arg

                tool_entry["args"] = args_summary
            except Exception:
                tool_entry["args"] = {}
        else:
            tool_entry["args"] = {}

        meta = getattr(t, "metadata", None)
        if meta and isinstance(meta, dict):
            tool_entry["readOnlyHint"] = bool(meta.get("readOnlyHint", False))

        safe_tools.append(tool_entry)

    return {"tools": safe_tools}
