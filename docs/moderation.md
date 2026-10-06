# 群管理 · 风控

> 目标：替代 Q 群管家的一部分能力，而且更可控、更透明——规则按群配、全程审计、可空跑、可灰度。
> 纯逻辑在 src/core/moderation.py，目标群解析在 src/core/scope.py，插件在 src/plugins/moderation/。

## 1. 能做什么

| 检测 | 说明 | 默认动作 |
| --- | --- | --- |
| 敏感词 / 正则 | 管理员配置的 keyword 或 regex 规则 | 规则自带的 action（默认 warn：撤回+警告） |
| 刷屏 | 短时间窗口内消息数超阈值 | mute（禁言） |
| 复读 | 窗口内相同文本/图片重复出现 | warn |
| @全体 | 消息里 @ 了全体成员 | warn |

处置动作（严重度 kick > mute > warn > recall_only）：

- **warn**：撤回 + @警告；累计到 warn_before_mute 次自动升级为禁言
- **recall_only**：只撤回
- **mute**：撤回 + 禁言
- **kick**：撤回 + 移出本群（默认只在你显式配规则或手动命令时触发）

## 2. 开关

~~~text
/config moderation on|off     # 群级开关（管理员；群内或私聊都行）
~~~

全局开关在 config.toml 的 [features].moderation（默认开）。默认不预置任何敏感词，所以即使开着也不会误伤。

## 3. 规则管理（/mod）

~~~text
/mod                                              # 状态：开关、规则数、阈值、机器人权限
/mod list [kind]                                  # 列出规则（含 id）
/mod add <kind> | <pattern> | <action> | <秒>     # 新增本群规则
/mod add --global ...                             # 新增全局规则（所有群叠加生效）
/mod add -n ...                                   # 不撤回（默认撤回）
/mod del <id>                                     # 删除规则
/mod test <文本>                                  # 空跑：看会命中什么，不处置
/mod log [n]                                      # 最近 n 条处置记录
~~~

示例：

~~~text
/mod add keyword | 代练加群 | mute | 600
/mod add regex | [0-9]{8,} | warn
/mod add --global -n keyword | 测试勿扰 | warn
/mod test 你还在代练加群吗
~~~

- kind：keyword（子串，大小写不敏感）｜regex（正则，非法正则自动跳过）
- action：warn｜recall_only｜mute｜kick
- 秒：仅 mute/kick 有意义，省略用默认禁言时长
- 作用域：全局规则 + 本群规则**叠加**生效（与 /chat 的群级覆盖不同）

## 4. 私聊管理（不用在群里当众敲命令）

管理员可以直接私聊机器人管理任意群：

~~~text
/use 123456789            # 绑定默认群（会校验机器人是否在群里）
/use                      # 查看当前绑定
/use off                  # 解除绑定

/mute 100001 600          # 绑定后省略群号
/mute -g 123456789 100001 600   # 或用 -g 单次指定
/mute -g 123456789 -s 100001 600  # -s 静默：不在群里发通告，只写审计
~~~

- **-g <群号>**：指定目标群；群内不需要（默认当前群）
- **-s**：静默，不发群内通告，但审计照记
- 私聊命令的回复回到私聊，不会在群里回显管理员操作
- 绑定关系**落库**（admin_bindings 表），重启后保留；-g 始终可用作单次指定

## 5. 手动群管理命令

~~~text
/warn   [-g 群号] [-s] <qq> [原因]    # 手动警告（计入累计次数）
/mute   [-g 群号] [-s] <qq> [秒]      # 手动禁言（默认 600，上限 30 天）
/unmute [-g 群号] [-s] <qq>           # 解除禁言
/kick   [-g 群号] [-s] <qq>           # 移出本群
/recall [-g 群号] [message_id]        # 撤回消息（群内可直接回复目标消息）
~~~

所有手动操作都会落审计；机器人需要具备群管理权限，否则撤回/禁言/踢人会失败并提示。

## 6. 配置（config/config.toml 的 [moderation]）

| 键 | 默认 | 含义 |
| --- | --- | --- |
| flood_window_seconds / flood_max_messages | 8 / 8 | 刷屏窗口与阈值 |
| flood_action / flood_mute_seconds | mute / 600 | 刷屏处置与时长 |
| duplicate_window_seconds / duplicate_max | 30 / 3 | 复读窗口与次数 |
| duplicate_action | warn | 复读处置 |
| mention_all_action | warn | @全体 处置 |
| warn_before_mute / strike_window_seconds | 3 / 600 | 警告升级与有效期 |
| action_cooldown_seconds | 30 | 同一人两次处置的最小间隔 |
| default_mute_seconds / max_mute_seconds | 600 / 2592000 | 禁言默认与上限 |
| exempt_group_admins | true | 群主/群管理员豁免 |
| dry_run | false | 只审计不执行（灰度用） |
| warn_text | 见示例 | 警告模板 |

warn_text 占位符：{nickname} {user_id} {reason} {count} {limit} {bot_name} {bot_title}。

## 7. 灰度与误伤应急

1. 先开 dry_run = true：所有判定只写审计，不真实撤回/禁言；
2. 用 /mod test 逐条验证规则不会误伤；
3. 确认后把 dry_run 改回 false 并重启业务层；
4. 出现误伤：/config moderation off 立刻关本群风控，或临时开 dry_run。

## 8. 审计

每条处置写入 audit_log，动作名为 moderation.recall / warn / mute / kick，规则增删为 moderation.rule.add / del。用 /mod log 或 /audit 查看。

## 9. 已知边界

- 图片/语音/文件**不做内容识别**（项目不接 AI）；图片只参与"重复图片"与频率检测。
- 警告计数与刷屏/复读窗口存内存，重启清零；处置记录持久在审计里。
- 机器人不是管理员时，撤回/禁言/踢人会失败（有日志与提示），但警告文案仍可能发出。
- 规则只匹配纯文本；QQ 富媒体卡片里的文字不一定能取到。
## 10. 内置敏感词库（不用手动加词）

默认内置一份来自 houbb/sensitive-word-data（Apache-2.0）的词库，**已排除政治类**，约 6.2 万词。
匹配用纯 Python DFA（src/core/sensitive.py），无需 Java、无第三方依赖。

配置项（[moderation]）：

| 键 | 默认 | 含义 |
| --- | --- | --- |
| sensitive_dict | true | 是否启用内置词库 |
| sensitive_action | warn | 命中处置：warn / recall_only / mute / kick |
| sensitive_skip | false | 容忍干扰字符：跳过空白/标点/符号/数字/字母 + 折叠连续重复字（刷1单、刷-单、刷刷单） |
| sensitive_min_length | 2 | 最短命中词长（过滤单字，降低误伤） |
| sensitive_traditional | true | 繁体先转简体再匹配（刷單） |
| sensitive_pinyin | false | 拼音变体匹配（shuadan）；误伤与内存略高，默认关 |
| sensitive_patterns | true | 内置正则：URL / 域名 / 手机号 / QQ 号 |
| sensitive_pattern_action | warn | 内置正则命中的处置 |

误伤处理：

1. 用 /mod test <文本> 查看会命中哪些词；
2. 确认是误伤后，把该词加进 src/core/wordlists/sensitive_allow.txt（每行一个，重启生效）；
3. 或直接 sensitive_dict = false 关闭内置词库，只用 /mod add 自定义规则。

词库更新：

~~~bash
uv run python scripts/import_sensitive_words.py            # 拉取上游最新词库并过滤
uv run python scripts/import_sensitive_words.py --exclude-tags 0,1   # 自定义排除标签
~~~

注意：内置词库是“大而全”的通用词库，短词（如 13点）可能误伤正常聊天；
这也是默认建议先 dry_run 观察、确认后再实际处置的原因。
