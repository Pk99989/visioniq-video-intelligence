"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { API, api, Video } from "@/lib/api";
import { Card, Empty, ErrorBox, Loading } from "@/components/ui";

export default function Dashboard() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<any>(null);
  useEffect(() => {
    api<Video[]>("/api/v1/videos").then(setVideos).catch((e) => setError(String(e.message)));
    fetch(`${API}/health`).then((r) => r.json()).then(setHealth).catch(() => {});
  }, []);
  if (error) return <><ErrorBox error={error} /><p className="mt-4 text-sm">Sign in first: <Link href="/login" className="text-indigo-600">Login</Link></p></>;
  if (!videos) return <Loading />;
  const ready = videos.filter((v) => v.status === "ready").length;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <div className="grid grid-cols-3 gap-4">
        <Card><p className="text-sm text-gray-500">Videos</p><p className="text-2xl font-bold">{videos.length}</p></Card>
        <Card><p className="text-sm text-gray-500">Ready</p><p className="text-2xl font-bold">{ready}</p></Card>
        <Card><p className="text-sm text-gray-500">Processing / failed</p><p className="text-2xl font-bold">{videos.length - ready}</p></Card>
      </div>
      {health && <Card><p className="text-sm">VLM provider: <b>{health.vlm_provider}</b> · Detection available: <b>{String(health.detection?.available)}</b></p></Card>}
      <Card>
        <h2 className="font-semibold">Recent videos</h2>
        {videos.length === 0 ? <Empty text="No videos yet. Upload one to get started." /> : videos.slice(0, 10).map((v) => (
          <div key={v.id} className="flex justify-between border-t py-2 text-sm">
            <Link href={`/video/${v.id}`} className="text-indigo-600">{v.title}</Link>
            <span>{v.status}{v.duration_seconds ? ` · ${v.duration_seconds.toFixed(1)}s` : ""}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}
