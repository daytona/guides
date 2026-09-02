# Installs pinned, digest-verified Cursor Agent and Git for Windows dependencies.
# -VerifyOnly checks a captured image without changing it.
[CmdletBinding()]
param(
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$CursorAgentVersion = '2026.09.02-e3e9343'
$CursorPackageUrl = 'https://downloads.cursor.com/lab/2026.09.02-e3e9343/windows/x64/agent-cli-package.zip'
$CursorPackageSha512 = 'd21126ba285c554c92f37cf816d0eddae0b1238a7f497c8462d33f6c462c60f9d893ed309b1e87b0a8146f3e37c1da68ee8692d49c77f1b51c0453a6066362de'
$NodeVersion = '22.23.2'
$NodeExecutableUrl = "https://nodejs.org/dist/v$NodeVersion/win-x64/node.exe"
$NodeExecutableSha256 = '0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4'
$ExpectedNodeModuleVersion = '127'
$ExpectedGitVersionOutput = 'git version 2.55.0.windows.2'
$GitInstallerUrl = 'https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.2/Git-2.55.0.2-64-bit.exe'
$GitInstallerSha256 = '74300da8dfe0d844c5449ffb809662f8eeac47916f83730c879c4084890c6c0e'

$CursorVersionRoot = Join-Path 'C:\ProgramData\cursor-agent\versions' $CursorAgentVersion
$CursorNode = Join-Path $CursorVersionRoot 'node.exe'
$CursorIndex = Join-Path $CursorVersionRoot 'index.js'
$CursorNativeModule = Join-Path $CursorVersionRoot 'node_modules\better-sqlite3'
$GitRoot = 'C:\Program Files\Git'
$GitExe = Join-Path $GitRoot 'cmd\git.exe'
$ProgramRoot = 'C:\ProgramData\cursor-self-hosted'
$BootstrapSource = Join-Path $PSScriptRoot 'windows_bootstrap.ps1'
$CheckoutHookSource = Join-Path $PSScriptRoot 'checkout_repo.ps1'
$Bootstrap = Join-Path $ProgramRoot 'windows-bootstrap.ps1'
$CheckoutHook = Join-Path $ProgramRoot 'checkout_repo.ps1'
# Cursor runs agent shell commands and worker hooks through bash on every
# platform; on Windows that is Git Bash.
$GitBashExe = Join-Path $GitRoot 'bin\bash.exe'
$Workspace = 'C:\cursor\workspace'
$SuccessMarker = 'CURSOR_SELF_HOSTED_WINDOWS_PREFLIGHT_OK'

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
        $client.Headers.Add('User-Agent', 'cursor-self-hosted-windows-provisioner')
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

function Assert-Sha512 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected
    )

    if ($Expected -notmatch '^[0-9a-fA-F]{128}$') {
        throw "Invalid expected SHA-512 value for $Path"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA512).Hash
    if (-not $actual.Equals($Expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "SHA-512 mismatch for $Path. Expected $Expected, got $actual"
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

    foreach ($existing in $entries) {
        if ($existing.Trim().TrimEnd('\').Equals($Entry.Trim().TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
    }
    $newEntries = @($entries) + @($Entry)
    [Environment]::SetEnvironmentVariable('Path', ($newEntries -join ';'), 'Machine')
}

function Set-HeadlessGitPrompting {
    # The worker runs headless as SYSTEM. Without these settings a git command
    # that has no credential yet (Cursor's own `git fetch origin` before the
    # minted token lands, or the checkout hook) blocks forever on a Git
    # Credential Manager or console prompt instead of failing.
    $null = Invoke-CheckedCommand -Executable $GitExe -Arguments @('config', '--system', 'credential.interactive', 'never') -Description 'git config credential.interactive never'
    [Environment]::SetEnvironmentVariable('GIT_TERMINAL_PROMPT', '0', 'Machine')
    $env:GIT_TERMINAL_PROMPT = '0'
}

function Set-ExplicitProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $combined = @((Join-Path $GitRoot 'cmd'), (Join-Path $GitRoot 'bin'))
    if (-not [String]::IsNullOrWhiteSpace($machinePath)) {
        $combined += @($machinePath.Split(';') | Where-Object { -not [String]::IsNullOrWhiteSpace($_) })
    }
    if (-not [String]::IsNullOrWhiteSpace($userPath)) {
        $combined += @($userPath.Split(';') | Where-Object { -not [String]::IsNullOrWhiteSpace($_) })
    }
    $env:Path = $combined -join ';'
}

function Test-CursorInstallation {
    if (-not (Test-Path -LiteralPath $CursorNode -PathType Leaf)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $CursorIndex -PathType Leaf)) {
        return $false
    }

    try {
        $versionOutput = Invoke-CheckedCommand -Executable $CursorNode -Arguments @($CursorIndex, '--version') -Description 'Cursor Agent --version'
        return (($versionOutput -join ' ') -match [Regex]::Escape($CursorAgentVersion))
    }
    catch {
        return $false
    }
}

function Test-Provisioning {
    Assert-Administrator

    Write-Host '[preflight] Checking pinned Node.js runtime'
    $nodeVersionOutput = Invoke-CheckedCommand -Executable $CursorNode -Arguments @('--version') -Description 'node --version'
    if (($nodeVersionOutput -join ' ') -cne "v$NodeVersion") {
        throw "node --version returned unexpected output: $($nodeVersionOutput -join [Environment]::NewLine)"
    }
    $nodeModuleVersionOutput = Invoke-CheckedCommand -Executable $CursorNode -Arguments @('-p', 'process.versions.modules') -Description 'Node.js module ABI'
    if (($nodeModuleVersionOutput -join ' ') -cne $ExpectedNodeModuleVersion) {
        throw "Node.js module ABI returned unexpected output: $($nodeModuleVersionOutput -join [Environment]::NewLine)"
    }
    Invoke-CheckedCommand -Executable $CursorNode -Arguments @('-e', 'require(process.argv[1])', $CursorNativeModule) -Description 'Cursor Agent native module probe' | Out-Null
    Write-Host '[preflight] Checking Cursor Agent version'

    $versionOutput = Invoke-CheckedCommand -Executable $CursorNode -Arguments @($CursorIndex, '--version') -Description 'Cursor Agent --version'
    if (($versionOutput -join ' ') -notmatch [Regex]::Escape($CursorAgentVersion)) {
        throw "Cursor Agent --version did not report $CursorAgentVersion. Output: $($versionOutput -join [Environment]::NewLine)"
    }

    Write-Host '[preflight] Checking Cursor worker help'
    $workerHelp = Invoke-CheckedCommand -Executable $CursorNode -Arguments @($CursorIndex, 'worker', '--help') -Description 'Cursor Agent worker --help'
    if (($workerHelp -join ' ') -notmatch '--on-session-start') {
        throw 'Cursor Agent worker --help does not list --on-session-start.'
    }

    Write-Host '[preflight] Checking Git for Windows'
    $gitOutput = Invoke-CheckedCommand -Executable $GitExe -Arguments @('--version') -Description 'git --version'
    if (($gitOutput -join ' ') -cne $ExpectedGitVersionOutput) {
        throw "git --version returned unexpected output: $($gitOutput -join [Environment]::NewLine)"
    }
    $credentialInteractive = Invoke-CheckedCommand -Executable $GitExe -Arguments @('config', '--system', '--get', 'credential.interactive') -Description 'git config credential.interactive'
    if (($credentialInteractive -join '') -ne 'never') {
        throw "git credential.interactive is not 'never' in the system config: $($credentialInteractive -join ' ')"
    }
    if ([Environment]::GetEnvironmentVariable('GIT_TERMINAL_PROMPT', 'Machine') -ne '0') {
        throw 'GIT_TERMINAL_PROMPT=0 is not set in the machine environment.'
    }

    Write-Host '[preflight] Checking runtime files'
    foreach ($requiredFile in @($Bootstrap, $CheckoutHook, $GitBashExe)) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "Required Cursor Self-Hosted Machines runtime file is missing: $requiredFile"
        }
    }

    Write-Host '[preflight] Checking repository workspace'
    if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        throw "Cursor workspace is missing: $Workspace"
    }
    $probePath = Join-Path $Workspace ('.cursor-self-hosted-write-probe-{0}.txt' -f [Guid]::NewGuid().ToString('N'))
    $probeValue = [Guid]::NewGuid().ToString('N')
    try {
        [IO.File]::WriteAllText($probePath, $probeValue, (New-Object Text.UTF8Encoding($false)))
        $readValue = [IO.File]::ReadAllText($probePath)
        if ($readValue -cne $probeValue) {
            throw 'Cursor workspace probe contents did not round-trip exactly.'
        }
    }
    finally {
        if (Test-Path -LiteralPath $probePath) {
            Remove-Item -LiteralPath $probePath -Force
        }
    }
    if (Test-Path -LiteralPath $probePath) {
        throw "Cursor workspace probe could not be deleted: $probePath"
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
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('cursor-self-hosted-provision-{0}' -f [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $installedGitVersion = $null
    if (Test-Path -LiteralPath $GitExe -PathType Leaf) {
        $versionOutput = @(& $GitExe --version 2>$null)
        if ($LASTEXITCODE -eq 0) {
            $installedGitVersion = $versionOutput -join ' '
        }
    }
    if ($installedGitVersion -cne $ExpectedGitVersionOutput) {
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
        try {
            while (-not $installer.WaitForExit(10000)) {
                Write-Host '[provision] Waiting for Git for Windows installer'
            }
            if ($installer.ExitCode -ne 0) {
                throw "Git for Windows installer failed with exit code $($installer.ExitCode)."
            }
        }
        finally {
            $installer.Dispose()
        }
        if (-not (Test-Path -LiteralPath $GitExe -PathType Leaf)) {
            throw 'Git for Windows installation completed without the expected executable.'
        }
    }
    else {
        Write-Host '[provision] Pinned Git for Windows is already installed'
    }

    if (-not (Test-CursorInstallation)) {
        Write-Host "[provision] Installing Cursor Agent $CursorAgentVersion"
        $cursorArchive = Join-Path $tempRoot 'agent-cli-package.zip'
        $cursorExtractRoot = Join-Path $tempRoot 'cursor-package'
        Download-File -Uri $CursorPackageUrl -Destination $cursorArchive
        Assert-Sha512 -Path $cursorArchive -Expected $CursorPackageSha512
        New-Item -ItemType Directory -Path $cursorExtractRoot -Force | Out-Null
        Expand-Archive -LiteralPath $cursorArchive -DestinationPath $cursorExtractRoot -Force

        $packageRoots = @(
            Get-ChildItem -LiteralPath $cursorExtractRoot -Filter 'node.exe' -File -Recurse |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName 'index.js') -PathType Leaf } |
                ForEach-Object { $_.DirectoryName } |
                Select-Object -Unique
        )
        if ($packageRoots.Count -ne 1) {
            throw "Cursor Agent archive must contain exactly one node.exe and index.js package root; found $($packageRoots.Count)."
        }

        if (Test-Path -LiteralPath $CursorVersionRoot) {
            Remove-Item -LiteralPath $CursorVersionRoot -Recurse -Force
        }
        New-Item -ItemType Directory -Path $CursorVersionRoot -Force | Out-Null
        Get-ChildItem -LiteralPath $packageRoots[0] -Force | Move-Item -Destination $CursorVersionRoot -Force
        if (-not (Test-CursorInstallation)) {
            throw "Installed Cursor Agent did not report the pinned version $CursorAgentVersion."
        }
    }
    else {
        Write-Host "[provision] Cursor Agent $CursorAgentVersion is already installed"
    }
    $installedNodeHash = $null
    if (Test-Path -LiteralPath $CursorNode -PathType Leaf) {
        $installedNodeHash = (Get-FileHash -LiteralPath $CursorNode -Algorithm SHA256).Hash
    }
    if (
        [String]::IsNullOrWhiteSpace($installedNodeHash) -or
        -not $installedNodeHash.Equals($NodeExecutableSha256, [StringComparison]::OrdinalIgnoreCase)
    ) {
        Write-Host "[provision] Installing Node.js $NodeVersion for Cursor native modules"
        $nodeExecutable = Join-Path $tempRoot 'node.exe'
        Download-File -Uri $NodeExecutableUrl -Destination $nodeExecutable
        Assert-Sha256 -Path $nodeExecutable -Expected $NodeExecutableSha256
        Copy-Item -LiteralPath $nodeExecutable -Destination $CursorNode -Force
    }
    else {
        Write-Host "[provision] Pinned Node.js $NodeVersion is already installed"
    }


    New-Item -ItemType Directory -Path $ProgramRoot -Force | Out-Null
    foreach ($sourceFile in @($BootstrapSource, $CheckoutHookSource)) {
        if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
            throw "Provisioning input is missing: $sourceFile"
        }
    }
    Copy-Item -LiteralPath $BootstrapSource -Destination $Bootstrap -Force
    Copy-Item -LiteralPath $CheckoutHookSource -Destination $CheckoutHook -Force
    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null

    Ensure-MachinePathEntry -Entry (Join-Path $GitRoot 'cmd')
    Ensure-MachinePathEntry -Entry (Join-Path $GitRoot 'bin')
    Set-ExplicitProcessPath
    Set-HeadlessGitPrompting
    Test-Provisioning
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
