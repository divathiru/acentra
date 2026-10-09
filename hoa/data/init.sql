-- HOA init: create audit_writer role and pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Insert-only role for audit_log (no UPDATE/DELETE)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_writer') THEN
    CREATE ROLE audit_writer NOLOGIN;
  END IF;
END
$$;
