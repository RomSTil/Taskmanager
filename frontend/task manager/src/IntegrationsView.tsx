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

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function DirectAccountCard({
  account,
  refreshing,
  deleting,
  onRefresh,
  onDelete,
}: {
  account: DirectAccount;
  refreshing: boolean;
  deleting: boolean;
  onRefresh: (account: DirectAccount) => void;
  onDelete: (account: DirectAccount) => void;
}) {
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
      <div className="integration-card-actions">
        <button
          className="secondary-button integration-action"
          type="button"
          onClick={() => onRefresh(account)}
          disabled={refreshing || deleting || !account.enabled}
        >
          {refreshing ? "Проверяем…" : "Проверить сейчас"}
        </button>
        <button
          className="danger-button integration-action"
          type="button"
          onClick={() => onDelete(account)}
          disabled={refreshing || deleting}
        >
          {deleting ? "Удаляем…" : "Удалить аккаунт"}
        </button>
      </div>
    </article>
  );
}

function MaxBotCard({
  bot,
  deleting,
  onRegister,
  onDelete,
}: {
  bot: MaxBot;
  deleting: boolean;
  onRegister: (bot: MaxBot) => void;
  onDelete: (bot: MaxBot) => void;
}) {
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
      <div className="integration-card-actions">
        <button className="secondary-button integration-action" type="button" onClick={() => onRegister(bot)} disabled={deleting}>Перерегистрировать webhook</button>
        <button className="danger-button integration-action" type="button" onClick={() => onDelete(bot)} disabled={deleting}>
          {deleting ? "Удаляем…" : "Удалить бота"}
        </button>
      </div>
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
  const [refreshingAccountId, setRefreshingAccountId] = useState<string | null>(null);
  const [deletingConnectionId, setDeletingConnectionId] = useState<string | null>(null);
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

  async function refreshDirectAccount(account: DirectAccount) {
    setRefreshingAccountId(account.id);
    setError("");
    setMessage(`Проверяем аккаунт «${account.name}»…`);
    try {
      let job = await api.createDirectJob(account.id, "balance_check");
      for (let attempt = 0; attempt < 30 && job.status !== "completed" && job.status !== "failed"; attempt += 1) {
        await wait(2000);
        job = await api.getDirectJob(job.id);
        if (job.status === "pending" && job.error && job.error !== "Yandex Direct report is pending") break;
      }
      await load();
      if (job.status === "completed") {
        setMessage(`Данные аккаунта «${account.name}» обновлены.`);
      } else if (job.status === "failed" || job.error) {
        throw new Error(job.error || "Проверка Яндекс Директа завершилась с ошибкой");
      } else {
        setMessage(`Проверка аккаунта «${account.name}» продолжается в фоне. Обнови страницу чуть позже.`);
      }
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setRefreshingAccountId(null);
    }
  }

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

  async function deleteDirectAccount(account: DirectAccount) {
    if (!window.confirm(`Удалить подключение Яндекс Директа «${account.name}»? Отменить это действие будет нельзя.`)) return;
    setDeletingConnectionId(account.id);
    setError("");
    setMessage("");
    try {
      await api.deleteDirectAccount(account.id);
      setAccounts((current) => current.filter((item) => item.id !== account.id));
      setMessage(`Подключение Яндекс Директа «${account.name}» удалено.`);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setDeletingConnectionId(null);
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

  async function deleteMaxBot(bot: MaxBot) {
    if (!window.confirm(`Удалить MAX-бота «${bot.name}»? Его webhook и настройки будут удалены без возможности восстановления.`)) return;
    setDeletingConnectionId(bot.id);
    setError("");
    setMessage("");
    try {
      await api.deleteMaxBot(bot.id);
      setBots((current) => current.filter((item) => item.id !== bot.id));
      setMessage(`MAX-бот «${bot.name}» удалён.`);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setDeletingConnectionId(null);
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
          <div className="integration-list">{loading ? <div className="loading-line">Загружаем аккаунты…</div> : accounts.length ? accounts.map((account) => <DirectAccountCard account={account} refreshing={refreshingAccountId === account.id} deleting={deletingConnectionId === account.id} onRefresh={refreshDirectAccount} onDelete={deleteDirectAccount} key={account.id} />) : <div className="integration-empty">Аккаунт ещё не подключён.</div>}</div>
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
          <div className="integration-list">{loading ? <div className="loading-line">Загружаем ботов…</div> : bots.length ? bots.map((bot) => <MaxBotCard bot={bot} deleting={deletingConnectionId === bot.id} onRegister={registerWebhook} onDelete={deleteMaxBot} key={bot.id} />) : <div className="integration-empty">MAX-бот ещё не подключён.</div>}</div>
        </div>
      </div>
    </section>
  );
}
