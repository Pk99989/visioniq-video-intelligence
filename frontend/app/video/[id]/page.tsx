"use client";
import { useEffect, useRef, useState } from "react";
import { API, api, getToken, Video } from "@/lib/api";
import FrameImage from "@/components/FrameImage";
import { Card, Empty, ErrorBox, Loading } from "@/components/ui";

type Scene = { id: number; index: number; start_seconds: number; end_seconds: number };
type Caption = { id: number; timestamp_seconds: number; text: string; provider: string; frame_id: number | null };
type Frame = { id: number; timestamp_seconds: number; scene_id: number | null; image_url: string };
type Detection = { id: number; frame_id: number; track_id: number | null; label: string; confidence: number; timestamp_seconds: number; x1: number; y1: number; x2: number; y2: number };
type Analytics = { detection_count: number; detections_by_label: Record<string, number>; top_labels: { label: string; count: number }[] };

export default function VideoPage({ params, searchParams }: {
  params: { id: string }; searchParams: { t?: string };
}) {
  // Next 14 passes params/searchParams as plain objects, NOT Promises.
  // The previous code used React's use() on them (a Next 15 pattern),
  // which threw a client-side exception on the video page.
  const { id } = params;
  const sp = searchParams;
  const videoRef = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<Video | null>(null);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // The pipeline writes scenes + frames first, then captions (after
    // detection), then sets status=ready. Opening the page mid-processing
    // used to show scenes/frames but an empty Captions box forever,
    // because nothing refetched. Poll until the video is ready.
    let stopped = false;
    const loadAll = () => {
      api<Video>(`/api/v1/videos/${id}`).then((v) => { if (!stopped) setVideo(v); })
        .catch((e) => setError(String(e.message)));
      api<Scene[]>(`/api/v1/videos/${id}/scenes`).then((s) => { if (!stopped) setScenes(s); }).catch(() => {});
      api<Caption[]>(`/api/v1/videos/${id}/captions`).then((c) => { if (!stopped) setCaptions(c); }).catch(() => {});
      api<Frame[]>(`/api/v1/videos/${id}/frames`).then((f) => { if (!stopped) setFrames(f); }).catch(() => {});
      api<Detection[]>(`/api/v1/videos/${id}/detections`).then((d) => { if (!stopped) setDetections(d); }).catch(() => {});
      api<Analytics>(`/api/v1/videos/${id}/analytics`).then((a) => { if (!stopped) setAnalytics(a); }).catch(() => {});
    };
    loadAll();
    // Phase 3: use the signed stream URL so the <video> tag can seek
    // with HTTP Range requests (206) instead of a blob fetch.
    api<{ url: string }>(`/api/v1/videos/${id}/stream-url`)
      .then((d) => { if (!stopped) setStreamUrl(`${API}${d.url}`); })
      .catch(() => {
        fetch(`${API}/api/v1/videos/${id}/stream`, { headers: { Authorization: `Bearer ${getToken()}` } })
          .then((r) => r.blob()).then((b) => { if (!stopped) setStreamUrl(URL.createObjectURL(b)); }).catch(() => {});
      });
    const timer = setInterval(() => {
      // Stop polling once ready/failed; the video state drives this.
      setVideo((v) => {
        if (v && v.status !== "processing" && v.status !== "uploaded") {
          clearInterval(timer);
        } else {
          loadAll();
        }
        return v;
      });
    }, 3000);
    return () => { stopped = true; clearInterval(timer); };
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
        {captions.length === 0 && <Empty text="No captions yet (video may still be processing — this page refreshes automatically)." />}
        {captions.map((c) => (
          <p key={c.id} className="border-t py-1 text-sm">
            <button className="text-indigo-600" onClick={() => seek(c.timestamp_seconds)}>{c.timestamp_seconds.toFixed(1)}s</button>
            {" "}{c.text} <span className="text-gray-500">({c.provider})</span>
          </p>
        ))}
      </Card>
      <Card>
        <h2 className="font-semibold">Detections {analytics ? `(${analytics.detection_count})` : ""}</h2>
        {analytics && analytics.top_labels.length > 0 ? (
          <p className="text-sm text-gray-500">{analytics.top_labels.map((x) => `${x.label}: ${x.count}`).join(" · ")}</p>
        ) : <Empty text="No detections yet (run YOLO, or video may still be processing)." />}
        {detections.slice(0, 20).map((d) => (
          <p key={d.id} className="border-t py-1 text-sm">
            <button className="text-indigo-600" onClick={() => seek(d.timestamp_seconds)}>{d.timestamp_seconds.toFixed(1)}s</button>
            {" "}{d.label} {d.confidence.toFixed(2)}{d.track_id !== null ? ` · track #${d.track_id}` : ""}
          </p>
        ))}
        {detections.length > 20 && <p className="text-xs text-gray-500">Showing first 20 of {detections.length} detections.</p>}
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
