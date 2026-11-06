export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("visioniq_token");
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include", // sends the httpOnly refresh cookie (Phase 9, M13)
    headers: {
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      ...(init.headers || {}),
    },
  });
  if (res.status === 401 && !path.startsWith("/api/v1/auth/") && !(init as any)._retried) {
    // Access tokens live 60 minutes (M13). Try the refresh cookie
    // once, then retry the original call with the new token.
    try {
      const refreshed = await api<{ access_token: string }>("/api/v1/auth/refresh", {
        method: "POST",
      });
      localStorage.setItem("visioniq_token", refreshed.access_token);
      return request(path, { ...init, _retried: true } as RequestInit);
    } catch {
      // Refresh failed — fall through and report the original 401.
    }
  }
  return res;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await request(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      const d = j.detail;
      // FastAPI 422 detail is a list; stringify it so callers never
      // receive an object/array they might try to render directly.
      detail = Array.isArray(d)
        ? d.map((x: any) => `${(x.loc || []).join(".")}: ${x.msg}`).join("; ")
        : (d || JSON.stringify(j));
    } catch { /* keep statusText */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type Video = {
  id: number; title: string; original_filename: string;
  duration_seconds: number | null; width: number | null; height: number | null;
  status: string; error_message: string | null;
};

export type SearchHit = {
  video_id: number; frame_id: number; timestamp_seconds: number;
  score: number; caption: string; frame_path: string | null; detections: string[];
};

export type Stats = {
  videos_total: number; videos_ready: number; videos_processing: number; videos_failed: number;
  total_duration_seconds: number; total_storage_bytes: number;
  detections_total: number; detections_by_label: { label: string; count: number }[];
  events_total: number; events_verified: number;
  avg_processing_seconds: number | null; jobs_timed: number;
};

export type Conversation = { id: number; title: string; video_id: number | null };
export type ChatMessage = { role: string; content: string };

export type VideoEvent = {
  id: number; rule_name: string; title: string; severity: string;
  timestamp_seconds: number; verified: boolean; description: string;
  zone_name: string | null; track_id: number | null; label: string | null;
  evidence_frame_id: number | null; evidence_clip_url: string | null;
};

/** Paginated list (Phase 8 / L10): the backend keeps the list shape
 *  and puts the total in the X-Total-Count header. */
export async function apiPage<T>(path: string): Promise<{ items: T[]; total: number }> {
  const res = await request(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = Array.isArray(j.detail) ? JSON.stringify(j.detail) : (j.detail || JSON.stringify(j));
    } catch { /* keep statusText */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  const items = (await res.json()) as T[];
  const raw = res.headers.get("x-total-count");
  const total = raw === null ? items.length : parseInt(raw, 10);
  return { items, total: Number.isNaN(total) ? items.length : total };
}

export function frameImageUrl(videoId: number, frameId: number): string {
  // Images are served through the authenticated API, so the frontend
  // fetches them with the token and creates an object URL (see
  // components/FrameImage.tsx). This helper is kept for the video stream:
  return `${API}/api/v1/videos/${videoId}/stream`;
}
