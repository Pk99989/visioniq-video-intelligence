"use client";
import { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900 ${className}`}>{children}</div>;
}

export function Button({ children, onClick, disabled, type }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; type?: "button" | "submit";
}) {
  return (
    <button type={type || "button"} onClick={onClick} disabled={disabled}
      className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props}
    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-800" />;
}

export function Empty({ text }: { text: string }) {
  return <p className="py-8 text-center text-sm text-gray-500">{text}</p>;
}

export function Loading({ text = "Loading…" }: { text?: string }) {
  return <p className="py-8 text-center text-sm text-gray-500">{text}</p>;
}

export function ErrorBox({ error }: { error: string }) {
  return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</p>;
}
