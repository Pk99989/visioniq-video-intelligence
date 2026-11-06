"use client";
import { Component, ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-900 ${className}`}>{children}</div>;
}

export function Button({ children, onClick, disabled, type, ariaLabel }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; type?: "button" | "submit";
  ariaLabel?: string;
}) {
  return (
    <button type={type || "button"} onClick={onClick} disabled={disabled} aria-label={ariaLabel}
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

/** Pulsing placeholder blocks (Phase 8): pages show skeletons shaped
 *  like their content while data loads, instead of a bare "Loading…". */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-lg bg-gray-200 dark:bg-gray-800 ${className}`} />;
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <Card>
      <Skeleton className="h-5 w-1/3" />
      <div className="mt-3 space-y-2">
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton key={i} className={`h-4 ${i % 2 ? "w-2/3" : "w-full"}`} />
        ))}
      </div>
    </Card>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{error}</p>;
}

/** Catches render errors in a page instead of blanking the whole app
 *  (Phase 8). The user gets a message and a way back, not a white page. */
export class ErrorBoundary extends Component<
  { children: ReactNode; fallback?: ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: ReactNode; fallback?: ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    // eslint-disable-next-line no-console
    console.error("VisionIQ page error:", error);
  }

  render() {
    if (this.state.error) {
      return this.props.fallback || (
        <div className="space-y-4">
          <h1 className="text-2xl font-bold">Something went wrong</h1>
          <ErrorBox error={this.state.error.message || "This page failed to render."} />
          <Button onClick={() => this.setState({ error: null })}>Try again</Button>
        </div>
      );
    }
    return this.props.children;
  }
}
