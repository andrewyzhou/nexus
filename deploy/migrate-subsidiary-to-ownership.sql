-- Rename existing 'subsidiary' edges to 'ownership' in the relationships
-- table. Run once on the EC2 box after deploying the rename/subsidiary-
-- to-ownership branch, or simply re-seed — ON CONFLICT DO NOTHING on the
-- new INSERTs already handles the common case.
--
-- Idempotent: re-running is safe.
--
-- Run:
--   sudo docker exec -i $(sudo docker ps -qf name=db) \
--       psql -U nexus -d corporate_data -f - < deploy/migrate-subsidiary-to-ownership.sql

BEGIN;

-- Count before
SELECT relationship_type, COUNT(*) AS before_count
FROM relationships
GROUP BY relationship_type
ORDER BY before_count DESC;

-- Rename. If an (source, target, 'ownership') row already exists for a
-- given (source, target, 'subsidiary'), keep the existing one and drop
-- the old subsidiary row (rare but possible if a previous seed ran both
-- the old and new code paths).
UPDATE relationships
   SET relationship_type = 'ownership'
 WHERE relationship_type = 'subsidiary'
   AND NOT EXISTS (
     SELECT 1 FROM relationships r2
      WHERE r2.source_ticker = relationships.source_ticker
        AND r2.target_ticker = relationships.target_ticker
        AND r2.relationship_type = 'ownership'
   );

DELETE FROM relationships WHERE relationship_type = 'subsidiary';

-- Count after
SELECT relationship_type, COUNT(*) AS after_count
FROM relationships
GROUP BY relationship_type
ORDER BY after_count DESC;

COMMIT;
