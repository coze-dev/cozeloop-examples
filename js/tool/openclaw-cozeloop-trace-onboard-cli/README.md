## 一键安装（Onboard）

在安装过程中无需跳转登录，会在命令行交互中要求输入 SAT Token 和 CozeLoop Workspace ID，并自动写入 OpenClaw 配置与启用插件。

```bash
npm i -g openclaw-cozeloop-trace-onboard-cli
openclaw-cozeloop-trace-onboard-cli install
```

默认会写入 `~/.openclaw/openclaw.json`（或由 `OPENCLAW_STATE_DIR` 指定目录）：
- `plugins.allow` 追加 `openclaw-cozeloop-trace`
- `plugins.entries["openclaw-cozeloop-trace"].enabled = true`
- `plugins.entries["openclaw-cozeloop-trace"].config.authorization`（自动补全为 `SAT ...`）
- `plugins.entries["openclaw-cozeloop-trace"].config.workspaceId`

安装后会尝试执行 `openclaw gateway restart`。
