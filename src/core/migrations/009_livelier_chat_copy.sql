-- 009：让内置聊天规则更贴合活泼的人设。
--
-- 只更新迁移 003 写入的默认规则，不覆盖管理员后来新增或修改的规则。

UPDATE chat_rules
SET reply = CASE reply
  WHEN '在的喵～' THEN '在的喵～有什么事尽管说！'
  WHEN '嗯？叫我吗' THEN '嗯？是在叫我嘛～'
  WHEN '{bot_name} 在的哦' THEN '{bot_name} 在的哦，随时可以找我玩！'
  WHEN '又叫我？怎么啦～' THEN '又叫我？怎么啦怎么啦～'
  WHEN '在呢在呢' THEN '在呢在呢，我有认真听！'
  WHEN '呜…好吵，让我歇会儿喵' THEN '呜…连续叫我好多次啦，让我喘口气嘛～'
  WHEN '早上好呀～今天也要开心哦' THEN '早上好呀～今天也要元气满满！'
  WHEN '早安！' THEN '早安早安！今天也要开心出门～'
  WHEN '晚安，好梦～' THEN '晚安啦，好梦～明天也要精神满满！'
  ELSE reply
END
WHERE created_by = 'migration-003';
