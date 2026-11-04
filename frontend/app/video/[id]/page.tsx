"use client";
import { use, useEffect, useRef, useState } from "react";
import { API, api, getToken, Video } from "@/lib/api";
import FrameImage from "@/components/FrameImage";
import { Card, Empty, ErrorBox, Loading } from "@/components/ui";

type Scene = { id: number; index: number; start_seconds: number; end_seconds: number };
type Caption = { id: number; timestamp_seconds: number; text: string; provider: string; frame_id: number | null };
type Frame = { id: number; timestamp_seconds: number; scene_id: number | null; image_url: string };

export default function VideoPage({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<{ t?: string }>;
}) {
  const { id } = use(params);
  const sp = use(searchParams);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<Video | null>(null);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Video>(`/api/v1/videos/${id}`).then(setVideo).catch((e) => setError(String(e.message)));
    api<Scene[]>(`/api/v1/videos/${id}/scenes`).then(setScenes).catch(() => {});
    api<Caption[]>(`/api/v1/videos/${id}/captions`).then(setCaptions).catch(() => {});
    api<Frame[]>(`/api/v1/videos/${id}/frames`).then(setFrames).catch(() => {});
    fetch(`${API}/api/v1/videos/${id}/stream`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => r.blob()).then((b) => setStreamUrl(URL.createObjectURL(b))).catch(() => {});
  }, [id]);

  useEffect(() => {
    if (sp.t && videoRef.current) videoRef.current.currentTime = parseFloat(sp.t);
  }, [sp, streamUrl]);

  const seek = (t: number) => { if (videoRef.current) { videoRef.current.currentTime = t; videoRef.current.play().catch(() => {}); } };
  if (error) return <ErrorBox error={error} />;
  if (!video) return <Loading />;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{video.title}</h1>
      <p className="text-sm text-gray-500">Status: {video.status}{video.duration_seconds ? ` · ${video.duration_seconds.toFixed(1)}s` : ""}</p>
      {streamUrl
        ? <video ref={videoRef} src={streamUrl} controls className="w-full rounded-xl bg-black" />
        : <p className="text-sm text-gray-500">Loading video stream…</p>}
      <Card>
        <h2 className="font-semibold">Scenes — click a timestamp to seek</h2>
        {scenes.length === 0 ? <Empty text="No scenes yet (video may still be processing)." /> : scenes.map((s) => (
          <p key={s.id} className="border-t py-1 text-sm">
            <button className="text-indigo-600" onClick={() => seek(s.start_seconds)}>Scene {s.index + 1}: {s.start_seconds.toFixed(1)}s – {s.end_seconds.toFixed(1)}s</button>
          </p>
        ))}
      </Card>
      <Card>
        <h2 className="font-semibold">Captions</h2>
        {captions.map((c) => (
          <p key={c.id} className="border-t py-1 text-sm">
            <button className="text-indigo-600" onClick={() => seek(c.timestamp_seconds)}>{c.timestamp_seconds.toFixed(1)}s</button>
            {" "}{c.text} <span className="text-gray-500">({c.provider})</span>
          </p>
        ))}
      </Card>
      <Card>
        <h2 className="font-semibold">Evidence frames</h2>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {frames.map((f) => (
            <button key={f.id} onClick={() => seek(f.timestamp_seconds)} className="text-left">
              <FrameImage videoId={video.id} frameId={f.id} alt={`Frame at ${f.timestamp_seconds}s`} />
              <p className="text-xs">{f.timestamp_seconds.toFixed(1)}s</p>
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}
