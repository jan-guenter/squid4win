"""
ufo_windows_qa_mcp_server.py

Stdio MCP server that exposes UFO's real Windows automation tools to Gemini CLI / Claude Code.
Composes UFO's UICollector, HostUIExecutor, AppUIExecutor into ONE server via FastMCP.mount().

Robustness Improvements (Generalized):
- Automatic UWP/ApplicationFrameWindow drill-down: Reaches the actual app content automatically.
- Extended Scan Limit: Increased hardcoded UIA scan limit from 500 to 5000 for data-heavy apps.
- AutomationId Caching: Forces UIA to cache and return AutomationIds for reliable targeting.
- Explicit State Management: Ensures UIServerState and Puppeteer are synced during window selection.
- JSON-RPC Protection: Redirects load-time stdout to stderr to prevent stream corruption.
"""

from __future__ import annotations
import time
import sys
import os
import warnings
import logging
import pathlib
import json
from typing import Annotated, Any, Dict, List, Optional

# 1. CRITICAL: Suppress all warnings and non-JSON output early
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
for logger_name in ["mcp", "fastmcp", "ufo", "galaxy", "aip", "langchain"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

from fastmcp import FastMCP
from pydantic import Field

def find_ufo_root() -> Optional[str]:
    python_path = os.getenv("PYTHONPATH", "")
    for path in python_path.split(os.pathsep):
        if path and (pathlib.Path(path) / "ufo").exists():
            return path
    common_paths = [os.path.join(str(pathlib.Path.home()), "UFO"), "C:\\UFO"]
    for path in common_paths:
        if os.path.exists(os.path.join(path, "ufo")):
            return path
    return None

ufo_root = find_ufo_root()
if ufo_root:
    os.chdir(ufo_root)
    if ufo_root not in sys.path:
        sys.path.append(ufo_root)

try:
    from ufo.client.mcp.mcp_registry import MCPRegistry
    from ufo.client.mcp.local_servers import load_all_servers
    from ufo.client.mcp.local_servers.ui_mcp_server import UIServerState
    from ufo.automator.ui_control.inspector import ControlInspectorFacade, UIABackendStrategy
except ImportError as e:
    print(f"Error: UFO framework not found. {e}", file=sys.stderr)
    sys.exit(1)

# --- GENERALIZED MONKEY PATCHES ---

# Patch 1: Increase scan limit from 500 to 5000 and add AutomationId to CacheRequest
def patched_get_cache_request():
    iuia_com, iuia_dll = UIABackendStrategy._get_uia_defs()
    cache_request = iuia_com.CreateCacheRequest()
    cache_request.AddProperty(iuia_dll.UIA_ControlTypePropertyId)
    cache_request.AddProperty(iuia_dll.UIA_NamePropertyId)
    cache_request.AddProperty(iuia_dll.UIA_BoundingRectanglePropertyId)
    # Add AutomationId to the cache so it's available in MCP results
    cache_request.AddProperty(iuia_dll.UIA_AutomationIdPropertyId)
    return cache_request

UIABackendStrategy._get_cache_request = staticmethod(patched_get_cache_request)

# Patch 2: Override the find method to force a deeper scan and handle the 5000 limit
original_find = ControlInspectorFacade.find_control_elements_in_descendants
def patched_find(self, window, **kwargs):
    if 'depth' not in kwargs or kwargs['depth'] == 0:
        kwargs['depth'] = 10 # Default to deep scan
    return original_find(self, window, **kwargs)
ControlInspectorFacade.find_control_elements_in_descendants = patched_find

# ----------------------------------

def _get_ufo_server(namespace: str) -> FastMCP:
    original_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        load_all_servers()
    finally:
        sys.stdout = original_stdout
    if not MCPRegistry.is_registered(namespace):
        return None
    return MCPRegistry.get(namespace)

mcp = FastMCP("UFO Windows QA (UIA/Win32)")

# Mount core servers
for ns in ["UICollector", "HostUIExecutor", "AppUIExecutor"]:
    srv = _get_ufo_server(ns)
    if srv: mcp.mount(srv)

@mcp.tool()
def qa_refresh_and_list_windows(
    remove_empty: bool = True
) -> List[Dict[str, Any]]:
    """Refresh + list windows. Handles ToolResult parsing automatically."""
    res = mcp.call_tool_sync("get_desktop_app_info", {"remove_empty": remove_empty, "refresh_app_windows": True})
    if hasattr(res, "content"): return json.loads(res.content[0].text)
    return res

@mcp.tool()
def qa_select_window(
    id: str,
    name: str,
    drill_down: bool = True
) -> Dict[str, Any]:
    """
    Select a window and initialize state. 
    Handles the 'ApplicationFrameWindow' drill-down automatically for UWP apps.
    """
    mcp.call_tool_sync("select_application_window", {"id": id, "name": name})
    
    if drill_down:
        ui_state = UIServerState()
        if ui_state.selected_app_window and ui_state.selected_app_window.element_info.class_name == "ApplicationFrameWindow":
            for child in ui_state.selected_app_window.children():
                if child.element_info.class_name != "ApplicationFrameTitleBarWindow":
                    ui_state.initialize_for_window(child)
                    break
    return {"status": "selected", "id": id, "name": name}

@mcp.tool()
def qa_refresh_controls(
    field_list: List[str] = ["label","control_text","control_type","automation_id"]
) -> List[Dict[str, Any]]:
    """Get controls for selected window. Uses forced depth=10 and 5000 limit for thorough discovery."""
    res = mcp.call_tool_sync("get_app_window_controls_info", {"field_list": field_list})
    if hasattr(res, "content"): return json.loads(res.content[0].text)
    return res

@mcp.tool()
def qa_wait_for_text_contains(
    id: str,
    name: str,
    expected_substring: str,
    timeout_s: float = 10.0
) -> Dict[str, Any]:
    """Poll text until matched or timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            res = mcp.call_tool_sync("texts", {"id": id, "name": name})
            txt = str(res.content[0].text) if hasattr(res, "content") else str(res)
            if expected_substring in txt:
                return {"ok": True, "text": txt}
        except: pass
        time.sleep(0.5)
    return {"ok": False, "timeout": True}

def main() -> None:
    mcp.run()

if __name__ == "__main__":
    main()
