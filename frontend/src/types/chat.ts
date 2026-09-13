export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  subject?: string | null;
  search?: boolean;
  conversation_id?: number | null;
  course_id?: number | null;
}

export interface ChatSource {
  title: string;
  url: string;
}

export interface QuizQuestion {
  question: string;
  options: string[];
  answer: 'A' | 'B' | 'C' | 'D';
  explanation: string;
}

export interface QuizResponse {
  topic: string;
  questions: QuizQuestion[];
}

export interface SummaryResponse {
  summary: string;
}

export interface ExploreLink {
  title: string;
  url: string;
  snippet: string;
}

export interface ExploreResponse {
  queries: string[];
  links: ExploreLink[];
}

export interface AskMoreResponse {
  questions: string[];
}

/** The two isolated single-source drafts behind a cross-checked answer -
 * only present when the question had both live search AND course context
 * available (see backend/services/answer_verification.py). Shown in the
 * "Thought for Xs" panel on that message. */
export interface ReasoningComparison {
  searchDraft: string;
  courseDraft: string;
  /** How the two drafts relate - what each uniquely covers, where they
   * agree/conflict. Optional/nullable: omitted if that one extra Groq call
   * failed, since the two raw drafts are still worth showing either way. */
  comparisonNotes?: string | null;
  /** A third, optional source: a previously cached search loosely related
   * to this question, found cheaply alongside the two always-present drafts
   * (see backend/services/search_cache.py::find_related_cached_search) -
   * only present when one happened to exist, never triggers extra live
   * search calls on its own. */
  cachedDraft?: string | null;
  /** The original question that cached search was for, shown as a label on
   * its card so a student can see it's a distinct, older question. */
  cachedQuery?: string | null;
}
