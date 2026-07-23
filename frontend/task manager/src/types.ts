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
  parent_id: string | null;
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

export interface PublicNote {
  title: string;
  path: string;
  content_markdown: string;
  updated_at: string;
}

export interface NoteShare {
  token: string;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface KnowledgeGraphNode {
  id: string;
  kind: "task" | "note";
  title: string;
  subtitle: string;
  tags: string[];
  status: TaskStatus | null;
  priority: number | null;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  kind: "task_note" | "subtask" | "note_link";
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

export interface DirectAccount {
  id: string;
  name: string;
  client_login: string | null;
  token_hint: string;
  enabled: boolean;
  balance_threshold: string | number;
  days_left_threshold: string | number;
  anomaly_ratio: string | number;
  monitor_interval_minutes: number;
  last_checked_at: string | null;
  last_error: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface MaxBot {
  id: string;
  name: string;
  token_hint: string;
  allowlist: number[];
  target_type: string | null;
  target_id: number | null;
  enabled: boolean;
  last_error: string | null;
  version: number;
  webhook_url: string;
  created_at: string;
  updated_at: string;
}

export interface MaxBotCreated extends MaxBot {
  webhook_secret: string;
}
