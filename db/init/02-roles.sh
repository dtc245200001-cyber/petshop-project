#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 \
     -v app_pw="$APP_DB_PASSWORD" \
     -v exp_pw="$EXPORTER_DB_PASSWORD" \
     -v dbname="$POSTGRES_DB" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'

-- Role cho ứng dụng: chỉ thao tác dữ liệu
CREATE ROLE petshop_app LOGIN PASSWORD :'app_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;

-- Role cho postgres-exporter: chỉ đọc metrics
CREATE ROLE exporter LOGIN PASSWORD :'exp_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT pg_monitor TO exporter;

-- Thu hồi quyền mặc định của PUBLIC
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Cấp quyền tối thiểu cho app
GRANT CONNECT ON DATABASE :"dbname" TO petshop_app, exporter;
GRANT USAGE ON SCHEMA public TO petshop_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO petshop_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO petshop_app;
EOSQL
