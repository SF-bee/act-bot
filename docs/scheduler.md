# 定时任务与定时推送

**一个调度器，不是一功能一模块。** 所有定时任务都由 `src/core/scheduler.py` 的
`_register_jobs(scheduler, settings)` 注册（`setup_and_start()` 负责创建/启动调度器，
进程启动时由 `src/bot.py` 调用），底层是 APScheduler，跨平台、不依赖系统 cron / 计划任务。

**单个任务配置写错只跳过它自己**：例如 `backup.daily_at` 非法时只少掉每日备份，
统计落库 / 日报 / 推送照常注册；启动日志会列出实际注册的 job id。

| 任务 | 触发 | 位置 |
| --- | --- | --- |
| 每日备份 | `CronTrigger`，`backup.daily_at` | `scheduler.py` |
| 统计落库 | `IntervalTrigger`，`stats.flush_seconds` | `scheduler.py` |
| 退出兜底落库 | 进程退出钩子，`stats.flush_timeout_seconds` | `src/bot.py` |
| 每日活跃简报 | `CronTrigger`，`stats.digest_at` | `scheduler.py` |
| 定时推送 | `CronTrigger`，来自 config.toml 的 `[[push]]` | `src/core/push.py` |

## 定时推送：只改配置，不改代码

要加一条「每天 08:00 给所有群发早报」，**只在 `config/config.toml` 里加一段**：

```toml
[[push]]
name = "早报"                      # 唯一，用作日志与 /push 列表里的名字
at = "08:00"                      # HH:MM，或 ["08:00", "20:00"]
weekdays = ["mon", "wed", "fri"]  # 可选；不写 = 每天（可用 mon..sun 或 周一..周日）
targets = ["all"]                 # "all" / "admins" / 具体群号（可混写）
text = "{bot_name}：早上好，今天是 {date}（{weekday}）～"
feature = "stats"                 # 可选：只有开启该功能的群才发
enabled = true                    # 可选：false = 暂停但不删配置
```

改完**重启业务层**生效（启动脚本 `scripts/` 或 `launchctl kickstart -k gui/$(id -u)/com.actbot.dev`）。

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | ✅ | 唯一；日志、`/push` 列表、`/push test` 都用它 |
| `at` | ✅ | `HH:MM` 或时间数组（一条推送可一天多次） |
| `text` | ✅ | 正文；支持占位符（见下） |
| `weekdays` | | 缺省每天；`mon..sun` / `周一..周日` |
| `targets` | | 缺省 `["admins"]`；`"all"`=全部已登记群、`"admins"`=私聊管理员、其余按群号 |
| `feature` | | 只在开启了该功能的群发（其余群跳过） |
| `enabled` | | 缺省 `true`；`false` 暂停该条 |

占位符（`str.replace` 实现，未识别的花括号原样保留）：`{bot_name}` `{bot_title}`
`{date}` `{time}` `{weekday}`。

### 怎么确认配对了

- `/push`：列出所有推送（时间 / 星期 / 目标 / 启停）；
- `/push test <名称>`：立即按该条配置试发一次，用来调文案；
- 配置写错（时间格式、未知 feature、重名…）会在**启动时**报 `ConfigError`，不会静默忽略。

### 目标群从哪来（`targets = ["all"]`）

`"all"` 取 `groups` 表里 `active=1` 的群。机器人**连上协议端时**会用
`get_group_list` 同步一次群名册（`src/bot.py` 的 `on_bot_connect` →
`groups.sync_from_bot`），所以正常情况下 `"all"` 就是机器人当前所在的全部群。
没被同步到（例如协议端不返回该群）的群，也可以直接在 `targets` 里写群号。

## 内部拆分（要做动态内容时看这里）

| 层 | 放哪 | 职责 |
| --- | --- | --- |
| 何时 | `src/core/push.py` / `scheduler.py` | `register_jobs` 把 `[[push]]` 变成 job |
| 发什么 | `src/core/push.py`（`render_text`）+ config | 渲染文本（纯函数，可单测） |
| 怎么发 | `src/core/notify.py` | 拿 Bot、逐个发、失败隔离 |

定时任务只会用一种方式发消息——`notify`：

```python
from src.core import notify

await notify.send_group([群号, ...], "文本", interval_seconds=3)  # 群发；返回成功条数
await notify.send_private([QQ, ...], "文本")                     # 私聊；返回成功条数
await notify.notify_admins("文本")                                # 私聊全部管理员
```

约定：只用第一个已连接账号、单个目标失败不影响其它目标、没有账号时安全返回 0。

**需要「算出来的内容」时**（例如统计日报 `stats.daily_digest`）：在 core 里加一个
返回文本的纯函数，再照 `scheduler.py` 里 `stats-digest` 的样子加一个 job（`push` 适合
静态文案，不负责查库）。步骤：写纯函数 → 在 `scheduler.py` `add_job` → 单测渲染 → 文档。

## 注意

- 时间统一用 `settings.timezone`（调度器启动时已设时区）；
- 群发记得传 `interval_seconds`（`[[push]]` 默认用 `[broadcast].interval_seconds`），降低风控；
- 每个 job 必须带 `id=` 且 `replace_existing=True`（`push` 自动用 `push:<名称>:<序号>`）；
- 定时任务**不自动检查群级功能开关**；`[[push]]` 的 `feature` 字段是唯一例外（会按群过滤）；
- 改完要**重启业务层**才生效（job 在启动时注册一次）。
