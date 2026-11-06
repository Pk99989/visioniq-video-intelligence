"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, apiPage, Video } from "@/lib/api";
import { Button, Card, Empty, ErrorBox, SkeletonCard } from "@/components/ui";

const PAGE_SIZE = 20;

export default function Library() {
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");

  const load = (off: number) => {
    apiPage<Video>(`/api/v1/videos?limit=${PAGE_SIZE}&offset=${off}`)
      .then((p) => { setVideos(p.items); setTotal(p.total); setOffset(off); })
      .catch((e) => setError(String(e.message)));
  };
  useEffect(() => { load(0); }, []);

  if (error) return <ErrorBox error={error} />;
  if (!videos) return <SkeletonCard lines={6} />;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Video library</h1>
      <Card>
        {videos.length === 0 ? <Empty text="No videos yet." /> : videos.map((v) => (
          <div key={v.id} className="flex items-center justify-between border-t py-2 text-sm">
            <Link href={`/video/${v.id}`} className="text-indigo-600">{v.title} <span className="text-gray-500">({v.original_filename})</span></Link>
            <span className="flex items-center gap-3">
              <span>{v.status}{v.duration_seconds ? ` · ${v.duration_seconds.toFixed(1)}s` : ""}</span>
              <Button onClick={async () => { await api(`/api/v1/videos/${v.id}`, { method: "DELETE" }); load(offset); }}>Delete</Button>
            </span>
          </div>
        ))}
      </Card>
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <Button disabled={offset === 0} onClick={() => load(Math.max(0, offset - PAGE_SIZE))}>← Previous</Button>
          <span>Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
          <Button disabled={offset + PAGE_SIZE >= total} onClick={() => load(offset + PAGE_SIZE)}>Next →</Button>
        </div>
      )}
    </div>
  );
}
