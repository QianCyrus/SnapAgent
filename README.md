# SnapAgent

A lightweight personal AI assistant framework built on Python.

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

## Demo

<!-- TODO: Add demo videos/GIFs here -->

---

## Quick Start

### 1. Install

```bash
git clone <repo-url>
cd snapagent
pip install -e .
```

### 2. Setup

```bash
snapagent onboard
```

The interactive onboard wizard will guide you through:
- Choosing an LLM provider and entering your API key
- Selecting a model
- Optionally configuring a chat platform (Telegram, Discord, etc.)
- Optionally setting up web search

### 3. Chat

```bash
# Interactive mode
snapagent agent

# Single message
snapagent agent -m "Hello!"

# Start gateway (connect to chat platforms)
snapagent gateway
```

---

## Configuration

Config file: `~/.snapagent/config.json` (JSON, supports both `camelCase` and `snake_case`)

### Providers

17 LLM providers supported. Add your `apiKey` under the provider name:

| Provider | Description | Get API Key |
|----------|-------------|-------------|
| `custom` | Any OpenAI-compatible endpoint (direct, no LiteLLM) | — |
| `openrouter` | Global gateway, access all models (recommended) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | Claude direct | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT direct | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | DeepSeek direct | [platform.deepseek.com](https://platform.deepseek.com) |
| `zhipu` | Zhipu GLM | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `dashscope` | Qwen (DashScope) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `volcengine` | VolcEngine / Doubao Seed | [volcengine.com](https://www.volcengine.com) |
| `moonshot` | Moonshot / Kimi | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `minimax` | MiniMax | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `siliconflow` | SiliconFlow | [siliconflow.cn](https://siliconflow.cn) |
| `aihubmix` | AiHubMix gateway | [aihubmix.com](https://aihubmix.com) |
| `gemini` | Google Gemini | [aistudio.google.com](https://aistudio.google.com) |
| `groq` | Groq (LLM + Whisper transcription) | [console.groq.com](https://console.groq.com) |
| `vllm` | Local deployment (vLLM / any OpenAI-compatible server) | — |
| `openai_codex` | OpenAI Codex (OAuth) | `snapagent provider login openai-codex` |
| `github_copilot` | GitHub Copilot (OAuth) | `snapagent provider login github-copilot` |

Example:

```json
{
  "providers": {
    "openrouter": { "apiKey": "" }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

**Auto-matching**: When `provider` is `"auto"` (default), the system matches providers by model name keywords (e.g. `claude` → `anthropic`, `qwen` → `dashscope`).

### Agent Settings

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "auto",
      "maxTokens": 8192,
      "temperature": 0.1,
      "maxToolIterations": 40,
      "memoryWindow": 100,
      "workspace": "~/.snapagent/workspace"
    }
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `model` | `anthropic/claude-opus-4-5` | LLM model identifier |
| `provider` | `auto` | Provider name, or `auto` for keyword-based matching |
| `maxTokens` | `8192` | Max tokens per response |
| `temperature` | `0.1` | Sampling temperature |
| `maxToolIterations` | `40` | Max tool call iterations per turn |
| `memoryWindow` | `100` | Session history window (message count) |

### Chat Platforms

Enable platforms in `channels`:

<details>
<summary><b>Telegram</b></summary>

1. Search `@BotFather` in Telegram, send `/newbot`, copy the token
2. Configure:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "",
      "allowFrom": []
    }
  }
}
```

3. Run `snapagent gateway`

</details>

<details>
<summary><b>Discord</b></summary>

1. Create app at [Discord Developer Portal](https://discord.com/developers/applications) → Bot → enable MESSAGE CONTENT INTENT
2. Configure:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "",
      "allowFrom": []
    }
  }
}
```

3. Generate invite URL (OAuth2 → Scopes: `bot`, Permissions: `Send Messages`, `Read Message History`)
4. Run `snapagent gateway`

</details>

<details>
<summary><b>Feishu</b></summary>

WebSocket long connection — no public IP needed.

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "",
      "appSecret": "",
      "allowFrom": []
    }
  }
}
```

</details>

<details>
<summary><b>DingTalk</b></summary>

Stream mode — no public IP needed.

```json
{
  "channels": {
    "dingtalk": {
      "enabled": true,
      "clientId": "",
      "clientSecret": "",
      "allowFrom": []
    }
  }
}
```

</details>

<details>
<summary><b>Slack</b></summary>

Socket Mode — no public URL needed.

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "",
      "appToken": "",
      "groupPolicy": "mention"
    }
  }
}
```

</details>

<details>
<summary><b>More platforms</b></summary>

QQ, WhatsApp, Email, Matrix, and Mochat are also supported. See `snapagent/config/schema.py` for all configuration options.

</details>

### Tools & MCP

```json
{
  "tools": {
    "web": {
      "search": { "apiKey": "", "maxResults": 5 }
    },
    "exec": { "timeout": 60 },
    "restrictToWorkspace": false,
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

Built-in tools: `web_search`, `web_fetch`, `read_file`, `write_file`, `edit_file`, `list_dir`, `exec`, `message`, `cron`, `spawn`

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
| `snapagent agent` | Interactive chat |
| `snapagent agent -m "..."` | Single message |
| `snapagent gateway` | Start gateway (connect chat platforms) |
| `snapagent status` | Show status |
| `snapagent provider login <name>` | OAuth login |
| `snapagent channels login` | WhatsApp QR link |
| `snapagent cron add/list/remove` | Manage scheduled tasks |

In-chat commands: `/new` (new session), `/stop` (cancel task), `/help`

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

### Message Flow

**1. Inbound (User → Agent)**
- Channel receives raw message → checks `allowFrom` → constructs `InboundMessage` → publishes to `MessageBus.inbound` queue → `AgentLoop` consumes and dispatches

**2. Processing (Agent Core)**
- `SessionManager.get_or_create()` → load history
- `ContextCompressor.compress()` — three-stage: recency keep + salient fact extraction + rolling summary
- `ContextBuilder.build_messages()` — assemble: system prompt + compressed context + runtime metadata + user message
- `ConversationOrchestrator.run_agent_loop()` — iterate: LLM call → tool execution → result injection → repeat until text reply

**3. Outbound (Agent → User)**
- `AgentLoop` constructs `OutboundMessage` → publishes to `MessageBus.outbound` → `ChannelManager` routes to target channel

### Core Modules

| Module | File | Description |
|--------|------|-------------|
| **MessageBus** | `bus/queue.py` | AsyncIO queue-based bidirectional message bus (44 lines) |
| **AgentLoop** | `agent/loop.py` | Core message processing engine |
| **ConversationOrchestrator** | `orchestrator/conversation.py` | Pure model/tool iteration loop, channel-agnostic |
| **ContextBuilder** | `agent/context.py` | System prompt assembly (identity + bootstrap + memory + skills) |
| **ContextCompressor** | `core/compression.py` | Three-stage context compression |
| **MemoryStore** | `agent/memory.py` | Two-layer persistent memory (MEMORY.md facts + HISTORY.md log) |
| **SessionManager** | `session/manager.py` | JSONL append-only persistence with in-memory cache |
| **ToolRegistry** | `agent/tools/registry.py` | Dynamic tool registration/execution with JSON Schema validation |
| **ProviderAdapter** | `adapters/provider.py` | Thin wrapper pinning model/max_tokens/temperature |
| **ToolGateway** | `adapters/tools.py` | Tool call tracing layer |
| **ChannelManager** | `channels/manager.py` | Channel lifecycle + outbound message routing |
| **SubagentManager** | `agent/subagent.py` | Background sub-task execution with independent ToolRegistry |
| **ProviderRegistry** | `providers/registry.py` | Provider metadata (17 specs), single source of truth |

---

## Project Structure

```
snapagent/
├── adapters/           # Adapter layer (isolate Orchestrator from Provider/Tool)
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

## License

MIT
