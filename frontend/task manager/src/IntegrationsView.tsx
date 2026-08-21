import { useEffect, useState, type FormEvent } from "react";
import { ApiError, type TaskmanApi } from "./api";
import type { DirectAccount, MarketAccount, MarketOrder, MaxAccessRequest, MaxBot, MaxBotCreated, OzonAccount } from "./types";

type IntegrationsViewProps = { api: TaskmanApi };

const emptyMarketForm = { name: "", campaign_id: "", api_key: "", poll_interval_seconds: "60" };
const emptyDirectForm = { name: "", token: "", client_login: "", balance_threshold: "5000", days_left_threshold: "3", anomaly_ratio: "2", monitor_interval_minutes: "30" };
const emptyMaxForm = { name: "", token: "", integration: "market" as "market" | "direct", allowlist: "" };
const emptyOzonForm = {
  name: "",
  client_id: "",
  api_key: "",
  poll_interval_minutes: "1",
};

function displayDate(value: string | null): string {
  if (!value) return "ещё не запускалась";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function errorText(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return reason instanceof Error ? reason.message : "Не удалось выполнить операцию";
}

function parseAllowlist(value: string): number[] {
  return value.split(",").map((item) => Number(item.trim())).filter((item) => Number.isSafeInteger(item) && item > 0);
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function packStateLabel(order: MarketOrder): string {
  if (order.pack_state === "packed") return "Готов к отправке";
  if (order.pack_state === "pending") return "Передаём в Маркет";
  if (order.pack_state === "failed") return "Ошибка";
  return "Ждёт сборщика";
}

function MarketAccountCard({ account, busy, onSync, onDelete }: { account: MarketAccount; busy: boolean; onSync: (account: MarketAccount) => void; onDelete: (account: MarketAccount) => void }) {
  return <article className="integration-card">
    <div className="integration-card-heading">
      <div><span className="integration-icon market-icon">M</span><div><strong>{account.name}</strong><small>Campaign ID: {account.campaign_id}</small></div></div>
      <span className={`integration-status ${account.enabled ? "online" : "offline"}`}>{account.enabled ? "Активен" : "Выключен"}</span>
    </div>
    <div className="integration-details"><span>API-ключ <strong>{account.api_key_hint}</strong></span><span>Проверка <strong>каждые {account.poll_interval_seconds} сек.</strong></span></div>
    <p className="integration-meta">Последняя синхронизация: {displayDate(account.last_polled_at)}</p>
    {account.last_error && <p className="integration-error">Последняя ошибка: {account.last_error}</p>}
    <div className="integration-card-actions">
      <button className="secondary-button integration-action" type="button" onClick={() => onSync(account)} disabled={busy || !account.enabled}>{busy ? "Синхронизируем…" : "Получить заказы"}</button>
      <button className="danger-button integration-action" type="button" onClick={() => onDelete(account)} disabled={busy}>Удалить магазин</button>
    </div>
  </article>;
}

function DirectAccountCard({ account, refreshing, deleting, onRefresh, onDelete }: { account: DirectAccount; refreshing: boolean; deleting: boolean; onRefresh: (account: DirectAccount) => void; onDelete: (account: DirectAccount) => void }) {
  return <article className="integration-card">
    <div className="integration-card-heading"><div><span className="integration-icon yandex-icon">Я</span><div><strong>{account.name}</strong><small>Токен: {account.token_hint}</small></div></div><span className={`integration-status ${account.enabled ? "online" : "offline"}`}>{account.enabled ? "Активен" : "Выключен"}</span></div>
    <div className="integration-details"><span>Порог баланса <strong>{account.balance_threshold}</strong></span><span>Прогноз <strong>{account.days_left_threshold} дн.</strong></span><span>Проверка <strong>каждые {account.monitor_interval_minutes} мин.</strong></span></div>
    <p className="integration-meta">Последняя проверка: {displayDate(account.last_checked_at)}</p>
    {account.last_error && <p className="integration-error">Последняя ошибка: {account.last_error}</p>}
    <div className="integration-card-actions"><button className="secondary-button integration-action" type="button" onClick={() => onRefresh(account)} disabled={refreshing || deleting || !account.enabled}>{refreshing ? "Проверяем…" : "Проверить сейчас"}</button><button className="danger-button integration-action" type="button" onClick={() => onDelete(account)} disabled={refreshing || deleting}>{deleting ? "Удаляем…" : "Удалить аккаунт"}</button></div>
  </article>;
}

function MaxBotCard({ bot, deleting, onRegister, onDelete }: { bot: MaxBot; deleting: boolean; onRegister: (bot: MaxBot) => void; onDelete: (bot: MaxBot) => void }) {
  return <article className="integration-card">
    <div className="integration-card-heading"><div><span className="integration-icon max-icon">M</span><div><strong>{bot.name}</strong><small>Токен: {bot.token_hint}</small></div></div><span className={`integration-status ${bot.enabled ? "online" : "offline"}`}>{bot.enabled ? "Активен" : "Выключен"}</span></div>
    <div className="integration-details integration-details-stack"><span>Назначение <strong>{bot.integration === "market" ? "Заказы маркетплейсов" : "Аналитика Директа"}</strong></span><span>Webhook <code>{bot.webhook_url}</code></span><span>Получатель <strong>{bot.target_id ? `${bot.target_type}: ${bot.target_id}` : "определится после /start"}</strong></span><span>Доступ <strong>{bot.allowlist.length ? `${bot.allowlist.length} пользователей` : "заявки через /start"}</strong></span></div>
    {bot.last_error && <p className="integration-error">Последняя ошибка: {bot.last_error}</p>}
    <div className="integration-card-actions"><button className="secondary-button integration-action" type="button" onClick={() => onRegister(bot)} disabled={deleting}>Перерегистрировать webhook</button><button className="danger-button integration-action" type="button" onClick={() => onDelete(bot)} disabled={deleting}>{deleting ? "Удаляем…" : "Удалить бота"}</button></div>
  </article>;
}

function OzonAccountCard({
  account,
  refreshing,
  deleting,
  onRefresh,
  onDelete,
}: {
  account: OzonAccount;
  refreshing: boolean;
  deleting: boolean;
  onRefresh: (account: OzonAccount) => void;
  onDelete: (account: OzonAccount) => void;
}) {
  return (
    <article className="integration-card">
      <div className="integration-card-heading">
        <div><span className="integration-icon ozon-icon">O</span><div><strong>{account.name}</strong><small>API-ключ: {account.api_key_hint}</small></div></div>
        <span className={`integration-status ${account.enabled ? "online" : "offline"}`}>{account.enabled ? "Активен" : "Выключен"}</span>
      </div>
      <div className="integration-details integration-details-stack">
        <span>Client-Id <strong>{account.client_id}</strong></span>
        <span>Проверка <strong>каждые {account.poll_interval_minutes} мин.</strong></span>
        <span>Начальная загрузка <strong>{account.baseline_completed ? "готова" : "ожидается"}</strong></span>
      </div>
      <p className="integration-meta">Последняя проверка: {displayDate(account.last_checked_at)}</p>
      {account.last_error && <p className="integration-error">Последняя ошибка: {account.last_error}</p>}
      <div className="integration-card-actions">
        <button className="secondary-button integration-action" type="button" onClick={() => onRefresh(account)} disabled={refreshing || deleting || !account.enabled}>
          {refreshing ? "Получаем заказы…" : "Проверить сейчас"}
        </button>
        <button className="danger-button integration-action" type="button" onClick={() => onDelete(account)} disabled={refreshing || deleting}>
          {deleting ? "Удаляем…" : "Удалить Ozon"}
        </button>
      </div>
    </article>
  );
}

export default function IntegrationsView({ api }: IntegrationsViewProps) {
  const [marketAccounts, setMarketAccounts] = useState<MarketAccount[]>([]);
  const [orders, setOrders] = useState<MarketOrder[]>([]);
  const [accounts, setAccounts] = useState<DirectAccount[]>([]);
  const [ozonAccounts, setOzonAccounts] = useState<OzonAccount[]>([]);
  const [bots, setBots] = useState<MaxBot[]>([]);
  const [accessRequests, setAccessRequests] = useState<MaxAccessRequest[]>([]);
  const [marketForm, setMarketForm] = useState(emptyMarketForm);
  const [directForm, setDirectForm] = useState(emptyDirectForm);
  const [maxForm, setMaxForm] = useState(emptyMaxForm);
  const [ozonForm, setOzonForm] = useState(emptyOzonForm);
  const [maxSecret, setMaxSecret] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");
  const [refreshingAccountId, setRefreshingAccountId] = useState<string | null>(null);
  const [deletingConnectionId, setDeletingConnectionId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setLoading(true); setError("");
    try {
      const [nextMarketAccounts, nextOrders, nextAccounts, nextOzonAccounts, nextBots] = await Promise.all([api.listMarketAccounts(), api.listMarketOrders(), api.listDirectAccounts(), api.listOzonAccounts(), api.listMaxBots()]);
      const nextRequests = (await Promise.all(nextBots.filter((bot) => bot.integration === "market").map((bot) => api.listMaxAccessRequests(bot.id)))).flat();
      setMarketAccounts(nextMarketAccounts); setOrders(nextOrders); setAccounts(nextAccounts); setOzonAccounts(nextOzonAccounts); setBots(nextBots); setAccessRequests(nextRequests);
    } catch (reason) { setError(errorText(reason)); } finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, [api]);

  async function submitMarket(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusyAction("market-create"); setError(""); setMessage("");
    try {
      await api.createMarketAccount({ name: marketForm.name.trim(), campaign_id: Number(marketForm.campaign_id), api_key: marketForm.api_key, poll_interval_seconds: Number(marketForm.poll_interval_seconds) });
      setMarketForm(emptyMarketForm); setMessage("Магазин подключён. Нажми «Получить заказы», чтобы проверить интеграцию сразу."); await load();
    } catch (reason) { setError(errorText(reason)); } finally { setBusyAction(""); }
  }

  async function syncMarketAccount(account: MarketAccount) {
    setBusyAction(`market-sync-${account.id}`); setError("");
    try { const result = await api.syncMarketAccount(account.id); setMessage(result.new_orders ? `Получено новых заказов: ${result.new_orders}.` : "Синхронизация завершена, новых заказов нет."); await load(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusyAction(""); }
  }

  async function deleteMarketAccount(account: MarketAccount) {
    if (!window.confirm(`Удалить магазин «${account.name}» и сохранённые заказы?`)) return;
    setBusyAction(`market-delete-${account.id}`); setError("");
    try { await api.deleteMarketAccount(account.id); setMessage(`Магазин «${account.name}» удалён.`); await load(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusyAction(""); }
  }

  async function updateAccess(request: MaxAccessRequest, status: "approved" | "denied", role?: "picker" | "admin") {
    setBusyAction(`access-${request.id}`); setError("");
    try { await api.updateMaxAccessRequest(request.bot_id, request.id, { status, role }); setMessage(status === "approved" ? `${request.display_name}: роль назначена.` : `${request.display_name}: доступ отклонён.`); await load(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusyAction(""); }
  }

  async function refreshDirectAccount(account: DirectAccount) {
    setRefreshingAccountId(account.id); setError(""); setMessage(`Проверяем аккаунт «${account.name}»…`);
    try {
      let job = await api.createDirectJob(account.id, "balance_check");
      for (let attempt = 0; attempt < 30 && job.status !== "completed" && job.status !== "failed"; attempt += 1) { await wait(2000); job = await api.getDirectJob(job.id); if (job.status === "pending" && job.error && job.error !== "Yandex Direct report is pending") break; }
      await load();
      if (job.status === "completed") setMessage(`Данные аккаунта «${account.name}» обновлены.`); else if (job.status === "failed" || job.error) throw new Error(job.error || "Проверка Яндекс Директа завершилась с ошибкой"); else setMessage(`Проверка аккаунта «${account.name}» продолжается в фоне.`);
    } catch (reason) { setError(errorText(reason)); } finally { setRefreshingAccountId(null); }
  }

  async function submitDirect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusyAction("direct-create"); setError(""); setMessage("");
    try { await api.createDirectAccount({ name: directForm.name.trim(), token: directForm.token, client_login: directForm.client_login.trim() || undefined, balance_threshold: Number(directForm.balance_threshold), days_left_threshold: Number(directForm.days_left_threshold), anomaly_ratio: Number(directForm.anomaly_ratio), monitor_interval_minutes: Number(directForm.monitor_interval_minutes) }); setDirectForm(emptyDirectForm); setMessage("Аккаунт Яндекс Директа добавлен."); await load(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusyAction(""); }
  }

  async function deleteDirectAccount(account: DirectAccount) {
    if (!window.confirm(`Удалить подключение Яндекс Директа «${account.name}»?`)) return;
    setDeletingConnectionId(account.id); setError("");
    try { await api.deleteDirectAccount(account.id); setMessage(`Подключение Яндекс Директа «${account.name}» удалено.`); await load(); }
    catch (reason) { setError(errorText(reason)); } finally { setDeletingConnectionId(null); }
  }

  async function submitOzon(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusyAction("ozon-create");
    setError("");
    setMessage("");
    try {
      const account = await api.createOzonAccount({
        name: ozonForm.name.trim(),
        client_id: ozonForm.client_id.trim(),
        api_key: ozonForm.api_key,
        poll_interval_minutes: Number(ozonForm.poll_interval_minutes),
      });
      setOzonForm(emptyOzonForm);
      setMessage(`Ozon Seller «${account.name}» подключён. Первая проверка запомнит текущие заказы без массовой рассылки.`);
      await load();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusyAction("");
    }
  }

  async function refreshOzonAccount(account: OzonAccount) {
    setRefreshingAccountId(account.id);
    setError("");
    setMessage(`Получаем заказы Ozon из кабинета «${account.name}»…`);
    try {
      const result = await api.syncOzonAccount(account.id);
      await load();
      setMessage(
        result.baseline
          ? `Начальная загрузка «${account.name}» готова: запомнено ${result.created} отправлений. Новые заказы будут приходить в MAX.`
          : `Ozon обновлён: получено ${result.fetched}, новых ${result.created}, уведомлений ${result.notified}.`,
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setRefreshingAccountId(null);
    }
  }

  async function deleteOzonAccount(account: OzonAccount) {
    if (!window.confirm(`Удалить подключение Ozon Seller «${account.name}» и историю его отправлений?`)) return;
    setDeletingConnectionId(account.id);
    setError("");
    setMessage("");
    try {
      await api.deleteOzonAccount(account.id);
      setOzonAccounts((current) => current.filter((item) => item.id !== account.id));
      setMessage(`Подключение Ozon Seller «${account.name}» удалено.`);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setDeletingConnectionId(null);
    }
  }

  async function registerWebhook(bot: MaxBot) {
    setBusyAction(`webhook-${bot.id}`); setError("");
    try { await api.registerMaxWebhook(bot.id); setMessage(`Webhook для «${bot.name}» зарегистрирован. Открой бота в MAX и отправь /start.`); await load(); }
    catch (reason) { setError(errorText(reason)); } finally { setBusyAction(""); }
  }

  async function submitMax(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusyAction("max-create"); setError(""); setMessage(""); setMaxSecret("");
    try {
      const created: MaxBotCreated = await api.createMaxBot({ name: maxForm.name.trim(), token: maxForm.token, integration: maxForm.integration, allowlist: parseAllowlist(maxForm.allowlist) });
      let registrationMessage = `Бот «${created.name}» добавлен.`;
      try { await api.registerMaxWebhook(created.id); registrationMessage += " Webhook зарегистрирован."; } catch (reason) { registrationMessage += ` Webhook пока не зарегистрирован: ${errorText(reason)}`; }
      setMaxSecret(created.webhook_secret); setMaxForm(emptyMaxForm); setMessage(`${registrationMessage} Отправь боту /start в MAX.`); await load();
    } catch (reason) { setError(errorText(reason)); } finally { setBusyAction(""); }
  }

  async function deleteMaxBot(bot: MaxBot) {
    if (!window.confirm(`Удалить MAX-бота «${bot.name}»?`)) return;
    setDeletingConnectionId(bot.id); setError("");
    try { await api.deleteMaxBot(bot.id); setMessage(`MAX-бот «${bot.name}» удалён.`); await load(); }
    catch (reason) { setError(errorText(reason)); } finally { setDeletingConnectionId(null); }
  }

  const marketBots = bots.filter((bot) => bot.integration === "market");
  const directBots = bots.filter((bot) => bot.integration === "direct");
  const waitingOrders = orders.filter((order) => order.pack_state === "new").length;
  const packedOrders = orders.filter((order) => order.pack_state === "packed").length;
  const pendingRequests = accessRequests.filter((request) => request.status === "pending").length;

  return <section className="integrations-page">
    <div className="integrations-intro"><div><p className="eyebrow">СКЛАД И УВЕДОМЛЕНИЯ</p><h2>Яндекс Маркет, Ozon и MAX</h2><p>Подключи кабинеты маркетплейсов и бота. Новые заказы появятся здесь и будут отправлены в MAX.</p></div><button className="text-button" type="button" onClick={() => void load()} disabled={loading}>Обновить</button></div>
    {error && <div className="error-message page-error">{error}</div>}
    {message && <div className="integration-success">{message}</div>}
    {maxSecret && <div className="integration-secret"><strong>Секрет webhook — сохрани сейчас:</strong><code>{maxSecret}</code><span>Он показывается только один раз.</span></div>}

    <div className="integration-metrics" aria-label="Сводка интеграции"><div><span>Кабинеты</span><strong>{marketAccounts.length + ozonAccounts.length}</strong></div><div><span>Ждут сборки</span><strong>{waitingOrders}</strong></div><div><span>Готовы</span><strong>{packedOrders}</strong></div><div><span>Заявки</span><strong>{pendingRequests}</strong></div></div>

    <div className="integration-columns integration-primary-columns">
      <div className="integration-column">
        <div className="section-heading"><div><p className="eyebrow">PROVIDER</p><h3>Магазин</h3></div></div>
        <form className="integration-form" onSubmit={submitMarket}>
          <label>Название магазина<input value={marketForm.name} onChange={(event) => setMarketForm({ ...marketForm, name: event.currentTarget.value })} placeholder="Основной магазин" required /></label>
          <label>Campaign ID<input type="number" min="1" value={marketForm.campaign_id} onChange={(event) => setMarketForm({ ...marketForm, campaign_id: event.currentTarget.value })} placeholder="149086260" required /></label>
          <label>API-Key Яндекс Маркета<input type="password" value={marketForm.api_key} onChange={(event) => setMarketForm({ ...marketForm, api_key: event.currentTarget.value })} placeholder="Ключ из кабинета продавца" minLength={20} autoComplete="off" required /></label>
          <label>Проверять новые заказы каждые, секунд<input type="number" min="15" max="3600" value={marketForm.poll_interval_seconds} onChange={(event) => setMarketForm({ ...marketForm, poll_interval_seconds: event.currentTarget.value })} required /></label>
          <p className="form-hint">Ключ хранится на сервере в зашифрованном виде и после сохранения полностью не показывается.</p>
          <button className="primary-button" type="submit" disabled={Boolean(busyAction)}>{busyAction === "market-create" ? "Подключаем…" : "Подключить магазин"}</button>
        </form>
        <div className="integration-list">{loading ? <div className="loading-line">Загружаем магазины…</div> : marketAccounts.length ? marketAccounts.map((account) => <MarketAccountCard account={account} busy={busyAction.endsWith(account.id)} onSync={syncMarketAccount} onDelete={deleteMarketAccount} key={account.id} />) : <div className="integration-empty">Магазин ещё не подключён. Заполни форму выше.</div>}</div>
      </div>

      <div className="integration-column">
        <div className="section-heading"><div><p className="eyebrow">TRANSPORT</p><h3>Бот в MAX</h3></div></div>
        <form className="integration-form" onSubmit={submitMax}>
          <label>Название бота<input value={maxForm.name} onChange={(event) => setMaxForm({ ...maxForm, name: event.currentTarget.value })} placeholder="Сборка заказов" required /></label>
          <label>Назначение<select value={maxForm.integration} onChange={(event) => setMaxForm({ ...maxForm, integration: event.currentTarget.value as "market" | "direct" })}><option value="market">Яндекс Маркет — сборка заказов</option><option value="direct">Яндекс Директ — аналитика</option></select></label>
          <label>Bot token MAX<input type="password" value={maxForm.token} onChange={(event) => setMaxForm({ ...maxForm, token: event.currentTarget.value })} placeholder="Токен из кабинета MAX" minLength={20} autoComplete="off" required /></label>
          <label>ID с доступом <span className="muted">необязательно, через запятую</span><input value={maxForm.allowlist} onChange={(event) => setMaxForm({ ...maxForm, allowlist: event.currentTarget.value })} placeholder="Оставь пустым — доступ выдашь по заявке" /></label>
          <p className="form-hint">После подключения открой бота в MAX и отправь /start. Первый пользователь станет администратором.</p>
          <button className="primary-button" type="submit" disabled={Boolean(busyAction)}>{busyAction === "max-create" ? "Подключаем…" : "Подключить MAX"}</button>
        </form>
        <div className="integration-list">{loading ? <div className="loading-line">Загружаем ботов…</div> : marketBots.length ? marketBots.map((bot) => <MaxBotCard bot={bot} deleting={deletingConnectionId === bot.id || busyAction === `webhook-${bot.id}`} onRegister={registerWebhook} onDelete={deleteMaxBot} key={bot.id} />) : <div className="integration-empty">Бот для заказов ещё не подключён.</div>}</div>
      </div>
    </div>

    <section className="integration-workspace-panel">
      <div className="section-heading"><div><p className="eyebrow">OZON SELLER</p><h3>Уведомления о новых заказах</h3></div><span className="muted">FBS и FBO · без дублей</span></div>
      <div className="integration-columns">
        <div className="integration-column">
          <form className="integration-form" onSubmit={submitOzon}>
            <label>Название кабинета<input value={ozonForm.name} onChange={(event) => setOzonForm({ ...ozonForm, name: event.currentTarget.value })} placeholder="Основной Ozon" required /></label>
            <label>Client-Id<input value={ozonForm.client_id} onChange={(event) => setOzonForm({ ...ozonForm, client_id: event.currentTarget.value })} placeholder="ID продавца из Ozon Seller" required /></label>
            <label>Api-Key<input type="password" value={ozonForm.api_key} onChange={(event) => setOzonForm({ ...ozonForm, api_key: event.currentTarget.value })} placeholder="API-ключ из настроек кабинета" minLength={10} autoComplete="off" required /></label>
            <label>Интервал проверки, минут<input type="number" min="1" max="1440" value={ozonForm.poll_interval_minutes} onChange={(event) => setOzonForm({ ...ozonForm, poll_interval_minutes: event.currentTarget.value })} /></label>
            <p className="form-hint">API-ключ хранится зашифрованным. Первая загрузка запомнит текущие отправления без массовой рассылки.</p>
            <button className="primary-button" type="submit" disabled={Boolean(busyAction)}>{busyAction === "ozon-create" ? "Подключаем…" : "Подключить Ozon"}</button>
          </form>
        </div>
        <div className="integration-column">
          <p className="form-hint">Новые отправления Ozon автоматически проверяются каждую минуту и приходят в тот же MAX-бот, который подключён для заказов Яндекс Маркета.</p>
          <div className="integration-list">{loading ? <div className="loading-line">Загружаем кабинеты Ozon…</div> : ozonAccounts.length ? ozonAccounts.map((account) => <OzonAccountCard account={account} refreshing={refreshingAccountId === account.id} deleting={deletingConnectionId === account.id} onRefresh={refreshOzonAccount} onDelete={deleteOzonAccount} key={account.id} />) : <div className="integration-empty">Ozon Seller ещё не подключён.</div>}</div>
        </div>
      </div>
    </section>

    <section className="integration-workspace-panel">
      <div className="section-heading"><div><p className="eyebrow">ЗАКАЗЫ</p><h3>Очередь сборки</h3></div><span className="muted">Всего: {orders.length}</span></div>
      {loading ? <div className="loading-line">Загружаем заказы…</div> : orders.length ? <div className="market-order-list">{orders.map((order) => <article className="market-order-row" key={order.id}><div className="market-order-number"><span>Заказ</span><strong>№{order.market_order_id}</strong></div><div className="market-order-products">{order.items.length ? order.items.map((item, index) => <div key={`${item.offerId ?? "item"}-${index}`}><strong>{item.offerName ?? item.offerId ?? "Товар"}</strong><span>{Number(item.count ?? 1)} шт.</span></div>) : <span className="muted">Состав заказа не передан</span>}</div><div className="market-order-progress"><span className={`pack-status ${order.pack_state}`}>{packStateLabel(order)}</span>{order.pack_requested_name && <small>Сборщик: {order.pack_requested_name}</small>}{order.pack_error && <small className="integration-error">{order.pack_error}</small>}</div></article>)}</div> : <div className="integration-empty">Заказов пока нет. Подключи магазин и нажми «Получить заказы».</div>}
    </section>

    <section className="integration-workspace-panel">
      <div className="section-heading"><div><p className="eyebrow">КОМАНДА</p><h3>Доступ к боту</h3></div><span className="muted">Сборщик может нажать «Запаковал», админ только наблюдает.</span></div>
      {!marketBots.length ? <div className="integration-empty">Сначала подключи MAX-бота для Яндекс Маркета.</div> : accessRequests.length ? <div className="access-request-list">{accessRequests.map((request) => <article className="access-request-row" key={request.id}><div><strong>{request.display_name}</strong><span>MAX ID {request.user_id} · {displayDate(request.requested_at)}</span></div><span className={`integration-status ${request.status === "approved" ? "online" : request.status === "denied" ? "offline" : "pending"}`}>{request.status === "approved" ? request.role === "picker" ? "Сборщик" : "Админ" : request.status === "denied" ? "Отклонён" : "Ждёт решения"}</span><div className="access-request-actions"><button className="secondary-button integration-action" type="button" onClick={() => void updateAccess(request, "approved", "picker")} disabled={busyAction === `access-${request.id}`}>Сборщик</button><button className="secondary-button integration-action" type="button" onClick={() => void updateAccess(request, "approved", "admin")} disabled={busyAction === `access-${request.id}`}>Админ</button><button className="danger-button integration-action" type="button" onClick={() => void updateAccess(request, "denied")} disabled={busyAction === `access-${request.id}`}>Отклонить</button></div></article>)}</div> : <div className="integration-empty">Заявок пока нет. Пользователь должен открыть бота и отправить /start.</div>}
    </section>

    <details className="secondary-integrations"><summary>Дополнительно: Яндекс Директ и его MAX-бот</summary><div className="integration-columns">
      <div className="integration-column">
        <div className="section-heading"><div><p className="eyebrow">PROVIDER</p><h3>Яндекс Директ</h3></div></div>
        <form className="integration-form" onSubmit={submitDirect}>
          <label>Название аккаунта<input value={directForm.name} onChange={(event) => setDirectForm({ ...directForm, name: event.currentTarget.value })} placeholder="Основной кабинет" required /></label>
          <label>OAuth-токен Яндекса<input type="password" value={directForm.token} onChange={(event) => setDirectForm({ ...directForm, token: event.currentTarget.value })} placeholder="Вставь токен из OAuth" minLength={20} required /></label>
          <label>Client-Login <span className="muted">для агентского аккаунта</span><input value={directForm.client_login} onChange={(event) => setDirectForm({ ...directForm, client_login: event.currentTarget.value })} placeholder="необязательно" /></label>
          <div className="integration-form-grid"><label>Порог баланса<input type="number" min="0" step="0.01" value={directForm.balance_threshold} onChange={(event) => setDirectForm({ ...directForm, balance_threshold: event.currentTarget.value })} /></label><label>Дней до бюджета<input type="number" min="0" step="0.1" value={directForm.days_left_threshold} onChange={(event) => setDirectForm({ ...directForm, days_left_threshold: event.currentTarget.value })} /></label><label>Интервал, минут<input type="number" min="5" max="1440" value={directForm.monitor_interval_minutes} onChange={(event) => setDirectForm({ ...directForm, monitor_interval_minutes: event.currentTarget.value })} /></label></div>
          <button className="primary-button" type="submit" disabled={Boolean(busyAction)}>Добавить аккаунт</button>
        </form>
        <div className="integration-list">{accounts.length ? accounts.map((account) => <DirectAccountCard account={account} refreshing={refreshingAccountId === account.id} deleting={deletingConnectionId === account.id} onRefresh={refreshDirectAccount} onDelete={deleteDirectAccount} key={account.id} />) : <div className="integration-empty">Аккаунт ещё не подключён.</div>}</div>
      </div>
      <div className="integration-column"><div className="section-heading"><div><p className="eyebrow">TRANSPORT</p><h3>MAX для аналитики</h3></div></div><div className="integration-list">{directBots.length ? directBots.map((bot) => <MaxBotCard bot={bot} deleting={deletingConnectionId === bot.id || busyAction === `webhook-${bot.id}`} onRegister={registerWebhook} onDelete={deleteMaxBot} key={bot.id} />) : <div className="integration-empty">Выбери «Яндекс Директ — аналитика» в форме MAX выше.</div>}</div></div>
    </div></details>
  </section>;
}
