"use client";
import { useEffect, useState } from "react";
import { api, Video } from "@/lib/api";
import { Button, Card, Empty, ErrorBox, Loading } from "@/components/ui";

export default function Processing() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api<Video[]>("/api/v1/videos").then(setVideos).catch((e) => setError(String(e.message)));
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!videos) return <Loading />;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Processing</h1>
      <p className="text-sm text-gray-500">This page refreshes every 5 seconds. Failed jobs can be retried here; interrupted jobs are marked failed on server restart so they never stay stuck.</p>
      <Card>
        {videos.length === 0 ? <Empty text="No videos yet." /> : videos.map((v) => (
          <div key={v.id} className="flex items-center justify-between border-t py-2 text-sm">
            <span>{v.title} — <b>{v.status}</b>{v.error_message ? ` — ${v.error_message}` : ""}</span>
            {v.status === "failed" && <Button onClick={async () => { await api(`/api/v1/videos/${v.id}/retry`, { method: "POST" }); load(); }}>Retry</Button>}
          </div>
        ))}
      </Card>
    </div>
  );
}
