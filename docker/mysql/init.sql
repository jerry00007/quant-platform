-- QuantWeave 数据库初始化脚本（MySQL）
-- Docker Compose 生产模式自动执行

CREATE DATABASE IF NOT EXISTS quantweave CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE quantweave;

-- 授权
GRANT ALL PRIVILEGES ON quantweave.* TO 'quantweave'@'%';
FLUSH PRIVILEGES;
