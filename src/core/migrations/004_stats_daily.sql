-- 004：统计表（内存累加 → 定时落库；单条消息不写库）
--
-- 口径：按 群 + 日期 + 指标 存一行；group_id = '' 表示全局指标
--   群级：messages / commands / auto_replies / joins / leaves / active_users(当日快照)
--   全局：online_seconds / errors
-- 注意：不存消息正文，也不落库「每人发了多少条」（只在内存保留当天 Top N）。

CREATE TABLE IF NOT EXISTS stats_daily (
  group_id TEXT NOT NULL DEFAULT '',
  date TEXT NOT NULL DEFAULT '',
  metric TEXT NOT NULL DEFAULT '',
  value INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (group_id, date, metric)
);

CREATE INDEX IF NOT EXISTS idx_stats_daily_date ON stats_daily(date, metric);

