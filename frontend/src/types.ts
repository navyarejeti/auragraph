// AuraGraph shared TypeScript types
// Used by hooks, components, and pages.

export type Proficiency = 'Foundations' | 'Practitioner' | 'Expert';

export interface Notebook {
  id: string;
  name: string;
  course: string;
  note?: string;
  proficiency?: Proficiency;
  graph?: { nodes: NotebookNode[]; edges: NotebookEdge[] };
  created_at?: string;
  updated_at?: string;
}

export interface NotebookNode {
  id: string;
  label: string;
  status?: 'unknown' | 'partial' | 'mastered';
  x?: number;
  y?: number;
}

export interface NotebookEdge {
  source: string;
  target: string;
  label?: string;
}

export interface Doubt {
  id: number;
  pageIdx: number;
  doubt: string;
  insight: string;
  gap?: string;
  source?: string;
  time: string;
  success: boolean;
  unresolved?: boolean;
  kind?: 'mutated' | 'answered';
}

export interface Section {
  id: string;
  notebook_id: string;
  title: string;
  note_type: 'topic' | 'chapter';
  content?: string;
  order?: number;
}

export interface PromptSpec {
  name: string;
  template: string;
  default_vars?: Record<string, string>;
  version?: string;
}

export interface UndoEntry {
  note: string;
  prof: Proficiency;
  label: string;
  expireAt: number;
}

export type ViewMode = 'single' | 'two' | 'scroll';
export type RightTab = 'map' | 'doubts' | 'contents';
export type NoteSource = 'azure' | 'local' | 'groq';
