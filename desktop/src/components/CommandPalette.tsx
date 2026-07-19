import { BookPlus, ClipboardPlus, Search, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import type { ViewName } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  onView: (view: ViewName) => void;
  onNewNote: () => void;
  onNewTask: () => void;
}

export function CommandPalette({ open, onClose, onView, onNewNote, onNewTask }: Props) {
  const [query, setQuery] = useState("");
  useEffect(() => { if (open) setQuery(""); }, [open]);
  if (!open) return null;
  const commands = [
    { label: "Создать задачу", icon: ClipboardPlus, action: onNewTask },
    { label: "Создать заметку", icon: BookPlus, action: onNewNote },
    { label: "Открыть поиск", icon: Search, action: () => onView("search") },
    { label: "Открыть настройки", icon: Settings, action: () => onView("settings") },
  ].filter((item) => item.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <div className="palette-backdrop" onMouseDown={onClose}><div className="command-palette" onMouseDown={(event) => event.stopPropagation()}><div><Search size={18} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Введите команду…" /></div>{commands.map(({ label, icon: Icon, action }) => <button key={label} onClick={() => { action(); onClose(); }}><Icon size={17} />{label}<kbd>↵</kbd></button>)}</div></div>;
}
