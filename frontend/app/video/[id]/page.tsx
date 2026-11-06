"use client";
import { useEffect, useRef, useState } from "react";
import { API, api, apiPage, getToken, Video, VideoEvent } from "@/lib/api";
import FrameImage from "@/components/FrameImage";
import { Button, Card, Empty, ErrorBox, Input, Loading, SkeletonCard } from "@/components/ui";

type Scene = { id: number; index: number; start_seconds: number; end_seconds: number };
type Caption = { id: number; timestamp_seconds: number; text: string; provider: string; frame_id: number | null };
type Frame = { id: number; timestamp_seconds: number; scene_id: number | null; image_url: string };
type Detection = { id: number; frame_id: number; track_id: number | null; label: string; confidence: number; timestamp_seconds: number; x1: number; y1: number; x2: number; y2: number };
type Analytics = { detection_count: number; detections_by_label: Record<string, number>; top_labels: { label: string; count: number }[] };
type Trajectory = { track_id: number; label: string; first_seen_seconds: number; last_seen_seconds: number; dwell_seconds: number; frames_seen: number; displacement_px: number };

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
  const [events, setEvents] = useState<VideoEvent[]>([]);
  const [trajectories, setTrajectories] = useState<Trajectory[]>([]);
  const [showTracks, setShowTracks] = useState(false);
  const [clipStart, setClipStart] = useState("");
  const [clipEnd, setClipEnd] = useState("");
  const [clipError, setClipError] = useState("");
  const [error, setError] = useState("");

  const loadAll = () => {
    api<Video>(`/api/v1/videos/${id}`).then(setVideo).catch((e) => setError(String(e.message)));
    api<Scene[]>(`/api/v1/videos/${id}/scenes`).then(setScenes).catch(() => {});
    api<Caption[]>(`/api/v1/videos/${id}/captions`).then(setCaptions).catch(() => {});
    apiPage<Frame>(`/api/v1/videos/${id}/frames?limit=100`).then((p) => setFrames(p.items)).catch(() => {});
    apiPage<Detection>(`/api/v1/videos/${id}/detections?limit=100`).then((p) => setDetections(p.items)).catch(() => {});
    api<Analytics>(`/api/v1/videos/${id}/analytics`).then(setAnalytics).catch(() => {});
    apiPage<VideoEvent>(`/api/v1/videos/${id}/events?limit=50`).then((p) => setEvents(p.items)).catch(() => {});
    api<Trajectory[]>(`/api/v1/videos/${id}/trajectories`).then(setTrajectories).catch(() => {});
  };

  useEffect(() => {
    loadAll();
    // Phase 3: use the signed stream URL so the <video> tag can seek
    // with HTTP Range requests (206) instead of a blob fetch.
    api<{ url: string }>(`/api/v1/videos/${id}/stream-url`)
      .then((d) => { setStreamUrl(`${API}${d.url}`); })
      .catch(() => {
        fetch(`${API}/api/v1/videos/${id}/stream`, { headers: { Authorization: `Bearer ${getToken()}` } })
          .then((r) => r.blob()).then((b) => { setStreamUrl(URL.createObjectURL(b)); }).catch(() => {});
      });
    // Phase 8: live status over SSE, with the old 3 s polling as the
    // fallback when EventSource fails (older browsers, proxies that
    // buffer SSE). Either path stops once the video is ready/failed.
    let timer: ReturnType<typeof setInterval> | null = null;
    let source: EventSource | null = null;
    const startPolling = () => {
      if (timer) return;
      timer = setInterval(() => {
        api<Video>(`/api/v1/videos/${id}`).then((v) => {
          setVideo(v);
          if (v.status !== "processing" && v.status !== "uploaded") {
            if (timer) clearInterval(timer);
            loadAll();
          } else {
            loadAll();
          }
        }).catch(() => {});
      }, 3000);
    };
    const token = getToken();
    if (typeof EventSource !== "undefined" && token) {
      source = new EventSource(`${API}/api/v1/videos/${id}/status-stream?token=${token}`);
      source.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          setVideo((v) => (v ? { ...v, status: data.status, error_message: data.error_message ?? v.error_message } : v));
          if (data.status === "ready" || data.status === "failed") {
            source?.close();
            loadAll();
          }
        } catch { /* ignore a malformed event */ }
      };
      source.onerror = () => { source?.close(); startPolling(); };
    } else {
      startPolling();
    }
    return () => { if (source) source.close(); if (timer) clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (sp.t && videoRef.current) videoRef.current.currentTime = parseFloat(sp.t);
  }, [sp, streamUrl]);

  const seek = (t: number) => { if (videoRef.current) { videoRef.current.currentTime = t; videoRef.current.play().catch(() => {}); } };

  async function downloadClip() {
    setClipError("");
    const start = parseFloat(clipStart);
    const end = parseFloat(clipEnd);
    if (Number.isNaN(start) || Number.isNaN(end) || end <= start) {
      setClipError("Enter a start and end in seconds, with end after start (max 120s).");
      return;
    }
    const res = await fetch(`${API}/api/v1/videos/${id}/clip?start=${start}&end=${end}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) { setClipError(`Clip download failed: ${res.status}`); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `clip_${id}_${start}-${end}.mp4`; a.click();
    URL.revokeObjectURL(url);
  }

  if (error) return <ErrorBox error={error} />;
  if (!video) return <SkeletonCard lines={6} />;
  const duration = video.duration_seconds || 0;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{video.title}</h1>
      <p className="text-sm text-gray-500">Status: {video.status}{duration ? ` · ${duration.toFixed(1)}s` : ""}</p>
      {streamUrl
        ? <video ref={videoRef} src={streamUrl} controls className="w-full rounded-xl bg-black" />
        : <p className="text-sm text-gray-500">Loading video stream…</p>}
      {events.length > 0 && duration > 0 && (
        <Card>
          <h2 className="font-semibold">Event timeline — click a marker to seek</h2>
          <div className="relative mt-3 h-6 rounded bg-gray-200 dark:bg-gray-800" role="group" aria-label="Event timeline">
            {events.map((e) => (
              <button key={e.id} onClick={() => seek(e.timestamp_seconds)}
                title={`${e.title} at ${e.timestamp_seconds.toFixed(1)}s${e.verified ? " (verified)" : ""}`}
                aria-label={`${e.title} at ${e.timestamp_seconds.toFixed(1)} seconds`}
                className={`absolute top-1 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-white ${e.severity === "warning" ? "bg-amber-500" : e.verified ? "bg-green-600" : "bg-indigo-600"}`} style={{ left: `${Math.min(100, (e.timestamp_seconds / duration) * 100)}%` }} />
            ))}
          </div>
          <div className="mt-2 space-y-1">
            {events.map((e) => (
              <p key={e.id} className="border-t py-1 text-sm">
                <button className="text-indigo-600" onClick={() => seek(e.timestamp_seconds)}>{e.timestamp_seconds.toFixed(1)}s</button>
                {" "}{e.title}{e.verified ? " ✓" : ""}{e.evidence_clip_url ? (
                  <> · <a className="text-indigo-600" href={`${API}${e.evidence_clip_url}`}>evidence clip</a></>
                ) : null}
              </p>
            ))}
          </div>
        </Card>
      )}
      <Card>
        <h2 className="font-semibold">Clip download</h2>
        <div className="mt-2 flex flex-wrap gap-2">
          <Input placeholder="Start (seconds)" value={clipStart} onChange={(e) => setClipStart(e.target.value)} />
          <Input placeholder="End (seconds)" value={clipEnd} onChange={(e) => setClipEnd(e.target.value)} />
          <Button onClick={downloadClip}>Download clip</Button>
        </div>
        {clipError && <div className="mt-2"><ErrorBox error={clipError} /></div>}
      </Card>
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
      {trajectories.length > 0 && (
        <Card>
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Tracks ({trajectories.length})</h2>
            <Button onClick={() => setShowTracks(!showTracks)} ariaLabel="Toggle detection boxes on evidence frames">
              {showTracks ? "Hide boxes" : "Show boxes"}
            </Button>
          </div>
          {trajectories.map((t) => (
            <p key={t.track_id} className="border-t py-1 text-sm">
              Track #{t.track_id} ({t.label}): {t.first_seen_seconds.toFixed(1)}s – {t.last_seen_seconds.toFixed(1)}s,
              dwell {t.dwell_seconds.toFixed(1)}s, {t.frames_seen} frames
            </p>
          ))}
        </Card>
      )}
      <Card>
        <h2 className="font-semibold">Evidence frames{showTracks ? " (with detection boxes)" : ""}</h2>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {frames.map((f) => (
            <button key={f.id} onClick={() => seek(f.timestamp_seconds)} className="text-left">
              <FrameImage videoId={video.id} frameId={f.id} alt={`Frame at ${f.timestamp_seconds}s`} annotated={showTracks} />
              <p className="text-xs">{f.timestamp_seconds.toFixed(1)}s</p>
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}
