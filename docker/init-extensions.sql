-- Enable pgvector for semantic retrieval
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable Apache AGE for graph storage (used in Phase 2+)
-- Note: AGE requires installation in the Postgres image.
-- If AGE is not available, this will fail gracefully and graph
-- features will be deferred until a compatible image is used.
-- CREATE EXTENSION IF NOT EXISTS age;
-- SET search_path = ag_catalog, "$user", public;
