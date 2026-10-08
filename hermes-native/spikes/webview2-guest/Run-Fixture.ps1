param([ValidateRange(1, 120)][int]$TimeoutSeconds = 75)
$ErrorActionPreference = 'Stop'
if (-not $env:VIRTUAL_ENV) { throw 'Activate the project Python virtual environment before automation.' }
$spikeRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$executable = Join-Path $spikeRoot 'target\debug\hermes-webview2-guest-spike.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'Build first: cargo build --offline --locked --quiet'
}
$checksRoot = Join-Path $spikeRoot '.checks'
New-Item -ItemType Directory -Path $checksRoot -Force | Out-Null
$runId = [Guid]::NewGuid().ToString('N')
$outputDirectory = Join-Path $checksRoot "run-$runId"
$stdout = Join-Path $checksRoot "$runId.stdout.log"
$stderr = Join-Path $checksRoot "$runId.stderr.log"
$process = Start-Process -FilePath $executable -ArgumentList @('"' + $outputDirectory + '"') -WorkingDirectory $spikeRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
try {
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        # This handle identifies only our just-created fixture and its descendants.
        $process.Kill($true)
        $process.WaitForExit()
        throw "Fixture exceeded ${TimeoutSeconds}s deadline. Owned output: $outputDirectory"
    }
    $process.Refresh()
    $reportPath = Join-Path $outputDirectory 'report.json'
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) {
        if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Tail 8 | Write-Output }
        throw "Fixture failed (exit $($process.ExitCode)). Owned output: $outputDirectory"
    }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.status -ne 'passed') { throw "Fixture reported failure: $reportPath" }
    [pscustomobject]@{
        Status = $report.status
        Runtime = $report.webview2_runtime
        ElapsedMilliseconds = $report.elapsed_ms
        Evidence = $reportPath
    }
} finally {
    $process.Dispose()
}
