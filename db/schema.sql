-- ============================================================
-- 智能化数据分析工作台 · 数据源管理中心 建表脚本
-- 数据库：excel_workbench_test（生产可改为 excel_workbench）
-- 字符集：utf8mb4
-- ============================================================

-- 分类表：数据源的自定义分类（映射表/订单表/会员信息表等）
CREATE TABLE IF NOT EXISTS categories (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(64)  NOT NULL UNIQUE COMMENT '分类名称',
    sort        INT          NOT NULL DEFAULT 0 COMMENT '排序权重',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sort (sort)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据源分类';

-- 数据源表：登记所有接入的数据源
CREATE TABLE IF NOT EXISTS data_sources (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    name              VARCHAR(255)  NOT NULL COMMENT '数据源名称',
    channel           VARCHAR(32)   NOT NULL COMMENT '采集通道：excel/folder/database/crawler',
    category_id       INT           NULL COMMENT '所属分类ID',
    file_path         VARCHAR(1024) NULL COMMENT '本地文件路径（excel/folder）',
    config            JSON          NULL COMMENT '通道配置（database/crawler 用）',
    row_count         INT           NOT NULL DEFAULT 0 COMMENT '总行数',
    col_count         INT           NOT NULL DEFAULT 0 COMMENT '总列数',
    sheet_names       JSON          NULL COMMENT '子表名称列表',
    status            VARCHAR(16)   NOT NULL DEFAULT 'pending' COMMENT '状态：ready/pending/error',
    last_collected_at DATETIME      NULL COMMENT '最后采集时间',
    created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_channel (channel),
    INDEX idx_category (category_id),
    INDEX idx_status (status),
    CONSTRAINT fk_ds_category FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据源登记';

-- 采集日志表：每次采集/重新采集的记录
CREATE TABLE IF NOT EXISTS collection_logs (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    source_id     INT          NOT NULL COMMENT '数据源ID',
    status        VARCHAR(16)  NOT NULL COMMENT '结果：success/failed',
    row_count     INT          NOT NULL DEFAULT 0 COMMENT '采集到的行数',
    error_msg     TEXT         NULL COMMENT '失败原因',
    duration_ms   INT          NOT NULL DEFAULT 0 COMMENT '耗时（毫秒）',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_source (source_id),
    INDEX idx_created (created_at),
    CONSTRAINT fk_log_source FOREIGN KEY (source_id) REFERENCES data_sources(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='采集日志';
