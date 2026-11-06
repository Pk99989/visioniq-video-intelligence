/** Frontend unit tests (Phase 8): components/ui.tsx — skeletons,
 *  error box, error boundary.
 *
 *  Run: npm test (from frontend/)
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary, ErrorBox, Skeleton, SkeletonCard } from "./ui";

describe("ui primitives", () => {
  it("Skeleton renders a pulsing placeholder", () => {
    const { container } = render(<Skeleton className="h-4 w-full" />);
    expect(container.firstChild).toHaveClass("animate-pulse");
  });

  it("SkeletonCard renders a title block and body lines", () => {
    const { container } = render(<SkeletonCard lines={2} />);
    expect(container.querySelectorAll(".animate-pulse")).toHaveLength(3);
  });

  it("ErrorBox shows the error text", () => {
    render(<ErrorBox error="Something failed" />);
    expect(screen.getByText("Something failed")).toBeInTheDocument();
  });

  it("ErrorBoundary catches a render error and offers a retry", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Boom = () => { throw new Error("boom"); };
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
