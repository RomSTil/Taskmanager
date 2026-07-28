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
  WorkspaceBootstrap,
  DirectAccount,
  DirectJob,
  MaxBot,
  MaxBotCreated,
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

export class TaskmanApi {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = normalizeUrl(baseUrl);
  }

  saveUrl(): void {
    localStorage.setItem(API_URL_KEY, validateBackendUrl(this.baseUrl));
  }

  private async request<T>(path: string, init: RequestInit = {}, authenticated = false): Promise<T> {
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
    password: string,
    setupToken?: string,
  ): Promise<TokenPair> {
    const session = await this.request<TokenPair>("/auth/setup", {
      method: "POST",
      headers: setupToken ? { "X-Setup-Token": setupToken } : undefined,
      body: JSON.stringify({ username, password }),
    });
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    return session;
  }

  async login(username: string, password: string): Promise<TokenPair> {
    const session = await this.request<TokenPair>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    return session;
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

  listMaxBots(): Promise<MaxBot[]> {
    return this.request<MaxBot[]>("/integrations/max/bots", {}, true);
  }

  createMaxBot(input: { name: string; token: string; allowlist: number[] }): Promise<MaxBotCreated> {
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
}
