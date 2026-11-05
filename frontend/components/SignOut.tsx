"use client";
import { useRouter } from "next/navigation";
import { API, getToken } from "@/lib/api";

export default function SignOut() {
  const router = useRouter();
  async function signOut() {
    const token = getToken();
    if (token) {
      await fetch(`${API}/api/v1/auth/logout`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
    localStorage.removeItem("visioniq_token");
    router.push("/login");
  }
  return <button onClick={signOut} className="text-sm text-indigo-600">Sign out</button>;
}
