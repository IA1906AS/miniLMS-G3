<#
    check.ps1 - Kiem tra chat luong code toan bo du an bang 1 lenh
    Cach dung:
        .\check.ps1
        (hoac) powershell -ExecutionPolicy Bypass -File check.ps1

    Chay lan luot: ruff (lint + format) -> mypy -> pytest (+coverage) -> pip-audit
#>

# Dam bao console hien thi UTF-8 (tieng Viet co dau)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$results = New-Object System.Collections.Generic.List[object]

function Invoke-Step {
    param([int]$Index, [int]$Total, [string]$Name, [scriptblock]$Cmd)

    Write-Host ""
    Write-Host ("=" * 64) -ForegroundColor Cyan
    Write-Host ("[$Index/$Total] $Name") -ForegroundColor Cyan
    Write-Host ("=" * 64) -ForegroundColor Cyan

    & $Cmd
    $code = $LASTEXITCODE
    $script:results.Add([PSCustomObject]@{ Name = $Name; Code = $code })
}

Invoke-Step 1 5 "Ruff   - Lint code"       { uv run ruff check . }
Invoke-Step 2 5 "Ruff   - Kiem tra format" { uv run ruff format --check . }
Invoke-Step 3 5 "Mypy   - Kiem tra kieu"   { uv run mypy main.py }
Invoke-Step 4 5 "Pytest - Test + coverage" { uv run pytest }
Invoke-Step 5 5 "Audit  - Quet bao mat"    { uv run pip-audit }

# --- Tong ket ---
Write-Host ""
Write-Host ("=" * 64) -ForegroundColor Yellow
Write-Host "                    TONG KET KIEM TRA" -ForegroundColor Yellow
Write-Host ("=" * 64) -ForegroundColor Yellow

$fail = 0
foreach ($r in $results) {
    if ($r.Code -eq 0) {
        Write-Host ("  [ PASS ]  {0}" -f $r.Name) -ForegroundColor Green
    } else {
        Write-Host ("  [ FAIL ]  {0}  (exit code = {1})" -f $r.Name, $r.Code) -ForegroundColor Red
        $fail++
    }
}

Write-Host ""
if ($fail -eq 0) {
    Write-Host "  >>> Tat ca deu PASS. Code san sang de commit!" -ForegroundColor Green
    exit 0
} else {
    Write-Host ("  >>> Co {0} buoc FAIL. Hay sua loi truoc khi commit." -f $fail) -ForegroundColor Red
    exit 1
}
