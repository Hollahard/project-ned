param()
$ErrorActionPreference = 'Stop'
if (-not $env:VIRTUAL_ENV -or -not (Test-Path -LiteralPath (Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'))) {
    throw 'Activate the Project Ned virtual environment before running checks.'
}
$previewManifest = Join-Path $PSScriptRoot 'Cargo.toml'
$previewChecks = Join-Path $PSScriptRoot '.checks'
New-Item -ItemType Directory -Path $previewChecks -Force | Out-Null
$previewLog = Join-Path $previewChecks ('verification-' + [Guid]::NewGuid().ToString('N') + '.log')
& cargo fmt --manifest-path $previewManifest --check *> $previewLog
if ($LASTEXITCODE -ne 0) { throw "Formatting failed; see $previewLog" }
& cargo test --offline --locked --quiet --manifest-path $previewManifest -- --test-threads=1 *>> $previewLog
if ($LASTEXITCODE -ne 0) { throw "Tests failed; see $previewLog" }
& cargo clippy --offline --locked --quiet --manifest-path $previewManifest --all-targets -- -D warnings *>> $previewLog
if ($LASTEXITCODE -ne 0) { throw "Clippy failed; see $previewLog" }
Write-Output "Preview watch native tests, formatting and Clippy passed. Log: $previewLog"
