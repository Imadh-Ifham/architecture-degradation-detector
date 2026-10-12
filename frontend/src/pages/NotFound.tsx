import { Link } from 'react-router'

export default function NotFound() {
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold tracking-tight text-white">
        Page not found
      </h1>
      <p className="text-slate-400">
        The page you are looking for does not exist.
      </p>
      <Link to="/" className="text-sm text-sky-400 transition hover:text-sky-300">
        Back to home
      </Link>
    </section>
  )
}
