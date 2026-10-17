# 群互动 · 骰子 / 运势 / 选一个

三个轻量群互动命令，**默认开启**，不落库、不调用外部服务，也不需要新增数据库表。

## 开关

- 全局：`config/config.toml` 的 `[features].fun`（默认 `true`）；
- 群级：管理员发 `/config fun on|off`（写入 `groups.features`）；
- 私聊不响应，会提示「这个命令要在群里用」。

## 命令

| 命令 | 别名 | 说明 |
| --- | --- | --- |
| `/骰子 [NdM]` | `/roll`、`/dice` | 缺省 `1d6`；支持 `2d6`、`d20`、`6`（等价 1d6） |
| `/运势` | `/fortune`、`/今日运势` | 今日运势：等级 + 文案 + 幸运数字 |
| `/选一个 <选项...>` | `/choose`、`/select` | 从 2–20 个选项里随机选一个 |

### 骰子

- 数量 1–20，面数 2–1000；超出范围直接返回提示，不抛异常；
- 单颗只显示点数，多颗显示逐颗与总和，例如 `🎲 2d6：3 + 5 = 8`。

### 运势

按 `(QQ 号, 本地日期)` 做 SHA-256 哈希，同一人同一天多次查询结果稳定；换天或换人才会变化。
文案在 `[fun].fortune_texts` 配置，每项形如 `"大吉|{nickname} 今天……"`：

- `|` 前是等级（没有 `|` 时显示「运势」）；
- 占位符支持 `{nickname}`、`{date}`；未知占位符原样保留；
- 单条文案长度上限 200 字，配置错误会在启动时由 `load_settings` 报 `ConfigError`。

### 选一个

空格、英文逗号、中文逗号、顿号、分号都可分隔选项；少于 2 个或超过 20 个会提示。

## 实现位置

- 纯逻辑与单测：`src/core/fun.py`、`tests/test_fun.py`；
- 命令注册与门控：`src/plugins/fun/__init__.py`；
- 功能名册：`src/core/features.py` 的 `FEATURE_FUN`；
- 配置：`src/core/config.py` 的 `fun_fortune_texts` 与 `config/config.example.toml` 的 `[fun]`。

## 验收

见 `docs/acceptance.md` 的「群互动 · 骰子 / 运势 / 选一个」一节。
