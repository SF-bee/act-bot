-- 007：群互动 · 签到（/签到、/签到榜）
--
-- 口径：一人一天一条；复合主键天然防重复签到（并发时靠主键冲突兜底）。
--   date 是**本地时区**的 YYYY-MM-DD（和 stats_daily 一致，便于按自然日回溯连续天数）；
--   display_name 是签到当时的群昵称快照，榜单直接用，不必逐个查协议端。
-- 隐私：只存昵称快照与日期，不存消息正文。

CREATE TABLE IF NOT EXISTS checkins (
  group_id     TEXT NOT NULL DEFAULT '',
  user_id      TEXT NOT NULL DEFAULT '',
  date         TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (group_id, user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_checkins_group_date ON checkins(group_id, date);
