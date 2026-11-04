"use client";
import { useState } from "react";
import { API, api, getToken } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Reports() {
  const [videoId, setVideoId] = useState("");
  const [kind, setKind] = useState("summary");
  const [format, setFormat] = useState("json");
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");

  async function create() {
    try {
      setReport(await api("/api/v1/reports", {
        method: "POST", body: JSON.stringify({ video_id: parseInt(videoId), kind, format }),
      }));
    } catch (e: any) { setError(String(e.message)); }
  }
  async function download() {
    const res = await fetch(`${API}/api/v1/reports/${report.id}/download`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `visioniq-report-${report.id}.${format}`; a.click();
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Reports</h1>
      <Card className="flex flex-wrap gap-2">
        <Input placeholder="Video ID" value={videoId} onChange={(e) => setVideoId(e.target.value)} />
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800">
          <option value="summary">Summary</option><option value="incident">Incident</option><option value="timeline">Timeline</option>
        </select>
        <select value={format} onChange={(e) => setFormat(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800">
          <option value="json">JSON</option><option value="pdf">PDF</option>
        </select>
        <Button onClick={create}>Generate report</Button>
      </Card>
      {error && <ErrorBox error={error} />}
      {report && (
        <Card>
          <p className="text-sm">Report #{report.id} ({report.kind}, {report.format})</p>
          <Button onClick={download}>Download</Button>
          <pre className="mt-3 overflow-auto text-xs">{JSON.stringify(report.data, null, 2)}</pre>
        </Card>
      )}
    </div>
  );
}
