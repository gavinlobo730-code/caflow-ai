-- Rollback for 453.
--
-- Restores migration 001's eight-value CHECK. It CANNOT be re-added while any
-- client is recorded as 'HUF', 'AOP' or 'BOI', and the VALIDATE below fails
-- loudly rather than silently re-typing them. Before running this, find them:
--   SELECT id, client_name, entity_type FROM public.clients
--    WHERE entity_type IN ('HUF', 'AOP', 'BOI');
-- and decide, per client, what they are to be recorded as. Recording a family
-- as an Individual hands it the s.87A rebate, the s.16(ia) standard deduction
-- and the senior-citizen slab, which it does not get -- so this is a decision
-- for a person, not a bulk UPDATE.

ALTER TABLE public.clients
    DROP CONSTRAINT IF EXISTS clients_entity_type_check;

ALTER TABLE public.clients
    ADD CONSTRAINT clients_entity_type_check
    CHECK (entity_type IN (
        'Proprietorship', 'Partnership', 'LLP', 'Private Limited',
        'Public Limited', 'Trust', 'Society', 'Individual'
    ))
    NOT VALID;

ALTER TABLE public.clients
    VALIDATE CONSTRAINT clients_entity_type_check;
