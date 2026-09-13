import { useEffect, useRef } from 'react';
import type { DisplayMessage } from '../../hooks/useChatStream';
import { MessageBubbleUser } from './MessageBubbleUser';
import { MessageBubbleAI } from './MessageBubbleAI';
import { MessageBubbleError } from './MessageBubbleError';
import { WelcomeSuggestions } from './WelcomeSuggestions';

interface Props {
  messages: DisplayMessage[];
  onPickSuggestion: (q: string) => void;
}

export function MessageList({ messages, onPickSuggestion }: Props) {
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    });
  }, [messages]);

  return (
    <div className="body" ref={bodyRef}>
      {messages.length === 0 ? (
        <WelcomeSuggestions onPick={onPickSuggestion} />
      ) : (
        <div className="conv">
          {messages.map((m, i) => {
            if (m.role === 'user') {
              return <MessageBubbleUser key={m.id} content={m.content} index={i} authorName={m.authorName} />;
            }
            if (m.role === 'error') return <MessageBubbleError key={m.id} content={m.content} />;
            return (
              <MessageBubbleAI
                key={m.id}
                content={m.content}
                streaming={m.streaming}
                error={m.error}
                reasoning={m.reasoning}
                thinkingSteps={m.thinkingSteps}
                thinkingDurationMs={m.thinkingDurationMs}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
