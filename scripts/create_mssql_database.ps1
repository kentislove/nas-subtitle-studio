param(
    [string]$EnvPath = "",
    [string]$Database = "NASSubtitleStudio"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($EnvPath)) {
    $EnvPath = Join-Path $projectRoot ".env"
}

if (-not (Test-Path -LiteralPath $EnvPath)) {
    throw "Env file not found: $EnvPath"
}

if ($Database -notmatch "^[A-Za-z0-9_]+$") {
    throw "Database name only supports letters, numbers, and underscore."
}

$map = @{}
foreach ($line in Get-Content -LiteralPath $EnvPath) {
    $trimmed = $line.Trim()
    if ($trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
    $key, $value = $trimmed.Split("=", 2)
    $map[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
}

$server = $map["MSSQL_HOST"]
$port = $map["MSSQL_PORT"]
$user = $map["MSSQL_USER"]
$password = $map["MSSQL_PASSWORD"]

if ([string]::IsNullOrWhiteSpace($server)) { throw "MSSQL_HOST is missing." }
if ([string]::IsNullOrWhiteSpace($port)) { $port = "1433" }
if ([string]::IsNullOrWhiteSpace($user)) { throw "MSSQL_USER is missing." }
if ([string]::IsNullOrWhiteSpace($password)) { throw "MSSQL_PASSWORD is missing." }

function Invoke-SqlBatch {
    param(
        [string]$DbName,
        [string]$Sql
    )

    $connectionString = "Server=$server,$port;Database=$DbName;User ID=$user;Password=$password;Encrypt=False;TrustServerCertificate=True;Connection Timeout=15;"
    $connection = New-Object System.Data.SqlClient.SqlConnection $connectionString
    $command = $connection.CreateCommand()
    $command.CommandTimeout = 120
    $command.CommandText = $Sql
    try {
        $connection.Open()
        [void]$command.ExecuteNonQuery()
    }
    finally {
        $connection.Close()
    }
}

$createDatabaseSql = @"
IF DB_ID(N'$Database') IS NULL
BEGIN
    CREATE DATABASE [$Database];
END
"@

Invoke-SqlBatch -DbName "master" -Sql $createDatabaseSql

$schemaSql = @"
IF OBJECT_ID(N'dbo.nas_subtitle_videos', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.nas_subtitle_videos (
        id NVARCHAR(36) NOT NULL,
        title NVARCHAR(255) NOT NULL,
        filename NVARCHAR(500) NOT NULL,
        stored_filename NVARCHAR(500) NOT NULL,
        status NVARCHAR(40) NOT NULL,
        created_at DATETIMEOFFSET(0) NOT NULL,
        updated_at DATETIMEOFFSET(0) NOT NULL,
        duration_seconds DECIMAL(18, 3) NULL,
        transcript NVARCHAR(MAX) NOT NULL CONSTRAINT DF_nas_subtitle_videos_transcript DEFAULT N'',
        error NVARCHAR(MAX) NULL,
        CONSTRAINT PK_nas_subtitle_videos PRIMARY KEY CLUSTERED (id)
    );
END;

IF OBJECT_ID(N'dbo.nas_subtitle_segments', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.nas_subtitle_segments (
        video_id NVARCHAR(36) NOT NULL,
        segment_id NVARCHAR(64) NOT NULL,
        sort_order INT NOT NULL,
        start_seconds DECIMAL(18, 3) NOT NULL,
        end_seconds DECIMAL(18, 3) NOT NULL,
        text NVARCHAR(MAX) NOT NULL,
        CONSTRAINT PK_nas_subtitle_segments PRIMARY KEY CLUSTERED (video_id, segment_id),
        CONSTRAINT FK_nas_subtitle_segments_video FOREIGN KEY (video_id)
            REFERENCES dbo.nas_subtitle_videos(id) ON DELETE CASCADE
    );
END;

IF OBJECT_ID(N'dbo.nas_subtitle_chapters', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.nas_subtitle_chapters (
        video_id NVARCHAR(36) NOT NULL,
        chapter_index INT NOT NULL,
        start_seconds DECIMAL(18, 3) NOT NULL,
        title NVARCHAR(255) NOT NULL,
        CONSTRAINT PK_nas_subtitle_chapters PRIMARY KEY CLUSTERED (video_id, chapter_index),
        CONSTRAINT FK_nas_subtitle_chapters_video FOREIGN KEY (video_id)
            REFERENCES dbo.nas_subtitle_videos(id) ON DELETE CASCADE
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_nas_subtitle_videos_created_at'
      AND object_id = OBJECT_ID(N'dbo.nas_subtitle_videos')
)
BEGIN
    CREATE INDEX IX_nas_subtitle_videos_created_at
    ON dbo.nas_subtitle_videos(created_at DESC);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_nas_subtitle_segments_video_sort'
      AND object_id = OBJECT_ID(N'dbo.nas_subtitle_segments')
)
BEGIN
    CREATE INDEX IX_nas_subtitle_segments_video_sort
    ON dbo.nas_subtitle_segments(video_id, sort_order);
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_nas_subtitle_chapters_video_sort'
      AND object_id = OBJECT_ID(N'dbo.nas_subtitle_chapters')
)
BEGIN
    CREATE INDEX IX_nas_subtitle_chapters_video_sort
    ON dbo.nas_subtitle_chapters(video_id, chapter_index);
END;
"@

Invoke-SqlBatch -DbName $Database -Sql $schemaSql

$verifySql = @"
SELECT COUNT(*)
FROM sys.tables
WHERE name IN (N'nas_subtitle_videos', N'nas_subtitle_segments', N'nas_subtitle_chapters');
"@

$connectionString = "Server=$server,$port;Database=$Database;User ID=$user;Password=$password;Encrypt=False;TrustServerCertificate=True;Connection Timeout=15;"
$connection = New-Object System.Data.SqlClient.SqlConnection $connectionString
$command = $connection.CreateCommand()
$command.CommandText = $verifySql
try {
    $connection.Open()
    $count = $command.ExecuteScalar()
}
finally {
    $connection.Close()
}

if ([int]$count -ne 3) {
    throw "Schema verification failed. Expected 3 tables, got $count."
}

Write-Host "MSSQL database ready: $Database"
