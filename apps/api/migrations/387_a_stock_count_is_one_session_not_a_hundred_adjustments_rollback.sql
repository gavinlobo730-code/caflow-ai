-- Rollback for 387. The lines go with the session (ON DELETE CASCADE), and
-- neither table has ever posted anything: the adjustments a session made are
-- ordinary journals through apply_stock_adjustment and are NOT touched here.
-- Dropping the worksheet loses the record of which count they belonged to,
-- which is why the reference_no is stamped on each journal rather than only
-- held here.
DROP TABLE IF EXISTS public.stock_count_lines;
DROP TABLE IF EXISTS public.stock_count_sessions;
