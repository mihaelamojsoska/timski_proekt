import { useMemo, useState } from 'react';
import { renderMarkdown, handleMarkdownClick } from '../../utils/markdown';
import { SparkleIcon, ChevronIcon, GlobeIcon, BookIcon, HistoryIcon } from '../icons';
import type { ReasoningComparison } from '../../types/chat';

// Matches the fixed heading SYSTEM_PROMPT instructs the model to use for a
// "what do the different sources say" section (see backend/ai/chat.py rule
// 11) - deliberately not "recap"/"summary", which already name the separate
// Study recap tool elsewhere in this app. Split out of the main answer flow
// so it renders as its own collapsed-by-default block instead of just
// another heading in the middle of the answer.
// Tolerates common model formatting habits around the heading text itself
// (bolding it, a trailing colon) - still requires the literal English words,
// so a translated/localized heading (the model matches the student's
// language elsewhere) won't match; that's a known, accepted gap, not fixed
// here, since forcing this one heading to stay untranslated would need its
// own carve-out in SYSTEM_PROMPT's language-matching rule.
const SOURCE_COMPARISON_HEADING = /^#{1,6}\s*\**Source comparison\**:?\s*$/im;

function splitSourceComparison(text: string): { main: string; comparison: string | null } {
  const match = SOURCE_COMPARISON_HEADING.exec(text);
  if (!match) return { main: text, comparison: null };
  const main = text.slice(0, match.index).trimEnd();
  const comparison = text.slice(match.index + match[0].length).trim();
  return { main, comparison: comparison || null };
}

interface Props {
  content: string;
  streaming?: boolean;
  error?: string;
  /** Only set once a cross-checked answer finishes streaming (see
   * useChatStream's onReasoning) - never during streaming, since the two
   * drafts are only known once the compare step has actually completed. */
  reasoning?: ReasoningComparison;
  /** Ordered log of live status updates from the dual-draft+verify pipeline
   * (see useChatStream's onThinking) - the last entry is shown live while
   * streaming with no content yet; the full list becomes the expandable
   * "Thought for Xs" trace once streaming ends. */
  thinkingSteps?: string[];
  /** Wall-clock time the pipeline took, for the "Thought for Xs" label -
   * only set once streaming finishes and thinkingSteps is non-empty. */
  thinkingDurationMs?: number;
}

export function MessageBubbleAI({ content, streaming, error, reasoning, thinkingSteps, thinkingDurationMs }: Props) {
  // Only split once the answer is fully in - slicing mid-stream could cut
  // the heading off partway through and flash a broken split, then un-split
  // once the rest arrives.
  const { main: mainContent, comparison: comparisonContent } = useMemo(
    () => (streaming ? { main: content, comparison: null } : splitSourceComparison(content)),
    [content, streaming],
  );
  const html = useMemo(() => renderMarkdown(mainContent), [mainContent]);
  const sourceComparisonHtml = useMemo(
    () => (comparisonContent ? renderMarkdown(comparisonContent) : ''),
    [comparisonContent],
  );
  const [showThinking, setShowThinking] = useState(false);
  const [showSourceComparison, setShowSourceComparison] = useState(false);
  const searchDraftHtml = useMemo(
    () => (reasoning ? renderMarkdown(reasoning.searchDraft) : ''),
    [reasoning],
  );
  const courseDraftHtml = useMemo(
    () => (reasoning ? renderMarkdown(reasoning.courseDraft) : ''),
    [reasoning],
  );
  const comparisonNotesHtml = useMemo(
    () => (reasoning?.comparisonNotes ? renderMarkdown(reasoning.comparisonNotes) : ''),
    [reasoning],
  );
  const cachedDraftHtml = useMemo(
    () => (reasoning?.cachedDraft ? renderMarkdown(reasoning.cachedDraft) : ''),
    [reasoning],
  );

  const liveStatus = thinkingSteps && thinkingSteps.length > 0 ? thinkingSteps[thinkingSteps.length - 1] : undefined;
  const thinkingSeconds = thinkingDurationMs ? Math.max(1, Math.round(thinkingDurationMs / 1000)) : undefined;
  // Gated on `reasoning` too, not just a non-empty thinkingSteps: the first
  // "Checking..." status fires before build_verified_answer runs, so a
  // single-source fallback (one draft failed, reasoning stays null) would
  // otherwise still show a "Thought for Xs" disclosure implying cross-source
  // verification happened when it silently didn't.
  const hasThinking = !streaming && !!reasoning && thinkingSteps && thinkingSteps.length > 0;

  return (
    <article className="msg-ai">
      <header className="msg-ai-head">
        <span className="msg-ai-mark">L</span>
        <span className="msg-label">LearnWise · The answer</span>
        <span className="msg-ai-rule" />
      </header>
      {/* Claude-style: a persisted, click-to-expand "Thought for Xs" pill
         above the answer - not a status line that flashes by mid-stream and
         is gone forever once content arrives (the previous approach). */}
      {hasThinking && (
        <div className="msg-ai-thinking">
          <button
            type="button"
            className="msg-ai-thinking-toggle"
            onClick={() => setShowThinking((v) => !v)}
            aria-expanded={showThinking}
          >
            <SparkleIcon />
            <span>Thought for {thinkingSeconds}s</span>
            <ChevronIcon style={{ transform: `rotate(${showThinking ? -90 : 90}deg)` }} />
          </button>
          {showThinking && (
            <div className="msg-ai-thinking-body">
              <ol className="msg-ai-thinking-steps">
                {thinkingSteps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
              {reasoning?.comparisonNotes && (
                <div className="msg-ai-comparison-notes">
                  <div className="msg-ai-reasoning-label">
                    <SparkleIcon /> How the two sources compare
                  </div>
                  <div
                    className="msg-ai-reasoning-text"
                    dangerouslySetInnerHTML={{ __html: comparisonNotesHtml }}
                  />
                </div>
              )}
              {reasoning && (
                <div className="msg-ai-reasoning-body">
                  <div className="msg-ai-reasoning-draft">
                    <div className="msg-ai-reasoning-label">
                      <GlobeIcon /> Web search draft
                    </div>
                    <div className="msg-ai-reasoning-text" dangerouslySetInnerHTML={{ __html: searchDraftHtml }} />
                  </div>
                  <div className="msg-ai-reasoning-draft">
                    <div className="msg-ai-reasoning-label">
                      <BookIcon /> Course materials draft
                    </div>
                    <div className="msg-ai-reasoning-text" dangerouslySetInnerHTML={{ __html: courseDraftHtml }} />
                  </div>
                  {reasoning.cachedDraft && (
                    <div className="msg-ai-reasoning-draft msg-ai-reasoning-draft-wide">
                      <div className="msg-ai-reasoning-label">
                        <HistoryIcon /> Cached search draft
                        {reasoning.cachedQuery && (
                          <span className="msg-ai-reasoning-sublabel">from: "{reasoning.cachedQuery}"</span>
                        )}
                      </div>
                      <div className="msg-ai-reasoning-text" dangerouslySetInnerHTML={{ __html: cachedDraftHtml }} />
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {!content && streaming && (
        <div className="msg-ai-generating">
          <SparkleIcon className="ic sparkle-spin" />
          <span>{liveStatus || 'Generating…'}</span>
        </div>
      )}
      {content && (
        <div
          className={`msg-ai-body${streaming ? ' streaming' : ''}`}
          onClick={handleMarkdownClick}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )}
      {comparisonContent && (
        <div className="msg-ai-thinking msg-ai-source-comparison">
          <button
            type="button"
            className="msg-ai-thinking-toggle"
            onClick={() => setShowSourceComparison((v) => !v)}
            aria-expanded={showSourceComparison}
          >
            <SparkleIcon />
            <span>Source comparison</span>
            <ChevronIcon style={{ transform: `rotate(${showSourceComparison ? -90 : 90}deg)` }} />
          </button>
          {showSourceComparison && (
            <div className="msg-ai-thinking-body">
              <div
                className="msg-ai-body"
                onClick={handleMarkdownClick}
                dangerouslySetInnerHTML={{ __html: sourceComparisonHtml }}
              />
            </div>
          )}
        </div>
      )}
      {error && <div className="msg-error">{error}</div>}
    </article>
  );
}
