-- 每个服务独立 schema（禁止跨库 join，见 docs/admin-phase1-plan.md §3.1）
CREATE DATABASE IF NOT EXISTS requirement_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS identity_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
