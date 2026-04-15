-- Enable pgvector for semantic retrieval
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable Apache AGE for graph storage (optional, used in Phase 2+).
-- If AGE is not installed in this Postgres image, the DO block catches
-- the error and graph features fall back to relational tables.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS age;
    SET search_path = ag_catalog, "$user", public;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Apache AGE extension not available: %. Graph features will use relational fallback.', SQLERRM;
END
$$;
