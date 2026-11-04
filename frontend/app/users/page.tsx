"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, ErrorBox, Loading } from "@/components/ui";

export default function Users() {
  const [users, setUsers] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<any[]>("/api/v1/auth/users").then(setUsers).catch((e) => setError(String(e.message))); }, []);
  if (error) return <><ErrorBox error={error} /><p className="mt-4 text-sm text-gray-500">User management is admin-only. Non-admin accounts get a 403 from the API.</p></>;
  if (!users) return <Loading />;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">User management</h1>
      <Card>
        {users.map((u) => <p key={u.id} className="border-t py-2 text-sm">{u.email} — {u.role}</p>)}
      </Card>
    </div>
  );
}
