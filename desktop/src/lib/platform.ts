import { invoke } from "@tauri-apps/api/core";

export const isTauri = () => "__TAURI_INTERNALS__" in window;

export async function saveRefreshToken(apiUrl: string, token: string): Promise<void> {
  if (isTauri()) {
    await invoke("save_secret", { apiUrl, value: token });
  } else {
    localStorage.setItem(`taskman:refresh:${apiUrl}`, token);
  }
}

export async function loadRefreshToken(apiUrl: string): Promise<string | null> {
  if (isTauri()) {
    return invoke<string | null>("load_secret", { apiUrl });
  }
  return localStorage.getItem(`taskman:refresh:${apiUrl}`);
}

export interface VaultFile {
  path: string;
  content: string;
  modified_ms: number;
}

export async function scanVault(root: string): Promise<VaultFile[]> {
  if (!isTauri()) return [];
  return invoke<VaultFile[]>("scan_vault", { root });
}

export async function writeVaultFile(root: string, path: string, content: string): Promise<void> {
  if (!isTauri()) return;
  await invoke("write_vault_file", { root, path, content });
}

export async function trashVaultFile(root: string, path: string): Promise<void> {
  if (!isTauri()) return;
  await invoke("trash_vault_file", { root, path });
}

export async function watchVault(root: string): Promise<void> {
  if (!isTauri()) return;
  await invoke("watch_vault", { root });
}
