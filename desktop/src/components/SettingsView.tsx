import { open } from "@tauri-apps/plugin-dialog";
import { Bot, CheckCircle2, Copy, FolderOpen, KeyRound, Link, Plus, RefreshCw, Server } from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import { isTauri } from "../lib/platform";
import { syncVault } from "../lib/vaultSync";
import type { Project, TelegramBot } from "../types";

interface Props {
  projects: Project[];
  bots: TelegramBot[];
  onRefreshBots: () => void;
}

export function SettingsView({ projects, bots, onRefreshBots }: Props) {
  const [vault, setVault] = useState(localStorage.getItem("taskman:vault") || "");
  const [syncMessage, setSyncMessage] = useState("");
  const [tokenName, setTokenName] = useState("Codex on Windows");
  const [createdToken, setCreatedToken] = useState("");
  const [botName, setBotName] = useState("");
  const [botToken, setBotToken] = useState("");
  const [botProject, setBotProject] = useState("");
  const [allowlist, setAllowlist] = useState("");

  async function chooseVault() {
    if (!isTauri()) return;
    const selected = await open({ directory: true, multiple: false, title: "Выберите Taskman vault" });
    if (typeof selected === "string") {
      setVault(selected);
      localStorage.setItem("taskman:vault", selected);
    }
  }

  async function runSync() {
    if (!vault) return;
    setSyncMessage("Синхронизация…");
    try {
      const result = await syncVault(vault);
      setSyncMessage(`Отправлено ${result.pushed}, получено ${result.pulled}, конфликтов ${result.conflicts}`);
    } catch (error) {
      setSyncMessage(error instanceof Error ? error.message : "Ошибка синхронизации");
    }
  }

  async function createMcpToken() {
    const result = await api.request<{ token: string }>("/auth/tokens", {
      method: "POST",
      body: {
        name: tokenName,
        scopes: ["projects:read", "projects:write", "tasks:read", "tasks:write", "notes:read", "notes:write"],
      },
    });
    setCreatedToken(result.token);
  }

  async function addBot(event: React.FormEvent) {
    event.preventDefault();
    await api.request("/integrations/telegram/bots", {
      method: "POST",
      body: {
        name: botName,
        token: botToken,
        project_id: botProject || null,
        allowlist: allowlist.split(/[ ,]+/).filter(Boolean).map(Number),
      },
    });
    setBotName(""); setBotToken(""); setAllowlist("");
    onRefreshBots();
  }

  const configSnippet = `[mcp_servers.taskman]\ncommand = "taskman-mcp"\nargs = ["serve"]\ndefault_tools_approval_mode = "writes"`;
  return (
    <div className="settings-view workspace-view">
      <header className="page-header"><div><p className="eyebrow">SYSTEM</p><h1>Настройки</h1></div></header>
      <div className="settings-grid">
        <section className="settings-card"><header><FolderOpen size={19} /><div><h2>Markdown vault</h2><p>Локальная папка для офлайн-работы</p></div></header><label>Путь<div className="inline-field"><input value={vault} onChange={(event) => setVault(event.target.value)} placeholder="C:\\Users\\me\\Taskman" /><button className="icon-button" onClick={chooseVault}><FolderOpen size={16} /></button></div></label><button className="secondary-button" onClick={runSync} disabled={!vault}><RefreshCw size={16} /> Синхронизировать</button>{syncMessage && <p className="settings-message">{syncMessage}</p>}</section>
        <section className="settings-card"><header><KeyRound size={19} /><div><h2>Codex MCP</h2><p>Локальный мост со scoped-доступом</p></div></header><label>Название устройства<input value={tokenName} onChange={(event) => setTokenName(event.target.value)} /></label><button className="secondary-button" onClick={createMcpToken}><Plus size={16} /> Создать токен</button>{createdToken && <div className="secret-once"><b>Скопируйте сейчас — повторно токен не показывается.</b><code>{createdToken}</code><button onClick={() => navigator.clipboard.writeText(createdToken)}><Copy size={15} /> Копировать</button></div>}<pre>{configSnippet}</pre><p className="command-line">taskman-mcp login --url {api.apiUrl}</p></section>
        <section className="settings-card wide-card"><header><Bot size={19} /><div><h2>Telegram-боты</h2><p>Тикеты, команды и inline-управление</p></div></header><div className="bot-list">{bots.map((item) => <article key={item.id}><span className={item.enabled ? "bot-status online" : "bot-status"} /><div><b>{item.name}</b><small>{item.token_hint} · {item.webhook_url}</small>{item.last_error && <em>{item.last_error}</em>}</div><button className="secondary-button compact" onClick={async () => { await api.request(`/integrations/telegram/bots/${item.id}/register-webhook`, { method: "POST" }); onRefreshBots(); }}><Link size={14} /> Webhook</button></article>)}</div><form className="bot-form" onSubmit={addBot}><input placeholder="Название" value={botName} onChange={(event) => setBotName(event.target.value)} required /><input placeholder="Bot token" value={botToken} onChange={(event) => setBotToken(event.target.value)} required /><select value={botProject} onChange={(event) => setBotProject(event.target.value)}><option value="">Без проекта</option>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select><input placeholder="Allowlist ID через пробел" value={allowlist} onChange={(event) => setAllowlist(event.target.value)} /><button className="primary-button compact"><Plus size={15} /> Добавить</button></form></section>
        <section className="settings-card"><header><Server size={19} /><div><h2>Сервер</h2><p>Текущая точка подключения</p></div></header><code>{api.apiUrl}</code><p className="healthy"><CheckCircle2 size={15} /> Авторизован и доступен</p></section>
      </div>
    </div>
  );
}
