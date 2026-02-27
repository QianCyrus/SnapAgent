# SnapAgent 四面可观测性架构设计（Health / Doctor / Logging / OTel）

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 基于统一事件骨架设计 SnapAgent 的四个可观测性面，形成“发现问题-定位问题-修复问题-防止复发”的闭环。

**Architecture:** 采用 Event Backbone（统一诊断事件）作为单一事实源。运行时只负责产出事件，Health/Doctor/Logging/OTel 四面各自消费，不反向耦合主执行链路。通过异步导出、失败隔离、修复冷却机制降低面间干扰。

**Tech Stack:** Python, asyncio, loguru, MessageBus, AgentLoop, ConversationOrchestrator, JSONL, OpenTelemetry(OTLP)

---

## 1. 背景与设计原则

SnapAgent 当前已经具备可观测性的局部能力（`status`、`channels status`、loguru 运行日志、`heartbeat`、`cron`），但能力分散在 CLI、运行时和各通道实现中，缺乏统一事件标准和跨面协同机制。

本方案采用四面分治：
- 健康面：回答“现在能不能用”。
- Doctor 面：回答“坏了怎么修，修完没”。
- 日志面：回答“到底发生了什么”。
- OTel 面：回答“长期趋势和链路瓶颈在哪里”。

核心原则：
- 人可读与机可算分离：`Logging` 为排障，`OTel` 为聚合与治理。
- 检测与修复分离：`Health` 判定状态，`Doctor` 编排修复。
- 短期排障与长期治理分离：`Logs/Doctor` 处理即时问题，`OTel` 关注趋势。

## 2. Event Backbone（单一事实源）

### 2.1 统一事件模型（v1）

建议字段：
- `event_id`: 事件唯一 ID
- `ts`: 事件时间戳（ISO8601）
- `severity`: `debug|info|warn|error|fatal`
- `component`: 如 `agent.loop`, `orchestrator`, `channel.telegram`
- `session_key`, `channel`, `chat_id`
- `run_id`, `turn_id`, `operation`
- `status`: `ok|degraded|failed|cancelled`
- `latency_ms`
- `error_code`, `error_message`
- `attrs`: 扩展字段（字典）

### 2.2 关键事件族

- `inbound.received`
- `turn.started`, `turn.finished`
- `tool.called`, `tool.succeeded`, `tool.failed`
- `channel.connected`, `channel.disconnected`, `channel.send.failed`
- `provider.request.started`, `provider.request.failed`
- `heartbeat.tick`, `heartbeat.run`
- `cron.job.scheduled`, `cron.job.started`, `cron.job.failed`, `cron.job.finished`
- `doctor.check.failed`, `doctor.repair.applied`

### 2.3 事件采集锚点（现有代码）

- `snapagent/bus/queue.py`
- `snapagent/agent/loop.py`
- `snapagent/orchestrator/conversation.py`
- `snapagent/channels/manager.py` 与各 `channels/*.py`
- `snapagent/heartbeat/service.py`
- `snapagent/cron/service.py`

## 3. 健康面（Health Surface）

### 3.1 职责
- 聚合系统实时健康快照。
- 输出 liveness/readiness/degraded 三层状态。
- 为 CLI、自动化脚本和 agent 排障入口提供机器可读状态。

### 3.2 建议输出接口
- `snapagent health`
- `snapagent status --deep --json`

语义定义：
- `--json`：输出单对象机器可读结果，供 agent/脚本消费。
- `--deep`：展开组件级证据（channel/provider/mcp/queue/heartbeat/cron）。

### 3.3 判定维度
- 进程与主循环状态（`AgentLoop` 是否活跃）
- 队列堆积（`inbound_size/outbound_size`）
- 关键依赖可用性（provider、MCP、启用 channel）
- 最近错误窗口（按组件聚合）

## 4. Doctor 面（Repair Surface）

### 4.1 职责
- 提供“检查 + 修复 + 复检”闭环。
- 面向配置、依赖、权限、状态一致性问题执行标准修复。

### 4.2 建议命令
- `snapagent doctor`（只检查）
- `snapagent doctor --repair`（执行修复）
- `snapagent doctor --repair --yes`（非交互修复）

### 4.3 检查/修复域
- 配置域：缺失字段、版本迁移、冲突键。
- 依赖域：provider 凭据、channel token、bridge/MCP 可达性。
- 本地域：`~/.snapagent` 目录权限、sessions/cron 文件完整性。
- 运行域：健康面显示异常时触发建议动作（重连、重载、禁用故障组件）。

### 4.4 审计
- 每个修复动作都写事件：`doctor.repair.applied`。
- 标注 `actor=doctor`，并附修复前后状态摘要。

## 5. 日志面（Logging Surface）

### 5.1 职责
- 提供结构化事件日志与人类友好日志。
- 支撑本地 tail 与按会话/运行链路查询。

### 5.2 设计
- 控制台日志：用于交互态观测。
- JSONL 文件日志：用于后续分析、重放和 agent 自动排障。

### 5.3 建议命令
- `snapagent logs --follow`
- `snapagent logs --session <session_key> --json`
- `snapagent logs --run <run_id> --json`

### 5.4 关键约束
- 所有日志携带关联 ID（`session_key/run_id/turn_id`）。
- 敏感信息脱敏（API key/token/cookie/邮箱凭据）。

## 6. OTel 面（Telemetry Surface）

### 6.1 职责
- 将统一事件映射为 metrics/traces/logs 并导出到 OTLP 后端。
- 支撑 SLO、容量趋势、跨组件链路分析。

### 6.2 信号映射
- Metrics：`turn_latency_ms`, `tool_success_ratio`, `queue_backlog`, `provider_error_rate`
- Traces：`inbound -> orchestrate -> tool -> outbound`
- Logs：可选将 JSONL 事件桥接到 OTLP logs

### 6.3 运行要求
- 默认可关闭，启用后异步导出。
- 导出失败只影响观测，不影响主链路。

## 7. 四面协同与排障路径

标准路径：
1. Health：判断是系统级故障还是组件级故障。
2. Logging：按 `session_key/run_id` 定位根因。
3. Doctor：执行修复并复检。
4. OTel：验证修复后的趋势是否回归正常。

## 8. 干扰风险与隔离策略

会有干扰风险，但可通过架构约束降到最低。

### 8.1 典型干扰点
- 观测写入与导出占用 I/O，影响主流程时延。
- 日志与 OTel 双重埋点导致重复采集。
- Doctor 自动修复触发告警回环（修复-告警-再修复）。

### 8.2 隔离策略
- 单向数据流：`runtime -> event backbone -> surfaces`。
- 异步缓冲：日志落盘与 OTel 导出走独立队列。
- 失败隔离：观测面失败不阻塞 `AgentLoop`。
- 去重与冷却：Doctor 修复动作需要 cooldown 与幂等键。
- 统一 schema：日志与 OTel 共享同一事件结构，避免双份埋点。

## 9. 任务拆分建议（便于并行）

- Task A: Event Backbone（事件模型 + 采集钩子）
- Task B: Health CLI（`health/status --deep --json`）
- Task C: Logging Pipeline（JSONL + 查询命令）
- Task D: Doctor CLI（检查/修复框架 + 规则集）
- Task E: OTel Exporter（metrics/traces/logs 映射与导出）
- Task F: 端到端验收（故障注入 + 四面闭环验证）

建议优先级：A -> B/C -> D -> E -> F。

## 10. 验收标准（架构层）

- 命令层可明确区分四面职责，无语义重叠。
- 任意一次失败可通过 `health + logs + doctor` 完成闭环。
- OTel 面可看见聚合趋势并与日志事件 ID 对齐。
- 观测面关闭或故障时，主对话链路仍可工作。
