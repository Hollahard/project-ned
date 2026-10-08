param([string]$VirtualEnvironment = 'G:\Project_Ned\.venv')
$ErrorActionPreference = 'Stop'
if (-not $env:VIRTUAL_ENV) {
    throw "Activate $VirtualEnvironment\Scripts\Activate.ps1 before running automation."
}
$manifest = Join-Path $PSScriptRoot 'Cargo.toml'
$checks = Join-Path $PSScriptRoot '.checks'
New-Item -ItemType Directory -Path $checks -Force | Out-Null
$log = Join-Path $checks ("tests-{0}.log" -f [Guid]::NewGuid().ToString('N'))
# Project Friday runbook: redirect test output to a temporary file on Windows.
cargo test --offline --locked --manifest-path $manifest --quiet -- --test-threads=1 > $log 2>&1
$testExit = $LASTEXITCODE
if ($testExit -ne 0) {
    Get-Content -LiteralPath $log -Tail 24 | Write-Output
    throw "ConPTY fixture tests failed with exit code $testExit. Log: $log"
}
Select-String -LiteralPath $log -Pattern '^test result:' | ForEach-Object { $_.Line }
Write-Output "INFO: ConPTY test log: $log"
