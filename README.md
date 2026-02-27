# SnapAgent

A lightweight personal AI assistant framework built on Python.

## Changelog

### v0.2 — Web Search Dedup, Plan Mode & Workflow Optimization

- **Tool call dedup**: identical tool calls within a turn are cached and executed only once.
- **Search loop detection**: 3+ consecutive `web_search` calls trigger a system nudge to stop and synthesize.
- **`/plan` & `/normal` mode toggle**: `/plan` switches the session to plan mode — all subsequent messages auto-generate a structured TODO-style plan before execution. `/normal` switches back to direct execution. Mode persists across messages via `session.metadata`.
- **Plan skill** (`always: true`): teaches the agent to auto-plan for complex tasks (3+ steps, research, comparison) even in normal mode.
- **PLAN → SEARCH → FETCH → SYNTHESIZE** workflow guidance in system prompt; search results include `web_fetch` hint.
- New modules: `orchestrator/dedup.py`, `skills/plan/SKILL.md`. Telegram registers `/plan` and `/normal` commands.

### v0.1 — Web Search Quality & Multi-Source Fusion

- Query variants for quoted and CJK queries to reduce missed results.
- Brave + DuckDuckGo source fusion with extensible backend pipeline (`html` → `lite`).
- URL normalization, tracking parameter removal, and cross-source dedup.
- Lightweight relevance reranking against query terms.
- Optional `freshness` and `language` hints for `web_search`.

### v0 — Initial Release

- Full agent pipeline: multi-turn conversation, tool calling, persistent memory, context compression, skill system, scheduled tasks, sub-task spawning.
- 10 chat platforms, 17 LLM providers, MCP protocol support.

~4,000 lines of core agent code covering the full agent pipeline: multi-turn conversation, tool calling, persistent memory, context compression, skill system, scheduled tasks, sub-task spawning, and integration with 10 chat platforms and 17 LLM providers.

## Features

- **Full Agent Pipeline** — LLM chat → tool calls → result injection → multi-turn iteration (up to 40 rounds)
- **10 Chat Platforms** — Telegram, Discord, Feishu, DingTalk, Slack, QQ, WhatsApp, Email, Matrix, Mochat
- **17 LLM Providers** — OpenRouter, Anthropic, OpenAI, DeepSeek, DashScope, Zhipu, Gemini, VolcEngine, etc.
- **Persistent Memory** — Two-layer memory system (facts + history log), LLM-driven consolidation
- **Context Compression** — Three-stage compression (recency keep + salient fact extraction + rolling summary)
- **Skill System** — Markdown-defined pluggable skills with custom and community support
- **MCP Protocol** — Stdio and HTTP transport, compatible with Claude Desktop / Cursor config format
- **Real-time Progress** — Tool call progress shown to users (e.g. `[Step 1] 🔍 Searching: ...`)
- **Sub-task System** — Agent can spawn background sub-tasks for parallel processing

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/QianCyrus/SnapAgent.git
cd SnapAgent
pip install -e .
```

### 2. Configure

Run the interactive setup wizard:

```bash
snapagent onboard
```

The wizard will guide you through:
- Choosing an LLM provider and entering your API key
- Selecting a model
- Optionally configuring a chat platform (Telegram, Discord, etc.)
- Optionally setting up web search

Config is saved to `~/.snapagent/config.json`. You can also edit it manually — see [Configuration](#configuration) below.

### 3. Run

```bash
# CLI interactive chat
snapagent agent

# Single message
snapagent agent -m "Hello!"
```

**To use with Telegram, Discord, or other chat platforms, you must start the gateway:**

```bash
snapagent gateway
```

This connects SnapAgent to the chat platforms you configured. Keep it running in the background (or use Docker/systemd — see [Deployment](#deployment)).

---

## Configuration

Config file: `~/.snapagent/config.json` (supports both `camelCase` and `snake_case` keys)

### Providers

17 LLM providers supported. Add your `apiKey` under the provider name:

| Provider | Description | Get API Key |
|----------|-------------|-------------|
| `openrouter` | Global gateway, access all models (recommended) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | Claude direct | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT direct | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | DeepSeek direct | [platform.deepseek.com](https://platform.deepseek.com) |
| `dashscope` | Qwen (DashScope) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `zhipu` | Zhipu GLM | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `volcengine` | VolcEngine / Doubao Seed | [volcengine.com](https://www.volcengine.com) |
| `gemini` | Google Gemini | [aistudio.google.com](https://aistudio.google.com) |
| `moonshot` | Moonshot / Kimi | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `groq` | Groq (LLM + Whisper transcription) | [console.groq.com](https://console.groq.com) |
| `minimax` | MiniMax | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `siliconflow` | SiliconFlow | [siliconflow.cn](https://siliconflow.cn) |
| `aihubmix` | AiHubMix gateway | [aihubmix.com](https://aihubmix.com) |
| `vllm` | Local deployment (vLLM / any OpenAI-compatible server) | — |
| `custom` | Any OpenAI-compatible endpoint | — |
| `openai_codex` | OpenAI Codex (OAuth) | `snapagent provider login openai-codex` |
| `github_copilot` | GitHub Copilot (OAuth) | `snapagent provider login github-copilot` |

Minimal config example:

```json
{
  "providers": {
    "openrouter": { "apiKey": "your-api-key-here" }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5",
      "provider": "openrouter"
    }
  }
}
```

> **Auto-matching**: When `provider` is `"auto"` (default), the system matches providers by model name keywords (e.g. `claude` → `anthropic`, `qwen` → `dashscope`).

### Chat Platforms

Configure a platform in `channels`, then run `snapagent gateway` to connect.

<details>
<summary><b>Telegram</b></summary>

1. Search `@BotFather` in Telegram, send `/newbot`, copy the token
2. Add to config:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "your-bot-token",
      "allowFrom": []
    }
  }
}
```

3. Run `snapagent gateway`

> `allowFrom`: list of allowed user IDs. Empty = allow all (fine for personal use).

</details>

<details>
<summary><b>Discord</b></summary>

1. Create app at [Discord Developer Portal](https://discord.com/developers/applications) → Bot → enable MESSAGE CONTENT INTENT
2. Add to config:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "your-bot-token",
      "allowFrom": []
    }
  }
}
```

3. Generate invite URL (OAuth2 → Scopes: `bot`, Permissions: `Send Messages`, `Read Message History`)
4. Run `snapagent gateway`

</details>

<details>
<summary><b>Feishu / DingTalk / Slack</b></summary>

All use long-connection / socket mode — no public IP needed.

```json
{
  "channels": {
    "feishu": { "enabled": true, "appId": "", "appSecret": "" },
    "dingtalk": { "enabled": true, "clientId": "", "clientSecret": "" },
    "slack": { "enabled": true, "botToken": "", "appToken": "" }
  }
}
```

Then run `snapagent gateway`.

</details>

<details>
<summary><b>More platforms</b></summary>

QQ, WhatsApp, Email, Matrix, and Mochat are also supported. See `snapagent/config/schema.py` for all options.

</details>

### Agent Settings

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5",
      "provider": "auto",
      "maxTokens": 8192,
      "temperature": 0.1,
      "maxToolIterations": 40,
      "memoryWindow": 100
    }
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `model` | `anthropic/claude-sonnet-4-5` | LLM model identifier |
| `provider` | `auto` | Provider name, or `auto` for keyword-based matching |
| `maxTokens` | `8192` | Max tokens per response |
| `temperature` | `0.1` | Sampling temperature |
| `maxToolIterations` | `40` | Max tool call iterations per turn |
| `memoryWindow` | `100` | Session history window (message count) |

### Tools & MCP

Built-in tools: `web_search`, `web_fetch`, `read_file`, `write_file`, `edit_file`, `list_dir`, `exec`, `message`, `cron`, `spawn`

```json
{
  "tools": {
    "web": {
      "search": { "apiKey": "", "maxResults": 5 }
    },
    "exec": { "timeout": 60 },
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "remote": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

MCP supports both `stdio` (local process) and `HTTP` (remote endpoint) transports.

### Context Compression

```json
{
  "compression": {
    "enabled": true,
    "mode": "balanced",
    "tokenBudgetRatio": 0.65,
    "recencyTurns": 6,
    "maxFacts": 12,
    "maxSummaryChars": 1400
  }
}
```

Modes: `off` / `balanced` / `aggressive`

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `snapagent onboard` | Interactive setup wizard |
| `snapagent agent` | Interactive CLI chat |
| `snapagent agent -m "..."` | Single message |
| `snapagent gateway` | **Start gateway — required for Telegram/Discord/etc.** |
| `snapagent status` | Show config and connection status |
| `snapagent provider login <name>` | OAuth login (Codex, Copilot) |
| `snapagent channels login` | WhatsApp QR link |
| `snapagent cron add/list/remove` | Manage scheduled tasks |

**In-chat commands**: `/new` (new session), `/stop` (cancel task), `/help`

---

## Deployment

### Docker

```bash
docker build -t snapagent .
docker run -v ~/.snapagent:/root/.snapagent --rm snapagent onboard
docker run -v ~/.snapagent:/root/.snapagent -p 18790:18790 snapagent gateway
```

### Docker Compose

```bash
docker compose run --rm snapagent-cli onboard
docker compose up -d snapagent-gateway
```

### systemd

Create `~/.config/systemd/user/snapagent-gateway.service`:

```ini
[Unit]
Description=SnapAgent Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/snapagent gateway
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now snapagent-gateway
```

---

## Architecture

```
User Message → [Channel] → [MessageBus] → [AgentLoop] → [ConversationOrchestrator]
                                              ↓                    ↕
                                       [SessionManager]    [ProviderAdapter] ↔ LLM
                                       [ContextBuilder]    [ToolGateway] ↔ [ToolRegistry]
                                       [ContextCompressor]
                                              ↓
                                       [MemoryStore]
```

### Core Modules

| Module | File | Description |
|--------|------|-------------|
| **MessageBus** | `bus/queue.py` | AsyncIO queue-based bidirectional message bus |
| **AgentLoop** | `agent/loop.py` | Core message processing engine |
| **ConversationOrchestrator** | `orchestrator/conversation.py` | Pure model/tool iteration loop, channel-agnostic |
| **ContextBuilder** | `agent/context.py` | System prompt assembly (identity + memory + skills) |
| **ContextCompressor** | `core/compression.py` | Three-stage context compression |
| **MemoryStore** | `agent/memory.py` | Two-layer persistent memory (facts + history log) |
| **SessionManager** | `session/manager.py` | JSONL append-only persistence with in-memory cache |
| **ToolRegistry** | `agent/tools/registry.py` | Dynamic tool registration/execution with JSON Schema validation |
| **ChannelManager** | `channels/manager.py` | Channel lifecycle + outbound message routing |
| **SubagentManager** | `agent/subagent.py` | Background sub-task execution |
| **ProviderRegistry** | `providers/registry.py` | Provider metadata (17 specs) |

## Project Structure

```
snapagent/
├── adapters/           # Adapter layer (Provider + Tool wrappers)
├── agent/              # Agent core (loop, context, memory, skills, tools/)
├── bus/                # Message bus (events, queue)
├── channels/           # Chat platform integrations (10 platforms)
├── cli/                # CLI commands (Typer)
├── config/             # Configuration (Pydantic schema + loader)
├── core/               # Core types and compression
├── cron/               # Scheduled tasks
├── heartbeat/          # Periodic wake-up service
├── interfaces/         # Interface layer
├── orchestrator/       # Conversation orchestration
├── providers/          # LLM providers (base, registry, litellm, custom)
├── session/            # Session management (JSONL persistence)
├── skills/             # Built-in skills
├── templates/          # Workspace templates (SOUL.md, TOOLS.md, etc.)
└── utils/              # Utilities
```

## Contributing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linter
ruff check .

# Run tests
pytest tests/ -q
```

CI runs automatically on push and pull requests (lint + test on Python 3.11–3.13).

## License

MIT
