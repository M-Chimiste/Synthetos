import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownProps {
  children: string | null | undefined;
}

/**
 * Rendered markdown component used across reports, postmortems, and pattern
 * detail views. Replaces the raw <pre>...</pre> rendering that landed in
 * Phases 1-5 -- see Phase 6 §5.3.
 */
export default function Markdown({ children }: MarkdownProps) {
  if (!children) {
    return <p className="text-sm text-[var(--c-ink-4)]">No content.</p>;
  }
  return (
    <article className="prose prose-sm max-w-none prose-headings:font-semibold prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg prose-pre:rounded-md prose-pre:bg-[var(--c-panel-2)] prose-pre:text-[var(--c-ink)] prose-code:before:content-none prose-code:after:content-none prose-code:rounded prose-code:bg-[var(--c-panel)] prose-code:px-1 prose-code:py-0.5 prose-code:text-xs prose-table:text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </article>
  );
}
