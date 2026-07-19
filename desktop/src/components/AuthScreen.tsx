import { useEffect, useState } from "react";
import { ArrowRight, Server, ShieldCheck } from "lucide-react";
import { api, ApiError } from "../lib/api";
import type { TokenPair } from "../types";

interface Props {
  onAuthenticated: (tokens: TokenPair) => Promise<void>;
}

export function AuthScreen({ onAuthenticated }: Props) {
  const [apiUrl, setApiUrl] = useState(api.apiUrl);
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [username, setUsername] = useState("owner");
  const [password, setPassword] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function inspectServer() {
    api.setApiUrl(apiUrl);
    setError("");
    try {
      const state = await api.request<{ setup_required: boolean }>("/auth/setup", { skipAuth: true });
      setSetupRequired(state.setup_required);
    } catch (reason) {
      setSetupRequired(null);
      setError(reason instanceof Error ? reason.message : "Сервер недоступен");
    }
  }

  useEffect(() => {
    void inspectServer();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const tokens = await api.request<TokenPair>(setupRequired ? "/auth/setup" : "/auth/login", {
        method: "POST",
        skipAuth: true,
        headers: setupRequired && setupToken ? { "X-Setup-Token": setupToken } : undefined,
        body: { username, password },
      });
      await onAuthenticated(tokens);
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 0
          ? "Нет соединения с сервером"
          : reason instanceof Error
            ? reason.message
            : "Ошибка входа",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-brand">
        <div className="brand-mark large">T</div>
        <p className="eyebrow">PERSONAL OPERATING SYSTEM</p>
        <h1>Все проекты.<br />Один ясный контекст.</h1>
        <p className="auth-lead">
          Задачи, Markdown-vault, Telegram-тикеты и Codex живут в одном рабочем пространстве.
        </p>
        <div className="auth-points">
          <span><ShieldCheck size={17} /> Один владелец и scoped-токены</span>
          <span><Server size={17} /> Глобальный сервер, локальный vault</span>
        </div>
      </section>
      <form className="auth-card" onSubmit={submit}>
        <p className="eyebrow">{setupRequired ? "ПЕРВЫЙ ЗАПУСК" : "С ВОЗВРАЩЕНИЕМ"}</p>
        <h2>{setupRequired ? "Создать владельца" : "Войти в Taskman"}</h2>
        <label>
          Адрес сервера
          <div className="inline-field">
            <input value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} />
            <button className="icon-button" type="button" onClick={inspectServer} title="Проверить сервер">
              <Server size={17} />
            </button>
          </div>
        </label>
        <label>
          Логин
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
        </label>
        <label>
          Пароль
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={setupRequired ? "new-password" : "current-password"}
          />
        </label>
        {setupRequired && (
          <label>
            Setup token <span className="muted">(если задан на сервере)</span>
            <input value={setupToken} onChange={(event) => setSetupToken(event.target.value)} />
          </label>
        )}
        {error && <div className="error-banner">{error}</div>}
        <button className="primary-button wide" disabled={loading || setupRequired === null}>
          {loading ? "Подключение…" : setupRequired ? "Создать пространство" : "Войти"}
          <ArrowRight size={17} />
        </button>
      </form>
    </main>
  );
}
