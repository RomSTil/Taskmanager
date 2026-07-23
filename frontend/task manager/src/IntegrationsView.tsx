import { useEffect, useState, type FormEvent } from "react";
import { ApiError, type TaskmanApi } from "./api";
import type { DirectAccount, MaxBot, MaxBotCreated } from "./types";

type IntegrationsViewProps = { api: TaskmanApi };

const emptyDirectForm = {
  name: "",
  token: "",
  client_login: "",
  balance_threshold: "5000",
  days_left_threshold: "3",
  anomaly_ratio: "2",
  monitor_interval_minutes: "30",
};

const emptyMaxForm = { name: "", token: "", allowlist: "" };

function displayDate(value: string | null): string {
  if (!value) return "ещё не запускался";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function errorText(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return reason instanceof Error ? reason.message : "Не удалось выполнить операцию";
}

function parseAllowlist(value: string): number[] {
  return value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isSafeInteger(item) && item > 0);
}

function DirectAccountCard({ account }: { account: DirectAccount }) {
  return (
    <article className="integration-card">
      <div className="integration-card-heading">
        <div><span className="integration-icon yandex-icon">Я</span><div><strong>{account.name}</strong><small>Токен: {account.token_hint}</small></div></div>
        <span className={`integration-status ${account.enabled ? "online" : "offline"}`}>{account.enabled ? "Активен" : "Выключен"}</span>
      </div>
      <div className="integration-details">
        <span>Порог баланса <strong>{account.balance_threshold}</strong></span>
        <span>Прогноз <strong>{account.days_left_threshold} дн.</strong></span>
        <span>Проверка <strong>каждые {account.monitor_interval_minutes} мин.</strong></span>
      </div>
      <p className="integration-meta">Последняя проверка: {displayDate(account.last_checked_at)}</p>
      {account.last_error && <p className="integration-error">Последняя ошибка: {account.last_error}</p>}
    </article>
  );
}

function MaxBotCard({ bot, onRegister }: { bot: MaxBot; onRegister: (bot: MaxBot) => void }) {
  return (
    <article className="integration-card">
      <div className="integration-card-heading">
        <div><span className="integration-icon max-icon">M</span><div><strong>{bot.name}</strong><small>Токен: {bot.token_hint}</small></div></div>
        <span className={`integration-status ${bot.enabled ? "online" : "offline"}`}>{bot.enabled ? "Активен" : "Выключен"}</span>
      </div>
      <div className="integration-details integration-details-stack">
        <span>Webhook <code>{bot.webhook_url}</code></span>
        <span>Получатель <strong>{bot.target_id ? `${bot.target_type}: ${bot.target_id}` : "определится после /start"}</strong></span>
        <span>Ограничение <strong>{bot.allowlist.length ? `${bot.allowlist.length} пользователей` : "нет allowlist"}</strong></span>
      </div>
      {bot.last_error && <p className="integration-error">Последняя ошибка: {bot.last_error}</p>}
      <button className="secondary-button integration-action" type="button" onClick={() => onRegister(bot)}>Перерегистрировать webhook</button>
    </article>
  );
}

export default function IntegrationsView({ api }: IntegrationsViewProps) {
  const [accounts, setAccounts] = useState<DirectAccount[]>([]);
  const [bots, setBots] = useState<MaxBot[]>([]);
  const [directForm, setDirectForm] = useState(emptyDirectForm);
  const [maxForm, setMaxForm] = useState(emptyMaxForm);
  const [maxSecret, setMaxSecret] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextAccounts, nextBots] = await Promise.all([api.listDirectAccounts(), api.listMaxBots()]);
      setAccounts(nextAccounts);
      setBots(nextBots);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [api]);

  async function submitDirect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.createDirectAccount({
        name: directForm.name.trim(),
        token: directForm.token,
        client_login: directForm.client_login.trim() || undefined,
        balance_threshold: Number(directForm.balance_threshold),
        days_left_threshold: Number(directForm.days_left_threshold),
        anomaly_ratio: Number(directForm.anomaly_ratio),
        monitor_interval_minutes: Number(directForm.monitor_interval_minutes),
      });
      setDirectForm(emptyDirectForm);
      setMessage("Аккаунт Яндекс Директа добавлен. Первый сбор данных выполнит platform-worker.");
      await load();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function registerWebhook(bot: MaxBot) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.registerMaxWebhook(bot.id);
      setMessage(`Webhook для «${bot.name}» зарегистрирован. Открой бота в MAX и отправь /start.`);
      await load();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function submitMax(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    setMaxSecret("");
    try {
      const created: MaxBotCreated = await api.createMaxBot({
        name: maxForm.name.trim(),
        token: maxForm.token,
        allowlist: parseAllowlist(maxForm.allowlist),
      });
      let registrationMessage = `Бот «${created.name}» добавлен.`;
      try {
        await api.registerMaxWebhook(created.id);
        registrationMessage += " Webhook зарегистрирован.";
      } catch (reason) {
        registrationMessage += ` Webhook пока не зарегистрирован: ${errorText(reason)}`;
      }
      setMaxSecret(created.webhook_secret);
      setMaxForm(emptyMaxForm);
      setMessage(`${registrationMessage} Сохрани секрет webhook и отправь боту /start в MAX.`);
      await load();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="integrations-page">
      <div className="integrations-intro">
        <div><p className="eyebrow">ПОДКЛЮЧЕНИЯ</p><h2>Яндекс Директ и MAX</h2><p>Добавь рекламный аккаунт и transport-бота. После регистрации webhook команды и алерты будут приходить прямо в MAX.</p></div>
        <button className="text-button" type="button" onClick={() => void load()} disabled={loading}>Обновить</button>
      </div>
      {error && <div className="error-message page-error">{error}</div>}
      {message && <div className="integration-success">{message}</div>}
      {maxSecret && <div className="integration-secret"><strong>Секрет webhook — сохрани сейчас:</strong><code>{maxSecret}</code><span>Он показывается только один раз.</span></div>}

      <div className="integration-columns">
        <div className="integration-column">
          <div className="section-heading"><div><p className="eyebrow">PROVIDER</p><h3>Яндекс Директ</h3></div></div>
          <form className="integration-form" onSubmit={submitDirect}>
            <label>Название аккаунта<input value={directForm.name} onChange={(event) => setDirectForm({ ...directForm, name: event.currentTarget.value })} placeholder="Основной кабинет" required /></label>
            <label>OAuth-токен Яндекса<input type="password" value={directForm.token} onChange={(event) => setDirectForm({ ...directForm, token: event.currentTarget.value })} placeholder="Вставь токен из OAuth" minLength={20} required /></label>
            <label>Client-Login <span className="muted">для агентского аккаунта</span><input value={directForm.client_login} onChange={(event) => setDirectForm({ ...directForm, client_login: event.currentTarget.value })} placeholder="необязательно" /></label>
            <div className="integration-form-grid">
              <label>Порог баланса<input type="number" min="0" step="0.01" value={directForm.balance_threshold} onChange={(event) => setDirectForm({ ...directForm, balance_threshold: event.currentTarget.value })} /></label>
              <label>Дней до бюджета<input type="number" min="0" step="0.1" value={directForm.days_left_threshold} onChange={(event) => setDirectForm({ ...directForm, days_left_threshold: event.currentTarget.value })} /></label>
              <label>Интервал, минут<input type="number" min="5" max="1440" value={directForm.monitor_interval_minutes} onChange={(event) => setDirectForm({ ...directForm, monitor_interval_minutes: event.currentTarget.value })} /></label>
            </div>
            <button className="primary-button" type="submit" disabled={busy}>Добавить аккаунт</button>
          </form>
          <div className="integration-list">{loading ? <div className="loading-line">Загружаем аккаунты…</div> : accounts.length ? accounts.map((account) => <DirectAccountCard account={account} key={account.id} />) : <div className="integration-empty">Аккаунт ещё не подключён.</div>}</div>
        </div>

        <div className="integration-column">
          <div className="section-heading"><div><p className="eyebrow">TRANSPORT</p><h3>Бот в MAX</h3></div></div>
          <form className="integration-form" onSubmit={submitMax}>
            <label>Название бота<input value={maxForm.name} onChange={(event) => setMaxForm({ ...maxForm, name: event.currentTarget.value })} placeholder="Direct alerts" required /></label>
            <label>Bot token MAX<input type="password" value={maxForm.token} onChange={(event) => setMaxForm({ ...maxForm, token: event.currentTarget.value })} placeholder="Токен из кабинета MAX" minLength={20} required /></label>
            <label>Allowlist <span className="muted">ID пользователей через запятую</span><input value={maxForm.allowlist} onChange={(event) => setMaxForm({ ...maxForm, allowlist: event.currentTarget.value })} placeholder="пусто — только для первого теста" /></label>
            <p className="form-hint">После создания приложение автоматически зарегистрирует webhook. Сервер должен быть доступен по публичному HTTPS-адресу.</p>
            <button className="primary-button" type="submit" disabled={busy}>Подключить MAX</button>
          </form>
          <div className="integration-list">{loading ? <div className="loading-line">Загружаем ботов…</div> : bots.length ? bots.map((bot) => <MaxBotCard bot={bot} onRegister={registerWebhook} key={bot.id} />) : <div className="integration-empty">MAX-бот ещё не подключён.</div>}</div>
        </div>
      </div>
    </section>
  );
}
