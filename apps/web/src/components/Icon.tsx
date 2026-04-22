import type { CSSProperties, SVGProps } from "react";

export type IconName =
  | "home"
  | "charter"
  | "cycle"
  | "pattern"
  | "skills"
  | "events"
  | "search"
  | "plus"
  | "chevron"
  | "chevronDown"
  | "arrow"
  | "play"
  | "pause"
  | "stop"
  | "settings"
  | "moon"
  | "sun"
  | "dot"
  | "bolt"
  | "check"
  | "x"
  | "filter"
  | "cmd"
  | "flask"
  | "book"
  | "graph"
  | "doc"
  | "spark";

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name" | "stroke"> {
  name: IconName;
  size?: number;
  stroke?: number;
  style?: CSSProperties;
}

const PATHS: Record<IconName, React.ReactNode> = {
  home: <path d="M4 11 L12 4 L20 11 V20 H14 V14 H10 V20 H4 Z" />,
  charter: (
    <>
      <rect x="5" y="4" width="14" height="16" rx="2" />
      <path d="M8 9h8M8 13h8M8 17h5" />
    </>
  ),
  cycle: (
    <>
      <path d="M4 12a8 8 0 1 0 3-6.2" />
      <path d="M7 3v4h4" />
    </>
  ),
  pattern: (
    <>
      <circle cx="7" cy="7" r="2.5" />
      <circle cx="17" cy="7" r="2.5" />
      <circle cx="7" cy="17" r="2.5" />
      <circle cx="17" cy="17" r="2.5" />
      <path d="M9 7h6M7 9v6M17 9v6M9 17h6" />
    </>
  ),
  skills: (
    <path d="M12 2 L14.5 8.5 L21 9 L16 13.5 L17.5 20 L12 16.5 L6.5 20 L8 13.5 L3 9 L9.5 8.5 Z" />
  ),
  events: <path d="M4 6h16M4 12h16M4 18h10" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="m20 20-4-4" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  play: <path d="M7 5v14l11-7z" />,
  pause: <path d="M7 5v14M17 5v14" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="1" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
    </>
  ),
  moon: <path d="M20 14A8 8 0 1 1 10 4a7 7 0 0 0 10 10Z" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.4 1.4M17.6 17.6 19 19M5 19l1.4-1.4M17.6 6.4 19 5" />
    </>
  ),
  dot: <circle cx="12" cy="12" r="3" />,
  bolt: <path d="M13 2 3 14h8l-1 8 10-12h-8l1-8z" />,
  check: <path d="M5 12l4 4L19 6" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  filter: <path d="M4 5h16l-6 8v6l-4-2v-4Z" />,
  cmd: (
    <path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3Z" />
  ),
  flask: (
    <>
      <path d="M9 3v6L4 19a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-5-10V3M9 3h6" />
      <path d="M7 14h10" />
    </>
  ),
  book: (
    <>
      <path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4V4Z" />
      <path d="M4 16a4 4 0 0 1 4-4h12" />
    </>
  ),
  graph: (
    <>
      <path d="M3 20V4M3 20h18" />
      <path d="M7 15l4-5 3 3 5-6" />
    </>
  ),
  doc: (
    <>
      <path d="M6 3h9l4 4v14H6z" />
      <path d="M15 3v4h4M9 13h6M9 17h6M9 9h3" />
    </>
  ),
  spark: (
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8" />
  ),
};

export default function Icon({
  name,
  size = 16,
  stroke = 1.6,
  style,
  ...rest
}: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      style={{
        width: size,
        height: size,
        stroke: "currentColor",
        strokeWidth: stroke,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        fill: "none",
        flexShrink: 0,
        ...style,
      }}
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
