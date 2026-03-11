#!/usr/bin/env node
import { Command } from "commander";
import inquirer from "inquirer";
import { execSync } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const PLUGIN_NAME = "openclaw-cozeloop-trace";
const PACKAGE_PATH = "@cozeloop/openclaw-cozeloop-trace";
const COZELOOP_ENDPOINT = "https://api.coze.cn/v1/loop/opentelemetry";

type OpenClawConfig = {
  plugins?: {
    allow?: string[];
    entries?: Record<string, { enabled?: boolean; config?: Record<string, unknown> }>;
  };
  installs?: Record<string, { installPath?: string }>;
};

function getOpenClawDir(): string {
  return process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), ".openclaw");
}

function getConfigPath(): string {
  return path.join(getOpenClawDir(), "openclaw.json");
}

function getExtensionsDir(): string {
  return path.join(getOpenClawDir(), "extensions");
}

async function readConfig(): Promise<OpenClawConfig> {
  try {
    const raw = await fs.readFile(getConfigPath(), "utf8");
    return JSON.parse(raw) as OpenClawConfig;
  } catch (error) {
    const err = error as { code?: string };
    if (err.code === "ENOENT") {
      return {};
    }
    throw error;
  }
}

async function writeConfig(config: OpenClawConfig): Promise<void> {
  const configPath = getConfigPath();
  await fs.mkdir(path.dirname(configPath), { recursive: true });
  await fs.writeFile(configPath, JSON.stringify(config, null, 2), "utf8");
}

function getPlatformCommand(command: string): string {
  if (process.platform === "win32" && (command === "openclaw" || command === "npm")) {
    return `${command}.cmd`;
  }
  return command;
}

function runCommand(command: string): void {
  execSync(command, { stdio: "inherit" });
}

function runCommandQuiet(command: string): string {
  return execSync(command, { encoding: "utf8" }).trim();
}

function normalizeAuthorization(token: string): string {
  const trimmed = token.trim();
  if (!trimmed) return "";
  const cleaned = trimmed.replace(/^(bearer|sat)\s+/i, "");
  return `Bearer ${cleaned}`;
}

async function collectPluginConfig(): Promise<{ authorization: string; workspaceId: string }> {
  const config = await readConfig();
  const existingEntry = config.plugins?.entries?.[PLUGIN_NAME];
  const existingConfig = existingEntry?.config || {};
  const existingAuthorization = typeof existingConfig.authorization === "string" ? existingConfig.authorization : "";
  const existingWorkspaceId = typeof existingConfig.workspaceId === "string" ? existingConfig.workspaceId : "";

  const answers = await inquirer.prompt([
    {
      name: "satToken",
      type: "password",
      message: "请输入服务访问令牌(sat_xxx)(服务访问令牌获取方式可参考：https://loop.coze.cn/open/docs/cozeloop/authentication-for-sdk#83f924a1):",
      mask: "*",
      validate: (input: string) => {
        if (input && input.trim()) return true;
        if (existingAuthorization) return true;
        return "服务访问令牌不能为空";
      },
    },
    {
      name: "workspaceId",
      type: "input",
      message: "请输入扣子罗盘空间id(空间id获取方式可参考：https://loop.coze.cn/open/docs/cozeloop/get_workspace_id_and_token):",
      default: existingWorkspaceId || undefined,
      validate: (input: string) => {
        if (input && input.trim()) return true;
        if (existingWorkspaceId) return true;
        return "空间id不能为空";
      },
    },
  ]);

  const rawToken = String(answers.satToken || "").trim();
  const authorization = rawToken ? normalizeAuthorization(rawToken) : normalizeAuthorization(existingAuthorization);
  const workspaceId = String(answers.workspaceId || existingWorkspaceId || "").trim();

  if (!authorization || !workspaceId) {
    throw new Error("服务访问令牌 或 空间id缺失");
  }

  return { authorization, workspaceId };
}

async function updateOpenClawConfig(pluginConfig: { authorization: string; workspaceId: string }): Promise<void> {
  const config = await readConfig();
  if (!config.plugins) config.plugins = {};
  if (!config.plugins.allow) config.plugins.allow = [];
  if (!config.plugins.allow.includes(PLUGIN_NAME)) {
    config.plugins.allow.push(PLUGIN_NAME);
  }
  if (!config.plugins.entries) config.plugins.entries = {};
  if (!config.plugins.entries[PLUGIN_NAME]) {
    config.plugins.entries[PLUGIN_NAME] = { enabled: true };
  }
  const entry = config.plugins.entries[PLUGIN_NAME];
  entry.enabled = true;
  const existing = entry.config && typeof entry.config === "object" ? entry.config : {};
  entry.config = {
    ...existing,
    authorization: pluginConfig.authorization,
    endpoint: COZELOOP_ENDPOINT,
    workspaceId: pluginConfig.workspaceId,
  };
  await writeConfig(config);
}

async function clearPluginConfig(): Promise<void> {
  const config = await readConfig();
  if (!config.plugins) return;
  if (config.plugins.entries && config.plugins.entries[PLUGIN_NAME]) {
    delete config.plugins.entries[PLUGIN_NAME];
  }
  if (config.plugins.allow) {
    config.plugins.allow = config.plugins.allow.filter((name) => name !== PLUGIN_NAME);
  }
  await writeConfig(config);
}

async function clearInstalledPlugin(): Promise<void> {
  const config = await readConfig();
  const installPath = config.installs?.[PLUGIN_NAME]?.installPath;
  if (installPath) {
    await fs.rm(installPath, { recursive: true, force: true });
    return;
  }
  const fallbackPath = path.join(getExtensionsDir(), PLUGIN_NAME);
  await fs.rm(fallbackPath, { recursive: true, force: true });
}

async function installPlugin(): Promise<void> {
  const openclawCmd = getPlatformCommand("openclaw");
  try {
    runCommandQuiet(`${openclawCmd} --version`);
  } catch {
    throw new Error("未检测到 OpenClaw CLI，请先安装 openclaw");
  }
  runCommand(`${openclawCmd} plugins install ${PACKAGE_PATH}`);
}

async function restartGateway(): Promise<void> {
  const openclawCmd = getPlatformCommand("openclaw");
  try {
    runCommand(`${openclawCmd} gateway restart`);
  } catch {
    console.log("网关重启失败，可稍后手动执行 openclaw gateway restart");
  }
}

async function handleInstall(): Promise<void> {
  const pluginConfig = await collectPluginConfig();
  await clearPluginConfig();
  await clearInstalledPlugin();
  await installPlugin();
  await updateOpenClawConfig(pluginConfig);
  await restartGateway();
  console.log("安装完成，openclaw-cozeloop-trace 已启用");
}

const program = new Command();
program.name("openclaw-cozeloop-trace-onboard-cli").version("0.1.0");
program
  .command("install", { isDefault: true })
  .description("一键安装 openclaw-cozeloop-trace 插件")
  .action(async () => {
    try {
      await handleInstall();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error(`安装失败: ${message}`);
      process.exit(1);
    }
  });

program.parse(process.argv);
