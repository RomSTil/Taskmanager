import { useEffect, useState, type FormEvent } from "react";

import { ApiError, type TaskmanApi } from "./api";
import type { ApiToken, User, UserAccessLog, UserRole } from "./types";

const roleLabels: Record<UserRole, string> = {
  administrator: "Администратор",
  supervisor: "Руководитель",
  worker: "Сотрудник",
};

const transliteration: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "yo", ж: "zh", з: "z", и: "i", й: "y",
  к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f",
  х: "kh", ц: "ts", ч: "ch", ш: "sh", щ: "shch", ы: "y", э: "e", ю: "yu", я: "ya", ь: "", ъ: "",
};

function usernameFromName(name: string): string {
  return Array.from(name.toLowerCase()).map((letter) => transliteration[letter] ?? letter).join("")
    .replace(/[^a-z0-9]+/g, ".").replace(/^\.+|\.+$/g, "").slice(0, 120);
}

function createPassword(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const values = crypto.getRandomValues(new Uint32Array(8));
  return Array.from(values, (value) => alphabet[value % alphabet.length]).join("");
}

type SettingsViewProps = {
  api: TaskmanApi;
  user: User;
  users: User[];
  onChanged: () => Promise<void>;
};

function errorText(reason: unknown): string {
  return reason instanceof ApiError || reason instanceof Error ? reason.message : "Не удалось сохранить изменения";
}

export default function SettingsView({ api, user, users, onChanged }: SettingsViewProps) {
  const [name, setName] = useState(user.name);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [newUser, setNewUser] = useState({ name: "", username: "", password: "", role: "worker" as UserRole });
  const [accessLogs, setAccessLogs] = useState<UserAccessLog[]>([]);
  const [mcpTokens, setMcpTokens] = useState<ApiToken[]>([]);
  const [mcpToken, setMcpToken] = useState("");
  const [runnerToken, setRunnerToken] = useState("");
  const administrator = user.role === "administrator";

  useEffect(() => {
    if (!administrator) return;
    void Promise.all([api.listAccessLog(), api.listApiTokens()])
      .then(([logs, tokens]) => { setAccessLogs(logs); setMcpTokens(tokens.filter((token) => token.name.startsWith("MCP Bridge"))); })
      .catch((reason: unknown) => setError(errorText(reason)));
  }, [api, administrator]);

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      await api.updateMyProfile(name.trim());
      await onChanged();
      setMessage("Профиль сохранён.");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(target: User, role: UserRole) {
    setBusy(true); setError(""); setMessage("");
    try {
      await api.updateUserRole(target.id, role);
      await onChanged();
      setMessage(`Роль для ${target.name || target.username} обновлена.`);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  function updateNewUserName(value: string) {
    setNewUser((current) => ({ ...current, name: value, username: usernameFromName(value), password: createPassword() }));
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const created = await api.createUser({ ...newUser, name: newUser.name.trim(), username: newUser.username.trim() });
      await onChanged();
      setMessage(`Пользователь ${created.name} создан. Передайте пароль: ${newUser.password}`);
      setNewUser({ name: "", username: "", password: "", role: "worker" });
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createMcpToken() {
    setBusy(true); setError(""); setMessage(""); setMcpToken("");
    try {
      const created = await api.createApiToken({
        name: `MCP Bridge ${new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date())}`,
        scopes: ["projects:read", "projects:write", "tasks:read", "tasks:write", "notes:read", "notes:write"],
      });
      setMcpToken(created.token);
      setMcpTokens((current) => [created, ...current]);
      setMessage("MCP-токен создан. Скопируйте его сейчас: повторно он не отображается.");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createRunnerToken() {
    setBusy(true); setError(""); setMessage(""); setRunnerToken("");
    try {
      const created = await api.createApiToken({
        name: `Codex Runner ${new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date())}`,
        scopes: ["agent_operations:read", "agent_operations:write"],
      });
      setRunnerToken(created.token);
      setMcpTokens((current) => [created, ...current]);
      setMessage("Токен Codex Runner создан. Скопируйте его сейчас: повторно он не отображается.");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function revokeMcpToken(token: ApiToken) {
    setBusy(true); setError(""); setMessage("");
    try {
      await api.revokeApiToken(token.id);
      setMcpTokens((current) => current.filter((item) => item.id !== token.id));
      setMessage("MCP-токен отозван.");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-page">
      <div className="settings-intro"><p className="eyebrow">НАСТРОЙКИ</p><h2>Профиль и доступ</h2><p>Имя показывается в рабочем пространстве. Роли управляют уровнем доступа пользователей.</p></div>
      {error && <div className="error-message page-error">{error}</div>}
      {message && <div className="integration-success">{message}</div>}

      <div className="settings-grid">
        <form className="settings-card" onSubmit={saveProfile}>
          <div><p className="eyebrow">МОЙ ПРОФИЛЬ</p><h3>{user.name || user.username}</h3></div>
          <label>Имя<input value={name} onChange={(event) => setName(event.currentTarget.value)} maxLength={120} required /></label>
          <div className="settings-readonly"><span>Username</span><strong>{user.username}</strong></div>
          <div className="settings-readonly"><span>Роль</span><strong>{roleLabels[user.role]}</strong></div>
          <button className="primary-button" type="submit" disabled={busy || name.trim() === user.name}>Сохранить</button>
        </form>

        <section className="settings-card">
          <div><p className="eyebrow">РОЛИ</p><h3>Уровни доступа</h3></div>
          <dl className="role-guide"><div><dt>Администратор</dt><dd>Управляет пользователями, ролями и настройками.</dd></div><div><dt>Руководитель</dt><dd>Координирует работу и контролирует задачи.</dd></div><div><dt>Сотрудник</dt><dd>Работает со своими задачами и материалами.</dd></div></dl>
        </section>
      </div>

      {administrator && <form className="settings-card settings-create-user" onSubmit={createUser}>
        <div><p className="eyebrow">НОВЫЙ ПОЛЬЗОВАТЕЛЬ</p><h3>Создать доступ</h3><p className="form-hint">Введите имя — username и пароль заполнятся автоматически. Их можно отредактировать перед созданием.</p></div>
        <div className="settings-create-grid">
          <label>Имя<input value={newUser.name} onChange={(event) => updateNewUserName(event.currentTarget.value)} placeholder="Например, Света" maxLength={120} required /></label>
          <label>Username<input value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.currentTarget.value })} minLength={3} maxLength={120} pattern="[A-Za-z0-9_.-]+" required /></label>
          <label>Пароль<input value={newUser.password} onChange={(event) => setNewUser({ ...newUser, password: event.currentTarget.value })} minLength={8} maxLength={256} required /></label>
          <label>Роль<select value={newUser.role} onChange={(event) => setNewUser({ ...newUser, role: event.currentTarget.value as UserRole })}>{Object.entries(roleLabels).map(([role, label]) => <option value={role} key={role}>{label}</option>)}</select></label>
        </div>
        <button className="primary-button" type="submit" disabled={busy}>Создать пользователя</button>
      </form>}

      <section className="settings-card settings-users">
        <div><p className="eyebrow">КОМАНДА</p><h3>Пользователи</h3></div>
        <div className="settings-user-list">
          {users.map((member) => <div className="settings-user-row" key={member.id}><div><strong>{member.name || member.username}</strong><span>@{member.username}</span></div>{administrator ? <select aria-label={`Роль ${member.username}`} value={member.role} disabled={busy} onChange={(event) => void changeRole(member, event.currentTarget.value as UserRole)}>{Object.entries(roleLabels).map(([role, label]) => <option value={role} key={role}>{label}</option>)}</select> : <span className="role-badge">{roleLabels[member.role]}</span>}</div>)}
        </div>
        {!administrator && <p className="form-hint">Роли изменяет администратор.</p>}
      </section>

      {administrator && <section className="settings-card settings-access-log">
        <div><p className="eyebrow">ЖУРНАЛ ДОСТУПА</p><h3>Входы и выходы</h3></div>
        {accessLogs.length ? <div className="access-log-list">{accessLogs.map((item) => <div className="access-log-row" key={item.id}><span className={`access-log-action ${item.action}`}>{item.action === "login" ? "Вход" : "Выход"}</span><div><strong>{item.user.name || item.user.username}</strong><span>@{item.user.username} · {item.client_host}</span></div><time dateTime={item.created_at}>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.created_at))}</time></div>)}</div> : <p className="form-hint">Записей пока нет.</p>}
      </section>}

      {administrator && <section className="settings-card settings-mcp">
        <div><p className="eyebrow">MCP BRIDGE</p><h3>Подключение Codex</h3><p className="form-hint">Создайте отдельный токен для MCP. Он получает доступ к проектам, задачам и заметкам, но не к административным настройкам.</p></div>
        <div className="mcp-connection"><span>Адрес сервера</span><code>{api.baseUrl}</code></div>
        <button className="primary-button" type="button" onClick={() => void createMcpToken()} disabled={busy}>Создать MCP-токен</button>
        {mcpToken && <div className="integration-secret"><strong>Токен — скопируйте сейчас:</strong><code>{mcpToken}</code><span>После закрытия страницы увидеть его снова нельзя.</span><strong>Команда подключения:</strong><code>{`taskman-mcp login --url ${api.baseUrl} --token ${mcpToken}`}</code></div>}
        <div className="mcp-token-list">{mcpTokens.length ? mcpTokens.map((token) => <div className="settings-user-row" key={token.id}><div><strong>{token.name}</strong><span>Создан {new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(token.created_at))}</span></div><button className="text-button danger" type="button" disabled={busy} onClick={() => void revokeMcpToken(token)}>Отозвать</button></div>) : <p className="form-hint">Активных MCP-токенов нет.</p>}</div>
      </section>}

      {administrator && <section className="settings-card settings-mcp">
        <div><p className="eyebrow">CODEX RUNNER</p><h3>Основной ПК</h3><p className="form-hint">Создайте отдельный токен для подключения ПК. Он даёт доступ только к очереди и управлению запусками агентов.</p></div>
        <div className="mcp-connection"><span>Адрес API</span><code>{api.baseUrl}</code></div>
        <button className="primary-button" type="button" onClick={() => void createRunnerToken()} disabled={busy}>Создать токен Runner</button>
        {runnerToken && <div className="integration-secret"><strong>Токен — скопируйте сейчас:</strong><code>{runnerToken}</code><span>После закрытия страницы увидеть его снова нельзя.</span><strong>Команда подключения:</strong><code>{`taskman-agent-runner register --api-url ${api.baseUrl} --name "Основной ПК" --workspace C:\\projects\\Taskmanager`}</code></div>}
      </section>}
    </section>
  );
}
