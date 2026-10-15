-- 商情罗盘 MarketCompass — SQLite 建表脚本
-- 口径：仅承载公开/授权数据的聚合分析结果，不含任何个人信息字段。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ========== 维度层 ==========
CREATE TABLE IF NOT EXISTS dim_platform (
    platform_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,          -- openapi / public_page / import
    compliance_note TEXT
);

CREATE TABLE IF NOT EXISTS dim_category (
    category_id TEXT PRIMARY KEY,
    parent_id   TEXT,
    name        TEXT NOT NULL,
    level       INTEGER NOT NULL DEFAULT 1,
    aliases_json TEXT
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_id   TEXT PRIMARY KEY,
    platform_id  TEXT NOT NULL,
    title        TEXT NOT NULL,
    brand        TEXT,
    category_id  TEXT NOT NULL,
    attrs_json   TEXT,
    url          TEXT,
    first_seen   TEXT,
    FOREIGN KEY (platform_id) REFERENCES dim_platform(platform_id),
    FOREIGN KEY (category_id) REFERENCES dim_category(category_id)
);

-- 跨平台同款簇
CREATE TABLE IF NOT EXISTS dim_product_cluster (
    cluster_id      TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    category_id     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_product_cluster_map (
    cluster_id   TEXT NOT NULL,
    product_id   TEXT NOT NULL,
    match_score  REAL NOT NULL,
    match_reason TEXT,
    PRIMARY KEY (cluster_id, product_id)
);

CREATE TABLE IF NOT EXISTS dim_keyword (
    keyword_id  TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    category_id TEXT,
    source      TEXT
);

-- ========== 事实层 ==========
-- 原始公开信号（日粒度）：累计已售件数、累计评价数、公开榜单排名
CREATE TABLE IF NOT EXISTS fact_signal_daily (
    product_id       TEXT NOT NULL,
    stat_date        TEXT NOT NULL,
    sold_cumulative  INTEGER,
    sales_semantics  TEXT,                  -- cumulative（可算增量）/ rolling_30d（滚动窗口销量）
    review_cumulative INTEGER,
    rank             INTEGER,
    list_size        INTEGER,
    price            REAL,
    promo_price      REAL,
    platform_id      TEXT,
    batch_id         TEXT,
    PRIMARY KEY (product_id, stat_date)
);

-- 指标层：销量代理指标（SPS）与置信区间
CREATE TABLE IF NOT EXISTS fact_metric_daily (
    product_id   TEXT NOT NULL,
    stat_date    TEXT NOT NULL,
    category_id  TEXT NOT NULL,
    sps_low      REAL NOT NULL,
    sps_mid      REAL NOT NULL,
    sps_high     REAL NOT NULL,
    gms_mid      REAL NOT NULL,
    confidence   REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (product_id, stat_date)
);

CREATE TABLE IF NOT EXISTS fact_review_agg (
    product_id        TEXT PRIMARY KEY,
    review_cnt        INTEGER,
    sentiment_pos     REAL,
    sentiment_neg     REAL,
    top_keywords_json TEXT
);

CREATE TABLE IF NOT EXISTS fact_search_heat (
    keyword_id TEXT NOT NULL,
    stat_date  TEXT NOT NULL,
    heat_index REAL NOT NULL,
    source     TEXT,
    PRIMARY KEY (keyword_id, stat_date)
);

-- ========== AI 交付层 ==========
CREATE TABLE IF NOT EXISTS ai_report (
    report_id  TEXT PRIMARY KEY,
    user_id    TEXT,
    topic      TEXT,
    params_json TEXT,
    content_md TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS ai_claim (
    claim_id   TEXT PRIMARY KEY,
    report_id  TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    metric     TEXT,
    value      REAL,
    period     TEXT,
    source_ref TEXT,
    confidence REAL,
    verified   INTEGER NOT NULL DEFAULT 0
);

-- ========== 合规审计 ==========
CREATE TABLE IF NOT EXISTS audit_collect_log (
    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,
    url            TEXT,
    fetched_at     TEXT NOT NULL,
    robots_allowed INTEGER NOT NULL,
    fields         TEXT,
    records        INTEGER,
    batch_id       TEXT
);

CREATE INDEX IF NOT EXISTS idx_metric_cat_date ON fact_metric_daily(category_id, stat_date);
CREATE INDEX IF NOT EXISTS idx_signal_product   ON fact_signal_daily(product_id, stat_date);
CREATE INDEX IF NOT EXISTS idx_product_cat      ON dim_product(category_id);
