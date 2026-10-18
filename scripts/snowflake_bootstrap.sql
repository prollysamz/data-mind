-- DataMind Snowflake bootstrap (idempotent; safe to re-run)
--
-- Creates everything DataMind needs in a fresh Snowflake trial account:
--   * DATAMIND_XS warehouse (X-Small, auto-suspends after 60 s, starts suspended)
--   * DATAMIND_MONITOR resource monitor capping the warehouse at 5 credits per month
--   * DATAMIND database (PUBLIC schema)
--   * DATAMIND_LOADER role: creates and loads tables (used by load scripts)
--   * DATAMIND_READONLY role: SELECT only (used by the DataMind agent at question time)
--
-- How to run: open a Snowflake worksheet as ACCOUNTADMIN, set your login name on the
-- next line, and run the whole script. Then load data with either
--   scripts/setup_snowflake_demo.sql       (synthetic demo tables, run as DATAMIND_LOADER), or
--   python scripts/load_olist_snowflake.py (Olist CSVs from data/olist/).

SET datamind_user = 'YOUR_SNOWFLAKE_LOGIN_NAME';

USE ROLE ACCOUNTADMIN;

-- 1. Compute, with a hard credit cap
CREATE WAREHOUSE IF NOT EXISTS DATAMIND_XS
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'DataMind query warehouse';

CREATE RESOURCE MONITOR IF NOT EXISTS DATAMIND_MONITOR
  WITH CREDIT_QUOTA = 5
  FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 80 PERCENT DO NOTIFY
           ON 100 PERCENT DO SUSPEND;

ALTER WAREHOUSE DATAMIND_XS SET RESOURCE_MONITOR = DATAMIND_MONITOR;

-- 2. Storage
CREATE DATABASE IF NOT EXISTS DATAMIND COMMENT = 'DataMind demo and evaluation data';
CREATE SCHEMA IF NOT EXISTS DATAMIND.PUBLIC;

-- 3. Roles
CREATE ROLE IF NOT EXISTS DATAMIND_LOADER COMMENT = 'Creates and loads DataMind tables';
CREATE ROLE IF NOT EXISTS DATAMIND_READONLY COMMENT = 'Read-only access used by the DataMind agent';

-- Keep both roles under SYSADMIN in the role hierarchy
GRANT ROLE DATAMIND_LOADER TO ROLE SYSADMIN;
GRANT ROLE DATAMIND_READONLY TO ROLE SYSADMIN;

-- 4. Loader privileges
GRANT USAGE ON WAREHOUSE DATAMIND_XS TO ROLE DATAMIND_LOADER;
GRANT USAGE ON DATABASE DATAMIND TO ROLE DATAMIND_LOADER;
GRANT USAGE, CREATE TABLE, CREATE STAGE, CREATE FILE FORMAT ON SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_LOADER;

-- 5. Read-only privileges (current and future tables)
GRANT USAGE ON WAREHOUSE DATAMIND_XS TO ROLE DATAMIND_READONLY;
GRANT USAGE ON DATABASE DATAMIND TO ROLE DATAMIND_READONLY;
GRANT USAGE ON SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_READONLY;
GRANT SELECT ON ALL TABLES IN SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_READONLY;
GRANT SELECT ON FUTURE TABLES IN SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_READONLY;

-- 6. Give your user both roles; DataMind connects as DATAMIND_READONLY
GRANT ROLE DATAMIND_LOADER TO USER IDENTIFIER($datamind_user);
GRANT ROLE DATAMIND_READONLY TO USER IDENTIFIER($datamind_user);

-- 7. Check
SHOW GRANTS TO ROLE DATAMIND_READONLY;
