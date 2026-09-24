# OneBot v11 接口契约（ACT Bot）

> **本文件是"业务层 ↔ 协议端"之间的唯一接口约定。**
> 业务代码只允许依赖本文件列出的能力；协议端（NapCat / LLOneBot / Lagrange / Fake OneBot）必须实现该子集。
> 修改契约 = 修改本文件 + 更新 Fake OneBot + 补充测试。

## 1. 连接模型

| 项 | 约定 |
| --- | --- |
| 方式 | **反向 WebSocket**：协议端作为客户端，主动连接 ACT Bot |
| 端点 | `ws://<机器人主机>:<端口>/onebot/v11/ws`（端口默认 8080，见 `.env`） |
| 握手头 | **必填**：`X-Self-ID: <机器人登录QQ号>`（缺失会被拒绝）；建议同时带 `X-Client-Role: Universal` |
| 鉴权 | 可选 `Authorization: Bearer <token>`；token 由 `.env` 的 `ONEBOT_ACCESS_TOKEN` 配置，协议端须一致（公网环境必须启用） |
| 心跳 | 协议端应周期性发送 `meta_event`；Bot 侧不因空闲主动断开 |
| 断线 | 由协议端负责重连（建议 5 秒退避）；Bot 侧等待重连，不主动拉取历史 |
| 方向 | 同一连接内双向：协议端 → 事件上报；Bot → API 调用（含 `echo` 关联应答） |

## 2. 事件子集（Bot 接收）

| 事件 | 用途 | 必填关键字段 |
| --- | --- | --- |
| `message.group`（`post_type=message, message_type=group`） | 群消息 → 全部群命令 | `message_id, group_id, user_id, sender, message[], raw_message` |
| `message.private`（`message_type=private`） | 私聊消息（可选支持） | 同上（无 `group_id`） |
| `notice.group_increase` | 有人入群（入群欢迎，P4） | `group_id, user_id, operator_id, sub_type` |
| `notice.group_decrease` | 有人退群 / 被踢（群管审计，P2） | `group_id, user_id, operator_id, sub_type` |
| `meta_event.lifecycle` / `meta_event.heartbeat` | 连接状态 | `time` |

> 备注：其余事件类型（戳一戳、文件上传等）暂不在契约内，出现时由适配器忽略即可。

## 3. API 子集（Bot 调用）

| action | 用途（对应功能） | 关键参数 | 成功返回 data |
| --- | --- | --- | --- |
| `send_msg` | **全部回复的主通道**（nonebot `Bot.send` / `matcher.finish` 的实际调用；按 `message_type` 路由群/私聊） | `message_type, user_id?, group_id?, message`（消息段数组） | `{message_id}` |
| `send_group_msg` | 群回复（直调时使用；协议端通常同样支持） | `group_id, message` | `{message_id}` |
| `send_private_msg` | （可选）私聊回复 | `user_id, message` | `{message_id}` |
| `get_login_info` | 启动自检 / 契约冒烟 | — | `{user_id, nickname}` |
| `get_group_member_info` | 入群欢迎 / 群管 | `group_id, user_id, no_cache` | `{user_id, nickname, card, role}` |
| `set_group_ban` | 基础群管理（禁言） | `group_id, user_id, duration` | — |
| `set_group_kick` | 基础群管理（移出） | `group_id, user_id, reject_add_request` | — |
| `delete_msg` | 基础群管理（撤回） | `message_id` | — |
| `get_msg` | 引用查询 / 去重 | `message_id` | `{message_id, message[]}` |

调用约定：每次调用携带自增 `echo`；协议端应答须带回同值 `echo`；默认超时 10 秒，失败仅记录日志，不自动重试。

## 4. 消息段（MVP 支持）

| 段类型 | 用途 |
| --- | --- |
| `text` | 全部功能 |
| `at` | @ 提醒（欢迎 / 通知） |
| `image` | 图片（资料 / 通知） |
| `reply` | 引用回复（可选） |

## 5. 兼容目标

- NapCat v4.x（Ubuntu / Windows；macOS 实验）
- LLOneBot、Lagrange.Core（备选协议端）
- `tests/` 与 `scripts/smoke_fake.py` 内的 Fake OneBot（同一子集，用于离线测试与冒烟）

## 6. 变更流程

1. 修改本文件（补"变更记录"）；
2. 同步更新 Fake OneBot 与相关测试；
3. 在提交信息中注明契约变更。

## 变更记录

| 日期 | 变更 | 备注 |
| --- | --- | --- |
| 2026-09-24 | 初版（P0） | 定义 MVP 所需最小子集 |
