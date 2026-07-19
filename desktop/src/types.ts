export type TaskStatus = "inbox" | "todo" | "in_progress" | "blocked" | "done";

export interface User {
  id: string;
  username: string;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_at: string;
  user: User;
}

export interface Project {
  id: string;
  name: string;
  key: string;
  description: string;
  color: string;
  version: number;
  archived_at: string | null;
}

export interface ChecklistItem {
  id: string;
  text: string;
  is_done: boolean;
  position: number;
  version: number;
}

export interface Comment {
  id: string;
  body_markdown: string;
  source: string;
  created_at: string;
}

export interface Task {
  id: string;
  identifier: string;
  project_id: string | null;
  parent_id: string | null;
  title: string;
  description_markdown: string;
  status: TaskStatus;
  priority: number;
  due_at: string | null;
  tags: string[];
  source: string;
  version: number;
  archived_at: string | null;
  checklist: ChecklistItem[];
  comments: Comment[];
  created_at: string;
  updated_at: string;
}

export interface NoteIndex {
  id: string;
  project_id: string | null;
  path: string;
  title: string;
  tags: string[];
  revision: number;
  content_hash: string;
  excerpt: string;
  size_bytes: number;
  deleted_at: string | null;
  conflict_of_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Note extends NoteIndex {
  content_markdown: string;
}

export interface Backlink {
  id: string;
  title: string;
  path: string;
  excerpt: string;
}

export interface TelegramBot {
  id: string;
  name: string;
  project_id: string | null;
  token_hint: string;
  allowlist: number[];
  enabled: boolean;
  last_error: string | null;
  version: number;
  webhook_url: string;
}

export type ViewName = "board" | "notes" | "search" | "settings";
