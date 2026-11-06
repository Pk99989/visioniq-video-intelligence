"use client";
import { useEffect, useRef, useState } from "react";
import { API, getToken } from "@/lib/api";

/** Authenticated frame image: the API checks video ownership, so the
 *  <img> src cannot be a plain URL — fetch with the token instead.
 *
 *  Phase 8 (L7): the blob URL is tracked in a ref and revoked when a
 *  new frame loads or the component unmounts. The old code revoked
 *  `url` from the effect closure, which was still null on the first
 *  run — every frame image leaked its object URL. */
export default function FrameImage({ videoId, frameId, alt, annotated = false }: {
  videoId: number; frameId: number; alt: string; annotated?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const urlRef = useRef<string | null>(null);
  useEffect(() => {
    let alive = true;
    const endpoint = annotated ? "annotated" : "image";
    fetch(`${API}/api/v1/videos/${videoId}/frames/${frameId}/${endpoint}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
      .then((r) => r.blob())
      .then((b) => {
        if (!alive) return;
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        const next = URL.createObjectURL(b);
        urlRef.current = next;
        setUrl(next);
      })
      .catch(() => {});
    return () => {
      alive = false;
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, [videoId, frameId, annotated]);
  if (!url) return <div className="flex h-32 items-center justify-center bg-gray-100 text-xs text-gray-500 dark:bg-gray-800">frame…</div>;
  return <img src={url} alt={alt} className="h-32 w-full object-cover" />;
}
