# Installs pinned, SHA-verified dependencies in a Windows sandbox image.
# -VerifyOnly re-checks an existing image without modifying it.
[CmdletBinding()]
param(
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ExpectedGitVersionOutput = 'git version 2.55.0.windows.2'
$GitInstallerUrl = 'https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.2/Git-2.55.0.2-64-bit.exe'
$GitInstallerSha256 = '74300da8dfe0d844c5449ffb809662f8eeac47916f83730c879c4084890c6c0e'
$DevinManifestUrl = 'https://static.devin.ai/cli/current/manifest.json'
$ChromeVersion = '150.0.7871.115'
$ChromeArchiveUrl = 'https://storage.googleapis.com/chrome-for-testing-public/150.0.7871.115/win64/chrome-win64.zip'
$ChromeArchiveSha256 = '90e0d112cb2f2743a7fd723f030c15b6421940be61dcbda7758563f821dd81da'
$GitRoot = 'C:\Program Files\Git'
$GitBash = Join-Path $GitRoot 'bin\bash.exe'
$GitExe = Join-Path $GitRoot 'cmd\git.exe'
$DevinBin = 'C:\ProgramData\devin-outposts\devin\bin'
$DevinExe = Join-Path $DevinBin 'devin.exe'
$ChromeRoot = 'C:\Program Files\Google\Chrome\Application'
$ChromeExe = Join-Path $ChromeRoot 'chrome.exe'
$FfmpegExe = 'C:\Program Files\ffmpeg\bin\ffmpeg.exe'
$ReposRoot = 'C:\repos'
$SuccessMarker = 'DEVIN_OUTPOSTS_WINDOWS_PREFLIGHT_OK'

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Provisioning must run from an elevated Windows PowerShell session.'
    }
}

function Download-File {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $parsedUri = New-Object System.Uri($Uri)
    if ($parsedUri.Scheme -ne 'https') {
        throw "Refusing non-HTTPS download URL: $Uri"
    }

    $client = New-Object System.Net.WebClient
    try {
        $client.Headers.Add('User-Agent', 'devin-outposts-windows-provisioner')
        $download = $client.DownloadFileTaskAsync($parsedUri, $Destination)
        while (-not $download.IsCompleted) {
            Write-Host "[download] Waiting for $($parsedUri.Host)"
            Start-Sleep -Seconds 10
        }
        $download.GetAwaiter().GetResult()
    }
    finally {
        $client.Dispose()
    }

    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) {
        throw "Download did not create the expected file: $Destination"
    }
}

function Assert-Sha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected
    )

    if ($Expected -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Invalid expected SHA-256 value for $Path"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if (-not $actual.Equals($Expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "SHA-256 mismatch for $Path. Expected $Expected, got $actual"
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "$Description executable is missing: $Executable"
    }

    $output = @(& $Executable @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode. Output: $($output -join [Environment]::NewLine)"
    }
    return ,$output
}

function Ensure-MachinePathEntry {
    param([Parameter(Mandatory = $true)][string]$Entry)

    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $entries = @()
    if (-not [String]::IsNullOrWhiteSpace($machinePath)) {
        $entries = @($machinePath.Split(';') | Where-Object { -not [String]::IsNullOrWhiteSpace($_) })
    }

    $present = $false
    foreach ($existing in $entries) {
        if ($existing.Trim().TrimEnd('\').Equals($Entry.Trim().TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
            $present = $true
            break
        }
    }

    if (-not $present) {
        $newEntries = @($entries) + @($Entry)
        [Environment]::SetEnvironmentVariable('Path', ($newEntries -join ';'), 'Machine')
    }
}

function Set-ExplicitProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $required = @((Join-Path $GitRoot 'cmd'), (Join-Path $GitRoot 'bin'), $DevinBin)
    $combined = @($required)
    if (-not [String]::IsNullOrWhiteSpace($machinePath)) {
        $combined += @($machinePath.Split(';') | Where-Object { -not [String]::IsNullOrWhiteSpace($_) })
    }
    if (-not [String]::IsNullOrWhiteSpace($userPath)) {
        $combined += @($userPath.Split(';') | Where-Object { -not [String]::IsNullOrWhiteSpace($_) })
    }
    $env:Path = $combined -join ';'
}

function Test-Provisioning {
    Assert-Administrator
    Write-Host '[preflight] Checking Git Bash'
    $bashMarker = 'DEVIN_OUTPOSTS_GIT_BASH_OK'
    $bashOutput = Invoke-CheckedCommand -Executable $GitBash -Arguments @('--noprofile', '--norc', '-c', "printf '%s' '$bashMarker'") -Description 'Git Bash marker check'
    if (($bashOutput -join [Environment]::NewLine) -cne $bashMarker) {
        throw "Git Bash returned an unexpected marker: $($bashOutput -join [Environment]::NewLine)"
    }

    Write-Host '[preflight] Checking Git CLI'
    $gitOutput = Invoke-CheckedCommand -Executable $GitExe -Arguments @('--version') -Description 'git --version'
    if (($gitOutput -join ' ') -cne $ExpectedGitVersionOutput) {
        throw "git --version returned unexpected output: $($gitOutput -join [Environment]::NewLine)"
    }

    Write-Host '[preflight] Checking Devin CLI'
    $devinVersionOutput = Invoke-CheckedCommand -Executable $DevinExe -Arguments @('--version') -Description 'devin --version'
    if ([String]::IsNullOrWhiteSpace(($devinVersionOutput -join ' '))) {
        throw 'devin --version returned no output.'
    }

    Write-Host '[preflight] Checking Devin worker command'
    $devinWorkerOutput = Invoke-CheckedCommand -Executable $DevinExe -Arguments @('worker', 'start', '--help') -Description 'devin worker start --help'
    if ([String]::IsNullOrWhiteSpace(($devinWorkerOutput -join ' '))) {
        throw 'devin worker start --help returned no output.'
    }

    Write-Host '[preflight] Checking Chrome'
    if (-not (Test-Path -LiteralPath $ChromeExe -PathType Leaf)) {
        throw "Chrome executable is missing: $ChromeExe"
    }
    $installedChromeVersion = (Get-Item -LiteralPath $ChromeExe).VersionInfo.ProductVersion
    if ($installedChromeVersion -cne $ChromeVersion) {
        throw "Chrome version mismatch. Expected $ChromeVersion, got $installedChromeVersion"
    }
    $chromeProbeRoot = Join-Path ([IO.Path]::GetTempPath()) ('devin-outposts-chrome-{0}' -f [Guid]::NewGuid().ToString('N'))
    $chromeProfile = Join-Path $chromeProbeRoot 'profile'
    New-Item -ItemType Directory -Path $chromeProbeRoot -Force | Out-Null
    $chromeProcess = $null
    try {
        $chromeArguments = @(
            '--headless=new',
            '--disable-gpu',
            '--no-sandbox',
            '--no-first-run',
            '--disable-background-networking',
            '--disable-component-update',
            '--disable-sync',
            '--remote-debugging-port=0',
            ('--user-data-dir="{0}"' -f $chromeProfile),
            'about:blank'
        )
        $chromeProcess = Start-Process -FilePath $ChromeExe -ArgumentList $chromeArguments -PassThru
        $devtoolsPortPath = Join-Path $chromeProfile 'DevToolsActivePort'
        for ($attempt = 0; $attempt -lt 60 -and -not (Test-Path -LiteralPath $devtoolsPortPath -PathType Leaf); $attempt++) {
            if ($chromeProcess.HasExited) {
                throw "Chrome exited before opening its DevTools endpoint with exit code $($chromeProcess.ExitCode)."
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not (Test-Path -LiteralPath $devtoolsPortPath -PathType Leaf)) {
            throw 'Chrome did not open its DevTools endpoint within 30 seconds.'
        }
        $devtoolsPort = [int](@(Get-Content -LiteralPath $devtoolsPortPath)[0])
        $version = Invoke-RestMethod -UseBasicParsing -Uri ('http://127.0.0.1:{0}/json/version' -f $devtoolsPort) -TimeoutSec 10
        if ([String]::IsNullOrWhiteSpace([string]$version.Browser) -or [string]$version.Browser -notmatch [Regex]::Escape($ChromeVersion)) {
            throw "Chrome DevTools returned an unexpected browser version: $($version.Browser)"
        }
    }
    finally {
        if ($null -ne $chromeProcess) {
            $taskkill = Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', $chromeProcess.Id, '/T', '/F') -Wait -PassThru -WindowStyle Hidden
            [void]$chromeProcess.WaitForExit(10000)
            $chromeProcess.Dispose()
            $taskkill.Dispose()
        }
        for ($cleanupAttempt = 0; $cleanupAttempt -lt 60 -and (Test-Path -LiteralPath $chromeProbeRoot); $cleanupAttempt++) {
            $profileProcesses = @(
                Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction SilentlyContinue |
                    Where-Object {
                        -not [String]::IsNullOrWhiteSpace([string]$_.CommandLine) -and
                        $_.CommandLine.IndexOf($chromeProfile, [StringComparison]::OrdinalIgnoreCase) -ge 0
                    }
            )
            foreach ($profileProcess in $profileProcesses) {
                Stop-Process -Id $profileProcess.ProcessId -Force -ErrorAction SilentlyContinue
            }
            try {
                Remove-Item -LiteralPath $chromeProbeRoot -Recurse -Force -ErrorAction Stop
            }
            catch {
                if ($cleanupAttempt -eq 59) {
                    throw
                }
                Start-Sleep -Milliseconds 500
            }
        }
    }

    Write-Host '[preflight] Checking ffmpeg'
    $ffmpegOutput = Invoke-CheckedCommand -Executable $FfmpegExe -Arguments @('-version') -Description 'ffmpeg -version'
    if (($ffmpegOutput -join [Environment]::NewLine) -notmatch '^ffmpeg version ') {
        throw "ffmpeg returned unexpected output: $($ffmpegOutput -join [Environment]::NewLine)"
    }

    Write-Host '[preflight] Checking repository workspace'
    if (-not (Test-Path -LiteralPath $ReposRoot -PathType Container)) {
        throw "Repository workspace is missing: $ReposRoot"
    }
    $probePath = Join-Path $ReposRoot ('.devin-outposts-write-probe-{0}.txt' -f [Guid]::NewGuid().ToString('N'))
    $probeValue = [Guid]::NewGuid().ToString('N')
    try {
        [IO.File]::WriteAllText($probePath, $probeValue, (New-Object Text.UTF8Encoding($false)))
        $readValue = [IO.File]::ReadAllText($probePath)
        if ($readValue -cne $probeValue) {
            throw 'Repository workspace probe contents did not round-trip exactly.'
        }
    }
    finally {
        if (Test-Path -LiteralPath $probePath) {
            Remove-Item -LiteralPath $probePath -Force
        }
    }
    if (Test-Path -LiteralPath $probePath) {
        throw "Repository workspace probe could not be deleted: $probePath"
    }

    Write-Output $SuccessMarker
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This provisioner only supports Windows.'
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if ($VerifyOnly) {
    Set-ExplicitProcessPath
    Test-Provisioning
    return
}

Assert-Administrator
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('devin-outposts-provision-{0}' -f [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $installedGitVersion = $null
    if ((Test-Path -LiteralPath $GitBash -PathType Leaf) -and (Test-Path -LiteralPath $GitExe -PathType Leaf)) {
        $versionOutput = @(& $GitExe --version 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $installedGitVersion = $versionOutput -join ' '
        }
    }

    if ($installedGitVersion -ne $ExpectedGitVersionOutput) {
        Write-Host '[provision] Installing pinned Git for Windows'
        $gitInstaller = Join-Path $tempRoot 'git-installer.exe'
        Download-File -Uri $GitInstallerUrl -Destination $gitInstaller
        Assert-Sha256 -Path $gitInstaller -Expected $GitInstallerSha256
        $installerArguments = @(
            '/VERYSILENT',
            '/NORESTART',
            '/NOCANCEL',
            '/SP-',
            '/CLOSEAPPLICATIONS',
            '/RESTARTAPPLICATIONS',
            ('/DIR="{0}"' -f $GitRoot)
        )
        $installer = Start-Process -FilePath $gitInstaller -ArgumentList $installerArguments -PassThru
        while (-not $installer.WaitForExit(10000)) {
            Write-Host '[provision] Waiting for Git for Windows installer'
        }
        if ($installer.ExitCode -ne 0) {
            throw "Git for Windows installer failed with exit code $($installer.ExitCode)."
        }
        if (-not (Test-Path -LiteralPath $GitBash -PathType Leaf) -or -not (Test-Path -LiteralPath $GitExe -PathType Leaf)) {
            throw 'Git for Windows installation completed without the expected Git Bash and Git executables.'
        }
    }
    else {
        Write-Host '[provision] Pinned Git for Windows is already installed'
    }

    $installedChromeVersion = $null
    if (Test-Path -LiteralPath $ChromeExe -PathType Leaf) {
        $installedChromeVersion = (Get-Item -LiteralPath $ChromeExe).VersionInfo.ProductVersion
    }
    if ($installedChromeVersion -cne $ChromeVersion) {
        Write-Host "[provision] Installing Chrome for Testing $ChromeVersion"
        $chromeArchive = Join-Path $tempRoot 'chrome-win64.zip'
        Download-File -Uri $ChromeArchiveUrl -Destination $chromeArchive
        Assert-Sha256 -Path $chromeArchive -Expected $ChromeArchiveSha256
        $chromeExtractRoot = Join-Path $tempRoot 'chrome-extracted'
        Expand-Archive -LiteralPath $chromeArchive -DestinationPath $chromeExtractRoot -Force
        $extractedChromeRoot = Join-Path $chromeExtractRoot 'chrome-win64'
        $extractedChromeExe = Join-Path $extractedChromeRoot 'chrome.exe'
        if (-not (Test-Path -LiteralPath $extractedChromeExe -PathType Leaf)) {
            throw 'Chrome archive did not contain chrome-win64\chrome.exe.'
        }
        $chromeParent = Split-Path -Path $ChromeRoot -Parent
        New-Item -ItemType Directory -Path $chromeParent -Force | Out-Null
        $stagedChromeRoot = Join-Path $chromeParent ('Application-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
        try {
            Copy-Item -LiteralPath $extractedChromeRoot -Destination $stagedChromeRoot -Recurse -Force
            if (Test-Path -LiteralPath $ChromeRoot) {
                Remove-Item -LiteralPath $ChromeRoot -Recurse -Force
            }
            Move-Item -LiteralPath $stagedChromeRoot -Destination $ChromeRoot
        }
        finally {
            if (Test-Path -LiteralPath $stagedChromeRoot) {
                Remove-Item -LiteralPath $stagedChromeRoot -Recurse -Force
            }
        }
    }
    else {
        Write-Host "[provision] Chrome for Testing $ChromeVersion is already installed"
    }

    Write-Host '[provision] Resolving current Devin CLI'
    $manifestPath = Join-Path $tempRoot 'devin-manifest.json'
    Download-File -Uri $DevinManifestUrl -Destination $manifestPath
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    }
    catch {
        throw "Devin CLI manifest is not valid JSON: $($_.Exception.Message)"
    }
    if ($null -eq $manifest.platforms) {
        throw 'Devin CLI manifest does not contain a platforms object.'
    }
    $platform = $manifest.platforms.'x86_64-pc-windows'
    if ($null -eq $platform -or [String]::IsNullOrWhiteSpace([string]$platform.url) -or [String]::IsNullOrWhiteSpace([string]$platform.sha256)) {
        throw 'Devin CLI manifest does not contain a complete x86_64-pc-windows entry.'
    }

    $installedDevinVersion = $null
    if (Test-Path -LiteralPath $DevinExe -PathType Leaf) {
        $versionOutput = @(& $DevinExe --version 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $installedDevinVersion = $versionOutput -join ' '
        }
    }
    $manifestVersion = [string]$manifest.version
    if ([String]::IsNullOrWhiteSpace($manifestVersion)) {
        throw 'Devin CLI manifest does not contain a version.'
    }

    if ($null -eq $installedDevinVersion -or $installedDevinVersion -cne $manifestVersion) {
        Write-Host "[provision] Installing Devin CLI $manifestVersion"
        $bundlePath = Join-Path $tempRoot 'devin-windows.zip'
        Download-File -Uri ([string]$platform.url) -Destination $bundlePath
        Assert-Sha256 -Path $bundlePath -Expected ([string]$platform.sha256)

        $extractRoot = Join-Path $tempRoot 'devin-extracted'
        Expand-Archive -LiteralPath $bundlePath -DestinationPath $extractRoot -Force
        $candidates = @(Get-ChildItem -LiteralPath $extractRoot -Recurse -File -Filter 'devin.exe')
        if ($candidates.Count -ne 1) {
            throw "Expected exactly one devin.exe in the Devin CLI bundle, found $($candidates.Count)."
        }
        New-Item -ItemType Directory -Path $DevinBin -Force | Out-Null
        $stagedDevin = Join-Path $DevinBin ('devin-{0}.tmp' -f [Guid]::NewGuid().ToString('N'))
        try {
            Copy-Item -LiteralPath $candidates[0].FullName -Destination $stagedDevin -Force
            Move-Item -LiteralPath $stagedDevin -Destination $DevinExe -Force
        }
        finally {
            if (Test-Path -LiteralPath $stagedDevin) {
                Remove-Item -LiteralPath $stagedDevin -Force
            }
        }
    }
    else {
        Write-Host "[provision] Devin CLI $manifestVersion is already installed"
    }

    New-Item -ItemType Directory -Path $ReposRoot -Force | Out-Null
    Ensure-MachinePathEntry -Entry (Join-Path $GitRoot 'cmd')
    Ensure-MachinePathEntry -Entry (Join-Path $GitRoot 'bin')
    Ensure-MachinePathEntry -Entry $DevinBin
    Set-ExplicitProcessPath
    Test-Provisioning
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
