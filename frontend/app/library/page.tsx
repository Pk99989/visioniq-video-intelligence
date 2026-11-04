"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Video } from "@/lib/api";
import { Button, Card, Empty, ErrorBox, Loading } from "@/components/ui";

export default function Library() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api<Video[]>("/api/v1/videos").then(setVideos).catch((e) => setError(String(e.message)));
  useEffect(() => { load(); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!videos) return <Loading />;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Video library</h1>
      <Card>
        {videos.length === 0 ? <Empty text="No videos yet." /> : videos.map((v) => (
          <div key={v.id} className="flex items-center justify-between border-t py-2 text-sm">
            <Link href={`/video/${v.id}`} className="text-indigo-600">{v.title} <span className="text-gray-500">({v.original_filename})</span></Link>
            <span className="flex items-center gap-3">
              <span>{v.status}{v.duration_seconds ? ` · ${v.duration_seconds.toFixed(1)}s` : ""}</span>
              <Button onClick={async () => { await api(`/api/v1/videos/${v.id}`, { method: "DELETE" }); load(); }}>Delete</Button>
            </span>
          </div>
        ))}
      </Card>
    </div>
  );
}
