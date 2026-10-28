"use client";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 bg-zinc-950 p-6 text-center text-zinc-100">
      <p role="alert" className="text-base text-zinc-200">
        Something went wrong showing this result.
      </p>
      <button
        type="button"
        onClick={() => reset()}
        className="min-h-11 rounded-xl bg-indigo-500 px-6 text-base font-semibold text-white transition hover:bg-indigo-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
      >
        Try again
      </button>
    </main>
  );
}
