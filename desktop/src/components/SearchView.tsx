import { FileText, Search, SquareCheckBig } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { NoteIndex, Task } from "../types";

interface Props {
  tasks: Task[];
  notes: NoteIndex[];
  onTask: (task: Task) => void;
  onNote: (id: string) => void;
}

export function SearchView({ tasks, notes, onTask, onNote }: Props) {
  const [query, setQuery] = useState("");
  const normalized = query.toLocaleLowerCase();
  const [remote, setRemote] = useState<{ tasks: Task[]; notes: NoteIndex[] } | null>(null);
  useEffect(() => {
    if (query.trim().length < 2) { setRemote(null); return; }
    const timer = window.setTimeout(() => {
      api.request<{ tasks: Task[]; notes: NoteIndex[] }>("/search", { query: { query: query.trim() } })
        .then(setRemote)
        .catch(() => setRemote(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  const localTasks = normalized ? tasks.filter((task) => `${task.title} ${task.description_markdown} ${task.tags.join(" ")}`.toLocaleLowerCase().includes(normalized)) : [];
  const localNotes = normalized ? notes.filter((note) => `${note.title} ${note.path} ${note.excerpt}`.toLocaleLowerCase().includes(normalized)) : [];
  const foundTasks = remote?.tasks ?? localTasks;
  const foundNotes = remote?.notes ?? localNotes;
  return <div className="search-view workspace-view"><header className="page-header"><div><p className="eyebrow">EVERYTHING</p><h1>Поиск</h1></div></header><div className="global-search"><Search size={21} /><input autoFocus placeholder="Задачи, заметки, теги, код…" value={query} onChange={(event) => setQuery(event.target.value)} /></div>{query && <div className="search-results"><section><p className="section-label">ЗАДАЧИ · {foundTasks.length}</p>{foundTasks.map((task) => <button key={task.id} onClick={() => onTask(task)}><SquareCheckBig size={17} /><span><b>{task.title}</b><small>{task.identifier} · {task.status}</small></span></button>)}</section><section><p className="section-label">ЗАМЕТКИ · {foundNotes.length}</p>{foundNotes.map((note) => <button key={note.id} onClick={() => onNote(note.id)}><FileText size={17} /><span><b>{note.title}</b><small>{note.path}</small></span></button>)}</section></div>}</div>;
}
