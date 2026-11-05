export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("visioniq_token");
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });
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

export function frameImageUrl(videoId: number, frameId: number): string {
  // Images are served through the authenticated API, so the frontend
  // fetches them with the token and creates an object URL (see
  // components/FrameImage.tsx). This helper is kept for the video stream:
  return `${API}/api/v1/videos/${videoId}/stream`;
}
