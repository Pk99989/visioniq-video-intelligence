"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { API } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const router = useRouter();

  async function submit(mode: "login" | "register") {
    setError("");
    // Client-side check first, so a short password gives a readable
    // message instead of a 422 from the API.
    if (!email.includes("@")) { setError("Enter a valid email address."); return; }
    if (mode === "register" && password.length < 8) {
      setError("Password must be at least 8 characters long."); return;
    }
    const res = await fetch(`${API}/api/v1/auth/${mode}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      // FastAPI validation errors (422) return detail as a LIST of
      // objects. Rendering that list directly crashed React with a
      // client-side exception, so always convert it to a string first.
      const detail = data.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: any) => `${(d.loc || []).join(".")}: ${d.msg}`).join("; ")
        : (detail || "Request failed");
      setError(String(msg));
      return;
    }
    if (mode === "register") { await submit("login"); return; }
    localStorage.setItem("visioniq_token", data.access_token);
    router.push("/");
  }

  return (
    <Card className="mx-auto max-w-md space-y-3">
      <h1 className="text-xl font-bold">Sign in to VisionIQ</h1>
      {error && <ErrorBox error={error} />}
      <Input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <Input placeholder="Password (min 8 characters)" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <div className="flex gap-2">
        <Button onClick={() => submit("login")}>Sign in</Button>
        <Button onClick={() => submit("register")}>Create account</Button>
      </div>
      <p className="text-xs text-gray-500">Passwords are hashed server-side (PBKDF2) and never stored in plain text. Tokens are stored only in your browser.</p>
    </Card>
  );
}
