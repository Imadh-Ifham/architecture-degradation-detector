/**
 * What can be done with the ranking on screen: share it, take it away, print it.
 *
 * Description:
 *   The link copies the exact view (ranking, comparison, opened row). The
 *   report downloads as the saved JSON, unchanged; the ranking as a CSV built
 *   from that same report, one row per ranked event with every part's value,
 *   weight and share. The printable report is the standalone page the backend
 *   wrote next to the JSON, so a printout is the same document as the file.
 */

import { useState } from 'react'
import { Button } from '../../components/ui'
import { runFileUrl, type SeverityReportV1 } from '../../lib/api'
import { rankingCsv } from './csv'

export default function RunActions({ report }: { report: SeverityReportV1 }) {
  const [copied, setCopied] = useState(false)

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const downloadCsv = () => {
    const blob = new Blob([rankingCsv(report)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${report.run_id}-ranking.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <Button size="sm" variant="quiet" onClick={() => void copyLink()}>
        {copied ? 'Link copied' : 'Copy link to this view'}
      </Button>
      <a
        href={runFileUrl(report.run_id, 'c4_report.json')}
        download={`${report.run_id}-report.json`}
        className={linkClass}
      >
        Download report (JSON)
      </a>
      <Button size="sm" variant="quiet" onClick={downloadCsv}>
        Download ranking (CSV)
      </Button>
      <a
        href={runFileUrl(report.run_id, 'c4_report.html')}
        target="_blank"
        rel="noreferrer"
        className={linkClass}
      >
        Printable report ↗
      </a>
    </div>
  )
}

const linkClass =
  'inline-flex items-center rounded-control px-3 py-1.5 text-xs font-medium text-ink-2 transition hover:bg-raised hover:text-ink'
