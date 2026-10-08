#Requires -Version 7.0
param(
    [Parameter(Mandatory = $true)][string]$UpstreamRoot,
    [Parameter(Mandatory = $true)][string]$TabbySource,
    [switch]$BuildRenderer,
    [switch]$NativeFixtures
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $env:VIRTUAL_ENV) { throw 'Activate the project Python virtual environment before automation.' }
$python = (Get-Command python -ErrorAction Stop).Source
& $python -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)'
if ($LASTEXITCODE -ne 0) { throw 'The active Python interpreter is not a virtual environment.' }
$nativeRoot = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $nativeRoot '.checks'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$node = (Get-Command node -ErrorAction Stop).Source
$cargo = (Get-Command cargo -ErrorAction Stop).Source
$oldUpstream = [Environment]::GetEnvironmentVariable('HERMES_UPSTREAM_ROOT', 'Process')
$oldTabbySource = [Environment]::GetEnvironmentVariable('HERMES_TABBY_SOURCE', 'Process')
$resolvedUpstream = (Resolve-Path -LiteralPath $UpstreamRoot).Path
$resolvedTabby = (Resolve-Path -LiteralPath $TabbySource).Path
$env:HERMES_UPSTREAM_ROOT = $resolvedUpstream
$env:HERMES_TABBY_SOURCE = $resolvedTabby
$results = [Collections.Generic.List[object]]::new()
$completed = $false

function Invoke-Check {
    param([string]$Name, [string]$Command, [string[]]$ToolArguments)
    $logPath = Join-Path $logs "$Name.log"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $passed = $false
    try {
        & $Command @ToolArguments *> $logPath
        if ($LASTEXITCODE -ne 0) {
            Get-Content -LiteralPath $logPath -Tail 25 | Write-Host
            throw "$Name failed with exit code $LASTEXITCODE. See $logPath"
        }
        $passed = $true
        Write-Host "PASS $Name"
    }
    finally {
        $results.Add([ordered]@{
            check = $Name
            passed = $passed
            elapsed_seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 3)
            log = $logPath
        })
    }
}

function New-TestDirectory {
    param([string]$Label)
    $candidate = [IO.Path]::GetFullPath((Join-Path $logs ($Label + '-' + [Guid]::NewGuid().ToString('N'))))
    $expectedPrefix = [IO.Path]::GetFullPath($logs).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid test temporary directory.' }
    if (Test-Path -LiteralPath $candidate) { throw 'Refusing to reuse an existing test temporary directory.' }
    $ancestor = [IO.DirectoryInfo]::new($logs)
    while ($null -ne $ancestor) {
        if ($ancestor.Exists -and ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Refusing a test temporary path through a reparse point.'
        }
        $ancestor = $ancestor.Parent
    }
    return $candidate
}

try {
    $ui = Join-Path $nativeRoot 'apps/desktop-ui'
    $uiTests = @(Get-ChildItem -LiteralPath (Join-Path $ui 'tests') -Filter '*.test.mjs' -File | ForEach-Object FullName)
    if ($uiTests.Count -eq 0) { throw 'No retained-renderer tests found.' }
    Invoke-Check -Name 'renderer-tests' -Command $node -ToolArguments (@('--test') + $uiTests)
    Invoke-Check -Name 'upstream-baseline' -Command $node -ToolArguments @((Join-Path $ui 'scripts/upstream.mjs'))
    Invoke-Check -Name 'renderer-typecheck' -Command $node -ToolArguments @((Join-Path $ui 'scripts/typecheck.mjs'))
    Invoke-Check -Name 'gateway-contracts' -Command $node -ToolArguments @((Join-Path $nativeRoot 'tests/gateway/run.mjs'), $env:HERMES_UPSTREAM_ROOT)

    $inference = Join-Path $nativeRoot 'services/inference'
    Invoke-Check -Name 'inference-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $inference 'pyproject.toml'), '-o', 'addopts=', (Join-Path $inference 'tests'), '-q')
    Invoke-Check -Name 'inference-lint' -Command $python -ToolArguments @('-m', 'ruff', 'check', (Join-Path $inference 'src'), (Join-Path $inference 'tests'), '--output-format', 'concise')
    Invoke-Check -Name 'inference-format' -Command $python -ToolArguments @('-m', 'ruff', 'format', '--check', (Join-Path $inference 'src'), (Join-Path $inference 'tests'))
    $auth = Join-Path $nativeRoot 'runtime-packs/tabby-v3'
    $authTemp = New-TestDirectory -Label 'auth-pytest'
    # A fresh directory avoids pytest replacing an earlier test directory.
    Invoke-Check -Name 'managed-pack-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $auth 'pytest.ini'), '-o', 'addopts=', (Join-Path $auth 'tests'), '--basetemp', $authTemp, '-q')
    $authCode = @('build_overlay.py','overlay','tests','config') | ForEach-Object { Join-Path $auth $_ }
    Invoke-Check -Name 'managed-pack-lint' -Command $python -ToolArguments (@('-m', 'ruff', 'check') + $authCode)
    Invoke-Check -Name 'managed-pack-format' -Command $python -ToolArguments (@('-m', 'ruff', 'format', '--check') + $authCode)
    Invoke-Check -Name 'managed-pack-config' -Command $python -ToolArguments @((Join-Path $auth 'config/validate_template.py'), '--schema', (Join-Path $resolvedTabby 'common/config_models.py'))

    $backend = Join-Path $nativeRoot 'services/backend-host'
    Invoke-Check -Name 'backend-host-lint' -Command $python -ToolArguments @('-m', 'ruff', 'check', (Join-Path $backend 'src'), (Join-Path $backend 'tests'))
    Invoke-Check -Name 'backend-host-format' -Command $python -ToolArguments @('-m', 'ruff', 'format', '--check', (Join-Path $backend 'src'), (Join-Path $backend 'tests'))
    if ($NativeFixtures) {
        $backendTemp = New-TestDirectory -Label 'backend-pytest'
        Invoke-Check -Name 'backend-host-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $backend 'pyproject.toml'), (Join-Path $backend 'tests'), '--basetemp', $backendTemp, '-q')
    }

    foreach ($package in @('services/resource-host', 'services/terminal-host', 'spikes/webview2-guest')) {
        $manifest = Join-Path (Join-Path $nativeRoot $package) 'Cargo.toml'
        $label = Split-Path -Leaf $package
        Invoke-Check -Name "$label-format" -Command $cargo -ToolArguments @('fmt', '--manifest-path', $manifest, '--check')
        $lintArgs = @('clippy', '--offline', '--locked', '--manifest-path', $manifest, '--all-targets', '--quiet')
        if ($label -eq 'resource-host') { $lintArgs += @('--features', 'test-fixture') }
        Invoke-Check -Name "$label-lint" -Command $cargo -ToolArguments ($lintArgs + @('--', '-D', 'warnings'))
        if ($NativeFixtures) {
            $testArgs = @('test', '--offline', '--locked', '--manifest-path', $manifest, '--quiet')
            if ($label -eq 'resource-host') { $testArgs += @('--features', 'test-fixture') }
            Invoke-Check -Name "$label-tests" -Command $cargo -ToolArguments ($testArgs + @('--', '--test-threads=1'))
        }
    }
    if ($BuildRenderer) {
        Invoke-Check -Name 'renderer-build' -Command $node -ToolArguments @((Join-Path $ui 'scripts/build.mjs'))
    }
    if ($NativeFixtures) {
        $view = Join-Path $nativeRoot 'spikes/webview2-guest'
        Invoke-Check -Name 'webview-native-build' -Command $cargo -ToolArguments @('build', '--offline', '--locked', '--manifest-path', (Join-Path $view 'Cargo.toml'), '--target-dir', (Join-Path $view 'target'), '--quiet')
        $shell = (Get-Process -Id $PID).Path
        Invoke-Check -Name 'webview-native-run' -Command $shell -ToolArguments @('-NoProfile', '-File', (Join-Path $view 'Run-Fixture.ps1'))
    }
    $completed = $true
}
finally {
    [Environment]::SetEnvironmentVariable('HERMES_UPSTREAM_ROOT', $oldUpstream, 'Process')
    [Environment]::SetEnvironmentVariable('HERMES_TABBY_SOURCE', $oldTabbySource, 'Process')
    [ordered]@{
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        completed = $completed
        passed = $completed -and @($results | Where-Object { -not $_.passed }).Count -eq 0
        renderer_build_requested = [bool]$BuildRenderer
        native_fixtures_requested = [bool]$NativeFixtures
        gpu_tests_requested = $false
        skipped_optional_groups = @(
            if (-not $BuildRenderer) { 'renderer-build' }
            if (-not $NativeFixtures) { 'native-fixtures' }
            'gpu-runtime'
        )
        checks = @($results.ToArray())
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $logs 'verification.latest.json') -Encoding utf8
}
