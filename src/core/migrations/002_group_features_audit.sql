-- 002：群功能开关统一进 groups.features(JSON)；audit_log 增加 group_id
--
-- 背景：001 里 groups 只有一个专用开关列 welcome_on；后续功能（聊天互动 / 防刷屏 /
-- 统计 …）都需要按群开关，故统一为 JSON：
--   groups.features = {"welcome": true, "chat": false, ...}
-- 做法：先把 welcome_on 的值搬进 JSON，再删掉专用列（SQLite >= 3.35 支持 DROP COLUMN）。

UPDATE groups
   SET features = json_set(
         COALESCE(NULLIF(features, ''), '{}'),
         '$.welcome',
         COALESCE(welcome_on, 1)
       );

ALTER TABLE groups DROP COLUMN welcome_on;

-- 审计：记录「哪个群」里发生的管理操作（不写 group_id 的记录视为全局操作）
ALTER TABLE audit_log ADD COLUMN group_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_audit_log_group ON audit_log(group_id, created_at);

