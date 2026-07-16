param(
    [string]$SourceEnv = "",
    [string]$TargetEnv = "",
    [string]$Database = "NASSubtitleStudio"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $projectRoot

if ([string]::IsNullOrWhiteSpace($SourceEnv)) {
    $SourceEnv = Join-Path $workspaceRoot "V12-0714-GIT.nas\backend\.env"
}

if ([string]::IsNullOrWhiteSpace($TargetEnv)) {
    $TargetEnv = Join-Path $projectRoot ".env"
}

if (-not (Test-Path -LiteralPath $SourceEnv)) {
    throw "Source env not found: $SourceEnv"
}

$source = Get-Content -LiteralPath $SourceEnv
$map = @{}
foreach ($line in $source) {
    if ($line.Trim().StartsWith("#") -or -not $line.Contains("=")) { continue }
    $key, $value = $line.Split("=", 2)
    $map[$key.Trim()] = $value.Trim()
}

foreach ($required in @("MSSQL_HOST", "MSSQL_PORT", "MSSQL_USER", "MSSQL_PASSWORD")) {
    if (-not $map.ContainsKey($required) -or [string]::IsNullOrWhiteSpace($map[$required])) {
        throw "Missing $required in $SourceEnv"
    }
}

$content = @(
    "GEMINI_API_KEY=",
    "APP_DATA_DIR=/data",
    "PUBLIC_BASE_URL=http://localhost:54320",
    "MAX_UPLOAD_MB=4096",
    "DB_BACKEND=mssql",
    "DB_AUTO_CREATE=true",
    "MSSQL_HOST=$($map['MSSQL_HOST'])",
    "MSSQL_PORT=$($map['MSSQL_PORT'])",
    "MSSQL_DATABASE=$Database",
    "MSSQL_USER=$($map['MSSQL_USER'])",
    "MSSQL_PASSWORD=$($map['MSSQL_PASSWORD'])"
)

Set-Content -LiteralPath $TargetEnv -Value $content -Encoding UTF8
Write-Host "Created $TargetEnv"
