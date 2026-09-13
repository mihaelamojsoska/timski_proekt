import type { SVGProps } from 'react';

export function PlusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function StopIcon(props: SVGProps<SVGSVGElement>) {
  // Inline style (not fill/stroke attrs) so it wins over the .ic class's
  // stroke-only styling - this icon needs a solid filled square, not an outline.
  return (
    <svg className="ic" viewBox="0 0 24 24" style={{ fill: 'currentColor', stroke: 'none' }} {...props}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

export function TrashIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />
    </svg>
  );
}

export function EditIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M12 20h9M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4z" />
    </svg>
  );
}

export function GlobeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic" viewBox="0 0 24 24" {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15 15 0 010 20M12 2a15 15 0 000 20" />
    </svg>
  );
}

export function SendIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic" viewBox="0 0 24 24" {...props}>
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  );
}

export function ArrowIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="sugg-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  );
}

export function SparkleIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic" viewBox="0 0 24 24" {...props}>
      <path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" />
    </svg>
  );
}

export function QuizIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M12 20h9M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4z" />
    </svg>
  );
}

export function SummaryIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5z" />
    </svg>
  );
}

export function AskMoreIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M21 11.5a8.4 8.4 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.4 8.4 0 01-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.4 8.4 0 013.8-.9h.5a8.5 8.5 0 018 8z" />
    </svg>
  );
}

export function ExploreIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <circle cx="11" cy="11" r="8" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

export function ExportIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M12 3v12M8 11l4 4 4-4M4 21h16" />
    </svg>
  );
}

export function ExternalLinkIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" style={{ color: 'var(--muted)' }} {...props}>
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" />
    </svg>
  );
}

export function GuestIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
    </svg>
  );
}

export function ChatIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M21 11.5a8.4 8.4 0 01-3.8 7 8.5 8.5 0 01-9.8 0A8.4 8.4 0 013 11.5a8.5 8.5 0 018.5-8.5h1a8.5 8.5 0 018.5 8z" />
    </svg>
  );
}

export function BookIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20V3H6.5A2.5 2.5 0 004 5.5v14z" />
      <path d="M4 19.5V5.5" />
    </svg>
  );
}

export function HistoryIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v4h4" />
      <path d="M12 8v4l3 3" />
    </svg>
  );
}

export function ChartIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M4 20V10" />
      <path d="M12 20V4" />
      <path d="M20 20v-6" />
    </svg>
  );
}

export function PlayIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M10 8l6 4-6 4V8z" />
    </svg>
  );
}

export function BackArrowIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M19 12H5M12 19l-7-7 7-7" />
    </svg>
  );
}

export function SunIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <circle cx="12" cy="12" r="4.5" />
      <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
    </svg>
  );
}

export function MoonIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M20 14.5A8.5 8.5 0 019.5 4 8.5 8.5 0 1020 14.5z" />
    </svg>
  );
}

export function ChevronIcon({ flip, style, ...props }: SVGProps<SVGSVGElement> & { flip?: boolean }) {
  return (
    <svg
      className="ic-sm"
      viewBox="0 0 24 24"
      style={{ transform: flip ? 'rotate(180deg)' : undefined, ...style }}
      {...props}
    >
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}

export function ShieldIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

export function StoreIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M3 9l1.5-5h15L21 9M3 9v11a1 1 0 001 1h16a1 1 0 001-1V9M3 9h18M8 9v3a2 2 0 01-4 0V9m8 3a2 2 0 01-4 0V9m8 3a2 2 0 01-4 0V9" />
    </svg>
  );
}

export function FileIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

export function HelpIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M9.1 9a3 3 0 015.8 1c0 2-3 2-3 4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

export function CopyIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg className="ic-sm" viewBox="0 0 24 24" {...props}>
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
    </svg>
  );
}
