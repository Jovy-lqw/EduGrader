$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Assert-CommandSucceeded([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = "py"
    $PythonArgs = @("-3")
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = "python"
    $PythonArgs = @()
}
else {
    throw "Python 3 was not found. Install Python 3.9 or later first."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found. Install Node.js 20 or later first."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $PythonCommand @PythonArgs -m venv .venv
    Assert-CommandSucceeded "Creating the Python virtual environment"
}

& ".venv\Scripts\python.exe" -m pip install --upgrade pip
Assert-CommandSucceeded "Upgrading pip"
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
Assert-CommandSucceeded "Installing backend dependencies"
& ".venv\Scripts\python.exe" -m playwright install chromium
Assert-CommandSucceeded "Installing Chromium"

Push-Location frontend
try {
    npm ci
    Assert-CommandSucceeded "Installing frontend dependencies"
    npm run build
    Assert-CommandSucceeded "Building the frontend"
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Installation completed. Run .\start.bat to start EduGrader."
