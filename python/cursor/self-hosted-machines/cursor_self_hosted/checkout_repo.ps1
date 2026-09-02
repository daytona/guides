# Cursor sessionStart hook: check out the claimed repository into the workspace.
#
# The spawn command already configured `origin` in the workspace, which is what
# makes Cursor route the request to this worker. Cursor runs this hook after the
# claim with the sessionStart payload on stdin and CURSOR_WORKER_WORKSPACE_DIR
# set. The fetch authenticates with the short-lived GitHub token that Cursor
# writes to the worker's git configuration (--mint-github-token).
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$GitExe = 'C:\Program Files\Git\cmd\git.exe'
$script:LastGitOutput = ''

# The hook has no terminal; a missing token must fail fast instead of prompting.
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'Never'

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    # Windows PowerShell turns redirected native stderr into a terminating error
    # under $ErrorActionPreference = 'Stop', and git reports progress on stderr.
    $ErrorActionPreference = 'Continue'
    $output = @(& $GitExe @Arguments 2>&1 | ForEach-Object { [string]$_ })
    $script:LastGitOutput = $output -join [Environment]::NewLine
    return $LASTEXITCODE -eq 0
}

try {
    $workspace = $env:CURSOR_WORKER_WORKSPACE_DIR
    if ([String]::IsNullOrWhiteSpace($workspace)) {
        throw 'CURSOR_WORKER_WORKSPACE_DIR is required'
    }

    # [Console]::In decodes stdin with the OEM code page and corrupted the
    # leading bytes of the payload; Cursor writes it as UTF-8.
    $reader = New-Object IO.StreamReader(
        [Console]::OpenStandardInput(),
        (New-Object Text.UTF8Encoding $false)
    )
    $payload = ConvertFrom-Json -InputObject $reader.ReadToEnd()
    $repos = @($payload.repos)
    $primary = @($repos | Where-Object { $_.PSObject.Properties['primary'] -and $_.primary })
    if ($primary.Count -eq 0) { $primary = $repos }
    $ref = ''
    if ($primary.Count -gt 0 -and $primary[0].PSObject.Properties['ref']) {
        $ref = [string]$primary[0].ref
    }
    if ([String]::IsNullOrWhiteSpace($ref)) {
        throw 'sessionStart payload has no repository ref'
    }

    # A follow-up session on the same worker already has the checkout.
    if (Invoke-Git -Arguments @('-C', $workspace, 'rev-parse', '--verify', '--quiet', 'HEAD')) {
        [Console]::Out.WriteLine('{"status":"ok"}')
        exit 0
    }

    # Cursor writes the minted token to git config in parallel with this hook
    # and kills the hook after 60 seconds, so keep trying for most of that window.
    for ($attempt = 1; $attempt -le 25; $attempt++) {
        if ((Invoke-Git -Arguments @('-C', $workspace, 'fetch', '--quiet', 'origin', $ref)) -and
            (Invoke-Git -Arguments @('-C', $workspace, 'checkout', '--quiet', '-B', $ref, 'FETCH_HEAD'))) {
            [Console]::Out.WriteLine('{"status":"ok"}')
            exit 0
        }
        Start-Sleep -Seconds 2
    }
    throw "could not fetch '$ref' from origin; confirm GitHub token minting and repository access: $script:LastGitOutput"
}
catch {
    # Cursor discards the stderr of a failed hook, so keep it next to the worker logs.
    Add-Content -LiteralPath (Join-Path $PSScriptRoot 'checkout.log') -Value "error: $($_.Exception.Message)"
    exit 1
}
