-- 005：群风控规则表（敏感词 / 正则 → 撤回 / 警告 / 禁言 / 踢出）
--
-- 设计：
--   group_id = '' 表示全局规则；非空为某群专属；
--   风控为「全局 + 本群叠加生效」（与 chat_rules 的群级覆盖不同）；
--   kind: keyword | regex
--   action: warn（警告，累计到阈值自动禁言） | recall_only（仅撤回）
--           | mute（撤回+禁言） | kick（撤回+踢出）
--   recall 控制是否撤回命中消息（默认 1；命令里 -n 关闭）。

CREATE TABLE IF NOT EXISTS moderation_rules (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id     TEXT NOT NULL DEFAULT '',
  kind         TEXT NOT NULL DEFAULT 'keyword',
  pattern      TEXT NOT NULL,
  action       TEXT NOT NULL DEFAULT 'warn',
  recall       INTEGER NOT NULL DEFAULT 1,
  mute_seconds INTEGER NOT NULL DEFAULT 600,
  enabled      INTEGER NOT NULL DEFAULT 1,
  note         TEXT NOT NULL DEFAULT '',
  created_by   TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_moderation_rules_group
  ON moderation_rules(group_id, kind, enabled);
