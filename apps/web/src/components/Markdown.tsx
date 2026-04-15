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
    return <p className="text-sm text-gray-400">No content.</p>;
  }
  return (
    <article className="prose prose-sm max-w-none prose-headings:font-semibold prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg prose-pre:rounded-md prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-code:before:content-none prose-code:after:content-none prose-code:rounded prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:text-xs prose-table:text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </article>
  );
}
