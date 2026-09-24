-- 001_init.sql — ACT Bot 初始结构（SQLite）
-- 说明：
--   * 本目录是数据库结构的唯一基线（模型文件需与其保持同步）；
--   * 所有时间字段统一存 UTC ISO-8601 字符串（应用侧写入）；
--   * 迁移按文件名前缀编号升序应用，版本记录在 PRAGMA user_version。

PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS admins (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  qq         TEXT NOT NULL UNIQUE,
  role       TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('owner', 'admin')),
  note       TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS "groups" (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id   TEXT NOT NULL UNIQUE,
  name       TEXT NOT NULL DEFAULT '',
  features   TEXT NOT NULL DEFAULT '{}',
  welcome_on INTEGER NOT NULL DEFAULT 1,
  active     INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS departments (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  contact     TEXT NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 0,
  active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  title           TEXT NOT NULL,
  description     TEXT NOT NULL DEFAULT '',
  location        TEXT NOT NULL DEFAULT '',
  start_at        TEXT NOT NULL DEFAULT '',
  end_at          TEXT NOT NULL DEFAULT '',
  signup_required INTEGER NOT NULL DEFAULT 0,
  signup_deadline TEXT NOT NULL DEFAULT '',
  capacity        INTEGER NOT NULL DEFAULT 0,
  status          TEXT NOT NULL DEFAULT 'draft',
  created_by      TEXT NOT NULL DEFAULT '',
  created_at      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS event_signups (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id     INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  qq           TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  note         TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'going',
  created_at   TEXT NOT NULL DEFAULT '',
  UNIQUE (event_id, qq)
);

CREATE TABLE IF NOT EXISTS announcements (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  title         TEXT NOT NULL DEFAULT '',
  content       TEXT NOT NULL,
  target_groups TEXT NOT NULL DEFAULT '[]',
  priority      INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'draft',
  created_by    TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL DEFAULT '',
  sent_at       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS archive_items (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  title       TEXT NOT NULL,
  category    TEXT NOT NULL DEFAULT '',
  year        INTEGER,
  authors     TEXT NOT NULL DEFAULT '',
  dept_id     INTEGER REFERENCES departments(id) ON DELETE SET NULL,
  description TEXT NOT NULL DEFAULT '',
  file_path   TEXT NOT NULL DEFAULT '',
  url         TEXT NOT NULL DEFAULT '',
  tags        TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  updated_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  qq         TEXT NOT NULL DEFAULT '',
  action     TEXT NOT NULL,
  detail     TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_event_signups_event ON event_signups(event_id);
CREATE INDEX IF NOT EXISTS idx_archive_items_category ON archive_items(category);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
