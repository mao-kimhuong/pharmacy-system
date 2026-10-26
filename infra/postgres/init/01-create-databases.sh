#!/bin/bash
# Creates one database and one user per service. Runs only on the first start
# of an empty postgres volume. Each user owns only its own database.
set -euo pipefail

create_db() {
  local svc="$1" pw="$2"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-SQL
    CREATE USER ${svc}_user WITH PASSWORD '${pw}';
    CREATE DATABASE pharmacy_${svc} OWNER ${svc}_user;
    REVOKE ALL ON DATABASE pharmacy_${svc} FROM PUBLIC;
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
