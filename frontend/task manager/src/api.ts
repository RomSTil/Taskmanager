import type {
  Note,
  NoteShare,
  NoteIndex,
  KnowledgeGraph,
  Project,
  PublicNote,
  SetupState,
  Task,
  TaskStatus,
  TokenPair,
  User,
  UserAccessLog,
  ApiToken,
  CreatedApiToken,
  UserRole,
  WorkspaceBootstrap,
  DirectAccount,
  DirectJob,
  MarketAccount,
  MarketOrder,
  MaxBot,
  MaxBotCreated,
  MaxAccessRequest,
  OzonAccount,
  OzonSyncResult,
  AgentRun,
  AgentRunner,
  AgentMode,
} from "./types";

const API_URL_KEY = "taskman.apiUrl";
const SESSION_KEY = "taskman.session";

export const DEFAULT_API_URL = "http://127.0.0.1:8765";
const PRODUCTION_API_URL = "https://apitaskman.nemidamc.ru";

function defaultApiUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_URL;
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") return DEFAULT_API_URL;
  return PRODUCTION_API_URL;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function normalizeUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function validateBackendUrl(value: string): string {
  const normalized = normalizeUrl(value);
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new ApiError("Некорректный адрес backend", 0);
  }
  if (parsed.username || parsed.password) {
    throw new ApiError("Адрес backend не должен содержать логин или пароль", 0);
  }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) {
    throw new ApiError("Для удалённого backend требуется HTTPS", 0);
  }
  return normalized;
}

function readError(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return fallback;
}

export function getSavedApiUrl(): string {
  const stored = localStorage.getItem(API_URL_KEY);
  const fallback = defaultApiUrl();
  if (!stored) return fallback;
  const normalized = normalizeUrl(stored);
  if (fallback === PRODUCTION_API_URL && (normalized === DEFAULT_API_URL || normalized.includes("127.0.0.1") || normalized.includes("localhost"))) {
    return fallback;
  }
  return normalized;
}

export function getSession(): TokenPair | null {
  const stored = localStorage.getItem(SESSION_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored) as TokenPair;
  } catch {
    localStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
}

function saveSession(session: TokenPair): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export class TaskmanApi {
  readonly baseUrl: string;
  private refreshInFlight: Promise<TokenPair> | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = normalizeUrl(baseUrl);
  }

  saveUrl(): void {
    localStorage.setItem(API_URL_KEY, validateBackendUrl(this.baseUrl));
  }

  private async request<T>(path: string, init: RequestInit = {}, authenticated = false, retried = false): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body) headers.set("Content-Type", "application/json");
    if (authenticated) {
      const session = getSession();
      if (!session) throw new ApiError("Требуется вход", 401);
      headers.set("Authorization", `Bearer ${session.access_token}`);
    }

    let response: Response;
    try {
      const baseUrl = validateBackendUrl(this.baseUrl);
      response = await fetch(`${baseUrl}/api/v1${path}`, { ...init, headers });
    } catch (reason) {
      if (reason instanceof ApiError) throw reason;
      throw new ApiError("Сервер недоступен. Проверьте адрес и запустите backend.", 0);
    }

    if (response.status === 401 && authenticated && !retried) {
      await this.refreshSession();
      return this.request<T>(path, init, authenticated, true);
    }
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(readError(payload, `Ошибка сервера (${response.status})`), response.status);
    }
    return payload as T;
  }

  setupState(): Promise<SetupState> {
    return this.request<SetupState>("/auth/setup");
  }

  async setup(
    username: string,
    name: string,
    password: string,
    setupToken?: string,
  ): Promise<TokenPair> {
    const session = await this.request<TokenPair>("/auth/setup", {
      method: "POST",
      headers: setupToken ? { "X-Setup-Token": setupToken } : undefined,
      body: JSON.stringify({ username, name, password }),
    });
    saveSession(session);
    return session;
  }

  async login(username: string, password: string): Promise<TokenPair> {
    const session = await this.request<TokenPair>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    saveSession(session);
    return session;
  }

  async refreshSession(): Promise<TokenPair> {
    if (this.refreshInFlight) return this.refreshInFlight;
    const current = getSession();
    if (!current) throw new ApiError("Требуется вход", 401);
    this.refreshInFlight = (async () => {
      try {
        const response = await fetch(`${validateBackendUrl(this.baseUrl)}/api/v1/auth/refresh`, {
          method: "POST",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: current.refresh_token }),
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new ApiError(readError(payload, "Не удалось обновить сессию"), response.status);
        const session = payload as TokenPair;
        saveSession(session);
        return session;
      } catch (reason) {
        clearSession();
        throw reason instanceof ApiError ? reason : new ApiError("Не удалось обновить сессию", 0);
      } finally {
        this.refreshInFlight = null;
      }
    })();
    return this.refreshInFlight;
  }

  bootstrap(): Promise<WorkspaceBootstrap> {
    return this.request<WorkspaceBootstrap>("/bootstrap", {}, true);
  }

  createTask(input: {
    title: string;
    project_id: string | null;
    priority: number;
    due_at?: string | null;
    source_data?: Record<string, unknown>;
  }): Promise<Task> {
    return this.request<Task>(
      "/tasks",
      {
        method: "POST",
        headers: { "X-Operation-Id": crypto.randomUUID() },
        body: JSON.stringify(input),
      },
      true,
    );
  }

  updateTask(task: Task, changes: {
    status?: TaskStatus;
    priority?: number;
    title?: string;
    description_markdown?: string;
    project_id?: string | null;
    archived?: boolean;
  }): Promise<Task> {
    return this.request<Task>(
      `/tasks/${encodeURIComponent(task.id)}`,
      {
        method: "PATCH",
        headers: { "X-Operation-Id": crypto.randomUUID() },
        body: JSON.stringify({ base_version: task.version, ...changes }),
      },
      true,
    );
  }

  listNotes(projectId?: string): Promise<NoteIndex[]> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return this.request<NoteIndex[]>(`/notes${query}`, {}, true);
  }

  getNote(noteId: string): Promise<Note> {
    return this.request<Note>(`/notes/${encodeURIComponent(noteId)}`, {}, true);
  }

  getNoteShare(noteId: string): Promise<NoteShare | null> {
    return this.request<NoteShare | null>(`/notes/${encodeURIComponent(noteId)}/share`, {}, true);
  }

  createNoteShare(noteId: string, expiresAt: string | null): Promise<NoteShare> {
    return this.request<NoteShare>(`/notes/${encodeURIComponent(noteId)}/share`, { method: "POST", body: JSON.stringify({ expires_at: expiresAt }) }, true);
  }

  revokeNoteShare(noteId: string): Promise<void> {
    return this.request<void>(`/notes/${encodeURIComponent(noteId)}/share`, { method: "DELETE" }, true);
  }

  publicNote(token: string): Promise<PublicNote> {
    return this.request<PublicNote>(`/public/notes/${encodeURIComponent(token)}`);
  }

  createProject(input: { name: string; key?: string; description?: string; color?: string; parent_id?: string | null }): Promise<Project> {
    return this.request<Project>("/projects", { method: "POST", body: JSON.stringify(input) }, true);
  }

  archiveProject(project: Project): Promise<Project> {
    return this.request<Project>(
      `/projects/${encodeURIComponent(project.id)}`,
      { method: "PATCH", body: JSON.stringify({ base_version: project.version, archived: true }) },
      true,
    );
  }

  createNote(input: { title: string; content_markdown: string; tags?: string[]; project_id?: string | null }): Promise<Note> {
    return this.request<Note>("/notes", { method: "POST", body: JSON.stringify(input) }, true);
  }

  updateNote(note: Note, input: { title: string; content_markdown: string; tags?: string[]; project_id?: string | null }): Promise<Note> {
    return this.request<Note>(
      `/notes/${encodeURIComponent(note.id)}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          base_revision: note.revision,
          title: input.title,
          content_markdown: input.content_markdown,
          tags: input.tags ?? note.tags,
          project_id: input.project_id ?? note.project_id,
        }),
      },
      true,
    );
  }

  listTaskNotes(taskId: string): Promise<NoteIndex[]> {
    return this.request<NoteIndex[]>(`/tasks/${encodeURIComponent(taskId)}/notes`, {}, true);
  }

  linkTaskNote(taskId: string, noteId: string): Promise<void> {
    return this.request<void>(`/tasks/${encodeURIComponent(taskId)}/notes/${encodeURIComponent(noteId)}`, { method: "POST" }, true);
  }

  knowledgeGraph(): Promise<KnowledgeGraph> {
    return this.request<KnowledgeGraph>("/knowledge-graph", {}, true);
  }

  updateMyProfile(name: string): Promise<User> {
    return this.request<User>("/auth/me", { method: "PATCH", body: JSON.stringify({ name }) }, true);
  }

  updateUserRole(userId: string, role: UserRole): Promise<User> {
    return this.request<User>(`/auth/users/${encodeURIComponent(userId)}/role`, { method: "PATCH", body: JSON.stringify({ role }) }, true);
  }

  createUser(input: { name: string; username: string; password: string; role: UserRole }): Promise<User> {
    return this.request<User>("/auth/users", { method: "POST", body: JSON.stringify(input) }, true);
  }

  listAccessLog(): Promise<UserAccessLog[]> {
    return this.request<UserAccessLog[]>("/auth/access-log", {}, true);
  }

  async logoutSession(): Promise<void> {
    const session = getSession();
    if (!session) return;
    try {
      await this.request<void>("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: session.refresh_token }) });
    } finally {
      clearSession();
    }
  }

  listApiTokens(): Promise<ApiToken[]> {
    return this.request<ApiToken[]>("/auth/tokens", {}, true);
  }

  createApiToken(input: { name: string; scopes: string[] }): Promise<CreatedApiToken> {
    return this.request<CreatedApiToken>("/auth/tokens", { method: "POST", body: JSON.stringify(input) }, true);
  }

  revokeApiToken(tokenId: string): Promise<void> {
    return this.request<void>(`/auth/tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE" }, true);
  }

  listDirectAccounts(): Promise<DirectAccount[]> {
    return this.request<DirectAccount[]>("/integrations/yandex-direct/accounts", {}, true);
  }

  createDirectAccount(input: {
    name: string;
    token: string;
    client_login?: string;
    balance_threshold: number;
    days_left_threshold: number;
    anomaly_ratio: number;
    monitor_interval_minutes: number;
  }): Promise<DirectAccount> {
    return this.request<DirectAccount>("/integrations/yandex-direct/accounts", {
      method: "POST",
      body: JSON.stringify(input),
    }, true);
  }

  deleteDirectAccount(accountId: string): Promise<void> {
    return this.request<void>(
      `/integrations/yandex-direct/accounts/${encodeURIComponent(accountId)}`,
      { method: "DELETE" },
      true,
    );
  }

  createDirectJob(accountId: string, jobType: "balance_check" | "campaign_sync" | "report"): Promise<DirectJob> {
    return this.request<DirectJob>(
      `/integrations/yandex-direct/accounts/${encodeURIComponent(accountId)}/jobs`,
      {
        method: "POST",
        body: JSON.stringify({ job_type: jobType }),
      },
      true,
    );
  }

  getDirectJob(jobId: string): Promise<DirectJob> {
    return this.request<DirectJob>(
      `/integrations/yandex-direct/jobs/${encodeURIComponent(jobId)}`,
      {},
      true,
    );
  }

  listMarketAccounts(): Promise<MarketAccount[]> {
    return this.request<MarketAccount[]>("/integrations/yandex-market/accounts", {}, true);
  }

  createMarketAccount(input: {
    name: string;
    campaign_id: number;
    api_key: string;
    poll_interval_seconds: number;
  }): Promise<MarketAccount> {
    return this.request<MarketAccount>("/integrations/yandex-market/accounts", {
      method: "POST",
      body: JSON.stringify(input),
    }, true);
  }

  deleteMarketAccount(accountId: string): Promise<void> {
    return this.request<void>(
      `/integrations/yandex-market/accounts/${encodeURIComponent(accountId)}`,
      { method: "DELETE" },
      true,
    );
  }

  syncMarketAccount(accountId: string): Promise<{ new_orders: number }> {
    return this.request<{ new_orders: number }>(
      `/integrations/yandex-market/accounts/${encodeURIComponent(accountId)}/sync`,
      { method: "POST" },
      true,
    );
  }

  listMarketOrders(): Promise<MarketOrder[]> {
    return this.request<MarketOrder[]>("/integrations/yandex-market/orders", {}, true);
  }

  listMaxBots(): Promise<MaxBot[]> {
    return this.request<MaxBot[]>("/integrations/max/bots", {}, true);
  }

  createMaxBot(input: {
    name: string;
    token: string;
    integration: "direct" | "market" | "operations";
    allowlist: number[];
  }): Promise<MaxBotCreated> {
    return this.request<MaxBotCreated>("/integrations/max/bots", {
      method: "POST",
      body: JSON.stringify(input),
    }, true);
  }

  deleteMaxBot(botId: string): Promise<void> {
    return this.request<void>(
      `/integrations/max/bots/${encodeURIComponent(botId)}`,
      { method: "DELETE" },
      true,
    );
  }

  registerMaxWebhook(botId: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>(
      `/integrations/max/bots/${encodeURIComponent(botId)}/register-webhook`,
      { method: "POST" },
      true,
    );
  }

  listMaxAccessRequests(botId: string): Promise<MaxAccessRequest[]> {
    return this.request<MaxAccessRequest[]>(
      `/integrations/max/bots/${encodeURIComponent(botId)}/access-requests`,
      {},
      true,
    );
  }

  listOzonAccounts(): Promise<OzonAccount[]> {
    return this.request<OzonAccount[]>("/integrations/ozon/accounts", {}, true);
  }

  createOzonAccount(input: {
    name: string;
    client_id: string;
    api_key: string;
    poll_interval_minutes: number;
  }): Promise<OzonAccount> {
    return this.request<OzonAccount>("/integrations/ozon/accounts", {
      method: "POST",
      body: JSON.stringify(input),
    }, true);
  }

  syncOzonAccount(accountId: string): Promise<OzonSyncResult> {
    return this.request<OzonSyncResult>(
      `/integrations/ozon/accounts/${encodeURIComponent(accountId)}/sync`,
      { method: "POST" },
      true,
    );
  }

  deleteOzonAccount(accountId: string): Promise<void> {
    return this.request<void>(
      `/integrations/ozon/accounts/${encodeURIComponent(accountId)}`,
      { method: "DELETE" },
      true,
    );
  }

  updateMaxAccessRequest(
    botId: string,
    requestId: string,
    input: { status: "approved" | "denied"; role?: "viewer" | "picker" | "admin" },
  ): Promise<MaxAccessRequest> {
    return this.request<MaxAccessRequest>(
      `/integrations/max/bots/${encodeURIComponent(botId)}/access-requests/${encodeURIComponent(requestId)}`,
      { method: "PATCH", body: JSON.stringify(input) },
      true,
    );
  }

  listAgentRuns(): Promise<AgentRun[]> {
    return this.request<AgentRun[]>("/agent-runs", {}, true);
  }

  listAgentRunners(): Promise<AgentRunner[]> {
    return this.request<AgentRunner[]>("/agent-runners", {}, true);
  }

  createAgentRun(input: {
    task_id: string;
    goal: string;
    mode: AgentMode;
    allowed_actions: Array<"research" | "browser" | "code_preview">;
  }): Promise<AgentRun> {
    return this.request<AgentRun>("/agent-runs", { method: "POST", body: JSON.stringify(input) }, true);
  }

  cancelAgentRun(runId: string): Promise<AgentRun> {
    return this.request<AgentRun>(`/agent-runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }, true);
  }

  acceptAgentRun(runId: string): Promise<AgentRun> {
    return this.request<AgentRun>(`/agent-runs/${encodeURIComponent(runId)}/accept`, { method: "POST" }, true);
  }

  feedbackAgentRun(runId: string, message: string, labels: Array<"too_template" | "off_brand" | "logic" | "bug">): Promise<AgentRun> {
    return this.request<AgentRun>(
      `/agent-runs/${encodeURIComponent(runId)}/feedback`,
      { method: "POST", body: JSON.stringify({ message, labels }) },
      true,
    );
  }

  decideAgentApproval(runId: string, approvalId: string, decision: "approved" | "rejected"): Promise<AgentRun> {
    return this.request<AgentRun>(
      `/agent-runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/decision`,
      { method: "POST", body: JSON.stringify({ decision }) },
      true,
    );
  }
}
