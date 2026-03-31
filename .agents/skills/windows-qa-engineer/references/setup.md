# Setup: Windows QA Engineer (UFO-powered)

The **Microsoft UFO UI automation framework** is a prerequisite for my UI interaction MCP servers. If the diagnostic script returns `ModuleNotFoundError: No module named 'ufo'`, the environment must be set up correctly.

## 1. Install Microsoft UFO & Dependencies
Clone the repository and install the verified dependencies. Open a PowerShell terminal and run:

```powershell
# Clone UFO (to C:\ or your preferred location)
cd C:\
git clone https://github.com/microsoft/UFO.git
cd UFO

# Install verified dependencies
pip install -r requirements.txt
pip install fastmcp uiautomation flask pyautogui html2text fastapi uvicorn
```

## 2. Configure UFO
Ensure the base configuration directory exists for UFO to run smoothly:

```powershell
# Inside the UFO directory, create basic config
mkdir config/ufo
New-Item -Path "config/ufo/system.yaml" -ItemType File -Value "MAX_STEP: 50`nCONTROL_BACKEND: ['uia']" -Force
New-Item -Path "config/ufo/mcp.yaml" -ItemType File -Value "{}" -Force
```

## 3. Register the MCP Server
Add the MCP server to your Gemini CLI `.mcp.json` file (in the project root) or your global config at `~/.gemini/mcp.json`:

```json
{
  "mcpServers": {
    "ufo-windows-qa": {
      "type": "stdio",
      "command": "python",
      "args": [
        "C:/Users/rodio/.agents/skills/windows-qa-engineer/scripts/ufo_windows_qa_mcp_server.py"
      ],
      "env": {
        "CONTROL_BACKEND": "uia",
        "SHOW_VISUAL_OUTLINE_ON_SCREEN": "true",
        "PYTHONPATH": "C:/UFO"
      }
    }
  }
}
```
*(Make sure `PYTHONPATH` points to the directory where you cloned the UFO repository).*

## Troubleshooting

### "Invalid JSON: EOF while parsing"
This happens when UFO or its dependencies print warnings/errors to `stdout` during startup, corrupting the JSON-RPC stream.
**Fix**: The improved `ufo_windows_qa_mcp_server.py` redirects all load-time output to `stderr`.

### "No configuration found for 'ufo'"
UFO's `ConfigLoader` is sensitive to the current working directory.
**Fix**: The MCP server script automatically `os.chdir()` to the detected `ufo_root` before initialization.
