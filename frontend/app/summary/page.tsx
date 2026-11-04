"use client";
import { useEffect, useState } from "react";
import { api, Video } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Summary() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [videoId, setVideoId] = useState("");
  const [length, setLength] = useState("medium");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<Video[]>("/api/v1/videos").then(setVideos).catch((e) => setError(String(e.message))); }, []);
  async function run() {
    try { setResult(await api(`/api/v1/videos/${videoId}/summary?length=${length}`)); }
    catch (e: any) { setError(String(e.message)); }
  }
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Video summaries</h1>
      <Card className="flex flex-wrap gap-2">
        <Input placeholder="Video ID" value={videoId} onChange={(e) => setVideoId(e.target.value)} />
        <select value={length} onChange={(e) => setLength(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800">
          <option value="short">Short</option><option value="medium">Medium</option><option value="long">Long</option>
        </select>
        <Button onClick={run}>Summarise</Button>
      </Card>
      {error && <ErrorBox error={error} />}
      {videos.length > 0 && <p className="text-xs text-gray-500">Your videos: {videos.map((v) => `${v.id} = ${v.title}`).join(" · ")}</p>}
      {result && (
        <Card>
          <p className="whitespace-pre-wrap text-sm">{result.summary}</p>
          <div className="mt-3 border-t pt-2">
            <p className="text-xs font-semibold">Timeline ({result.scene_count} scenes)</p>
            {result.timeline.map((t: any, i: number) => (
              <p key={i} className="text-xs text-gray-600 dark:text-gray-400">{t.start_seconds.toFixed(1)}s – {t.end_seconds.toFixed(1)}s: {t.text.slice(0, 200)}</p>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
