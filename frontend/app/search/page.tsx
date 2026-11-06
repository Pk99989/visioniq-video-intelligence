"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { API, api, apiPage, getToken, SearchHit, Video } from "@/lib/api";
import FrameImage from "@/components/FrameImage";
import { Button, Card, Empty, ErrorBox, Input, SkeletonCard } from "@/components/ui";

export default function Search() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState("");
  const [videos, setVideos] = useState<Video[]>([]);
  const [videoId, setVideoId] = useState("");
  const [label, setLabel] = useState("");
  const [provider, setProvider] = useState("");
  const [startSeconds, setStartSeconds] = useState("");
  const [endSeconds, setEndSeconds] = useState("");
  const [topK, setTopK] = useState("20");
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    apiPage<Video>("/api/v1/videos?limit=100").then((p) => setVideos(p.items)).catch(() => {});
  }, []);

  async function downloadClip(h: SearchHit) {
    const start = Math.max(0, h.timestamp_seconds - 2);
    const end = h.timestamp_seconds + 2;
    const res = await fetch(`${API}/api/v1/videos/${h.video_id}/clip?start=${start}&end=${end}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) { setError(`Clip download failed: ${res.status}`); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `clip_${h.video_id}_${start.toFixed(1)}-${end.toFixed(1)}.mp4`; a.click();
    URL.revokeObjectURL(url);
  }

  async function run() {
    setError("");
    setSearching(true);
    try {
      const body: any = { query, top_k: parseInt(topK) || 20 };
      if (videoId) body.video_id = parseInt(videoId);
      if (label.trim()) body.label = label.trim();
      if (provider) body.provider = provider;
      if (startSeconds !== "") body.start_seconds = parseFloat(startSeconds);
      if (endSeconds !== "") body.end_seconds = parseFloat(endSeconds);
      setHits(await api<SearchHit[]>("/api/v1/search", { method: "POST", body: JSON.stringify(body) }));
    } catch (e: any) { setError(String(e.message)); }
    finally { setSearching(false); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Semantic search</h1>
      <Card className="flex flex-wrap gap-2">
        <Input placeholder="Describe what you are looking for…" value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") run(); }} />
        <select value={videoId} onChange={(e) => setVideoId(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800" aria-label="Filter by video">
          <option value="">All videos</option>
          {videos.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
        </select>
        <Input placeholder="Label (e.g. bus)" value={label} onChange={(e) => setLabel(e.target.value)} />
        <select value={provider} onChange={(e) => setProvider(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800" aria-label="Filter by caption provider">
          <option value="">Any caption source</option>
          <option value="ollama">VLM (ollama)</option>
          <option value="detection">Detection only</option>
          <option value="fallback">Template</option>
        </select>
        <Input placeholder="From (seconds)" value={startSeconds} onChange={(e) => setStartSeconds(e.target.value)} />
        <Input placeholder="To (seconds)" value={endSeconds} onChange={(e) => setEndSeconds(e.target.value)} />
        <select value={topK} onChange={(e) => setTopK(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800" aria-label="Results per search">
          <option value="10">10 results</option>
          <option value="20">20 results</option>
          <option value="50">50 results</option>
        </select>
        <Button onClick={run} disabled={searching}>{searching ? "Searching…" : "Search"}</Button>
      </Card>
      {error && <ErrorBox error={error} />}
      {searching && <SkeletonCard lines={4} />}
      {!searching && hits && (hits.length === 0 ? <Empty text="No matches." /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {hits.map((h) => (
            <Card key={h.frame_id}>
              <FrameImage videoId={h.video_id} frameId={h.frame_id} alt={h.caption} />
              <p className="mt-2 text-sm">{h.caption}</p>
              <p className="text-xs text-gray-500">Score {h.score.toFixed(3)} · Detections: {h.detections.join(", ") || "none"}</p>
              <Link href={`/video/${h.video_id}?t=${h.timestamp_seconds}`} className="text-sm text-indigo-600">
                Open video at {h.timestamp_seconds.toFixed(1)}s →
              </Link>
              {" · "}
              <button onClick={() => downloadClip(h)} className="text-sm text-indigo-600">Download clip (±2s)</button>
            </Card>
          ))}
        </div>
      ))}
    </div>
  );
}
