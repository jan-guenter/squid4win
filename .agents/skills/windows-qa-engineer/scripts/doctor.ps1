# UFO Windows QA Doctor
# Diagnostics and quick-fix script

Write-Host "--- UFO Windows QA Diagnostics ---" -ForegroundColor Cyan

# 1. Check Python
$py = python --version 2>&1
if ($LASTEXITCODE -ne 0) { Write-Error "Python not found."; exit 1 }
Write-Host "Python: $py"

# 2. Check UFO root
$ufo_root = "C:\UFO"
if (!(Test-Path $ufo_root)) {
    Write-Host "UFO not found in $ufo_root. Searching..." -ForegroundColor Yellow
    # Just a placeholder for search logic
} else {
    Write-Host "UFO Root: $ufo_root"
}

# 3. Check dependencies
$deps = @("fastmcp", "uiautomation", "flask", "pyautogui", "html2text", "fastapi", "uvicorn")
foreach ($d in $deps) {
    python -c "import $d" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Dependency missing: $d" -ForegroundColor Red
    } else {
        Write-Host "Dependency OK: $d" -ForegroundColor Green
    }
}

# 4. Check UFO Config (CRITICAL FINDING)
$sys_yaml = Join-Path $ufo_root "config\ufo\system.yaml"
if (Test-Path $sys_yaml) {
    $content = Get-Content $sys_yaml
    if (!($content -match "CONTROL_LIST")) {
        Write-Host "CRITICAL: CONTROL_LIST missing in system.yaml. UI discovery will fail." -ForegroundColor Red
        Write-Host "Fixing system.yaml..." -ForegroundColor Yellow
        $patch = "`nCONTROL_LIST: ['Button', 'Edit', 'Text', 'MenuItem', 'CheckBox', 'RadioButton', 'ComboBox', 'ListItem', 'TabItem', 'Hyperlink', 'Window', 'Pane', 'Group', 'Image', 'MenuBar', 'ScrollBar', 'Slider', 'Spinner', 'StatusBar', 'ToolBar', 'ToolTip', 'TreeItem', 'DataGrid', 'DataItem', 'Document', 'SplitButton', 'Header', 'HeaderItem', 'Table', 'TitleBar', 'Separator']"
        $content += $patch
        $content | Set-Content $sys_yaml -Force
        Write-Host "Applied CONTROL_LIST patch." -ForegroundColor Green
    } else {
        Write-Host "UFO Config: CONTROL_LIST OK." -ForegroundColor Green
    }
} else {
    Write-Host "UFO Config: system.yaml NOT FOUND." -ForegroundColor Red
}

Write-Host "--- Diagnostics Complete ---" -ForegroundColor Cyan
