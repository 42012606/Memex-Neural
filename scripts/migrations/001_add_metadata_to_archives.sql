-- Add meta_data column to archives if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'archives'
          AND column_name = 'meta_data'
    ) THEN
        ALTER TABLE archives
        ADD COLUMN meta_data JSONB NOT NULL DEFAULT '{}';
    END IF;
END$$;

