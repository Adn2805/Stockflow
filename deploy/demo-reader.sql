-- Run as the owner after migration and seeding, in a dedicated synthetic demo database.
-- psql prompts for the reader secret without putting it in source or shell history.
\set ON_ERROR_STOP on
BEGIN;
CREATE ROLE stockflow_demo_reader LOGIN NOINHERIT NOCREATEDB NOCREATEROLE;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()) \gexec
GRANT USAGE ON SCHEMA public TO stockflow_demo_reader;
GRANT SELECT ON products, warehouses, inventory, orders, order_items, stock_movements
    TO stockflow_demo_reader;
ALTER ROLE stockflow_demo_reader SET default_transaction_read_only = on;
COMMIT;
\password stockflow_demo_reader
