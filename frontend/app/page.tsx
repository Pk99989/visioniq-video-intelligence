"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { API, api, apiPage, Stats, Video } from "@/lib/api";
import { Card, Empty, ErrorBox, Skeleton, SkeletonCard } from "@/components/ui";

export default function Dashboard() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<any>(null);
  useEffect(() => {
    apiPage<Video>("/api/v1/videos?limit=10").then((p) => setVideos(p.items)).catch((e) => setError(String(e.message)));
    api<Stats>("/api/v1/stats").then(setStats).catch(() => {});
    fetch(`${API}/health`).then((r) => r.json()).then(setHealth).catch(() => {});
  }, []);
  if (error) return <><ErrorBox error={error} /><p className="mt-4 text-sm">Sign in first: <Link href="/login" className="text-indigo-600">Login</Link></p></>;
  if (!videos) return <SkeletonCard lines={6} />;
  const ready = videos.filter((v) => v.status === "ready").length;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <div className="grid grid-cols-3 gap-4">
        <Card><p className="text-sm text-gray-500">Videos</p><p className="text-2xl font-bold">{stats ? stats.videos_total : videos.length}</p></Card>
        <Card><p className="text-sm text-gray-500">Ready</p><p className="text-2xl font-bold">{stats ? stats.videos_ready : ready}</p></Card>
        <Card><p className="text-sm text-gray-500">Processing / failed</p><p className="text-2xl font-bold">{stats ? stats.videos_processing + stats.videos_failed : videos.length - ready}</p></Card>
      </div>
      {stats ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <h2 className="font-semibold">Detections</h2>
            <p className="text-2xl font-bold">{stats.detections_total}</p>
            <p className="text-sm text-gray-500">{stats.detections_by_label.map((x) => `${x.label}: ${x.count}`).join(" · ") || "No detections yet."}</p>
          </Card>
          <Card>
            <h2 className="font-semibold">Library</h2>
            <p className="text-sm">Total duration: <b>{stats.total_duration_seconds.toFixed(1)}s</b></p>
            <p className="text-sm">Storage: <b>{(stats.total_storage_bytes / 1048576).toFixed(1)} MB</b></p>
            <p className="text-sm">Events: <b>{stats.events_total}</b> ({stats.events_verified} verified)</p>
            <p className="text-sm">Avg processing time: <b>{stats.avg_processing_seconds !== null ? `${stats.avg_processing_seconds.toFixed(1)}s (${stats.jobs_timed} jobs)` : "—"}</b></p>
          </Card>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>
      )}
      {health && <Card><p className="text-sm">VLM provider: <b>{health.vlm_provider}</b> · Detection available: <b>{String(health.detection?.available)}</b></p></Card>}
      <Card>
        <h2 className="font-semibold">Recent videos</h2>
        {videos.length === 0 ? <Empty text="No videos yet. Upload one to get started." /> : videos.map((v) => (
          <div key={v.id} className="flex justify-between border-t py-2 text-sm">
            <Link href={`/video/${v.id}`} className="text-indigo-600">{v.title}</Link>
            <span>{v.status}{v.duration_seconds ? ` · ${v.duration_seconds.toFixed(1)}s` : ""}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}
