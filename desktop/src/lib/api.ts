import type { TokenPair } from "../types";
import { loadRefreshToken, saveRefreshToken } from "./platform";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `Taskman API error (${status})`);
  }
}

class ApiClient {
  apiUrl = localStorage.getItem("taskman:api-url") || "http://127.0.0.1:8765";
  accessToken: string | null = null;
  private refreshPromise: Promise<boolean> | null = null;

  setApiUrl(value: string) {
    this.apiUrl = value.trim().replace(/\/$/, "");
    localStorage.setItem("taskman:api-url", this.apiUrl);
  }

  async acceptTokens(tokens: TokenPair) {
    this.accessToken = tokens.access_token;
    await saveRefreshToken(this.apiUrl, tokens.refresh_token);
  }

  async restore(): Promise<boolean> {
    const refreshToken = await loadRefreshToken(this.apiUrl);
    if (!refreshToken) return false;
    try {
      const tokens = await this.request<TokenPair>("/auth/refresh", {
        method: "POST",
        body: { refresh_token: refreshToken },
        skipAuth: true,
        skipRefresh: true,
      });
      await this.acceptTokens(tokens);
      return true;
    } catch {
      return false;
    }
  }

  private async refresh(): Promise<boolean> {
    if (!this.refreshPromise) {
      this.refreshPromise = this.restore().finally(() => {
        this.refreshPromise = null;
      });
    }
    return this.refreshPromise;
  }

  async request<T>(
    path: string,
    options: {
      method?: string;
      body?: unknown;
      headers?: Record<string, string>;
      skipAuth?: boolean;
      skipRefresh?: boolean;
      query?: Record<string, string | number | boolean | null | undefined>;
    } = {},
  ): Promise<T> {
    const url = new URL(`${this.apiUrl}/api/v1${path}`);
    Object.entries(options.query || {}).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, String(value));
    });
    const headers: Record<string, string> = { "Content-Type": "application/json", ...options.headers };
    if (!options.skipAuth && this.accessToken) headers.Authorization = `Bearer ${this.accessToken}`;
    let response: Response;
    try {
      response = await fetch(url, {
        method: options.method || "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch (error) {
      throw new ApiError(0, error instanceof Error ? error.message : "Network unavailable");
    }
    if (response.status === 401 && !options.skipRefresh && !options.skipAuth && (await this.refresh())) {
      return this.request(path, { ...options, skipRefresh: true });
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, payload.detail ?? payload);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }
}

export const api = new ApiClient();
