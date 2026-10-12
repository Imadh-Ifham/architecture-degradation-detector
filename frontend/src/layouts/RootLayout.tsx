import { Link, Outlet } from 'react-router'

export default function RootLayout() {
  return (
    <div className="flex min-h-svh flex-col bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between gap-4 px-6 py-4">
          <Link
            to="/"
            className="text-sm font-semibold tracking-tight transition hover:text-sky-400"
          >
            Architecture Degradation Detector
          </Link>
          <span className="text-xs text-slate-500">Research System</span>
        </div>
      </header>
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">
        <Outlet />
      </main>
    </div>
  )
}
