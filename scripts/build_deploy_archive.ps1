param(
    [string]$OutputPath = (Join-Path (Get-Location) 'clinic_schedule_deploy.zip')
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$staging = Join-Path $temporaryRoot ('clinic_schedule_deploy_' + [guid]::NewGuid().ToString('N'))
$resolvedOutput = [IO.Path]::GetFullPath($OutputPath)

if (-not ([IO.Path]::GetFullPath($staging).StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase))) {
    throw 'The staging directory is outside the system temporary directory.'
}

try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    $excludedDirectories = @(
        'venv', '.venv', '.testdeps', '.tools', 'node_modules', '.git', '.pytest_cache', '__pycache__',
        'static_root', 'logs', 'dist', 'android'
    )
    # ВАЖНО: db.sqlite3 и .env на сервер НЕ едут — там свои (SQLite-файл
    # расписания живёт только на VPS, секрет — только в серверном .env).
    # Сюда же: ключи Firebase и Android-сборка на сервер не едут.
    $excludedFiles = @('.env', '*.pyc', '*.log', 'db.sqlite3', 'clinic_schedule_deploy.zip', '.firebase-service.json', 'google-services.json')
    & robocopy $projectRoot $staging /E /XD $excludedDirectories /XF $excludedFiles /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) {
        throw "Robocopy failed with exit code $LASTEXITCODE."
    }
    if (Test-Path -LiteralPath $resolvedOutput) {
        Remove-Item -LiteralPath $resolvedOutput -Force
    }
    # ВАЖНО: Compress-Archive на Windows пишет пути с обратными слешами —
    # Linux-unzip их не понимает. Пакуем через .NET с прямыми слешами.
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zipHandle = [IO.Compression.ZipFile]::Open(
        $resolvedOutput, [IO.Compression.ZipArchiveMode]::Create)
    try {
        Get-ChildItem -LiteralPath $staging -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($staging.Length + 1) -replace '\\', '/'
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zipHandle, $_.FullName, $relative,
                [IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
    } finally {
        $zipHandle.Dispose()
    }
    Write-Output "Deployment archive created: $resolvedOutput"
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
