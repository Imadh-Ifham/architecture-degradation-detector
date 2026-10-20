/**
 * One component, as the artifacts describe it.
 *
 * Description:
 *   Everything recovery recorded about a single element, in the order a
 *   reader needs it: what it is, how it was found, the files that identify it,
 *   and the files inside it.
 *
 *   **Two kinds of number, kept apart.** `files`, `languages` and `file_count`
 *   were extracted by the inventory and discovery stages. Incoming, outgoing
 *   and total are counted here from the graph that is on screen, which is the
 *   only place they can be counted consistently with what is drawn.
 *
 *   **Read as a data sheet, not a dashboard.** Hairline rules instead of
 *   boxes, one type size per rank of information, and colour only where it
 *   carries a fact: a value that is declared rather than inferred, an
 *   artifact that is missing. A protocol tag is not purple, because purple
 *   means a model was involved and a manifest is not a model.
 *
 *   Long lists are collapsed rather than truncating silently: a component with
 *   four hundred files is a real fact about a repository, and hiding the
 *   four hundredth while claiming to show them is the thing to avoid.
 */

import { useState } from "react";
import { Pill } from "../../components/ui";
import type {
  ArchitectureDetails,
  DiscoveryEvidence,
  ElementDetails,
  ElementFile,
  SnapshotEvidenceEntry,
} from "../../lib/api";

const COLLAPSED = 8;

/**
 * How a value was established, said in one word and one tone.
 *
 * Direct and confirmed are the same claim made by two stages: a file names
 * the thing. Heuristic and inferred mean structure suggested it. The tone is
 * the only colour either carries, which is why it is confined to this.
 */
function confidenceTone(value: string | null | undefined): "ok" | "warn" | "neutral" {
  if (value === "direct" || value === "confirmed") return "ok";
  if (value === "heuristic" || value === "inferred") return "warn";
  return "neutral";
}

export interface ElementGraphStats {
  incoming: number;
  outgoing: number;
  protocols: string[];
}

export default function ComponentDetail({
  element,
  stats,
  details,
}: {
  element: ElementDetails;
  stats: ElementGraphStats;
  details: ArchitectureDetails | null;
}) {
  const detected = element.detected;

  return (
    <div className="flex flex-col divide-y divide-line">
      <Section title="Identity">
        <Specs>
          <Fact label="identifier" value={element.id} mono />
          <Fact label="type" value={detected.type ?? element.kind} mono />
          <Fact
            label="root path"
            value={detected.root_path ?? "not recorded"}
            mono
            missing={!detected.root_path}
          />
          <Fact
            label="identity"
            value={
              element.logical_id ? (
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[13px] text-ink">
                    {element.logical_id}
                  </span>
                  <Pill tone={confidenceTone(element.identity_basis)}>
                    {element.identity_basis}
                  </Pill>
                </span>
              ) : (
                "no cross-release identity"
              )
            }
            mono
            missing={!element.logical_id}
          />
        </Specs>
      </Section>

      <Section title="How it was identified">
        <Specs>
          <Fact
            label="method"
            value={detected.method ?? "not recorded"}
            mono
            missing={!detected.method}
          />
          <Fact
            label="confidence"
            value={
              detected.confidence ? (
                <Pill tone={confidenceTone(detected.confidence)}>
                  {detected.confidence}
                </Pill>
              ) : (
                "not recorded"
              )
            }
            mono
            missing={!detected.confidence}
          />
          <Fact
            label="size"
            value={
              element.size !== null
                ? `${element.size} ${element.size_unit ?? ""}`.trim()
                : "not measured"
            }
            mono
            missing={element.size === null}
          />
          <Fact
            label="inventory kind"
            value={detected.inventory_kind ?? "not recorded"}
            mono
            missing={!detected.inventory_kind}
          />
        </Specs>

        {element.discovery_evidence.length > 0 && (
          <Evidence
            title="Discovery rules that fired"
            items={element.discovery_evidence.map(evidenceLine)}
          />
        )}

        {element.artifacts.length > 0 && (
          <div className="flex flex-col gap-3">
            <SubLabel>Artifacts that named it</SubLabel>
            <ul className="flex flex-col divide-y divide-line rounded-control border border-line">
              {element.artifacts.map((artifact) => (
                <li
                  key={artifact.id}
                  className="flex flex-wrap items-baseline gap-x-4 gap-y-1.5 px-4 py-2.5"
                >
                  <code className="font-mono text-[12px] break-all text-ink">
                    {artifact.path}
                  </code>
                  <span className="font-mono text-[10.5px] tracking-wide text-ink-4">
                    {[
                      artifact.kind?.replace(/_/g, " "),
                      artifact.role?.replace(/_/g, " "),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                  {artifact.confidence && (
                    <span className="ml-auto">
                      <Pill tone={confidenceTone(artifact.confidence)}>
                        {artifact.confidence}
                      </Pill>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <Section title="Files">
        <Specs>
          <Fact
            label="files"
            value={detected.file_count ?? element.files.length}
            note="extracted by the inventory"
          />
          <Fact
            label="source files"
            value={element.source_file_count}
            note="extracted by the inventory"
          />
          <Fact
            label="languages"
            value={
              element.languages.length > 0
                ? element.languages.join(", ")
                : "none detected"
            }
            note="extracted from source files"
            missing={element.languages.length === 0}
          />
          <Fact
            label="in / out"
            value={`${stats.incoming} / ${stats.outgoing}`}
            note="counted from this graph"
          />
        </Specs>

        {stats.protocols.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <SubLabel>Protocols on its dependencies</SubLabel>
            {stats.protocols.map((protocol) => (
              <Tag key={protocol}>{protocol}</Tag>
            ))}
          </div>
        )}

        {element.files.length > 0 ? (
          <FileList files={element.files} />
        ) : (
          <Note>
            No files were attributed to this component. The inventory attributes
            a file to a component only when the manifest owning it is known, so
            a component discovered from a deployment declaration has none.
          </Note>
        )}
      </Section>

      <Section title="Stage evidence">
        <p className="max-w-prose text-[11.5px] leading-relaxed text-ink-4">
          What each recovery stage contributed to this element's presence in the
          graph. Declared means a file says so; the count is the number of
          artifact records behind it.
        </p>
        <ul className="flex flex-col divide-y divide-line rounded-control border border-line">
          {element.snapshot_evidence.map((entry) => (
            <li
              key={`${entry.stage}-${entry.type}`}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-1 px-4 py-2.5 sm:grid-cols-[minmax(0,2fr)_minmax(0,2fr)_auto_auto]"
            >
              <span className="font-mono text-[12px] text-ink">
                {entry.stage.replace(/_/g, " ")}
              </span>
              <span className="font-mono text-[11.5px] text-ink-3">
                {entry.type.replace(/_/g, " ")}
              </span>
              <span
                className={`font-mono text-[10.5px] tracking-wide uppercase ${
                  entry.declared ? "text-ok" : "text-ink-4"
                }`}
              >
                {entry.declared ? "declared" : "inferred"}
              </span>
              <span className="text-right font-mono text-[11px] text-ink-4">
                {entry.count} rec.
              </span>
            </li>
          ))}
        </ul>
      </Section>

      {details && details.artifacts.some((item) => !item.present) && (
        <MissingArtifacts details={details} />
      )}
    </div>
  );
}

/** A hairline grid of facts: one value per cell, no boxes inside boxes. */
function Specs({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-2 lg:grid-cols-4 *:bg-panel *:px-4 *:py-3">
      {children}
    </div>
  );
}

/** The files, with the overflow behind one control rather than cut off. */
function FileList({ files }: { files: ElementFile[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? files : files.slice(0, COLLAPSED);

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col divide-y divide-line rounded-control border border-line">
        {shown.map((file) => (
          <li
            key={file.path}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2"
          >
            <code className="font-mono text-[12px] break-all text-ink">
              {file.path}
            </code>
            <span className="flex shrink-0 items-center gap-3 font-mono text-[10.5px] tracking-wide text-ink-4">
              {file.language && (
                <span className="text-ink-3">{file.language}</span>
              )}
              {file.category && <span>{file.category.replace(/_/g, " ")}</span>}
              {file.size_bytes !== null && (
                <span className="tabular-nums">{file.size_bytes} B</span>
              )}
            </span>
          </li>
        ))}
      </ul>

      {files.length > COLLAPSED && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="self-start font-mono text-[11px] tracking-wide text-ink-3 underline-offset-4 hover:text-ink hover:underline"
        >
          {expanded ? "show fewer" : `show all ${files.length} files`}
        </button>
      )}
    </div>
  );
}

/**
 * One section of the sheet.
 *
 * The title is followed by a rule that runs to the edge, which is what makes
 * a long panel read as a sequence of parts rather than one wall of facts.
 */
export function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-5 py-7 first:pt-0 last:pb-0">
      <div className="flex items-center gap-4">
        <h3 className="font-mono text-[10.5px] tracking-[0.16em] whitespace-nowrap text-ink-4 uppercase">
          {title}
        </h3>
        <span className="h-px flex-1 bg-line" />
      </div>
      {children}
    </section>
  );
}

/** One labelled value. A note says where the value came from, quietly. */
export function Fact({
  label,
  value,
  note,
  mono,
  missing,
}: {
  label: string;
  value: React.ReactNode;
  note?: string;
  mono?: boolean;
  missing?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] tracking-[0.12em] text-ink-4 uppercase">
        {label}
      </span>
      <span
        className={`text-[13px] leading-snug wrap-break-word ${
          mono ? "font-mono" : ""
        } ${missing ? "text-ink-4" : mono ? "text-ink" : "text-ink-2"}`}
      >
        {value}
      </span>
      {note && (
        <span className="font-mono text-[10px] tracking-wide text-ink-4">
          {note}
        </span>
      )}
    </div>
  );
}

/** A heading for a list that has no section of its own. */
function SubLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] tracking-[0.14em] text-ink-4 uppercase">
      {children}
    </span>
  );
}

/** A value with no traffic light attached: a protocol is a fact, not a state. */
function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-[3px] border border-line-strong px-1.5 py-0.5 font-mono text-[10.5px] tracking-wide text-ink-2">
      {children}
    </span>
  );
}

/** Quiet prose, for the case where a section has nothing to list. */
function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="max-w-prose border-l border-line pl-4 text-[12px] leading-relaxed text-ink-3">
      {children}
    </p>
  );
}

export function Evidence({ title, items }: { title: string; items: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, COLLAPSED);

  return (
    <div className="flex flex-col gap-2">
      <SubLabel>{title}</SubLabel>
      <ul className="flex flex-col gap-1.5">
        {shown.map((item, index) => (
          <li
            key={`${item}-${index}`}
            className="border-l border-line pl-4 font-mono text-[11.5px] leading-relaxed wrap-break-word text-ink-3"
          >
            {item}
          </li>
        ))}
      </ul>
      {items.length > COLLAPSED && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="self-start font-mono text-[11px] tracking-wide text-ink-3 underline-offset-4 hover:text-ink hover:underline"
        >
          {expanded ? "show fewer" : `show all ${items.length}`}
        </button>
      )}
    </div>
  );
}

function evidenceLine(evidence: DiscoveryEvidence): string {
  const where = evidence.path
    ? `${evidence.path}${evidence.line ? `:${evidence.line}` : ""}`
    : "no location recorded";

  return [where, evidence.rule, evidence.detail].filter(Boolean).join(" — ");
}

export function MissingArtifacts({
  details,
}: {
  details: ArchitectureDetails;
}) {
  const absent = details.artifacts.filter((item) => !item.present);

  return (
    <div className="flex flex-col gap-2 rounded-control border border-warn/40 bg-warn-wash px-4 py-3">
      <span className="font-mono text-[10px] tracking-[0.14em] text-warn uppercase">
        Incomplete evidence
      </span>
      <p className="max-w-prose text-[11.5px] leading-relaxed text-ink-2">
        <code className="font-mono text-[11px] text-ink">
          {absent.map((item) => item.file).join(", ")}
        </code>{" "}
        could not be read for this release. The clone is removed with the
        repository and the snapshot outlives it — re-run recovery for this
        release to rebuild the artifacts.
      </p>
    </div>
  );
}

export type { SnapshotEvidenceEntry };
