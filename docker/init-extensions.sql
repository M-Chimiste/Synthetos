CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS age;
EXCEPTION
    WHEN undefined_file THEN
        RAISE NOTICE 'Apache AGE extension is not available; relational graph fallback will be used.';
END
$$;
