USE NASSubtitleStudio;
GO

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
END
GO

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
END
GO

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
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'IX_nas_subtitle_videos_created_at'
      AND object_id = OBJECT_ID(N'dbo.nas_subtitle_videos')
)
BEGIN
    CREATE INDEX IX_nas_subtitle_videos_created_at
    ON dbo.nas_subtitle_videos(created_at DESC);
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'IX_nas_subtitle_segments_video_sort'
      AND object_id = OBJECT_ID(N'dbo.nas_subtitle_segments')
)
BEGIN
    CREATE INDEX IX_nas_subtitle_segments_video_sort
    ON dbo.nas_subtitle_segments(video_id, sort_order);
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = N'IX_nas_subtitle_chapters_video_sort'
      AND object_id = OBJECT_ID(N'dbo.nas_subtitle_chapters')
)
BEGIN
    CREATE INDEX IX_nas_subtitle_chapters_video_sort
    ON dbo.nas_subtitle_chapters(video_id, chapter_index);
END
GO
