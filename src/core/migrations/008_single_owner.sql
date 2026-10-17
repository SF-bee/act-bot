-- 008：owner 全局唯一（数据库层兜底）
--
-- 背景：以前唯一性只靠 bootstrap_admin.py 的「先查再写」，admins add --role owner
--   或并发 bootstrap 都能造出多个 owner，换届逻辑（transfer_owner）也会含糊。
--
-- 去重口径（确定性、可审计）：若历史上已有多个 owner，保留 id 最大的那个，
--   其余降级为 admin。重复执行安全（部分唯一索引已存在时 CREATE 被 IF NOT EXISTS 跳过）。
--
-- SQLite 的部分唯一索引（WHERE role='owner'）只约束 owner 行，
--   admin 可以有任意多个，符合业务口径。

UPDATE admins
   SET role = 'admin'
 WHERE role = 'owner'
   AND id < (SELECT MAX(id) FROM admins WHERE role = 'owner');

CREATE UNIQUE INDEX IF NOT EXISTS uq_admins_single_owner
    ON admins(role)
 WHERE role = 'owner';
