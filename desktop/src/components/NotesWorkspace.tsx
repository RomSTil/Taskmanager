import DOMPurify from "dompurify";
import { marked } from "marked";
import { Braces, FilePlus2, PanelLeftClose, Save, Search, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import type { Backlink, Note, NoteIndex, Project } from "../types";
import { MarkdownEditor } from "./MarkdownEditor";

type EditorMode = "visual" | "raw" | "split";

interface Props {
  notes: NoteIndex[];
  projects: Project[];
  selectedProject: string | null;
  selected: Note | null;
  backlinks: Backlink[];
  onSelect: (id: string) => void;
  onCreate: () => void;
  onSave: (note: Note, markdown: string, title: string) => Promise<void>;
}

export function NotesWorkspace({ notes, selected, backlinks, onSelect, onCreate, onSave }: Props) {
  const [mode, setMode] = useState<EditorMode>("visual");
  const [markdown, setMarkdown] = useState("");
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setMarkdown(selected?.content_markdown || "");
    setTitle(selected?.title || "");
  }, [selected?.id, selected?.revision]);
  async function save() {
    if (!selected) return;
    setSaving(true);
    try { await onSave(selected, markdown, title); } finally { setSaving(false); }
  }
  const filtered = notes.filter((note) => !query || `${note.title} ${note.path}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="notes-layout">
      <aside className="note-list-pane">
        <header><div><p className="eyebrow">VAULT</p><h1>Заметки</h1></div><button className="icon-button" aria-label="Создать заметку" onClick={onCreate}><FilePlus2 size={18} /></button></header>
        <div className="note-search"><Search size={15} /><input placeholder="Фильтр заметок" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
        <div className="note-list">
          {filtered.map((note) => (
            <button key={note.id} className={selected?.id === note.id ? "note-row active" : "note-row"} onClick={() => onSelect(note.id)}>
              <span>{note.conflict_of_id && <b className="conflict-badge">!</b>}{note.title}</span>
              <small>{note.path}</small>
              <p>{note.excerpt || "Пустая заметка"}</p>
            </button>
          ))}
        </div>
      </aside>
      {selected ? (
        <main className="note-editor-pane">
          <header className="editor-header">
            <input className="note-title-input" value={title} onChange={(event) => setTitle(event.target.value)} />
            <div className="mode-switch">
              <button className={mode === "visual" ? "active" : ""} onClick={() => setMode("visual")}><Sparkles size={15} /> Visual</button>
              <button className={mode === "raw" ? "active" : ""} onClick={() => setMode("raw")}><Braces size={15} /> Markdown</button>
              <button className={mode === "split" ? "active" : ""} onClick={() => setMode("split")}><PanelLeftClose size={15} /> Split</button>
            </div>
            <button className="primary-button compact" onClick={save} disabled={saving}><Save size={15} />{saving ? "Сохранение" : "Сохранить"}</button>
          </header>
          <div className={`editor-body mode-${mode}`}>
            {mode === "visual" && <MarkdownEditor value={markdown} onChange={setMarkdown} />}
            {(mode === "raw" || mode === "split") && <textarea className="raw-editor" value={markdown} onChange={(event) => setMarkdown(event.target.value)} spellCheck={false} />}
            {mode === "split" && <article className="markdown-preview" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(markdown) as string) }} />}
          </div>
        </main>
      ) : <main className="empty-state"><FilePlus2 size={28} /><h2>Выберите заметку</h2><p>Или создайте новый Markdown-документ.</p></main>}
      <aside className="context-pane">
        <p className="section-label">СВОЙСТВА</p>
        {selected && <><dl><dt>Путь</dt><dd>{selected.path}</dd><dt>Ревизия</dt><dd>{selected.revision}</dd><dt>Размер</dt><dd>{Math.ceil(selected.size_bytes / 1024)} KB</dd></dl><p className="section-label">ОБРАТНЫЕ ССЫЛКИ · {backlinks.length}</p>{backlinks.map((item) => <button className="backlink" key={item.id} onClick={() => onSelect(item.id)}><b>[[{item.title}]]</b><span>{item.excerpt}</span></button>)}</>}
      </aside>
    </div>
  );
}
