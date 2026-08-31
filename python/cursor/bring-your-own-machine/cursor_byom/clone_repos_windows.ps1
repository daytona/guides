# Clones repositories from one Cursor sessionStart JSON payload read from stdin.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$GitExe = 'C:\Program Files\Git\cmd\git.exe'
$Workspace = 'C:\cursor\workspace'
$CloneAttempts = 5
$RetryDelays = @(1, 2, 4, 8)

function Get-RequiredString {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Field
    )

    if ($Value -isnot [string] -or [String]::IsNullOrWhiteSpace([string]$Value)) {
        throw "$Field must be a non-empty string"
    }
    return [string]$Value
}

function Get-RepositoryUrl {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string]$Field
    )

    $url = Get-RequiredString -Value $Value -Field $Field
    $parsedUri = $null
    if (
        -not [Uri]::TryCreate($url, [UriKind]::Absolute, [ref]$parsedUri) -or
        $parsedUri.Scheme -cne 'https' -or
        [String]::IsNullOrWhiteSpace($parsedUri.Host) -or
        -not [String]::IsNullOrEmpty($parsedUri.UserInfo) -or
        -not [String]::IsNullOrEmpty($parsedUri.Query) -or
        -not [String]::IsNullOrEmpty($parsedUri.Fragment)
    ) {
        throw "$Field must be a credential-free HTTPS URL"
    }
    return $url
}

function Test-JsonProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )
    return $null -ne $Object.PSObject.Properties[$Name]
}

function Get-Repositories {
    param([Parameter(Mandatory = $true)][AllowNull()][object]$Payload)

    if ($Payload -isnot [PSCustomObject]) {
        throw 'payload must be a JSON object'
    }

    $repositories = @()
    if (Test-JsonProperty -Object $Payload -Name 'repos') {
        $rawRepositories = $Payload.repos
        if ($rawRepositories -isnot [System.Array]) {
            throw 'repos must be a JSON array'
        }
        for ($index = 0; $index -lt $rawRepositories.Count; $index++) {
            $rawRepository = $rawRepositories[$index]
            if ($rawRepository -isnot [PSCustomObject]) {
                throw "repos[$index] must be a JSON object"
            }
            $rawUrl = $null
            if (Test-JsonProperty -Object $rawRepository -Name 'repo_url') {
                $rawUrl = $rawRepository.repo_url
            }
            $url = Get-RepositoryUrl -Value $rawUrl -Field "repos[$index].repo_url"
            $ref = $null
            if (Test-JsonProperty -Object $rawRepository -Name 'ref') {
                if ($null -ne $rawRepository.ref) {
                    $ref = Get-RequiredString -Value $rawRepository.ref -Field "repos[$index].ref"
                }
            }
            $repositories += [PSCustomObject]@{ Url = $url; Ref = $ref }
        }
        return ,$repositories
    }

    if (-not (Test-JsonProperty -Object $Payload -Name 'repo_urls')) {
        return ,$repositories
    }
    $rawUrls = $Payload.repo_urls
    if ($rawUrls -isnot [System.Array]) {
        throw 'repo_urls must be a JSON array'
    }
    for ($index = 0; $index -lt $rawUrls.Count; $index++) {
        $url = Get-RepositoryUrl -Value $rawUrls[$index] -Field "repo_urls[$index]"
        $repositories += [PSCustomObject]@{ Url = $url; Ref = $null }
    }
    return ,$repositories
}

function Get-UrlDigest {
    param([Parameter(Mandatory = $true)][string]$Url)

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($Url))
        return -join @($hash | ForEach-Object { $_.ToString('x2') })
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-TargetName {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][System.Collections.Generic.HashSet[string]]$UsedNames
    )

    $path = $Url.Replace('\', '/').TrimEnd('/')
    $parsedUri = $null
    if ([Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$parsedUri)) {
        $path = $parsedUri.AbsolutePath
    }
    elseif ($path.Contains(':')) {
        $path = $path.Substring($path.LastIndexOf(':') + 1)
    }

    $basename = $path.Replace('\', '/').TrimEnd('/').Split('/')[-1]
    try {
        $basename = [Uri]::UnescapeDataString($basename)
    }
    catch {
        # A malformed escape is handled by the filename sanitizer below.
    }
    if ($basename.EndsWith('.git', [StringComparison]::OrdinalIgnoreCase)) {
        $basename = $basename.Substring(0, $basename.Length - 4)
    }
    $basename = [Regex]::Replace($basename, '[^A-Za-z0-9._-]+', '-')
    while ($basename.Contains('..')) {
        $basename = $basename.Replace('..', '.')
    }
    $basename = $basename.Trim([char[]]@('.', '_', '-'))
    if ([String]::IsNullOrWhiteSpace($basename) -or -not [char]::IsLetterOrDigit($basename[0])) {
        $basename = 'repo'
    }

    $digest = (Get-UrlDigest -Url $Url).Substring(0, 12)
    $stem = "$basename-$digest"
    $candidate = $stem
    $suffix = 2
    while (-not $UsedNames.Add($candidate)) {
        $candidate = "$stem-$suffix"
        $suffix++
    }
    return $candidate
}

function Remove-PartialClone {
    param([Parameter(Mandatory = $true)][string]$Destination)

    if (-not (Test-Path -LiteralPath $Destination)) {
        return
    }
    try {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    catch {
        throw "Could not remove partial repository clone at $Destination."
    }
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    if (-not (Test-Path -LiteralPath $GitExe -PathType Leaf)) {
        throw "Git executable is missing: $GitExe"
    }
    $output = @(& $GitExe @Arguments 2>&1 | ForEach-Object { $_.ToString() })
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
    return ,$output
}

function Clone-Repositories {
    param([Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Repositories)

    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
    $usedNames = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $namesByUrl = [System.Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)

    foreach ($repository in $Repositories) {
        $name = $null
        if (-not $namesByUrl.TryGetValue($repository.Url, [ref]$name)) {
            $name = Get-TargetName -Url $repository.Url -UsedNames $usedNames
            $namesByUrl.Add($repository.Url, $name)
        }
        $destination = Join-Path $Workspace $name
        $gitMetadata = Join-Path $destination '.git'

        if (-not (Test-Path -LiteralPath $gitMetadata)) {
            Remove-PartialClone -Destination $destination
            $cloned = $false
            for ($attempt = 0; $attempt -lt $CloneAttempts; $attempt++) {
                try {
                    Invoke-Git -Arguments @('clone', '--', $repository.Url, $destination) -Description 'git clone' | Out-Null
                    $cloned = $true
                    break
                }
                catch {
                    Remove-PartialClone -Destination $destination
                    if ($attempt -eq ($CloneAttempts - 1)) {
                        throw 'Repository clone failed after credential retries; verify that the minted GitHub credential can access every configured repository.'
                    }
                    Start-Sleep -Seconds $RetryDelays[$attempt]
                }
            }
            if (-not $cloned) {
                throw 'Repository clone did not create a checkout.'
            }
        }

        if ($null -ne $repository.Ref) {
            try {
                Invoke-Git -Arguments @('-C', $destination, 'checkout', '--detach', $repository.Ref) -Description 'git checkout' | Out-Null
            }
            catch {
                Remove-PartialClone -Destination $destination
                throw 'Repository checkout failed; verify that each configured ref exists and is accessible.'
            }
        }
    }
}

try {
    $inputJson = [Console]::In.ReadToEnd()
    if ([String]::IsNullOrWhiteSpace($inputJson)) {
        throw 'stdin must contain one valid Cursor sessionStart JSON payload'
    }
    try {
        $payload = ConvertFrom-Json -InputObject $inputJson
    }
    catch {
        throw 'stdin must contain one valid Cursor sessionStart JSON payload'
    }
    if (-not $inputJson.TrimStart().StartsWith('{')) {
        throw 'payload must be a JSON object'
    }

    $repositories = @(Get-Repositories -Payload $payload)
    Clone-Repositories -Repositories $repositories
    [Console]::Out.WriteLine('{"status":"ok"}')
    exit 0
}
catch {
    [Console]::Error.WriteLine("error: $($_.Exception.Message)")
    exit 1
}
