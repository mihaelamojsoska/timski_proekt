import type { ChatSource } from '../../types/chat';
import {
  SparkleIcon,
  QuizIcon,
  SummaryIcon,
  AskMoreIcon,
  ExploreIcon,
  ExportIcon,
  ExternalLinkIcon,
} from '../icons';

function siteFromUrl(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

interface Props {
  sources: ChatSource[];
  /** True when these sources were served from the search cache (see
   * backend/services/search_cache.py) instead of a fresh live web search -
   * shown as a small pill so it's clear why the answer came back quickly. */
  sourcesFromCache: boolean;
  onQuiz: () => void;
  onSummary: () => void;
  onAskMore: () => void;
  onExplore: () => void;
  onExport: () => void;
  quizLabel: string;
  summaryLabel: string;
  askMoreLabel: string;
  exploreLabel: string;
  exportLabel: string;
  toolsDisabled: boolean;
  exportDisabled: boolean;
}

export function SourcesSidebar({
  sources,
  sourcesFromCache,
  onQuiz,
  onSummary,
  onAskMore,
  onExplore,
  onExport,
  quizLabel,
  summaryLabel,
  askMoreLabel,
  exploreLabel,
  exportLabel,
  toolsDisabled,
  exportDisabled,
}: Props) {
  return (
    <>
      <div className="dossier-head">
        <div>
          <div className="dossier-kicker">The dossier</div>
          <div className="dossier-title">Sources &amp; insights</div>
        </div>
        <SparkleIcon style={{ color: 'var(--muted)' }} />
      </div>
      <div className="dossier-body">
        <div className="sec-head">
          <h3 className="sec-title">Cited sources</h3>
          <span className="sec-sub">{sources.length} references</span>
        </div>
        {sources.length > 0 && sourcesFromCache && (
          <div className="src-cache-pill" title="Served from a previously cached search instead of a fresh live lookup">
            <svg className="ic-sm" viewBox="0 0 24 24" style={{ width: 11, height: 11 }}>
              <circle cx="12" cy="12" r="10" />
              <path d="M12 6v6l4 2" />
            </svg>
            <span>From cached search</span>
          </div>
        )}
        {sources.length === 0 ? (
          <div className="empty">
            When you ask a question, live documentation citations will appear here, numbered as footnotes alongside
            the answer.
          </div>
        ) : (
          <ol className="src-list">
            {sources.map((s, i) => (
              <li key={s.url + i}>
                <a className="src" href={s.url} target="_blank" rel="noreferrer">
                  <div className="src-row">
                    <span className="src-num">{i + 1}</span>
                    <div className="src-body">
                      <div className="src-title">{s.title}</div>
                      <div className="src-meta">
                        <svg className="ic-sm" viewBox="0 0 24 24" style={{ width: 10, height: 10 }}>
                          <circle cx="12" cy="12" r="10" />
                          <path d="M2 12h20" />
                        </svg>
                        <span>{siteFromUrl(s.url)}</span>
                      </div>
                    </div>
                    <ExternalLinkIcon />
                  </div>
                </a>
              </li>
            ))}
          </ol>
        )}

        <div className="divider" />

        <div className="sec-head">
          <h3 className="sec-title">Study tools</h3>
        </div>
        <div className="tools-grid">
          <button className="tool" onClick={onQuiz} disabled={toolsDisabled}>
            <span className="tool-icon">
              <QuizIcon />
            </span>
            <span className="tool-label">{quizLabel}</span>
            <span className="tool-hint">5 questions</span>
          </button>
          <button className="tool" onClick={onSummary} disabled={toolsDisabled}>
            <span className="tool-icon">
              <SummaryIcon />
            </span>
            <span className="tool-label">{summaryLabel}</span>
            <span className="tool-hint">TL;DR</span>
          </button>
          <button className="tool" onClick={onAskMore} disabled={toolsDisabled}>
            <span className="tool-icon">
              <AskMoreIcon />
            </span>
            <span className="tool-label">{askMoreLabel}</span>
            <span className="tool-hint">Follow-ups</span>
          </button>
          <button className="tool" onClick={onExplore} disabled={toolsDisabled}>
            <span className="tool-icon">
              <ExploreIcon />
            </span>
            <span className="tool-label">{exploreLabel}</span>
            <span className="tool-hint">Related</span>
          </button>
          <button className="tool" onClick={onExport} disabled={exportDisabled} style={{ gridColumn: '1 / -1' }}>
            <span className="tool-icon">
              <ExportIcon />
            </span>
            <span className="tool-label">{exportLabel}</span>
            <span className="tool-hint">Markdown</span>
          </button>
        </div>
      </div>
    </>
  );
}
