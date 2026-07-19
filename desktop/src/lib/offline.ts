import { api, ApiError } from "./api";

export interface QueuedMutation {
  id: string;
  method: string;
  path: string;
  body: unknown;
  createdAt: string;
  attempts: number;
  lastError?: string;
}

const QUEUE_KEY = "taskman:mutation-queue";

export function getQueue(): QueuedMutation[] {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]") as QueuedMutation[];
  } catch {
    return [];
  }
}

function saveQueue(queue: QueuedMutation[]) {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  window.dispatchEvent(new CustomEvent("taskman:queue", { detail: queue.length }));
}

export function queueMutation(method: string, path: string, body: unknown): QueuedMutation {
  const mutation: QueuedMutation = {
    id: crypto.randomUUID(),
    method,
    path,
    body,
    createdAt: new Date().toISOString(),
    attempts: 0,
  };
  saveQueue([...getQueue(), mutation]);
  return mutation;
}

export async function flushQueue(): Promise<{ sent: number; conflicts: QueuedMutation[] }> {
  const queue = getQueue();
  const remaining: QueuedMutation[] = [];
  const conflicts: QueuedMutation[] = [];
  let sent = 0;
  for (const mutation of queue) {
    try {
      await api.request(mutation.path, {
        method: mutation.method,
        body: mutation.body,
        headers: { "X-Operation-Id": mutation.id },
      });
      sent += 1;
    } catch (error) {
      mutation.attempts += 1;
      mutation.lastError = error instanceof Error ? error.message : "Sync failed";
      remaining.push(mutation);
      if (error instanceof ApiError && error.status === 409) conflicts.push(mutation);
      if (error instanceof ApiError && error.status === 0) {
        remaining.push(...queue.slice(queue.indexOf(mutation) + 1));
        break;
      }
    }
  }
  saveQueue(remaining);
  return { sent, conflicts };
}

export function saveCache<T>(key: string, value: T): void {
  localStorage.setItem(`taskman:cache:${key}`, JSON.stringify(value));
}

export function readCache<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(localStorage.getItem(`taskman:cache:${key}`) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}
