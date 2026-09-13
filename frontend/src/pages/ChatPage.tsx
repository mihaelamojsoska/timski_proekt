import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';
import { ConversationSidebar } from '../components/sidebar/ConversationSidebar';
import { ChatMasthead } from '../components/chat/ChatMasthead';
import { MessageList } from '../components/chat/MessageList';
import { MessageInput } from '../components/chat/MessageInput';
import type { MessageInputHandle } from '../components/chat/MessageInput';
import { SourcesSidebar } from '../components/sources/SourcesSidebar';
import { QuizModal } from '../components/modals/QuizModal';
import { SummaryModal } from '../components/modals/SummaryModal';
import { ExploreModal } from '../components/modals/ExploreModal';
import { AskMoreModal } from '../components/modals/AskMoreModal';
import { useChatStream, uid } from '../hooks/useChatStream';
import type { DisplayMessage } from '../hooks/useChatStream';
import { useConversations } from '../hooks/useConversations';
import { useConversationPolling } from '../hooks/useConversationPolling';
import { useCollapsed } from '../hooks/useCollapsed';
import { getConversation, exportConversation } from '../api/conversations';
import { listCourses } from '../api/courses';
import * as chatTools from '../api/chatTools';
import { useAuth } from '../context/AuthContext';
import { InviteModal } from '../components/modals/InviteModal';
import type { ChatSource, QuizResponse, ExploreResponse } from '../types/chat';
import type { ConversationDetailOut, ConversationMemberOut } from '../types/conversation';
import type { CourseOut } from '../types/course';

/** Shared by the initial load and the polling refresh below - only another
 * member's message gets an authorName label (shown as "You" otherwise). */
function toDisplayMessages(detail: ConversationDetailOut, viewerId: number | undefined): DisplayMessage[] {
  return detail.messages.map((m) => ({
    id: uid(),
    role: m.role === 'assistant' ? 'ai' : 'user',
    content: m.content,
    authorName: m.author_user_id != null && m.author_user_id !== viewerId ? m.author_name ?? undefined : undefined,
  }));
}

type ModalState =
  | { kind: 'quiz'; data: QuizResponse }
  | { kind: 'summary'; data: string }
  | { kind: 'explore'; data: ExploreResponse }
  | { kind: 'askMore'; data: string[] }
  | null;

export function ChatPage() {
  const params = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const routeId = params.conversationId ? Number(params.conversationId) : null;

  const [activeId, setActiveId] = useState<number | null>(routeId);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [sources, setSources] = useState<ChatSource[]>([]);
  const [sourcesFromCache, setSourcesFromCache] = useState(false);
  const [subject, setSubject] = useState('Any subject');
  const [live, setLive] = useState(true);
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [courseId, setCourseId] = useState<number | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [toolLoading, setToolLoading] = useState<null | 'quiz' | 'summary' | 'explore' | 'askMore'>(null);
  const [exporting, setExporting] = useState(false);
  const [members, setMembers] = useState<ConversationMemberOut[]>([]);
  const [isOwner, setIsOwner] = useState(true);
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [otherMemberGenerating, setOtherMemberGenerating] = useState(false);
  const [maxMembers, setMaxMembers] = useState(3);

  const skipNextLoad = useRef(false);
  const inputRef = useRef<MessageInputHandle>(null);
  const { send, isStreaming, abort } = useChatStream();
  const conversations = useConversations();
  const { user } = useAuth();
  const [sourcesCollapsed, toggleSources] = useCollapsed('lw_sidebar_right');

  // Single place that applies a ConversationDetailOut to local state - used
  // by the initial load, the poll refresh, and the invite modal's
  // post-change refetch, so none of them can drift by forgetting to update
  // one of these fields (which happened here before: the invite modal's
  // refetch used to update messages/members but not isOwner/generating).
  const applyConversationDetail = useCallback(
    (detail: ConversationDetailOut) => {
      setMessages(toDisplayMessages(detail, user?.id));
      setMembers(detail.members);
      setIsOwner(detail.is_owner);
      setOtherMemberGenerating(detail.generating);
      setMaxMembers(detail.max_members);
    },
    [user?.id],
  );

  // Load the course catalog once, for the "tie this chat to a course" picker
  // in the masthead - courses.finki-hub data, not required to use the app.
  useEffect(() => {
    listCourses()
      .then(setCourses)
      .catch(() => {
        /* course picker just stays empty/hidden on failure - not critical */
      });
  }, []);

  // Load (or reset) the active conversation whenever the route param changes,
  // unless we just set it ourselves right after streaming created a new one.
  useEffect(() => {
    if (skipNextLoad.current) {
      skipNextLoad.current = false;
      setActiveId(routeId);
      return;
    }
    setActiveId(routeId);
    setSources([]);
    setSourcesFromCache(false);
    if (routeId == null) {
      setMessages([]);
      setMembers([]);
      setIsOwner(true);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await getConversation(routeId);
        if (cancelled) return;
        applyConversationDetail(detail);
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId]);

  // Group-chat "real-time" strategy: poll rather than push (see the
  // group-chat plan) - picks up another member's new messages within a few
  // seconds. Paused while this tab's own message is streaming, so a poll
  // never clobbers the in-flight partial reply being built up locally below.
  useConversationPolling(activeId, isStreaming, messages.length, applyConversationDetail);

  const activeThread = conversations.threads.find((t) => t.id === activeId);
  const title = activeThread?.title || 'New conversation';
  // "No." is an issue number, like a real magazine - the backend stamps
  // issue_no once at creation (User.conversation_seq, see
  // backend/routes/conversationRoute.py::create_conversation), so it stays
  // permanent even if an earlier conversation is later deleted, unlike a
  // position recomputed from the live conversation list. The fallback here
  // is only a placeholder for a brand-new, not-yet-created conversation -
  // it becomes fixed as soon as the first message actually creates it.
  const issueNo = activeThread?.issue_no ?? conversations.threads.length + 1;

  const handleNewConversation = useCallback(() => {
    if (isStreaming) return;
    navigate('/chat');
  }, [isStreaming, navigate]);

  // Cmd/Ctrl+N is reserved by every major browser for "open a new window",
  // and it turns out Cmd/Ctrl+Shift+O is too - both Chrome and Firefox bind
  // it to their bookmark manager, so the page never even sees the keydown.
  // A bare, unmodified letter key is never reserved by browser chrome (only
  // modifier combos are), so this uses the same pattern as Gmail's "c" for
  // compose or Linear's "c" for create - fires only when focus isn't in a
  // text field, so it can't eat a keystroke while typing.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // e.code is the physical key position, not the character the active
      // keyboard layout maps it to - e.key would silently never match for a
      // Macedonian Cyrillic layout (where this key produces "н", not "n"),
      // which matters since that's this app's primary audience.
      if (e.code !== 'KeyN' || e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target?.isContentEditable) return;
      // Every modal (quiz/summary/explore/ask-more/invite, the help tour)
      // renders through ModalShell's .modal-overlay, the course/subject
      // pickers' open option list is a .dropdown-menu, and the account menu
      // is a .user-foot-dropdown - skip while any is open instead of firing
      // underneath it.
      if (document.querySelector('.modal-overlay, .dropdown-menu, .user-foot-dropdown')) return;
      e.preventDefault();
      handleNewConversation();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [handleNewConversation]);

  const handleSelectThread = useCallback(
    (id: number) => {
      if (isStreaming) return;
      navigate(`/chat/${id}`);
    },
    [isStreaming, navigate],
  );

  const handleDeleteThread = useCallback(
    async (id: number) => {
      await conversations.remove(id);
      if (activeId === id) {
        navigate('/chat');
      }
    },
    [conversations, activeId, navigate],
  );

  const handleSend = useCallback(
    (content: string) => {
      if (isStreaming) return;

      const userMsg: DisplayMessage = { id: uid(), role: 'user', content };
      const aiMsgId = uid();
      const aiMsg: DisplayMessage = { id: aiMsgId, role: 'ai', content: '', streaming: true, thinkingStartedAt: Date.now() };

      // Marks when the first real answer content arrives, so "Thought for
      // Xs" can measure just the drafting/verification phase - not the
      // entire request including however long the final (already-decided)
      // answer itself takes to stream in. Plain per-send local state (not
      // component state): closed over by this call's callbacks only.
      let thinkingEndedAt: number | null = null;

      const priorMessages = messages;
      setMessages((prev) => [...prev, userMsg, aiMsg]);

      const payloadMessages = [...priorMessages, userMsg].map((m) => ({
        role: m.role === 'ai' ? ('assistant' as const) : ('user' as const),
        content: m.content,
      }));

      const subjectValue = subject === 'Any subject' ? null : subject;
      const wasNewConversation = activeId === null;

      send(
        payloadMessages,
        { subject: subjectValue, search: live, conversationId: activeId, courseId },
        {
          onConversationInfo: (info) => {
            setActiveId(info.id);
            if (wasNewConversation) {
              skipNextLoad.current = true;
              navigate(`/chat/${info.id}`, { replace: true });
              const now = new Date().toISOString();
              conversations.upsertLocal({
                id: info.id,
                title: info.title,
                subject: subjectValue,
                issue_no: info.issue_no,
                message_count: 0,
                created_at: now,
                updated_at: now,
              });
            }
          },
          onSources: (srcs) => setSources(srcs),
          onSearchMeta: (meta) => setSourcesFromCache(meta.fromCache),
          onReasoning: (data) => {
            setMessages((prev) => prev.map((m) => (m.id === aiMsgId ? { ...m, reasoning: data } : m)));
          },
          onThinking: (status) => {
            setMessages((prev) =>
              prev.map((m) => (m.id === aiMsgId ? { ...m, thinkingSteps: [...(m.thinkingSteps || []), status] } : m)),
            );
          },
          onSessionExpired: () => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId ? { id: uid(), role: 'error', content: 'Your session expired - please sign in again.' } : m,
              ),
            );
          },
          onError: (message) => {
            // Attach the error to the existing AI bubble instead of replacing
            // it, so any partial answer already streamed in isn't discarded.
            setMessages((prev) =>
              prev.map((m) => (m.id === aiMsgId ? { ...m, streaming: false, error: message } : m)),
            );
          },
          onDone: () => {
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== aiMsgId) return m;
                const thinkingDurationMs =
                  m.thinkingSteps && m.thinkingSteps.length > 0 && m.thinkingStartedAt
                    ? (thinkingEndedAt ?? Date.now()) - m.thinkingStartedAt
                    : undefined;
                return { ...m, streaming: false, thinkingDurationMs };
              }),
            );
          },
        },
        (fullText) => {
          if (thinkingEndedAt === null && fullText.length > 0) {
            thinkingEndedAt = Date.now();
          }
          setMessages((prev) => prev.map((m) => (m.id === aiMsgId ? { ...m, content: fullText } : m)));
        },
      )
        .catch((err: Error) => {
          // Same principle as onError above: keep whatever content already
          // rendered, just mark it as failed rather than wiping it out.
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiMsgId ? { ...m, streaming: false, error: err.message || 'Connection error' } : m,
            ),
          );
        })
        .finally(() => {
          conversations.reload();
          inputRef.current?.focus();
        });
    },
    [isStreaming, messages, subject, live, activeId, courseId, send, navigate, conversations],
  );

  const conversationMessages = () =>
    messages
      .filter((m) => m.role === 'user' || m.role === 'ai')
      .map((m) => ({ role: m.role === 'ai' ? ('assistant' as const) : ('user' as const), content: m.content }));

  const subjectValue = subject === 'Any subject' ? null : subject;
  const hasConversation = messages.some((m) => m.role !== 'error');

  const runTool = async (kind: 'quiz' | 'summary' | 'explore' | 'askMore') => {
    if (!hasConversation) {
      window.alert(
        kind === 'quiz'
          ? 'Have a conversation first, then I can quiz you on it!'
          : kind === 'summary'
            ? 'Have a conversation first, then I can summarize it!'
            : kind === 'explore'
              ? 'Have a conversation first, then I can find related links!'
              : 'Have a conversation first, then I can suggest follow-up questions!',
      );
      return;
    }
    setToolLoading(kind);
    try {
      const payload = { messages: conversationMessages(), subject: subjectValue, course_id: courseId };
      if (kind === 'quiz') {
        const data = await chatTools.generateQuiz(payload);
        setModal({ kind: 'quiz', data });
      } else if (kind === 'summary') {
        const data = await chatTools.generateSummary(payload);
        setModal({ kind: 'summary', data: data.summary });
      } else if (kind === 'explore') {
        const data = await chatTools.generateExplore(payload);
        setModal({ kind: 'explore', data });
      } else {
        const data = await chatTools.generateAskMore(payload);
        setModal({ kind: 'askMore', data: data.questions });
      }
    } catch (err) {
      window.alert(`Could not complete request: ${err instanceof Error ? err.message : 'unknown error'}`);
    } finally {
      setToolLoading(null);
    }
  };

  const handleExport = async () => {
    if (!activeId) {
      window.alert('Open (or send a message in) a saved conversation first, then you can export it.');
      return;
    }
    setExporting(true);
    try {
      const { blob, filename } = await exportConversation(activeId, 'markdown');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      window.alert(`Could not export: ${err instanceof Error ? err.message : 'unknown error'}`);
    } finally {
      setExporting(false);
    }
  };

  const pickFollowup = (question: string) => {
    setModal(null);
    // handleSend takes the question directly - clear (rather than fill) the
    // composer so there's nothing left sitting in it to accidentally resend.
    inputRef.current?.clear();
    inputRef.current?.focus();
    handleSend(question);
  };

  const toolLabel = (kind: 'quiz' | 'summary' | 'explore' | 'askMore', idleLabel: string, loadingLabel: string) =>
    toolLoading === kind ? loadingLabel : idleLabel;

  return (
    <AppShell
      sidebar={
        <ConversationSidebar
          threads={conversations.threads}
          activeId={activeId}
          loggedIn
          searchQuery={conversations.searchQuery}
          onSearchChange={conversations.onSearchChange}
          onNewConversation={handleNewConversation}
          onSelect={handleSelectThread}
          onDelete={handleDeleteThread}
          onRename={conversations.rename}
        />
      }
      rightSidebarCollapsed={sourcesCollapsed}
      rightSidebar={
        <SourcesSidebar
          sources={sources}
          sourcesFromCache={sourcesFromCache}
          onQuiz={() => runTool('quiz')}
          onSummary={() => runTool('summary')}
          onAskMore={() => runTool('askMore')}
          onExplore={() => runTool('explore')}
          onExport={handleExport}
          quizLabel={toolLabel('quiz', 'Quiz me', 'Generating…')}
          summaryLabel={toolLabel('summary', 'Summary', 'Summarizing…')}
          askMoreLabel={toolLabel('askMore', 'Ask more', 'Thinking…')}
          exploreLabel={toolLabel('explore', 'Explore', 'Searching…')}
          exportLabel={exporting ? 'Exporting…' : 'Export'}
          toolsDisabled={toolLoading !== null}
          exportDisabled={exporting}
        />
      }
    >
      <ChatMasthead
        title={title}
        issueNo={issueNo}
        subject={subject}
        onSubjectChange={setSubject}
        live={live}
        onToggleLive={() => setLive((l) => !l)}
        courses={courses}
        courseId={courseId}
        onCourseChange={setCourseId}
        memberCount={activeId ? members.length : undefined}
        onOpenMembers={activeId ? () => setShowInviteModal(true) : undefined}
        sourcesCollapsed={sourcesCollapsed}
        onToggleSources={toggleSources}
      />
      {otherMemberGenerating && !isStreaming && (
        <div className="empty" style={{ padding: '4px 24px', textAlign: 'left' }}>
          Someone is asking something…
        </div>
      )}
      <MessageList messages={messages} onPickSuggestion={handleSend} />
      <MessageInput ref={inputRef} disabled={isStreaming} live={live} subject={subject} onSend={handleSend} onStop={abort} />

      {modal?.kind === 'quiz' && (
        <QuizModal data={modal.data} subject={subjectValue} onClose={() => setModal(null)} />
      )}
      {modal?.kind === 'summary' && <SummaryModal summary={modal.data} onClose={() => setModal(null)} />}
      {modal?.kind === 'explore' && <ExploreModal data={modal.data} onClose={() => setModal(null)} />}
      {modal?.kind === 'askMore' && (
        <AskMoreModal questions={modal.data} onPick={pickFollowup} onClose={() => setModal(null)} />
      )}
      {showInviteModal && activeId && (
        <InviteModal
          conversationId={activeId}
          isOwner={isOwner}
          maxMembers={maxMembers}
          onClose={() => setShowInviteModal(false)}
          onMembersChanged={() => {
            getConversation(activeId).then(applyConversationDetail);
          }}
        />
      )}
    </AppShell>
  );
}
