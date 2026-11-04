"use client";
import { useEffect, useState } from "react";
import { API, getToken } from "@/lib/api";

/** Authenticated frame image: the API checks video ownership, so the
 *  <img> src cannot be a plain URL — fetch with the token instead. */
export default function FrameImage({ videoId, frameId, alt }: {
  videoId: number; frameId: number; alt: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API}/api/v1/videos/${videoId}/frames/${frameId}/image`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => r.blob())
      .then((b) => { if (alive) setUrl(URL.createObjectURL(b)); })
      .catch(() => {});
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, frameId]);
  if (!url) return <div className="flex h-32 items-center justify-center bg-gray-100 text-xs text-gray-500 dark:bg-gray-800">frame…</div>;
  return <img src={url} alt={alt} className="h-32 w-full object-cover" />;
}
