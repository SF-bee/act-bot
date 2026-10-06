-- 006：私聊管理群的「默认群」绑定（/use），重启后保留
--
-- 背景：scope.py 最初把 qq -> group_id 的绑定放在进程内存，重启即丢。
-- 本表把它落库；启动时 scope.load_all() 回填内存缓存，读路径保持同步。

CREATE TABLE IF NOT EXISTS admin_bindings (
  qq         TEXT PRIMARY KEY,
  group_id   TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);
