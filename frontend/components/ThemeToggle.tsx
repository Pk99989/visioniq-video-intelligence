"use client";
import { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const saved = localStorage.getItem("visioniq_theme");
    setDark(saved !== "light");
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("visioniq_theme", dark ? "dark" : "light");
  }, [dark]);
  return (
    <button onClick={() => setDark(!dark)} className="rounded-lg border px-2 py-1 text-xs">
      {dark ? "☀ Light" : "☾ Dark"}
    </button>
  );
}
