"""Mini Windows GUI evaluation tasks for the Daytona computer-use guide."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Task:
    id: str
    instruction: str
    setup: list[str]
    verify: str
    oracle: list[str]
    timeout_s: int = 300


TASKS: list[Task] = [
    Task(
        id="notepad-write-save",
        instruction=(
            "Open Notepad. Type exactly this sentence, with no extra characters: "
            "Daytona Windows GUI evals can save exact text. "
            "Save the file exactly as C:\\evals\\report.txt."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals'
$null = New-Item -ItemType Directory -Path $root -Force
Remove-Item -LiteralPath (Join-Path $root 'report.txt') -Force -ErrorAction SilentlyContinue
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$path = 'C:\evals\report.txt'
$expected = 'Daytona Windows GUI evals can save exact text.'
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    Write-Output 'FAIL'
    Write-Output 'report.txt was not created'
    exit 0
}
$actual = [System.IO.File]::ReadAllText($path)
if ($actual -ceq $expected) {
    Write-Output 'PASS'
} else {
    Write-Output 'FAIL'
    Write-Output ('report.txt content mismatch; length=' + $actual.Length)
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals'
$path = Join-Path $root 'report.txt'
$null = New-Item -ItemType Directory -Path $root -Force
Set-Content -LiteralPath $path -Value 'Daytona Windows GUI evals can save exact text.' -NoNewline -Encoding UTF8
""".strip()
        ],
    ),
    Task(
        id="explorer-folder-tree",
        instruction=(
            "Use File Explorer to create this folder tree exactly: "
            "C:\\evals\\projects\\alpha\\docs and C:\\evals\\projects\\beta\\docs."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals'
$null = New-Item -ItemType Directory -Path $root -Force
Remove-Item -LiteralPath (Join-Path $root 'projects') -Recurse -Force -ErrorAction SilentlyContinue
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$required = @(
    'C:\evals\projects\alpha\docs',
    'C:\evals\projects\beta\docs'
)
$missing = @()
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        $missing += $path
    }
}
if ($missing.Count -eq 0) {
    Write-Output 'PASS'
} else {
    Write-Output 'FAIL'
    Write-Output ('missing directories: ' + ($missing -join ', '))
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
$null = New-Item -ItemType Directory -Path 'C:\evals\projects\alpha\docs' -Force
$null = New-Item -ItemType Directory -Path 'C:\evals\projects\beta\docs' -Force
""".strip()
        ],
    ),
    Task(
        id="env-var-gui",
        instruction=(
            "Use the Windows System Properties Environment Variables dialog to add a User variable. "
            "Set the variable name exactly to EVALS_PROBE and the value exactly to 42. "
            "Do not create a System variable."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$null = New-Item -ItemType Directory -Path 'C:\evals' -Force
[Environment]::SetEnvironmentVariable('EVALS_PROBE', $null, 'User')
try { [Environment]::SetEnvironmentVariable('EVALS_PROBE', $null, 'Machine') } catch { }
Remove-ItemProperty -Path 'HKCU:\Environment' -Name 'EVALS_PROBE' -ErrorAction SilentlyContinue
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$props = Get-ItemProperty -Path 'HKCU:\Environment' -Name 'EVALS_PROBE' -ErrorAction SilentlyContinue
if ($null -eq $props) {
    Write-Output 'FAIL'
    Write-Output 'EVALS_PROBE is missing from HKCU:\Environment'
    exit 0
}
$value = $props.EVALS_PROBE
$machineValue = [Environment]::GetEnvironmentVariable('EVALS_PROBE', 'Machine')
if ($machineValue -ceq '42') {
    Write-Output 'FAIL'
    Write-Output 'EVALS_PROBE was also created as a System variable with value 42'
} elseif ($value -ceq '42') {
    Write-Output 'PASS'
} else {
    Write-Output 'FAIL'
    Write-Output ('EVALS_PROBE value was ' + [string]$value)
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
[Environment]::SetEnvironmentVariable('EVALS_PROBE', '42', 'User')
Set-ItemProperty -Path 'HKCU:\Environment' -Name 'EVALS_PROBE' -Value '42'
""".strip()
        ],
    ),
    Task(
        id="zip-roundtrip",
        instruction=(
            "Use File Explorer's context menu to compress the folder C:\\evals\\to-archive "
            "into a zip file saved exactly as C:\\evals\\archive.zip."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals'
$source = Join-Path $root 'to-archive'
$null = New-Item -ItemType Directory -Path $root -Force
Remove-Item -LiteralPath (Join-Path $root 'archive.zip') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $source -Recurse -Force -ErrorAction SilentlyContinue
$null = New-Item -ItemType Directory -Path $source -Force
Set-Content -LiteralPath (Join-Path $source 'alpha.txt') -Value 'alpha file' -Encoding UTF8
Set-Content -LiteralPath (Join-Path $source 'beta.txt') -Value 'beta file' -Encoding UTF8
Set-Content -LiteralPath (Join-Path $source 'gamma.txt') -Value 'gamma file' -Encoding UTF8
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$ErrorActionPreference = 'Stop'
$zip = 'C:\evals\archive.zip'
if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) {
    Write-Output 'FAIL'
    Write-Output 'archive.zip was not created'
    exit 0
}
$temp = Join-Path $env:TEMP ('daytona-zip-check-' + [guid]::NewGuid().ToString('N'))
try {
    $null = New-Item -ItemType Directory -Path $temp -Force
    Expand-Archive -LiteralPath $zip -DestinationPath $temp -Force
    $expected = @{
        'alpha.txt' = 'alpha file'
        'beta.txt' = 'beta file'
        'gamma.txt' = 'gamma file'
    }
    $files = @(Get-ChildItem -LiteralPath $temp -Recurse -File)
    $actualNames = @($files | Select-Object -ExpandProperty Name | Sort-Object)
    $expectedNames = @($expected.Keys | Sort-Object)
    $nameDiff = @(Compare-Object -ReferenceObject $expectedNames -DifferenceObject $actualNames)
    $badContent = @()
    foreach ($file in $files) {
        if ($expected.ContainsKey($file.Name)) {
            $content = [System.IO.File]::ReadAllText($file.FullName).Trim()
            if ($content -cne $expected[$file.Name]) {
                $badContent += $file.Name
            }
        }
    }
    if ($actualNames.Count -eq 3 -and $nameDiff.Count -eq 0 -and $badContent.Count -eq 0) {
        Write-Output 'PASS'
    } else {
        Write-Output 'FAIL'
        Write-Output ('zip filenames were: ' + ($actualNames -join ', '))
        if ($badContent.Count -gt 0) {
            Write-Output ('files with wrong content: ' + ($badContent -join ', '))
        }
    }
} catch {
    Write-Output 'FAIL'
    Write-Output ('zip could not be expanded: ' + $_.Exception.Message)
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
$zip = 'C:\evals\archive.zip'
Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -LiteralPath 'C:\evals\to-archive' -DestinationPath $zip -Force
""".strip()
        ],
    ),
    Task(
        id="calc-to-notepad",
        instruction=(
            "Use Calculator to compute 847 * 63. Then open Notepad, type only the result, "
            "and save the file exactly as C:\\evals\\result.txt."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals'
$null = New-Item -ItemType Directory -Path $root -Force
Remove-Item -LiteralPath (Join-Path $root 'result.txt') -Force -ErrorAction SilentlyContinue
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$path = 'C:\evals\result.txt'
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    Write-Output 'FAIL'
    Write-Output 'result.txt was not created'
    exit 0
}
$actual = [System.IO.File]::ReadAllText($path).Trim()
if ($actual -ceq '53361') {
    Write-Output 'PASS'
} else {
    Write-Output 'FAIL'
    Write-Output ('result.txt contained: ' + $actual)
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
$path = 'C:\evals\result.txt'
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force
Set-Content -LiteralPath $path -Value '53361' -NoNewline -Encoding UTF8
""".strip()
        ],
    ),
    Task(
        id="mspaint-save",
        instruction=(
            "Open Paint, draw anything visible on the canvas, and save it as a PNG file "
            "exactly at C:\\evals\\drawing.png."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals'
$null = New-Item -ItemType Directory -Path $root -Force
Remove-Item -LiteralPath (Join-Path $root 'drawing.png') -Force -ErrorAction SilentlyContinue
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$path = 'C:\evals\drawing.png'
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    Write-Output 'FAIL'
    Write-Output 'drawing.png was not created'
    exit 0
}
$file = Get-Item -LiteralPath $path
if ($file.Length -le 1024) {
    Write-Output 'FAIL'
    Write-Output ('drawing.png was too small: ' + $file.Length + ' bytes')
    exit 0
}
$stream = [System.IO.File]::OpenRead($path)
try {
    $header = New-Object byte[] 8
    $read = $stream.Read($header, 0, 8)
} finally {
    $stream.Dispose()
}
$expected = [byte[]](137, 80, 78, 71, 13, 10, 26, 10)
$matches = ($read -eq 8)
for ($i = 0; $i -lt 8; $i++) {
    if ($header[$i] -ne $expected[$i]) { $matches = $false }
}
if (-not $matches) {
    Write-Output 'FAIL'
    Write-Output 'drawing.png did not have PNG magic bytes'
    exit 0
}
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap -ArgumentList $path
try {
    $colors = New-Object 'System.Collections.Generic.HashSet[int]'
    $hasNonWhitePixel = $false
    for ($x = 0; $x -lt $bitmap.Width; $x++) {
        for ($y = 0; $y -lt $bitmap.Height; $y++) {
            $color = $bitmap.GetPixel($x, $y)
            $null = $colors.Add($color.ToArgb())
            if (-not ($color.R -gt 245 -and $color.G -gt 245 -and $color.B -gt 245)) {
                $hasNonWhitePixel = $true
            }
        }
    }
    if ($colors.Count -ge 2 -and $hasNonWhitePixel) {
        Write-Output 'PASS'
    } else {
        Write-Output 'FAIL'
        Write-Output 'drawing.png appears blank'
    }
} finally {
    $bitmap.Dispose()
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
$path = 'C:\evals\drawing.png'
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap -ArgumentList 256, 256
try {
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $colors = @('#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f')
        for ($i = 0; $i -lt $colors.Count; $i++) {
            $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($colors[$i]))
            try {
                $graphics.FillRectangle($brush, 0, $i * 32, 256, 32)
            } finally {
                $brush.Dispose()
            }
        }
    } finally {
        $graphics.Dispose()
    }
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $pen = New-Object System.Drawing.Pen -ArgumentList ([System.Drawing.Color]::Black), 4
        $graphics.DrawEllipse($pen, 32, 32, 192, 192)
        $graphics.DrawLine($pen, 0, 255, 255, 0)
    } finally {
        if ($pen) { $pen.Dispose() }
        $graphics.Dispose()
    }
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    $bitmap.Dispose()
}
""".strip()
        ],
    ),
    Task(
        id="powershell-interactive",
        instruction=(
            "Open a visible Windows PowerShell window using the Windows GUI. In that window, "
            "type a command that writes Get-Date output to C:\\evals\\when.txt, then press Enter."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals'
$null = New-Item -ItemType Directory -Path $root -Force
Remove-Item -LiteralPath (Join-Path $root 'when.txt') -Force -ErrorAction SilentlyContinue
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$path = 'C:\evals\when.txt'
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    Write-Output 'FAIL'
    Write-Output 'when.txt was not created'
    exit 0
}
$content = [System.IO.File]::ReadAllText($path).Trim()
$parsed = [datetime]::MinValue
if ([datetime]::TryParse($content, [Globalization.CultureInfo]::CurrentCulture, [Globalization.DateTimeStyles]::AllowWhiteSpaces, [ref]$parsed)) {
    Write-Output 'PASS'
} else {
    Write-Output 'FAIL'
    Write-Output 'when.txt did not contain parseable Get-Date output'
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
$path = 'C:\evals\when.txt'
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force
Get-Date | Out-File -LiteralPath $path -Encoding UTF8
""".strip()
        ],
    ),
    Task(
        id="find-and-fix",
        instruction=(
            "Use File Explorer search under C:\\evals\\cfg to find the nested settings.ini "
            "file containing the exact line colour=blu. Open that file in Notepad, change only "
            "that line to colour=blue, and save it. There are decoy files; leave them unchanged."
        ),
        setup=[
            r"""
$ErrorActionPreference = 'Stop'
$root = 'C:\evals\cfg'
Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
$targetDir = 'C:\evals\cfg\prod\desktop\primary'
$decoyDirA = 'C:\evals\cfg\prod\desktop\backup'
$decoyDirB = 'C:\evals\cfg\archive\mobile\legacy'
$null = New-Item -ItemType Directory -Path $targetDir -Force
$null = New-Item -ItemType Directory -Path $decoyDirA -Force
$null = New-Item -ItemType Directory -Path $decoyDirB -Force
Set-Content -LiteralPath (Join-Path $targetDir 'settings.ini') -Value @('[display]', 'profile=primary', 'colour=blu', 'scale=100') -Encoding UTF8
Set-Content -LiteralPath (Join-Path $decoyDirA 'settings.ini') -Value @('[display]', 'profile=backup', 'colour=green', 'scale=100') -Encoding UTF8
Set-Content -LiteralPath (Join-Path $decoyDirB 'settings.ini') -Value @('[display]', 'profile=legacy', 'color=blu', 'scale=125') -Encoding UTF8
Set-Content -LiteralPath (Join-Path $root 'readme.txt') -Value 'Search the settings files. Only one has the exact colour typo.' -Encoding UTF8
Write-Output 'setup-ok'
""".strip()
        ],
        verify=r"""
$target = 'C:\evals\cfg\prod\desktop\primary\settings.ini'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
    Write-Output 'FAIL'
    Write-Output 'target settings.ini was missing'
    exit 0
}
$targetLines = @(Get-Content -LiteralPath $target)
$expectedTarget = @('[display]', 'profile=primary', 'colour=blue', 'scale=100')
$expectedBackup = @('[display]', 'profile=backup', 'colour=green', 'scale=100')
$expectedLegacy = @('[display]', 'profile=legacy', 'color=blu', 'scale=125')
$backup = 'C:\evals\cfg\prod\desktop\backup\settings.ini'
$legacy = 'C:\evals\cfg\archive\mobile\legacy\settings.ini'
$problems = @()
if (($targetLines -join "`n") -cne ($expectedTarget -join "`n")) {
    $problems += 'target settings.ini was not changed exactly as expected'
}
if (-not (Test-Path -LiteralPath $backup -PathType Leaf) -or ((@(Get-Content -LiteralPath $backup) -join "`n") -cne ($expectedBackup -join "`n"))) {
    $problems += 'backup decoy changed'
}
if (-not (Test-Path -LiteralPath $legacy -PathType Leaf) -or ((@(Get-Content -LiteralPath $legacy) -join "`n") -cne ($expectedLegacy -join "`n"))) {
    $problems += 'legacy decoy changed'
}
if ($problems.Count -eq 0) {
    Write-Output 'PASS'
} else {
    Write-Output 'FAIL'
    $problems | ForEach-Object { Write-Output $_ }
}
""".strip(),
        oracle=[
            r"""
$ErrorActionPreference = 'Stop'
$target = 'C:\evals\cfg\prod\desktop\primary\settings.ini'
$updated = @(Get-Content -LiteralPath $target | ForEach-Object {
    if ($_ -ceq 'colour=blu') { 'colour=blue' } else { $_ }
})
Set-Content -LiteralPath $target -Value $updated -Encoding UTF8
""".strip()
        ],
    ),
]
