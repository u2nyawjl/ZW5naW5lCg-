// Cliente de la API del gateway (Vercel). El token del dashboard NO se compila en el
// bundle: lo escribe el usuario en el login y vive en localStorage.

const API_BASE = "https://u2scribe-gateway.vercel.app";
const TOKEN_KEY = "u2s_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function req<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (resp.status === 401) throw new Error("401");
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export interface StatusResp {
  agent_core: string;
  honeypot: string;
  last_heartbeat: { at: string; trigger: string; conclusion: string; url: string } | null;
}
export interface LogEvent {
  ts: string; type: string; level: string; message: string; url?: string;
}
export interface VaultEntry { name: string; path: string; type: string; }
export type VaultResp =
  | { type: "folder"; entries: VaultEntry[] }
  | { type: "file"; path: string; content: string };
export interface FileRow {
  filename: string; sha256: string; mime: string; vt_status: string;
  vt_detections: string; decision: string; drive_link: string;
  drive_id?: string; note_path: string;
}

export async function fetchFileBlob(driveId: string): Promise<Blob> {
  const resp = await fetch(`${API_BASE}/api/file?id=${encodeURIComponent(driveId)}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.blob();
}

export function driveIdFromLink(link: string): string {
  const m = link.match(/\/d\/([^/]+)/);
  return m ? m[1] : "";
}
export interface CalEvent {
  id: string; summary: string; start: string; end: string;
  all_day: boolean; location: string; link: string;
}
export interface Person {
  email: string; name: string; role: string;
  first_seen?: string; last_seen?: string; sources?: string[];
}
export interface ServiceRow { name: string; status: string; detail: string; }
export interface ChatMsg { role: "user" | "assistant"; content: string; }

export interface ChatResp { reply: string; conversation_id: string; title: string; }
export interface Conversation { id: string; title: string; updated: string; messages: ChatMsg[]; }

export async function chat(messages: ChatMsg[], model?: string, conversationId?: string): Promise<ChatResp> {
  const resp = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    body: JSON.stringify({ messages, model, conversation_id: conversationId }),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export async function convAction(action: "delete" | "rename", id: string, title?: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/conv`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    body: JSON.stringify({ action, id, title }),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
}

export async function listModels(): Promise<{ models: string[]; default: string }> {
  return req<{ models: string[]; default: string }>("/api/models");
}

export async function compileLatex(tex: string): Promise<Blob> {
  const resp = await fetch(`${API_BASE}/api/latex`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    body: JSON.stringify({ tex }),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.blob();
}

export async function writeVault(path: string, content: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/vault/${path}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
}

export const api = {
  status: () => req<StatusResp>("/api/status"),
  logs: () => req<{ events: LogEvent[] }>("/api/logs"),
  services: () => req<{ services: ServiceRow[] }>("/api/services"),
  vault: (path: string) => req<VaultResp>(`/api/vault/${path}`),
  writeVault,
  files: async (): Promise<FileRow[]> => {
    const r = await req<VaultResp>("/api/vault/files/manifest.json");
    if (r.type !== "file") return [];
    try { return JSON.parse(r.content); } catch { return []; }
  },
  timeline: async (): Promise<LogEvent[]> => {
    const day = new Date().toISOString().slice(0, 10);
    try {
      const r = await req<VaultResp>(`/api/vault/timeline/${day}.json`);
      if (r.type === "file") return JSON.parse(r.content);
    } catch { /* aún no hay timeline hoy */ }
    return [];
  },
  calendar: () => req<{ events: CalEvent[] }>("/api/calendar"),
};
