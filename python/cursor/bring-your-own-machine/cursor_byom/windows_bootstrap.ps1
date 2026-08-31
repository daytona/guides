[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$PidPath,
    [Parameter(Mandatory = $true)][string]$StdinPath,
    [Parameter(Mandatory = $true)][string]$StdoutPath,
    [Parameter(Mandatory = $true)][string]$StderrPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$launchConfigPath = $ConfigPath
try {
    $config = Get-Content -LiteralPath $launchConfigPath -Raw | ConvertFrom-Json
    if ($null -eq $config.environment) {
        throw 'Launch configuration has no environment object.'
    }
    if ($config.arguments -isnot [string] -or $config.arguments.Length -eq 0) {
        throw 'Launch configuration has no argument string.'
    }

    foreach ($property in $config.environment.PSObject.Properties) {
        [Environment]::SetEnvironmentVariable(
            $property.Name,
            [string]$property.Value,
            [EnvironmentVariableTarget]::Process
        )
    }
    $arguments = $config.arguments
}
finally {
    Remove-Item -LiteralPath $launchConfigPath -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $launchConfigPath) {
        throw "Failed to remove launch configuration: $launchConfigPath"
    }
}

Set-Content -LiteralPath $StdinPath -Value '' -Encoding Ascii
$process = Start-Process `
    -FilePath $Executable `
    -ArgumentList $arguments `
    -WorkingDirectory $WorkingDirectory `
    -RedirectStandardInput $StdinPath `
    -RedirectStandardOutput $StdoutPath `
    -RedirectStandardError $StderrPath `
    -WindowStyle Hidden `
    -PassThru

$pidDirectory = Split-Path -Parent $PidPath
$temporaryPidPath = Join-Path $pidDirectory (
    '.worker.pid.{0}.tmp' -f [Guid]::NewGuid().ToString('N')
)
try {
    [IO.File]::WriteAllText(
        $temporaryPidPath,
        ([string]$process.Id + [Environment]::NewLine),
        [Text.Encoding]::ASCII
    )
    Move-Item -LiteralPath $temporaryPidPath -Destination $PidPath -Force
}
catch {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw
}
finally {
    Remove-Item -LiteralPath $temporaryPidPath -Force -ErrorAction SilentlyContinue
}

Write-Output $process.Id
