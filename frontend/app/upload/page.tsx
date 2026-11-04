"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { API, getToken } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Upload() {
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const router = useRouter();

  async function submit() {
    if (!file || !title) { setError("Title and a video file are required."); return; }
    setError(""); setDone("");
    const form = new FormData();
    form.append("title", title);
    form.append("file", file);
    const res = await fetch(`${API}/api/v1/videos/upload`, {
      method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setError(data.detail || "Upload failed"); return; }
    setDone(`Uploaded video #${data.id}. Processing runs in the background — check Processing for its status.`);
    setTimeout(() => router.push("/processing"), 1500);
  }

  return (
    <Card className="mx-auto max-w-lg space-y-3">
      <h1 className="text-xl font-bold">Upload video</h1>
      {error && <ErrorBox error={error} />}
      {done && <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-700">{done}</p>}
      <Input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <input type="file" accept=".mp4,.mov,.webm,.mkv,.avi" onChange={(e) => setFile(e.target.files?.[0] || null)} className="text-sm" />
      <p className="text-xs text-gray-500">Supported: mp4, mov, webm, mkv, avi. Default size limit 500 MB (MAX_UPLOAD_MB on the server).</p>
      <Button onClick={submit}>Upload and process</Button>
    </Card>
  );
}
