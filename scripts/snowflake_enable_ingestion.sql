-- Run once in Snowsight as an administrator. Replace this with the ingestion
-- login, which can be the existing login or a separate loader service account.
-- Never change DataMind's question-time role from DATAMIND_READONLY.
-- Run snowflake_bootstrap.sql first if the loader role does not exist yet.
SET ingestion_login = 'YOUR_INGESTION_LOGIN';
USE ROLE ACCOUNTADMIN;
GRANT ROLE DATAMIND_LOADER TO USER IDENTIFIER($ingestion_login);
GRANT USAGE ON WAREHOUSE DATAMIND_XS TO ROLE DATAMIND_LOADER;
GRANT USAGE ON DATABASE DATAMIND TO ROLE DATAMIND_LOADER;
GRANT CREATE SCHEMA ON DATABASE DATAMIND TO ROLE DATAMIND_LOADER;
GRANT USAGE ON SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_LOADER;
-- Needed only for the isolated-clone data-change demo.
GRANT SELECT ON TABLE DATAMIND.PUBLIC.SALES TO ROLE DATAMIND_LOADER;
SHOW GRANTS TO ROLE DATAMIND_LOADER;
-- Afterwards: python scripts/demo_data_change.py datamind_snowflake.yaml
-- For a separate login, set SNOWFLAKE_LOADER_USER and SNOWFLAKE_LOADER_PASSWORD.
