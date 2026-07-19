import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudOff, RefreshCw, Wifi } from "lucide-react";
import { listen } from "@tauri-apps/api/event";
import { api, ApiError } from "./lib/api";
import { flushQueue, getQueue, queueMutation, readCache, saveCache } from "./lib/offline";
import { isTauri, watchVault, writeVaultFile } from "./lib/platform";
import { AuthScreen } from "./components/AuthScreen";
import { Sidebar } from "./components/Sidebar";
import { Kanban } from "./components/Kanban";
import { NotesWorkspace } from "./components/NotesWorkspace";
import { TaskInspector } from "./components/TaskInspector";
import { SettingsView } from "./components/SettingsView";
import { SearchView } from "./components/SearchView";
import { CommandPalette } from "./components/CommandPalette";
import { CreateDialog, type CreateKind } from "./components/CreateDialog";
import type { Backlink, Note, NoteIndex, Project, Task, TaskStatus, TelegramBot, TokenPair, ViewName } from "./types";

export default function App() {
  const queryClient = useQueryClient();
  const [booting, setBooting] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [view, setView] = useState<ViewName>("board");
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [queueSize, setQueueSize] = useState(getQueue().length);
  const [palette, setPalette] = useState(false);
  const [createKind, setCreateKind] = useState<CreateKind | null>(null);

  useEffect(() => {
    api.restore().then(setAuthenticated).finally(() => setBooting(false));
    const onlineHandler = () => {
      setOnline(true);
      void flushQueue().then(() => {
        setQueueSize(getQueue().length);
        void queryClient.invalidateQueries();
      });
    };
    const offlineHandler = () => setOnline(false);
    const queueHandler = (event: Event) => setQueueSize((event as CustomEvent<number>).detail);
    const keyboard = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); setPalette((value) => !value);
      }
      if (event.key === "Escape") setPalette(false);
    };
    window.addEventListener("online", onlineHandler);
    window.addEventListener("offline", offlineHandler);
    window.addEventListener("taskman:queue", queueHandler);
    window.addEventListener("keydown", keyboard);
    return () => {
      window.removeEventListener("online", onlineHandler); window.removeEventListener("offline", offlineHandler);
      window.removeEventListener("taskman:queue", queueHandler); window.removeEventListener("keydown", keyboard);
    };
  }, [queryClient]);

  useEffect(() => {
    const root = localStorage.getItem("taskman:vault");
    if (!authenticated || !root || !isTauri()) return;
    void watchVault(root);
    let timer = 0;
    const unlisten = listen("vault-changed", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => queryClient.invalidateQueries({ queryKey: ["notes"] }), 800);
    });
    return () => { void unlisten.then((callback) => callback()); window.clearTimeout(timer); };
  }, [authenticated, queryClient]);

  const projectsQuery = useQuery({
    queryKey: ["projects"], enabled: authenticated,
    queryFn: async () => { const data = await api.request<Project[]>("/projects"); saveCache("projects", data); return data; },
    initialData: () => readCache<Project[]>("projects", []),
  });
  const tasksQuery = useQuery({
    queryKey: ["tasks"], enabled: authenticated,
    queryFn: async () => { const data = await api.request<Task[]>("/tasks"); saveCache("tasks", data); return data; },
    initialData: () => readCache<Task[]>("tasks", []), refetchInterval: online ? 30_000 : false,
  });
  const notesQuery = useQuery({
    queryKey: ["notes"], enabled: authenticated,
    queryFn: async () => { const data = await api.request<NoteIndex[]>("/notes"); saveCache("notes", data); return data; },
    initialData: () => readCache<NoteIndex[]>("notes", []),
  });
  const botsQuery = useQuery({
    queryKey: ["bots"], enabled: authenticated && view === "settings",
    queryFn: () => api.request<TelegramBot[]>("/integrations/telegram/bots"), initialData: [],
  });
  const noteQuery = useQuery({
    queryKey: ["note", selectedNoteId], enabled: authenticated && Boolean(selectedNoteId),
    queryFn: () => api.request<Note>(`/notes/${selectedNoteId}`),
  });
  const backlinksQuery = useQuery({
    queryKey: ["backlinks", selectedNoteId], enabled: authenticated && Boolean(selectedNoteId),
    queryFn: () => api.request<Backlink[]>(`/notes/${selectedNoteId}/backlinks`), initialData: [],
  });

  async function authenticatedWith(tokens: TokenPair) {
    await api.acceptTokens(tokens);
    setAuthenticated(true);
  }

  const projects = projectsQuery.data || [];
  const allTasks = tasksQuery.data || [];
  const allNotes = notesQuery.data || [];
  const tasks = useMemo(() => allTasks.filter((task) => !selectedProject || task.project_id === selectedProject), [allTasks, selectedProject]);
  const notes = useMemo(() => allNotes.filter((note) => !selectedProject || note.project_id === selectedProject), [allNotes, selectedProject]);

  async function createProject(name: string, key: string) {
    await api.request("/projects", { method: "POST", body: { name, key, color: "#8b5cf6" } });
    await queryClient.invalidateQueries({ queryKey: ["projects"] });
  }

  async function createTask(title?: string, projectId: string | null = selectedProject) {
    if (!title) { setCreateKind("task"); return; }
    const actualTitle = title;
    if (!actualTitle) return;
    const optimistic: Task = {
      id: crypto.randomUUID(), identifier: "OFFLINE", project_id: projectId, parent_id: null,
      title: actualTitle, description_markdown: "", status: "inbox", priority: 1, due_at: null,
      tags: [], source: "desktop", version: 1, archived_at: null, checklist: [], comments: [],
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
    const body = { id: optimistic.id, title: actualTitle, project_id: projectId, source: "desktop" };
    queryClient.setQueryData<Task[]>(["tasks"], (old = []) => [optimistic, ...old]);
    try {
      const created = await api.request<Task>("/tasks", { method: "POST", body, headers: { "X-Operation-Id": crypto.randomUUID() } });
      queryClient.setQueryData<Task[]>(["tasks"], (old = []) => old.map((item) => item.id === optimistic.id ? created : item));
    } catch (error) {
      if (error instanceof ApiError && error.status === 0) queueMutation("POST", "/tasks", body);
      else { queryClient.setQueryData<Task[]>(["tasks"], (old = []) => old.filter((item) => item.id !== optimistic.id)); throw error; }
    }
  }

  async function moveTask(task: Task, status: TaskStatus) {
    const previous = allTasks;
    queryClient.setQueryData<Task[]>(["tasks"], (old = []) => old.map((item) => item.id === task.id ? { ...item, status, version: item.version + 1 } : item));
    const body = { base_version: task.version, status };
    try {
      const updated = await api.request<Task>(`/tasks/${task.id}`, { method: "PATCH", body, headers: { "X-Operation-Id": crypto.randomUUID() } });
      queryClient.setQueryData<Task[]>(["tasks"], (old = []) => old.map((item) => item.id === task.id ? updated : item));
    } catch (error) {
      if (error instanceof ApiError && error.status === 0) queueMutation("PATCH", `/tasks/${task.id}`, body);
      else { queryClient.setQueryData(["tasks"], previous); void queryClient.invalidateQueries({ queryKey: ["tasks"] }); }
    }
  }

  async function addComment(task: Task, bodyMarkdown: string) {
    await api.request(`/tasks/${task.id}/comments`, { method: "POST", body: { body_markdown: bodyMarkdown, source: "desktop" } });
    await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    setSelectedTask(await api.request<Task>(`/tasks/${task.id}`));
  }

  async function archiveTask(task: Task) {
    await api.request(`/tasks/${task.id}`, { method: "PATCH", body: { base_version: task.version, archived: true } });
    setSelectedTask(null);
    await queryClient.invalidateQueries({ queryKey: ["tasks"] });
  }

  async function createNote(title?: string) {
    if (!title) { setCreateKind("note"); return; }
    try {
      const created = await api.request<Note>("/notes", { method: "POST", body: { title, project_id: selectedProject, content_markdown: `# ${title}\n` } });
      setSelectedNoteId(created.id); setView("notes");
      await queryClient.invalidateQueries({ queryKey: ["notes"] });
    } catch (error) {
      const vault = localStorage.getItem("taskman:vault");
      if (error instanceof ApiError && error.status === 0 && vault) {
        await writeVaultFile(vault, `Inbox/${title.replace(/[<>:"/\\|?*]/g, "-")}.md`, `# ${title}\n`);
        window.alert("Заметка сохранена локально и будет отправлена при синхронизации.");
      } else throw error;
    }
  }

  async function saveNote(note: Note, content: string, title: string) {
    const updated = await api.request<Note>(`/notes/${note.id}`, { method: "PATCH", body: { base_revision: note.revision, title, content_markdown: content, device_id: "desktop-ui" } });
    queryClient.setQueryData(["note", note.id], updated);
    await queryClient.invalidateQueries({ queryKey: ["notes"] });
  }

  function openNote(id: string) { setSelectedNoteId(id); setView("notes"); }
  if (booting) return <main className="splash"><div className="brand-mark large">T</div><p>Загружаем контекст…</p></main>;
  if (!authenticated) return <AuthScreen onAuthenticated={authenticatedWith} />;
  return (
    <div className="app-shell">
      <Sidebar projects={projects} selectedProject={selectedProject} view={view} onProject={setSelectedProject} onView={setView} onCommand={() => setPalette(true)} onCreateProject={() => setCreateKind("project")} />
      <main className="main-surface">
        <div className="connection-pill">{online ? <Wifi size={13} /> : <CloudOff size={13} />} {online ? "Синхронизировано" : "Офлайн"}{queueSize > 0 && <b>{queueSize} в очереди</b>}{queueSize > 0 && online && <button onClick={() => void flushQueue().then(() => setQueueSize(getQueue().length))}><RefreshCw size={12} /></button>}</div>
        {view === "board" && <Kanban tasks={tasks} projects={projects} selectedProject={selectedProject} onMove={moveTask} onCreate={createTask} onSelect={setSelectedTask} />}
        {view === "notes" && <NotesWorkspace notes={notes} projects={projects} selectedProject={selectedProject} selected={noteQuery.data || null} backlinks={backlinksQuery.data} onSelect={setSelectedNoteId} onCreate={() => setCreateKind("note")} onSave={saveNote} />}
        {view === "search" && <SearchView tasks={allTasks} notes={allNotes} onTask={setSelectedTask} onNote={openNote} />}
        {view === "settings" && <SettingsView projects={projects} bots={botsQuery.data} onRefreshBots={() => void botsQuery.refetch()} />}
      </main>
      <TaskInspector task={selectedTask} onClose={() => setSelectedTask(null)} onComment={addComment} onArchive={archiveTask} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} onView={setView} onNewNote={() => setCreateKind("note")} onNewTask={() => setCreateKind("task")} />
      <CreateDialog
        kind={createKind}
        onClose={() => setCreateKind(null)}
        onSubmit={async (name, projectKey) => {
          if (createKind === "project") await createProject(name, projectKey || "PROJ");
          if (createKind === "task") await createTask(name);
          if (createKind === "note") await createNote(name);
        }}
      />
    </div>
  );
}
