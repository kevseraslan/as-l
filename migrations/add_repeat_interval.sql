-- Migration: Add RepeatInterval column to UserSettings table
-- Date: 2026-05-20
-- Description: Kullanıcının tekrar sıklığı ayarını saklamak için UserSettings tablosuna RepeatInterval sütunu eklenir.

-- Check if column exists before adding (SQL Server syntax)
IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_NAME = 'UserSettings' AND COLUMN_NAME = 'RepeatInterval'
)
BEGIN
    ALTER TABLE UserSettings ADD RepeatInterval INT DEFAULT 1;
END

-- SQLite syntax (if using SQLite):
-- ALTER TABLE UserSettings ADD COLUMN RepeatInterval INTEGER DEFAULT 1;
