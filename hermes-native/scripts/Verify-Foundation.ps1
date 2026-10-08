#Requires -Version 7.0
# CPU-only foundation checks. -NativeFixtures includes owned harmless processes,
# filesystem watches and the retained settings UI integration (npm test:integration).
# Desktop-shell asset packaging, full Tauri builds and its bounded native UI modes
# remain separate: apps/desktop-shell/scripts/verify_native.py. GPU/model tests are
# never selected by this script.
# Model-catalog checks use only synthetic metadata/header fixtures; real user
# model directories are never inspected by this foundation runner.
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
$savedEnvironment = @{}
foreach ($name in @(
    'HERMES_UPSTREAM_ROOT', 'HERMES_TABBY_SOURCE', 'HERMES_CONTROL_PYTHON',
    'HERMES_CONTROL_WORKER_ROOT', 'HERMES_CONTROL_INFERENCE_SRC',
    'HERMES_BASE_PYTHON', 'HERMES_INFERENCE_SRC', 'HERMES_NATIVE_DESKTOP',
    'HERMES_CATALOG_PYTHON', 'HERMES_CATALOG_TEST_ROOT'
)) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
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
    $inference = Join-Path $nativeRoot 'services/inference'
    $control = Join-Path $nativeRoot 'services/control-worker'
    $catalog = Join-Path $nativeRoot 'services/model-catalog'
    $catalogHost = Join-Path $nativeRoot 'services/catalog-host'
    if ($NativeFixtures) {
        # Windows venv executables redirect to a base interpreter. The owned host
        # and UI fixtures must pin that actual interpreter, not an ambient override.
        $baseOutput = @(& $python -I -S -B -c 'from pathlib import Path; import json, sys; print(json.dumps({"path": str(Path(sys._base_executable).resolve(strict=True)), "version": list(sys.version_info[:2])}))')
        if ($LASTEXITCODE -ne 0 -or $baseOutput.Count -ne 1) { throw 'Unable to discover the active virtual environment base interpreter.' }
        $baseInfo = $baseOutput[0] | ConvertFrom-Json
        if ($baseInfo.version[0] -ne 3 -or $baseInfo.version[1] -lt 12 -or $baseInfo.version[1] -ge 14) {
            throw 'Control fixtures require the active virtual environment to use Python 3.12 or 3.13.'
        }
        $basePython = (Resolve-Path -LiteralPath $baseInfo.path).Path
        if (-not (Test-Path -LiteralPath $basePython -PathType Leaf)) { throw 'The base interpreter is not a file.' }
        $env:HERMES_CONTROL_PYTHON = $basePython
        $env:HERMES_BASE_PYTHON = $basePython
        $env:HERMES_CATALOG_PYTHON = $basePython
        $env:HERMES_CATALOG_TEST_ROOT = New-TestDirectory -Label 'catalog-host-native'
        $env:HERMES_CONTROL_WORKER_ROOT = (Resolve-Path -LiteralPath $control).Path
        $env:HERMES_CONTROL_INFERENCE_SRC = (Resolve-Path -LiteralPath (Join-Path $inference 'src')).Path
        $env:HERMES_INFERENCE_SRC = $env:HERMES_CONTROL_INFERENCE_SRC
        $env:HERMES_NATIVE_DESKTOP = (Resolve-Path -LiteralPath $ui).Path
    }
    $uiTests = @(Get-ChildItem -LiteralPath (Join-Path $ui 'tests') -Filter '*.test.mjs' -File | ForEach-Object FullName)
    if ($uiTests.Count -eq 0) { throw 'No retained-renderer tests found.' }
    Invoke-Check -Name 'renderer-tests' -Command $node -ToolArguments (@('--test') + $uiTests)
    Invoke-Check -Name 'upstream-baseline' -Command $node -ToolArguments @((Join-Path $ui 'scripts/upstream.mjs'))
    Invoke-Check -Name 'renderer-typecheck' -Command $node -ToolArguments @((Join-Path $ui 'scripts/typecheck.mjs'))
    Invoke-Check -Name 'gateway-contracts' -Command $node -ToolArguments @((Join-Path $nativeRoot 'tests/gateway/run.mjs'), $env:HERMES_UPSTREAM_ROOT)

    Invoke-Check -Name 'inference-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $inference 'pyproject.toml'), '-o', 'addopts=', (Join-Path $inference 'tests'), '-q')
    Invoke-Check -Name 'inference-lint' -Command $python -ToolArguments @('-m', 'ruff', 'check', (Join-Path $inference 'src'), (Join-Path $inference 'tests'), '--output-format', 'concise')
    Invoke-Check -Name 'inference-format' -Command $python -ToolArguments @('-m', 'ruff', 'format', '--check', (Join-Path $inference 'src'), (Join-Path $inference 'tests'))

    $catalogTemp = New-TestDirectory -Label 'model-catalog-pytest'
    $catalogCode = @('src', 'tests', 'inspect_model.py') | ForEach-Object { Join-Path $catalog $_ }
    Invoke-Check -Name 'model-catalog-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $catalog 'pyproject.toml'), '-o', 'addopts=', (Join-Path $catalog 'tests'), '--basetemp', $catalogTemp, '-q')
    Invoke-Check -Name 'model-catalog-lint' -Command $python -ToolArguments (@('-m', 'ruff', 'check') + $catalogCode)
    Invoke-Check -Name 'model-catalog-format' -Command $python -ToolArguments (@('-m', 'ruff', 'format', '--check') + $catalogCode)

    $catalogHostCode = @('bootstrap.py', 'prepare_config.py', 'tests/test_bootstrap.py') | ForEach-Object { Join-Path $catalogHost $_ }
    Invoke-Check -Name 'catalog-host-python-lint' -Command $python -ToolArguments (@('-m', 'ruff', 'check') + $catalogHostCode)
    Invoke-Check -Name 'catalog-host-python-format' -Command $python -ToolArguments (@('-m', 'ruff', 'format', '--check') + $catalogHostCode)
    if ($NativeFixtures) {
        # Bootstrap tests run only synthetic CPU child processes and prepare fresh
        # receipts. They never inspect user model roots or import model engines.
        $catalogHostTemp = New-TestDirectory -Label 'catalog-host-pytest'
        Invoke-Check -Name 'catalog-host-python-tests' -Command $python -ToolArguments @('-m', 'pytest', '-o', 'addopts=', (Join-Path $catalogHost 'tests/test_bootstrap.py'), '--basetemp', $catalogHostTemp, '-q')
    }

    $auth = Join-Path $nativeRoot 'runtime-packs/tabby-v3'
    $authTemp = New-TestDirectory -Label 'auth-pytest'
    # A fresh directory avoids pytest replacing an earlier test directory.
    Invoke-Check -Name 'managed-pack-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $auth 'pytest.ini'), '-o', 'addopts=', (Join-Path $auth 'tests'), '--basetemp', $authTemp, '-q')
    $authCode = @('build_overlay.py','overlay','tests','config') | ForEach-Object { Join-Path $auth $_ }
    Invoke-Check -Name 'managed-pack-lint' -Command $python -ToolArguments (@('-m', 'ruff', 'check') + $authCode)
    Invoke-Check -Name 'managed-pack-format' -Command $python -ToolArguments (@('-m', 'ruff', 'format', '--check') + $authCode)
    Invoke-Check -Name 'managed-pack-config' -Command $python -ToolArguments @((Join-Path $auth 'config/validate_template.py'), '--schema', (Join-Path $resolvedTabby 'common/config_models.py'))

    $controlCode = @('src', 'bootstrap.py', 'tests') | ForEach-Object { Join-Path $control $_ }
    Invoke-Check -Name 'control-worker-lint' -Command $python -ToolArguments (@('-m', 'ruff', 'check') + $controlCode)
    Invoke-Check -Name 'control-worker-format' -Command $python -ToolArguments (@('-m', 'ruff', 'format', '--check') + $controlCode)
    if ($NativeFixtures) {
        $controlTemp = New-TestDirectory -Label 'control-pytest'
        Invoke-Check -Name 'control-worker-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $control 'pyproject.toml'), '-o', 'addopts=', (Join-Path $control 'tests'), '--basetemp', $controlTemp, '-q')
        # Invoke the exact npm test:integration entry point without an npm shell.
        Invoke-Check -Name 'renderer-integration' -Command $node -ToolArguments @((Join-Path $ui 'tests/integration/run.mjs'))
    }

    $backend = Join-Path $nativeRoot 'services/backend-host'
    Invoke-Check -Name 'backend-host-lint' -Command $python -ToolArguments @('-m', 'ruff', 'check', (Join-Path $backend 'src'), (Join-Path $backend 'tests'))
    Invoke-Check -Name 'backend-host-format' -Command $python -ToolArguments @('-m', 'ruff', 'format', '--check', (Join-Path $backend 'src'), (Join-Path $backend 'tests'))
    if ($NativeFixtures) {
        $backendTemp = New-TestDirectory -Label 'backend-pytest'
        Invoke-Check -Name 'backend-host-tests' -Command $python -ToolArguments @('-m', 'pytest', '-c', (Join-Path $backend 'pyproject.toml'), (Join-Path $backend 'tests'), '--basetemp', $backendTemp, '-q')
    }

    Invoke-Check -Name 'owned-ws-vendor' -Command $python -ToolArguments @((Join-Path $nativeRoot 'services/owned-ws/verify_vendor.py'))

    foreach ($package in @('services/resource-host', 'services/preview-watch', 'services/control-host', 'services/catalog-host', 'services/owned-http', 'services/owned-ws', 'services/terminal-host', 'spikes/webview2-guest')) {
        $manifest = Join-Path (Join-Path $nativeRoot $package) 'Cargo.toml'
        $label = Split-Path -Leaf $package
        Invoke-Check -Name "$label-format" -Command $cargo -ToolArguments @('fmt', '--manifest-path', $manifest, '--check')
        $lintArgs = @('clippy', '--offline', '--locked', '--manifest-path', $manifest, '--all-targets', '--quiet')
        # resource-host enables owned, captured and framed worker suites; control-host
        # enables its synthetic peers and actual Python worker tests with the env above.
        # catalog-host uses the resolved base interpreter and a fresh synthetic
        # output root; its one-shot tests do not load engines or user models.
        # owned-http enables harmless loopback peers; the retained real-handler proof is separate.
        if ($label -in @('resource-host', 'control-host', 'owned-http')) { $lintArgs += @('--features', 'test-fixture') }
        if ($label -eq 'owned-ws') { $lintArgs += '--all-features' }
        Invoke-Check -Name "$label-lint" -Command $cargo -ToolArguments ($lintArgs + @('--', '-D', 'warnings'))
        if ($NativeFixtures) {
            $testArgs = @('test', '--offline', '--locked', '--manifest-path', $manifest, '--quiet')
            if ($label -in @('resource-host', 'control-host', 'owned-http')) { $testArgs += @('--features', 'test-fixture') }
            if ($label -eq 'owned-ws') { $testArgs += '--all-features' }
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
    foreach ($name in $savedEnvironment.Keys) {
        # Preserve the difference between absent and empty on PowerShell 7.5+/.NET 9.
        $value = if ($null -eq $savedEnvironment[$name]) { [NullString]::Value } else { $savedEnvironment[$name] }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
    [ordered]@{
        generated_at_utc = [DateTime]::UtcNow.ToString('o')
        completed = $completed
        passed = $completed -and @($results | Where-Object { -not $_.passed }).Count -eq 0
        renderer_build_requested = [bool]$BuildRenderer
        native_fixtures_requested = [bool]$NativeFixtures
        gpu_tests_requested = $false
        separate_runners = @('desktop-shell-assets', 'desktop-shell-build', 'desktop-shell-native-ui', 'retained-rust-http-diagnostic')
        skipped_optional_groups = @(
            if (-not $BuildRenderer) { 'renderer-build' }
            if (-not $NativeFixtures) { 'native-fixtures' }
            'gpu-runtime'
        )
        checks = @($results.ToArray())
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $logs 'verification.latest.json') -Encoding utf8
}
