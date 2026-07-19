import { BookOpenText, Boxes, Command, Plus, Search, Settings, Sparkles } from "lucide-react";
import type { Project, ViewName } from "../types";

interface Props {
  projects: Project[];
  selectedProject: string | null;
  view: ViewName;
  onProject: (id: string | null) => void;
  onView: (view: ViewName) => void;
  onCommand: () => void;
  onCreateProject: () => void;
}

export function Sidebar({ projects, selectedProject, view, onProject, onView, onCommand, onCreateProject }: Props) {
  const navigation = [
    { id: "board" as const, label: "Задачи", icon: Boxes },
    { id: "notes" as const, label: "Заметки", icon: BookOpenText },
    { id: "search" as const, label: "Поиск", icon: Search },
  ];
  return (
    <aside className="sidebar">
      <div className="sidebar-brand"><div className="brand-mark">T</div><span>Taskman</span></div>
      <nav className="nav-section">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button key={id} className={view === id ? "nav-item active" : "nav-item"} onClick={() => onView(id)}>
            <Icon size={17} /> {label}
          </button>
        ))}
      </nav>
      <div className="section-label"><span>ПРОЕКТЫ</span><button className="bare-icon" aria-label="Создать проект" onClick={onCreateProject}><Plus size={14} /></button></div>
      <nav className="project-list">
        <button className={selectedProject === null ? "project-row active" : "project-row"} onClick={() => onProject(null)}>
          <span className="project-dot all" /> Все проекты
        </button>
        {projects.map((project) => (
          <button key={project.id} className={selectedProject === project.id ? "project-row active" : "project-row"} onClick={() => onProject(project.id)}>
            <span className="project-dot" style={{ background: project.color }} />
            <span>{project.name}</span>
            <small>{project.key}</small>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <button className={view === "settings" ? "nav-item active" : "nav-item"} onClick={() => onView("settings")}>
          <Settings size={17} /> Настройки
        </button>
        <button className="command-hint" onClick={onCommand}><Command size={15} /> Команды <kbd>Ctrl K</kbd></button>
      </div>
    </aside>
  );
}
