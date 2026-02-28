# SnapAgent 版本回滚设计（方案 B 精简版）

## 1. 背景与目标

当前 SnapAgent 需要支持“新 feature 不稳定时，用户可快速切回旧版本”。

本设计目标：
- 提供可操作、低门槛的版本回滚路径（优先面向 pip 与 Docker 用户）。
- 避免源码层回滚（`git checkout`）成为最终用户的主要手段。
- 不引入 feature flag；仅通过版本发布与通道控制实现回滚。

非目标：
- 本轮不实现灰度开关/功能开关系统。
- 本轮不改变业务逻辑，仅改发布与部署面。

## 2. 现状约束

- 仓库已有 Python 包版本（`pyproject.toml`）与运行时版本常量（`snapagent/__init__.py`）。
- 当前 `docker-compose.yml` 以 `build` 为主，不利于用户直接切历史镜像 tag。
- CI（`.github/workflows/ci.yml`）已存在，但缺少 release 流程与通道发布。

## 3. 总体方案

采用“不可变制品 + 可移动通道别名”的发布模型：

1) 不可变版本（真实版本）
- Python 包：`X.Y.Z`（例如 `0.1.5`）
- Docker 镜像：`vX.Y.Z`、`sha-<shortsha>`、`canary-<shortsha>`

2) 可移动通道（逻辑入口）
- `stable`：当前稳定版本
- `latest`：固定跟随 `stable`
- `canary`：当前试验版本（从 `release` 分支自动构建）

3) 回滚机制
- 回滚不重新构建：仅将运行配置切到历史不可变 tag/version。
- 用户操作：
  - pip: `pip install "snapagent-ai==<old_version>"`
  - Docker: 设置 `SNAPAGENT_TAG=<old_tag>` 后重启 compose。

## 4. 控制面设计

### 4.1 版本源统一

将版本号维护为单一来源，避免 `pyproject.toml` 与 `__init__.py` 漂移：
- `pyproject.toml` 作为事实源（source of truth）。
- `snapagent/__init__.py` 通过 `importlib.metadata.version("snapagent-ai")` 动态读取；
  当本地未安装分发包时回退到开发占位值。

### 4.2 发布触发

- `push release`：
  - 执行 CI 等价测试
  - 构建并推送 canary 镜像（`canary-<sha>` + `sha-<sha>` + 可选 `canary`）
  - 不更新 `stable/latest`

- `push tag v*`：
  - 执行测试
  - 发布正式 Python 包
  - 构建并推送 `vX.Y.Z` 镜像
  - 更新 `stable` 与 `latest` 指向该版本

### 4.3 运行时切换

`docker-compose.yml` 增加 image 模式：
- `snapagent-gateway` 默认使用 `ghcr.io/<org>/snapagent:${SNAPAGENT_TAG:-stable}`。
- 可保留开发 profile（本地 build）以兼容开发流程。

## 5. 用户侧操作路径

### 5.1 升级
- pip: `pip install -U snapagent-ai`
- Docker: `SNAPAGENT_TAG=stable docker compose pull && docker compose up -d`

### 5.2 回滚
- pip: `pip install "snapagent-ai==0.1.4.post2"`
- Docker: `SNAPAGENT_TAG=v0.1.4.post2 docker compose pull && docker compose up -d`

### 5.3 排障建议
- 运行 `snapagent --version` 验证生效版本。
- Docker 通过 `docker ps --format` / 日志确认镜像 tag 已切换。

## 6. 风险与缓解

风险：
- 镜像 tag 管理不当导致 `stable` 被错误覆盖。
- Python 包版本与 git tag 不一致。

缓解：
- 仅允许 tag workflow 更新 `stable/latest`。
- 在 release workflow 中校验 tag 与包版本一致性。
- 将回滚命令写入 README，避免用户临时依赖源码回滚。

## 7. 验收标准

- 用户无需操作 git，即可切换到历史稳定版本。
- 发布流水线可区分 canary 与 stable。
- README 提供可执行、可复制的升级/回滚命令。
- `snapagent --version` 与安装版本一致。

## 8. 实施范围（本轮）

- 新增 release workflow（canary + stable）。
- 调整 compose 支持按 tag 运行镜像。
- 统一版本读取来源。
- 补充 README 的版本切换/回滚说明。

