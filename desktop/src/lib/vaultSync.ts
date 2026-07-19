import type { Note, NoteIndex } from "../types";
import { api } from "./api";
import { scanVault, trashVaultFile, writeVaultFile } from "./platform";

interface LocalState {
  noteId: string;
  revision: number;
  localHash: string;
}

type StateMap = Record<string, LocalState>;

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function stateKey(root: string) {
  return `taskman:vault-state:${root}`;
}

function readState(root: string): StateMap {
  try {
    return JSON.parse(localStorage.getItem(stateKey(root)) || "{}") as StateMap;
  } catch {
    return {};
  }
}

export async function syncVault(root: string): Promise<{ pushed: number; pulled: number; conflicts: number }> {
  const files = await scanVault(root);
  const state = readState(root);
  const manifest = await api.request<{ notes: NoteIndex[] }>("/sync/manifest");
  const serverByPath = new Map(manifest.notes.map((note) => [note.path.toLocaleLowerCase(), note]));
  const serverById = new Map(manifest.notes.map((note) => [note.id, note]));
  const localByPath = new Map(files.map((file) => [file.path.toLocaleLowerCase(), file]));
  let pushed = 0;
  let pulled = 0;
  let conflicts = 0;

  for (const file of files) {
    const key = file.path.toLocaleLowerCase();
    const previous = state[key];
    const localHash = await sha256(file.content);
    const movedOnServer = previous ? serverById.get(previous.noteId) : undefined;
    if (previous && movedOnServer && movedOnServer.path.toLocaleLowerCase() !== key && previous.localHash === localHash) {
      await trashVaultFile(root, file.path);
      delete state[key];
      continue;
    }
    if (previous?.localHash === localHash) continue;
    const server = serverByPath.get(key);
    const result = await api.request<{ status: string; note?: Note; conflict?: Note }>("/sync/push", {
      method: "POST",
      body: {
        operation_id: crypto.randomUUID(),
        device_id: localStorage.getItem("taskman:device-id") || "windows-desktop",
        id: previous?.noteId || server?.id,
        path: file.path,
        base_revision: previous?.revision || 0,
        content_markdown: file.content,
      },
    });
    if (result.note) {
      await writeVaultFile(root, result.note.path, result.note.content_markdown);
      state[key] = {
        noteId: result.note.id,
        revision: result.note.revision,
        localHash: await sha256(result.note.content_markdown),
      };
    }
    if (result.conflict) {
      await writeVaultFile(root, result.conflict.path, result.conflict.content_markdown);
      state[result.conflict.path.toLocaleLowerCase()] = {
        noteId: result.conflict.id,
        revision: result.conflict.revision,
        localHash: await sha256(result.conflict.content_markdown),
      };
      conflicts += 1;
    } else {
      pushed += 1;
    }
  }

  for (const [key, previous] of Object.entries(state)) {
    if (localByPath.has(key)) continue;
    const server = manifest.notes.find((note) => note.id === previous.noteId);
    if (!server || server.deleted_at) {
      delete state[key];
      continue;
    }
    const result = await api.request<{ status: string; note?: Note }>("/sync/push", {
      method: "POST",
      body: {
        operation_id: crypto.randomUUID(),
        device_id: localStorage.getItem("taskman:device-id") || "windows-desktop",
        id: previous.noteId,
        path: server.path,
        base_revision: previous.revision,
        deleted: true,
      },
    });
    if (result.status === "applied") delete state[key];
    else if (result.note) {
      await writeVaultFile(root, result.note.path, result.note.content_markdown);
      state[key] = { noteId: result.note.id, revision: result.note.revision, localHash: await sha256(result.note.content_markdown) };
      conflicts += 1;
    }
  }

  for (const server of manifest.notes) {
    const key = server.path.toLocaleLowerCase();
    if (server.deleted_at) {
      if (localByPath.has(key)) await trashVaultFile(root, server.path);
      delete state[key];
      continue;
    }
    const previous = state[key];
    if (localByPath.has(key) && previous && previous.revision >= server.revision) continue;
    const note = await api.request<Note>(`/notes/${server.id}`);
    await writeVaultFile(root, note.path, note.content_markdown);
    state[key] = {
      noteId: note.id,
      revision: note.revision,
      localHash: await sha256(note.content_markdown),
    };
    pulled += 1;
  }
  localStorage.setItem(stateKey(root), JSON.stringify(state));
  return { pushed, pulled, conflicts };
}
