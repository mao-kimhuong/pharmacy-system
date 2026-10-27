#!/bin/bash
# Creates one database and one user per service. Runs only on the first start
# of an empty postgres volume. Each user owns only its own database.
#
# The password is passed as a psql variable and used as :'pw', so psql quotes
# it as a literal: quotes, $, spaces and any other character are safe.
set -euo pipefail

create_db() {
  local svc="$1" pw="$2"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v svc_user="${svc}_user" -v svc_db="pharmacy_${svc}" -v pw="$pw" <<-'SQL'
    CREATE USER :"svc_user" WITH PASSWORD :'pw';
    CREATE DATABASE :"svc_db" OWNER :"svc_user";
    REVOKE ALL ON DATABASE :"svc_db" FROM PUBLIC;
SQL
}

create_db auth "${AUTH_DB_PASSWORD}"
create_db branch "${BRANCH_DB_PASSWORD}"
create_db catalog "${CATALOG_DB_PASSWORD}"
create_db inventory "${INVENTORY_DB_PASSWORD}"
create_db stockcount "${STOCKCOUNT_DB_PASSWORD}"
create_db prescription "${PRESCRIPTION_DB_PASSWORD}"
create_db controlled "${CONTROLLED_DB_PASSWORD}"
create_db sales "${SALES_DB_PASSWORD}"
create_db customers "${CUSTOMERS_DB_PASSWORD}"
create_db purchasing "${PURCHASING_DB_PASSWORD}"
create_db reports "${REPORTS_DB_PASSWORD}"
create_db notification "${NOTIFICATION_DB_PASSWORD}"
create_db document "${DOCUMENT_DB_PASSWORD}"
create_db ai "${AI_DB_PASSWORD}"
