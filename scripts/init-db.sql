-- PostgreSQL initialization script
-- This script runs automatically when the database container starts

-- Create the main database if it doesn't exist
-- (This is handled by POSTGRES_DB environment variable, but keeping for reference)

-- Create extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Set timezone
SET timezone = 'UTC';

-- Log initialization
DO $$
BEGIN
    RAISE NOTICE '✅ Database initialized successfully for Trazo development environment';
END
$$; 