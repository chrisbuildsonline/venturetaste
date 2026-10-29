"use client";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 p-6 text-center text-zinc-100">
      <p role="alert" className="text-base text-zinc-200">
        Something went wrong showing this result.
      </p>
      <button
        type="button"
        onClick={() => reset()}
        className="btn btn-primary"
      >
        Try again
      </button>
    </main>
  );
}
