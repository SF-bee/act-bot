-- 003：聊天引擎规则表（确定性机制：关键词 / 正则 / @ 回复池）
--
-- 设计：
--   group_id = '' 表示全局默认规则（任何群都可用），非空为某群专属；
--   同一 kind 下，群级规则存在时**覆盖**全局规则（群自定义梗优先）；
--   kind: keyword | regex | mention | mention_more | mention_tired
--     mention        被 @ / 被叫到时的常规回复池
--     mention_more   短时间连续被叫（第 2 档）
--     mention_tired  连续被叫到第 3 档及以后
--   回复内容支持占位符 {bot_name} / {bot_title} / {nickname} / {user_id} / {group_name}

CREATE TABLE IF NOT EXISTS chat_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'keyword',
  pattern TEXT NOT NULL DEFAULT '',
  reply TEXT NOT NULL,
  weight INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_chat_rules_group ON chat_rules(group_id, kind, enabled);

-- 全局默认池：任何群只要 /config chat on 就有效果（不需要先配规则）
INSERT INTO chat_rules (group_id, kind, pattern, reply, weight, enabled, created_by, created_at) VALUES
  ('', 'mention', '', '在的喵～', 3, 1, 'migration-003', ''),
  ('', 'mention', '', '嗯？叫我吗', 2, 1, 'migration-003', ''),
  ('', 'mention', '', '{bot_name} 在的哦', 2, 1, 'migration-003', ''),
  ('', 'mention_more', '', '又叫我？怎么啦～', 2, 1, 'migration-003', ''),
  ('', 'mention_more', '', '在呢在呢', 2, 1, 'migration-003', ''),
  ('', 'mention_tired', '', '呜…好吵，让我歇会儿喵', 1, 1, 'migration-003', ''),
  ('', 'keyword', '早上好', '早上好呀～今天也要开心哦', 1, 1, 'migration-003', ''),
  ('', 'keyword', '早安', '早安！', 1, 1, 'migration-003', ''),
  ('', 'keyword', '晚安', '晚安，好梦～', 1, 1, 'migration-003', '');

