# Runs inside the Windows sandbox and starts the remote detached.
# The pid file it writes is the source of truth polled by the orchestrator.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ConfigPath,
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$PidPath,
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

    # The remote and agent shell inherit this process environment. Remove ambient
    # variables before adding the explicit spawn contract supplied by the launcher.
    $allowedNames = @($config.environment.PSObject.Properties.Name)
    Get-ChildItem Env: | ForEach-Object {
        if ($allowedNames -notcontains $_.Name) {
            Remove-Item -LiteralPath ("Env:{0}" -f $_.Name) -ErrorAction SilentlyContinue
        }
    }
    foreach ($property in $config.environment.PSObject.Properties) {
        Set-Item -LiteralPath ("Env:{0}" -f $property.Name) -Value ([string]$property.Value)
    }
}
finally {
    # Always remove the exact bearer-token-bearing launch file supplied by the
    # launcher, including when reading, parsing, validation, or setup fails.
    Remove-Item -LiteralPath $launchConfigPath -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $launchConfigPath) {
        throw "Failed to remove launch configuration: $launchConfigPath"
    }
}

# Give the remote file handles for all three standard streams. Without an
# explicit stdin it inherits the launching exec's pipe and keeps the Daytona
# exec call open until the server kills it.
$stdinPath = $PidPath + '.stdin'
Set-Content -LiteralPath $stdinPath -Value '' -Encoding Ascii

$startParameters = @{
    FilePath = $Executable
    ArgumentList = 'serve'
    WorkingDirectory = $WorkingDirectory
    RedirectStandardInput = $stdinPath
    RedirectStandardOutput = $StdoutPath
    RedirectStandardError = $StderrPath
    WindowStyle = 'Hidden'
    PassThru = $true
}
$process = Start-Process @startParameters

Set-Content -LiteralPath $PidPath -Value $process.Id -Encoding Ascii
Write-Output $process.Id
