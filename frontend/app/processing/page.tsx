"use client";
import { useEffect, useState } from "react";
import { api, apiPage, Video } from "@/lib/api";
import { Button, Card, Empty, ErrorBox, SkeletonCard } from "@/components/ui";

const PAGE_SIZE = 20;

export default function Processing() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const load = () => apiPage<Video>(`/api/v1/videos?limit=${PAGE_SIZE}&offset=0`)
    .then((p) => { setVideos(p.items); setTotal(p.total); })
    .catch((e) => setError(String(e.message)));

  useEffect(() => {
    load();
    // Phase 8: the page watches every video, so it polls every 5 s,
    // but it stops polling once nothing is still processing.
    const t = setInterval(() => {
      apiPage<Video>(`/api/v1/videos?limit=${PAGE_SIZE}&offset=0`).then((p) => {
        setVideos(p.items);
        setTotal(p.total);
        if (!p.items.some((v) => v.status === "processing" || v.status === "uploaded")) {
          clearInterval(t);
        }
      }).catch(() => {});
    }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!videos) return <SkeletonCard lines={6} />;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Processing</h1>
      <p className="text-sm text-gray-500">This page refreshes every 5 seconds while anything is processing, then stops. Failed jobs can be retried here; interrupted jobs are marked failed on server restart so they never stay stuck.</p>
      <Card>
        {videos.length === 0 ? <Empty text="No videos yet." /> : videos.map((v) => (
          <div key={v.id} className="flex items-center justify-between border-t py-2 text-sm">
            <span>{v.title} — <b>{v.status}</b>{v.error_message ? ` — ${v.error_message}` : ""}</span>
            {v.status === "failed" && <Button onClick={async () => { await api(`/api/v1/videos/${v.id}/retry`, { method: "POST" }); load(); }}>Retry</Button>}
          </div>
        ))}
      </Card>
      {total > PAGE_SIZE && <p className="text-sm text-gray-500">Showing first {videos.length} of {total} videos.</p>}
    </div>
  );
}
