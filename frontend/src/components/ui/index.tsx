/**
 * Shared primitives.
 *
 * Description:
 *   The small pieces every screen is built from. They take tokens and props
 *   and nothing else - no fetching, no routing, no knowledge of which screen
 *   they are on - so a screen can be read in isolation and a redesign is a
 *   change here rather than a change everywhere.
 *
 *   Kept in one file deliberately. Eight components of fifteen lines each in
 *   eight files is a directory nobody reads; when one of them grows past
 *   that, it moves out on its own.
 */

import type { ReactNode } from 'react'

type Tone = 'neutral' | 'ok' | 'warn' | 'bad' | 'ai'

const TONE_CLASS: Record<Tone, string> = {
  neutral: 'border-line-strong text-ink-2',
  ok: 'border-ok/60 bg-ok-wash text-ok',
  warn: 'border-warn/60 bg-warn-wash text-warn',
  bad: 'border-bad/60 bg-bad-wash text-bad',
  ai: 'border-ai/60 bg-ai-wash text-ai',
}

/** A state, as a word and a colour. Never a colour alone. */
export function Pill({
  tone = 'neutral',
  children,
}: {
  tone?: Tone
  children: ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-xs whitespace-nowrap ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  )
}

/** A panel. Borders mark a thing as separate, so they are used sparingly. */
export function Card({
  title,
  action,
  children,
  className = '',
}: {
  title?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-card border border-line bg-panel ${className}`}
    >
      {(title || action) && (
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-7 py-4">
          {typeof title === 'string' ? (
            <h2 className="text-sm font-semibold">{title}</h2>
          ) : (
            title
          )}
          {action}
        </header>
      )}
      <div className="p-7">{children}</div>
    </section>
  )
}

/** One number, with what it counts and where it came from. */
export function Stat({
  label,
  value,
  note,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  tone?: Tone
}) {
  // Written out rather than interpolated: a class name built at runtime is a
  // class name the stylesheet was never told to generate.
  const valueTone = {
    neutral: 'text-ink',
    ok: 'text-ok',
    warn: 'text-warn',
    bad: 'text-bad',
    ai: 'text-ai',
  }[tone]

  return (
    <div className="flex flex-col gap-1.5 px-7 py-6">
      <span className="text-xs tracking-wide text-ink-3">{label}</span>
      <span className={`font-mono text-3xl leading-none ${valueTone}`}>{value}</span>
      {note && <span className="text-xs text-ink-4">{note}</span>}
    </div>
  )
}

/** A row of stats, hairline-separated rather than boxed individually. */
export function StatRow({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-4 [&>*]:bg-panel">
      {children}
    </div>
  )
}

export function Button({
  variant = 'secondary',
  size = 'base',
  type = 'button',
  disabled,
  onClick,
  children,
}: {
  variant?: 'primary' | 'secondary' | 'quiet'
  size?: 'base' | 'sm'
  type?: 'button' | 'submit'
  disabled?: boolean
  onClick?: () => void
  children: ReactNode
}) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-control font-medium transition disabled:cursor-not-allowed disabled:opacity-40'
  const sizing = size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2.5 text-sm'
  const look = {
    primary: 'bg-ink text-field hover:opacity-90',
    secondary: 'border border-line-strong bg-raised text-ink hover:border-ink-4',
    quiet: 'text-ink-2 hover:text-ink',
  }[variant]

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`${base} ${sizing} ${look}`}
    >
      {children}
    </button>
  )
}

/** A labelled input. The label is a real label, so the hit target is both. */
export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-xs tracking-wide text-ink-2">{label}</span>
      {children}
      {hint && <span className="text-xs text-ink-4">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full rounded-control border border-line-strong bg-sunken px-3.5 py-2.5 font-mono text-sm text-ink placeholder:text-ink-4 focus:border-ai focus:outline-none'

/** What a screen says when it has nothing, and why that is not a failure. */
export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-start gap-3 px-2 py-10">
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="max-w-prose text-sm leading-relaxed text-ink-3">{body}</p>
      {action}
    </div>
  )
}

/** A failure, with the backend's own words and a way to ask again. */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-control border border-bad/40 bg-bad-wash px-5 py-4">
      <p className="text-sm text-bad">{message}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2.5 text-sm text-ink-3">
      <span className="size-3 animate-spin rounded-full border-[1.5px] border-ai border-t-transparent" />
      {label}
    </span>
  )
}

/** Tabs that switch a view, not a route. */
export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly { id: T; label: string; count?: number }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          type="button"
          aria-selected={tab.id === active}
          onClick={() => onChange(tab.id)}
          className={`rounded-control px-3.5 py-1.5 text-sm transition ${
            tab.id === active
              ? 'bg-raised text-ink'
              : 'text-ink-3 hover:text-ink-2'
          }`}
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="ml-2 font-mono text-xs text-ink-4">{tab.count}</span>
          )}
        </button>
      ))}
    </div>
  )
}

/** The page title block. One per screen, always in the same place. */
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string
  title: string
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-6">
      <div className="flex max-w-prose flex-col gap-2">
        {eyebrow && (
          <span className="font-mono text-xs tracking-wide text-ink-4">{eyebrow}</span>
        )}
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="text-sm leading-relaxed text-ink-3">{description}</p>
        )}
      </div>
      {action}
    </header>
  )
}
