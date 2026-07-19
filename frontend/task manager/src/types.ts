export type TaskStatus = "inbox" | "todo" | "in_progress" | "blocked" | "done";

export interface SetupState {
  setup_required: boolean;
}

export interface User {
  id: string;
  username: string;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
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
  created_at: string;
  updated_at: string;
}

export interface ChecklistItem {
  id: string;
  text: string;
  is_done: boolean;
  position: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Comment {
  id: string;
  body_markdown: string;
  source: string;
  source_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  title: string;
  description_markdown: string;
  project_id: string | null;
  parent_id: string | null;
  sequence: number | null;
  status: TaskStatus;
  priority: number;
  due_at: string | null;
  completed_at: string | null;
  tags: string[];
  source: string;
  source_data: Record<string, unknown>;
  version: number;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  checklist: ChecklistItem[];
  comments: Comment[];
  identifier: string;
}

export interface SavedView {
  id: string;
  name: string;
  filters: Record<string, unknown>;
  position: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Dashboard {
  inbox: number;
  todo: number;
  in_progress: number;
  blocked: number;
  done: number;
  overdue: number;
}

export interface WorkspaceBootstrap {
  server_time: string;
  user: User;
  users: User[];
  projects: Project[];
  tasks: Task[];
  views: SavedView[];
  dashboard: Dashboard;
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
