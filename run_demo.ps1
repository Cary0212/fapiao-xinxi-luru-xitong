$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host '首次运行：请先创建虚拟环境并安装依赖：'
    Write-Host '  python -m venv .venv'
    Write-Host '  .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
    exit 1
}
Write-Host '发票信息录入 Demo：http://127.0.0.1:8000'
& $python -m uvicorn web_demo.app:app --host 127.0.0.1 --port 8000
