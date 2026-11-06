# Quality gate đầy đủ cho máy local (Windows).
# CI chạy đúng các bước này; xanh ở đây mới được coi là "xong".
#
#   powershell -File scripts/gate.ps1
#
#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipAudit,
    [switch]$SkipSemgrep
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = if (Test-Path ".venv\Scripts\python.exe") {
    Join-Path $root ".venv\Scripts\python.exe"
} else {
    "python"
}

$failed = [System.Collections.Generic.List[string]]::new()

function Invoke-GateStep {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Command
    )

    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        $script:failed.Add($Name)
        Write-Host "FAILED: $Name (exit $LASTEXITCODE)" -ForegroundColor Red
    }
}

Invoke-GateStep "ruff format --check" { & $python -m ruff format --check . }
Invoke-GateStep "ruff check" { & $python -m ruff check . }
Invoke-GateStep "mypy" { & $python -m mypy app }
Invoke-GateStep "pytest + coverage (>=80%)" {
    & $python -m pytest -q --cov=app --cov-report=term-missing --cov-fail-under=80
}

if (-not $SkipAudit) {
    Invoke-GateStep "pip-audit" { & $python -m pip_audit -r requirements.txt }
}

if (-not $SkipSemgrep -and (Get-Command semgrep -ErrorAction SilentlyContinue)) {
    Invoke-GateStep "semgrep" {
        semgrep scan --config p/python --config p/flask --error --metrics=off
    }
}

if ($failed.Count -gt 0) {
    Write-Host "`nGATE FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host "`nGATE PASSED" -ForegroundColor Green
exit 0
