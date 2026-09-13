# LearnWise – AI Tutor with Live Search

An AI tutor that searches live documentation before answering, so you always get accurate, up-to-date answers with sources.

## Trello Board
https://trello.com/b/UqREXgJa/timski-proekt

## Features

-  **Streaming AI chat** — answers appear word by word, with a stop button to cancel generation mid-answer
-  **Live web search** — fetches current docs via the Tavily Search API
-  **Source sidebar** — see exactly where the AI got its info
-  **Subject mode** — focus on Python, FastAPI, React, etc.
-  **Replies in your language/script** — the tutor matches whatever language and script the student asked in, including Macedonian written in either Cyrillic or Latin letters (see `SYSTEM_PROMPT` rule 8 in `backend/ai/chat.py`)
-  **Accounts & chat history** — register/login, and every conversation is saved, searchable, renameable, exportable
-  **Group chat** — invite up to 2 others (3 total) to a conversation via a shareable link; everyone's messages are labeled and the AI's replies stay in sync for all members
-  **React frontend** — a proper Vite + TypeScript SPA, editorial paper/ink look (light or dark theme, remembered per browser), collapsible sidebars, markdown rendered with IDE-style syntax-highlighted code blocks (one-click copy), and a skippable first-visit onboarding tour replayable any time from the account menu
-  **Course-aware tutoring** — pick a real FINKI course from a dropdown right in the chat masthead, and the tutor folds in that course's metadata, lecture topics, and materials (with real links) as extra context
-  **AI-generated lesson content** — per-course lessons with Gemini-generated study documentation and on-demand quizzes, grounded in real textbook/course-material excerpts
-  **Marketplace** — premium users submit new courses (with materials), an admin approves or rejects them, and approved ones go live for everyone — free or priced
-  **Billing (Stripe, test-mode)** — a recurring subscription unlocks course submission; a one-time purchase unlocks a single priced course's materials/recordings
-  **File uploads** — course material files (PDFs, slides, videos) upload to Supabase Storage and get a public URL, open to any logged-in user (no subscription required)
-  **Community study notes** — any logged-in user can attach a study note (file or link) to any course; always free to view, even on a priced course - a separate, non-premium alternative to submitting a whole course
-  **Quiz progress & recommendations** — every quiz attempt is tracked per user; low-scoring subjects are surfaced back as "worth another look" recommendations
-  **News & Recommendations (Blog)** — a curated feed of FINKI announcements, job postings, and hand-picked articles; announcements sync automatically from the official FINKI board, and admins can add external articles by pasting a URL

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your API keys
```bash
cp .env.example .env
# Edit .env and add your keys
```

**GROQ_API_KEY** (required)
→ Get from https://console.groq.com/keys

**TAVILY_API_KEY** (optional but recommended)
→ Sign up at https://app.tavily.com/home

**GEMINI_API_KEY** (optional — only needed for the lesson-generation pipeline, see "Lesson Content" below)
→ Get from https://aistudio.google.com/apikey

**ENABLE_ANSWER_VERIFICATION** (optional, defaults `true`)
→ Kill switch for the dual-source answer-verification pipeline (see "Answer Verification" below) — set to `false` to instantly disable it (no deploy needed) if its extra Groq calls cause cost/latency/rate-limit problems. Reuses the same `GROQ_API_KEY`, no separate key needed.

**DATABASE_URL** (required)
→ You need a local PostgreSQL server. Create a database (e.g. `learnwise`), then set:
```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/learnwise
```

**JWT_SECRET_KEY** (required)
→ Any long random string, used to sign login tokens. Generate one with:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET / STRIPE_PRICE_ID / FRONTEND_URL** (optional — needed for Marketplace billing)
→ Test-mode keys at https://dashboard.stripe.com/test/apikeys, create a recurring Price for STRIPE_PRICE_ID, run `stripe listen --forward-to localhost:8000/api/billing/webhook` (step 6 below) for STRIPE_WEBHOOK_SECRET

**SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / SUPABASE_STORAGE_BUCKET** (optional — needed for course material uploads)
→ Free project at https://supabase.com, copy the Project URL + `service_role` key from Settings > API, create a Public bucket named `course-materials` under Storage

### 3. Set up the database
```bash
alembic upgrade head
```
This creates all tables (`users`, `verification_tokens`, `conversations`, `chat_messages`, `conversation_members`, `conversation_invites`, `cached_searches`, `courses`, `course_materials`, `course_notes`, `recordings`, `course_purchases`, `quiz_attempts`, `lessons`, `course_sources`, `blog_posts`) and enables the `pg_trgm` Postgres extension (used for fuzzy search-cache matching and course-name search). Whenever you pull new migration files from git, re-run this command to apply them to your local database.

### 3b. Create an admin account
There's no in-app way to become an admin — registration always creates a plain `"student"`. Register a user normally through the app, then promote it with the `make_admin` script:
```bash
python -m backend.scripts.make_admin your@email.com
# python -m backend.scripts.make_admin your@email.com --demote   # to undo
```
Needed to reach the Admin panel and approve/reject Marketplace course submissions. Everyone should have their own admin account (promoted this way) rather than sharing one login — keeps admin actions attributable to a real person.

### 4. Run the backend
```bash
uvicorn backend.main:app --reload 
```
The API is now at http://localhost:8000 (interactive docs at `/docs`).

### 5. Run the frontend
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173 — Vite's dev server proxies `/api/*` straight to the backend on :8000 (see `frontend/vite.config.ts`), so no CORS setup is needed in development.

For a production build, `cd frontend && npm run build` produces `frontend/dist`, which `backend/main.py` will serve directly at `/` if the directory exists (no separate frontend server needed in that case).

### 6. (Optional) Run the Stripe webhook listener
Requires the Stripe CLI (https://stripe.com/docs/stripe-cli) installed first.
```bash
stripe listen --forward-to localhost:8000/api/billing/webhook
```
Needed for Marketplace billing to actually work in dev — without this running, Stripe has no way to tell the backend a checkout succeeded, so `is_premium`/`CoursePurchase` never update even after a successful test payment. Keep it running alongside the backend/frontend while testing subscriptions or course purchases. The first time you run it, it prints the `STRIPE_WEBHOOK_SECRET` to put in `.env`.

### 7. (Optional) Ingest course data
```bash
source .venv/bin/activate
python -m backend.services.ingestion.cli --source all
```
Pulls course/lecture-recording data from the public finki-hub.com sites into the `courses`/`course_materials`/`recordings` tables — see "Course Data" below before running this at full scale.

### 7b. (Optional) Sync FINKI announcements into the Blog feed
```bash
source .venv/bin/activate
python -m backend.scripts.fetch_finki_announcements
# python -m backend.scripts.fetch_finki_announcements --dry-run   # preview without writing
```
Pulls new posts from the official FINKI student-announcement board (oldsite.finki.ukim.mk/mk/student-announcement)
into the `blog_posts` table shown on the Ресурси/Blog page — the automated counterpart to an admin manually
pasting a link. Safe to re-run any time: it only ever adds announcements whose URL isn't already imported.

The same script also pulls from a second, national source — the Ministry of Education and Science's own
"Конкурси" and "Стипендии" boards (`mon.gov.mk`, see `backend/services/mon_konkursi.py`). Not every posting
there is student-relevant (a lot is K-12 textbooks, pupil dormitories, gymnasium programs), so
`mon_konkursi.is_relevant_to_students` filters before anything is imported. Both sources land in the same
"Конкурси" Blog category and each scraped posting is fetched via the exact same `blog_fetcher.py` path a
manually-pasted admin link would use, so they're indistinguishable from any other Blog card once imported.

To run it automatically every day on Windows, use `run_finki_announcements.bat` (in the project root) with
Task Scheduler:
```
schtasks /create /tn "FINKI Oglasi Sync" /tr "C:\Users\stoja\Desktop\timski_proekt\run_finki_announcements.bat" /sc daily /st 09:00
```
Each run's output is appended to `finki_announcements_log.txt` in the project root, since a scheduled task has
no visible console — check that file to see what was added on each run.

**On Linux (e.g. the deployment server)**, use `run_finki_announcements.sh` instead of the `.bat` file, and
`crontab` instead of Task Scheduler:
```bash
chmod +x run_finki_announcements.sh
crontab -e
# add this line to run daily at 09:00 (adjust the path to where the project lives on that machine):
0 9 * * * /full/path/to/timski_proekt/run_finki_announcements.sh
```
Same idea as the Windows version — it activates the venv, runs the sync, and appends output to
`finki_announcements_log.txt` next to it.

### 8. Run the tests
```bash
source .venv/bin/activate
pytest backend/tests/ -v
```
Needs a real Postgres database reachable via `DATABASE_URL` with `alembic upgrade head` already applied (some tests exercise the `pg_trgm` fuzzy-match extension directly — there's no SQLite fallback). No frontend tests exist yet (see "Current Status").

If you hit `ModuleNotFoundError: No module named 'backend'`: that means `backend/__init__.py` is missing. Without it, pytest's own import-path resolution stops one directory too shallow (inserts `backend/` onto `sys.path` instead of the project root) and `backend.xxx` imports fail - even though the app itself runs fine either way, since `uvicorn`/`python -m` add the project root differently. The file should already exist in this repo; if it's gone, `touch backend/__init__.py` fixes it.

## Project Architecture

```
.
├── README.md                    # Project documentation
├── config.py                    # Environment variables & app config
├── requirements.txt             # Python dependencies
├── alembic.ini                  # Alembic config
│
├── alembic/                     # Database migrations
│   └── versions/                # One file per migration - run `alembic upgrade head`
│
├── frontend/                    # React + TypeScript SPA (Vite) - see "Frontend" below
│   └── src/
│       ├── api/                 # apiFetch client, auth/conversations/chatTools/blog calls
│       ├── context/             # AuthContext (user/token/status), ThemeContext (light/dark), HelpTourContext (onboarding)
│       ├── hooks/                # useChatStream (SSE), useConversations, useConversationPolling (group chat), useCollapsed (sidebar state)
│       ├── routes/               # ProtectedRoute - redirects to /login unless authenticated
│       ├── pages/                # Login/Register/Chat/Courses/CourseDetail/BlogPage/etc.
│       │                        #   (CommunityCoursesPage.tsx and AdminStub.tsx exist but aren't wired into
│       │                        #   App.tsx's route table - leftover/unused, not a bug if you can't find them linked anywhere)
│       ├── components/          # layout/sidebar/chat/sources/modals(AddBlogPostModal)/courses/onboarding(HelpTourModal)/Dropdown.tsx
│       │                        #   (courses/LessonDetail.tsx - lesson documentation + quiz UI,
│       │                        #    courses/MaterialStudyGuide.tsx - Marketplace material study-guide UI)
│       └── types/                # TS interfaces mirroring backend/models/*.py
│
└── backend/                     # Main application root
    │
    ├── main.py                  # FastAPI entry point - registers all routes, CORS config
    │
    ├── ai/                      # AI integration layer
    │   └── chat.py              # Groq API calls, streaming, quiz/summary/explore/followups generation,
    │                            #   isolated single-source drafts + verify/merge call (see "Answer Verification")
    │
    ├── database/                # Data storage layer
    │   ├── session.py           # SQLAlchemy engine, SessionLocal, get_db dependency
    │   └── models.py            # ORM tables: User, VerificationToken, Conversation, ChatMessage,
    │                            #   ConversationMember, ConversationInvite, CachedSearch, Course,
    │                            #   CourseMaterial, CourseNote, Recording, CoursePurchase, Lesson,
    │                            #   CourseSource, QuizAttempt, BlogPost
    │
    ├── middleware/               # Request/response processing
    │   ├── auth.py               # get_current_user dependency (JWT auth guard)
    │   └── rate_limit.py         # slowapi Limiter used on auth routes
    │
    ├── models/                  # Pydantic schemas
    │   ├── message.py           # Message schema: {role, content}
    │   ├── chatRequest.py       # Chat request: {messages, subject, search, conversation_id}
    │   ├── searchResult.py      # Search result: {title, url, snippet}
    │   ├── QuizRequest.py       # Quiz generation request
    │   ├── exploreRequest.py    # Topic exploration request
    │   ├── summaryRequest.py    # Summary generation request
    │   ├── askMoreRequest.py    # Follow-up questions request
    │   ├── authRequest.py       # Register/Login/ForgotPassword/ResetPassword schemas
    │   ├── conversationRequest.py # Conversation create/update/list/detail + member/invite schemas
    │   ├── courseResponse.py    # Course/CourseMaterial/CourseNote/Recording/Lesson/AdminCourseOut/MaterialStudyGuideOut response schemas
    │   ├── courseSubmitRequest.py # Course submission + admin reject-reason schemas
    │   ├── courseNoteRequest.py  # Community study-note create schema
    │   ├── quizProgressRequest.py # Quiz attempt create/update schemas
    │   ├── quizProgressResponse.py # Quiz attempt + recommendation response schemas
    │   ├── blogRequest.py         # Blog post create-from-URL request schema
    │   └── blogResponse.py       # BlogPost response schema
    │
    ├── routes/                  # API endpoints (controllers)
    │   ├── health.py            # /api/health - Service health check
    │   ├── chatRoute.py         # /api/chat, /api/quiz, /api/summary, /api/explore, /api/ask-more
    │   ├── conversationRoute.py # /api/conversations/* - CRUD + export for chat history
    │   ├── courseRoute.py       # /api/courses/* - catalog, Marketplace submission, deletion,
    │   │                        #   + lessons, community-notes, and Marketplace material study-guide endpoints
    │   ├── adminRoute.py        # /api/admin/* - course approval/rejection queue
    │   ├── billingRoute.py      # /api/billing/* - Stripe subscription + one-time course purchase
    │   ├── uploadRoute.py       # /api/courses/upload-material - Supabase Storage file uploads
    │   ├── quizProgressRoute.py # /api/quiz-progress/* - quiz attempt tracking + recommendations
    │   ├── blogRoute.py         # /api/blog/* - News & Recommendations feed, admin article submission
    │   └── auth/                # /api/auth/* - Register, Login, Logout, Me, verify, reset
    │       └── __init__.py
    │
    ├── services/                # Business logic layer
    │   ├── search_cache.py      # Cache lookup/write in front of Tavily (exact + pg_trgm fuzzy match),
    │   │                        #   plus a looser related-search lookup for answer_verification.py
    │   ├── answer_verification.py # Dual-source (+ optional third) draft/verify orchestration - see "Answer Verification"
    │   ├── chat_service.py      # Conversation resolve/save helpers used by chatRoute.py
    │   ├── chat_state.py        # In-memory, self-expiring "is a reply generating for this conversation" flag (group chat)
    │   ├── course_context.py    # Formats a Course into a context block for the AI prompt
    │   ├── blog_fetcher.py      # Scrapes title/excerpt/image from a pasted article URL
    │   ├── finki_announcements.py # Discovers and imports FINKI student announcements + job posts
    │   ├── mon_konkursi.py      # Discovers Ministry of Education konkursi/stipendii postings, filtered for student relevance
    │   ├── material_study_guide.py # Extracts text from a Marketplace material's own URL for AI study-guide generation
    │   └── ingestion/           # Standalone scrapers/loaders - never triggered by live API traffic
    │       ├── finki_hub_client.py  # Polite httpx wrapper (UA, rate limit, robots.txt check)
    │       ├── predmeti_scraper.py  # Course metadata from assets.finki-hub.com/courses.json
    │       ├── snimki_scraper.py    # Recording listings from the recordings-listing GitHub repo
    │       ├── upsert.py            # Idempotent ON CONFLICT DO UPDATE helpers (courses/materials/recordings)
    │       ├── cli.py               # `python -m backend.services.ingestion.cli --source all|predmeti|snimki|lessons`
    │       │
    │       │   # Below: AI-generated lesson content pipeline, driven by an
    │       │   # externally-held courses_db.json (see README's "Lesson Content" section)
    │       ├── courses_db.py        # Loads/looks up courses_db.json
    │       ├── source_discovery.py  # Gemini + Google Search grounding - finds real content-page URLs
    │       ├── source_text.py       # Fetches + splits sources into sections (HTML/PDF/local .docx)
    │       ├── title_translation.py # Macedonian -> English lesson title translation (cached)
    │       ├── lesson_matching.py   # Scores/picks the best source excerpt per lesson topic
    │       ├── gemini_generator.py  # Generates lesson documentation + quiz via Gemini
    │       ├── lesson_upsert.py     # Manual find-then-update-or-insert for Lesson/CourseSource
    │       └── seed_lessons.py      # Orchestrates the whole pipeline per course, writes a run report
    │
    ├── scripts/                 # One-off admin CLI scripts, not imported by the running app
    │   ├── make_admin.py         # `python -m backend.scripts.make_admin <email> [--demote]` - promote/demote a user to admin
    │   └── fetch_finki_announcements.py # `python -m backend.scripts.fetch_finki_announcements` - sync FINKI announcements + jobs into blog_posts
    │
    ├── static/                  # Legacy static files, no longer served by main.py (kept for reference)
    │   ├── index.html           # Alternative/older UI
    │   └── learnwise-2.html     # Original vanilla-JS chat UI - superseded by frontend/
    │
    ├── utils/                   # Helper functions
    │   ├── security.py          # Password hashing (bcrypt) + JWT create/decode
    │   └── email.py              # Sends via Resend if configured, else logs to console
    │
    ├── web_search/              # Web search integration
    │   └── search.py            # Tavily API - search, query building
    │
    └── tests/                   # Unit & integration tests
        ├── conftest.py            # Shared helpers (register_and_login, cleanup_test_data) + disables the register rate limit for tests marked @pytest.mark.bulk_register
        ├── test_search_cache.py   # Cache normalize/match/hit tests + find_related_cached_search bounds (needs a real Postgres w/ pg_trgm)
        ├── test_answer_verification.py # should_verify gating/size-gate, the fallback matrix, third-source draft handling (Groq calls mocked)
        ├── test_course_context.py # format_course_context() + _get_course_context() coverage
        ├── test_ai_chat.py        # Prompt construction, course_context threading, model/prompt regression guards
        ├── test_chat_route.py     # SSE mid-stream failure handling (event: error frame + partial-reply save), group-chat prompt-rebuild-from-DB, member can chat
        ├── test_conversation_members.py # Invites (accept/revoke/expire/cap), member leave/kick, owner-only actions
        ├── test_course_submission.py  # Submission gating, pending/rejected visibility, /mine, has_submitted_courses
        ├── test_course_notes.py       # Community notes: no premium gate, never locked, pending-course visibility, delete permissions
        ├── test_admin_approval.py     # Admin approve/reject state machine + permission gating
        ├── test_make_admin_script.py  # make_admin.py's promote/demote role-switching logic
        ├── test_marketplace_pricing.py # source/price_filter listing, priced-course locking rules
        ├── test_course_deletion.py    # Owner/admin delete permissions, official-catalog guard
        ├── test_billing.py            # Stripe checkout/cancel/webhook (Stripe SDK mocked, no real keys needed)
        ├── test_upload_material.py    # Supabase upload endpoint (Supabase SDK mocked, no real keys needed)
        ├── test_datetime_usage.py     # Guards against naive/deprecated datetime.utcnow() usage creeping back in
        ├── test_gemini_prompts.py     # Lesson-generation prompt construction/regression guards
        ├── test_lesson_matching.py    # Source-excerpt-to-lesson-topic matching/scoring
        ├── test_lesson_quiz_rate_limit.py # POST .../lessons/{id}/quiz rate limiting
        ├── test_lesson_quiz_difficulty.py # Medium/Hard quiz tiers - independent columns, no premium needed
        ├── test_lesson_upsert.py      # Lesson/CourseSource find-then-update-or-insert logic
        ├── test_quiz_progress_route.py # /api/quiz-progress/* CRUD + recommendations
        ├── test_seed_lessons.py       # Lesson-seeding pipeline orchestration/report generation
        ├── test_finki_announcements.py # FINKI announcement sync: category guessing, URL discovery, import, deduplication
        ├── test_mon_konkursi.py       # MON konkursi/stipendii scraping + student-relevance filtering
        ├── test_blog_route.py         # Admin add/delete auth gating, SSRF guard on pasted URLs, duplicate-URL guard
        ├── test_material_study_guide.py # Marketplace material study-guide generation, category gating, purchase/lock gating
        └── test_generation_method.py  # Lesson.generation_method ("source" vs "general_knowledge") tagging
```

## Architecture Layers Explained

| Layer | Directory | Purpose |
|-------|-----------|---------|
| Presentation | routes/ | API endpoints - handles HTTP requests/responses |
| Business Logic | services/ | Search caching, chat/conversation persistence, course context formatting, course-data ingestion |
| Data Access | database/ | Database models and connections |
| AI Integration | ai/ | Groq API calls and prompt engineering |
| Search | web_search/ | Tavily API integration for live documentation |
| Middleware | middleware/ | Request processing - JWT auth guard, rate limiting |
| Models | models/ | Pydantic schemas for request/response validation |
| Utils | utils/ | Helper functions used across the app |
| Static | static/ | Legacy HTML/JS - no longer served, kept for reference only |
| Frontend | frontend/ | React + TypeScript SPA (Vite) - the actual UI now |
| Tests | tests/ | Unit and integration tests |

## Data Flow

```
1. User sends message → routes/chatRoute.py
2. Web search (if enabled) → services/search_cache.py → cache hit, or web_search/search.py → Tavily API on a miss
3. Optional course context (if course_id given) → services/course_context.py → courses/recordings tables
4. Build final prompt context → ai/chat.py
5. AI response → Groq API (streaming)
6. Save to database → database/models.py
7. Return response → routes/chatRoute.py → User
```

## Key Components

### AI Layer (ai/chat.py)
- Handles all Groq API interactions, called directly via `httpx`, no SDK. `GROQ_MODEL = "openai/gpt-oss-120b"` is the main model (`llama-3.3-70b-versatile` was retired from Groq's catalog and this is its closest replacement, confirmed 2026-08-20); `DRAFT_MODEL = "openai/gpt-oss-20b"` is a smaller/cheaper model in the same family, used only for the internal draft/comparison calls in the answer-verification pipeline below
- Manages system prompts and context injection (search results are injected as extra context before the model answers)
- Streams responses back to the client via Server-Sent Events
- Also powers `/api/quiz`, `/api/summary`, `/api/explore`, `/api/ask-more` — these do **not** call Groq's streaming path, they return a single JSON response each
- `_ANSWER_MAX_TOKENS = 1800` caps every student-facing streamed answer (both the plain path and the verification pipeline's merge step). This isn't just an output-length cap: Groq's per-minute token budget (TPM) is charged against the *reserved* `max_tokens` the instant a request is made, not against what the model actually ends up generating — so a generous `max_tokens` eats most of a tight TPM budget before a single prompt token is even counted, and was a direct cause of the rate-limit crash described below

### Web Search (web_search/search.py) + Search Cache (services/search_cache.py)
- `web_search/search.py` integrates with the Tavily Search API, builds queries, and formats results for AI context
- `services/search_cache.py` sits in front of it: `/api/chat` and `/api/explore` now call `get_or_search()`/`get_or_search_many()` instead of hitting Tavily directly. A question is matched against the `cached_searches` table first — exact normalized match, then a Postgres `pg_trgm` fuzzy-similarity fallback for near-duplicate phrasing (scoped per `subject`) — and only falls through to a live Tavily call on a genuine cache miss. Cache entries soft-refresh after 90 days rather than expiring outright, since study-content answers don't go stale on a clock
- `find_related_cached_search()` is a second, looser lookup used only by the answer-verification pipeline below: given this turn's own search already went live (no exact/near-duplicate hit), it cheaply checks (one extra `pg_trgm` query, **no live API call**) whether some *other*, genuinely different past question is still loosely related, to offer as a third source to cross-check against. Bounded both below (`RELATED_SIMILARITY_THRESHOLD = 0.15`, otherwise it surfaces noise) and above (`SIMILARITY_THRESHOLD = 0.35`, otherwise it can "find" the row `get_or_search()` itself just inserted for this exact question a moment earlier — a real bug caught during live testing)

### Answer Verification (services/answer_verification.py + ai/chat.py)
**Why this exists**: before this, `/api/chat` just concatenated live search results and course materials into one string and sent it to Groq in a single call — nothing caught it if the model blended details across the two sources, or embellished beyond what either one actually said. This module cross-checks instead.

**How it works, when both a live search *and* real course content are available for a question** (`answer_verification.should_verify()` gates on exactly that, plus a size check below):
1. Two isolated draft answers are generated **concurrently** (`asyncio.gather`), each using the cheaper `DRAFT_MODEL` and seeing **only one** raw context block — one draft sees only the search results, the other only the course materials — with an explicit instruction to say plainly what its one source does and doesn't cover, never filling a gap from outside/general knowledge. These drafts are internal artifacts, never shown to the student raw.
2. If a third, loosely-related cached search happens to be cheaply available (see `find_related_cached_search()` above) **and** adding it still fits the token budget (`_cached_source_fits_budget` — its context was never counted by the initial gate below, since it's only looked up *after* that gate passes), a **third** isolated draft is generated from it too. This Groq call is deliberately deferred until *after* the two always-present drafts are confirmed to have succeeded (run alongside the comparison note instead), specifically so a primary-draft failure never pays for a third-source call it's about to throw away in the fallback branches below — purely additive either way: if it fails, or didn't fit the budget, it's just omitted, never triggers a fallback.
3. A short comparison note is generated (`generate_comparison_notes`) explaining how the search and course drafts relate — what each uniquely covers, where they agree, where they conflict, and which to trust more. Also non-fatal if it fails.
4. A final **verify/merge** call (the stronger `GROQ_MODEL`) sees *all* the drafts **and** the raw context blocks they were built from — not just the drafts' own wording — and produces the one answer the student actually sees, keeping only claims a raw context block actually supports, dropping anything no source backs (even if it "sounds reasonable"), and calling out conflicts between sources explicitly instead of silently picking one. This is the actual hallucination guard: checking a claim against its real source, not just against another draft's paraphrase of it.
5. **Fallback matrix** (`build_verified_answer`): both main drafts fail → falls back to today's plain joined-context single call (the pre-feature path, so it needs no new testing); only one fails → falls back to a single-source call scoped to whichever draft succeeded; both succeed but the verify call fails before its first chunk → still falls back to the joined-context call, but the reasoning panel is still shown (the drafts were real); verify fails **after** streaming has started → propagates to `chatRoute.py`'s existing SSE error handling, since there's no way to retroactively un-stream partial text.
6. The frontend shows all of this as a persisted, click-to-expand **"Thought for Xs"** panel on the message (`MessageBubbleAI.tsx`) — status updates stream live via `event: thinking` SSE frames while it's working, then the trace stays there afterward instead of vanishing the moment the answer starts. Expanding it shows the comparison note and each source's card (Web search / Course materials / Cached search when present).
7. Separately, the model is instructed (`SYSTEM_PROMPT` rule 11) to title any in-answer "what do the sources say" comparison exactly `## Source comparison` and put it last — the frontend regex-splits that heading out of the raw answer text and renders it as its own collapsed-by-default block at the bottom of the message, instead of it just being another heading in the middle of the answer. (Deliberately not named "recap"/"summary" — that already means the separate Study recap/Summary tool elsewhere in the app.)

**Cost/safety controls** (all in `services/answer_verification.py` unless noted):
- `ENABLE_ANSWER_VERIFICATION` (`config.py`, defaults `"true"`) — a kill switch. This pipeline can make up to 5 Groq calls for one question instead of 1, so being able to turn it off instantly (no deploy) matters if cost/latency doesn't pan out.
- A size gate (`_MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION`, a rough chars-per-token estimate — no real tokenizer is used) skips the whole pipeline and falls back to the plain single-call path when the combined context + conversation history is already large. This exists because of a **real production crash**: a course with 100+ ingested recordings, combined with a long conversation, made this pipeline's stacked Groq calls blow straight through the account's Groq tier's 8,000-tokens-per-minute limit — failing *every* call in the pipeline, including the safety-net fallback, since it reused the same oversized context. Below this gate, behavior is unaffected either way. Sized with the verify call's *actual* worst-case cost in mind (its own reserved `max_tokens`, system-prompt overhead, and up to 3 full drafts re-embedded on top of the gated context/history — not just the gated amount alone), not merely "some number under 8000."
- Draft calls send only the latest user message, not the full conversation history — they don't need conversational continuity (never shown to the student), and sending full history to 2-3 draft calls was needlessly duplicating it on top of what the verify call (which does need it) already sends.
- `_ANSWER_MAX_TOKENS` (see AI Layer above) — the actual root cause fix: Groq counts a request's *reserved* `max_tokens` against its per-minute budget regardless of real output length, so this was lowered from 4096 across the board.
- **The plain single-call path (`stream_groq_response`) has its own independent size safety net too** (`ai/chat.py::_fit_to_token_budget`, a separate, more generous budget since this call carries none of the pipeline's extra overhead) — it isn't just protected indirectly through the verification gate above. This closes what was originally a real gap: every fallback destination in this pipeline (the plain default path, *and* the verify-failure fallback) ultimately calls this same function, so it's now never itself unprotected regardless of which caller reached it. Trims context first (truncated, not dropped), then the oldest conversation turns if that alone isn't enough — always keeping at least the latest message.

**Not shown as a source, but visible elsewhere**: whether *this turn's own* search came from the cache at all (as opposed to the third, cross-check-only cached source above) is a separate, simpler signal — see `event: searchMeta` in the API Endpoints section below and the "From cached search" pill in the sources sidebar.

### Routes (routes/)
- `chatRoute.py`: `/api/chat`, `/api/quiz`, `/api/summary`, `/api/explore`, `/api/ask-more` — **all require auth**
- `health.py`: service health monitoring
- `auth/`: authentication endpoints (register, login, logout, me, verify-email, forgot/reset password)
- `conversationRoute.py`: chat history CRUD + export, **all require auth**
- `courseRoute.py`: `/api/courses/*` - catalog (public), Marketplace submission/deletion/uploads and lessons endpoints (mixed auth requirements, see "API Endpoints" below)
- `adminRoute.py`: `/api/admin/*` - course approval/rejection queue, **requires an admin account**
- `blogRoute.py`: `/api/blog/*` - News & Recommendations feed; `GET` is public, `POST`/`DELETE` **require an admin account** and `POST` is rate-limited (10/minute per IP) - see "API Endpoints" below
- `billingRoute.py`: `/api/billing/*` - Stripe subscription + one-time course purchase
- `uploadRoute.py`: `/api/courses/upload-material` - Supabase Storage file uploads
- `quizProgressRoute.py`: `/api/quiz-progress/*` - quiz attempt tracking + recommendations, **all require auth**

### Models (models/)
- Request/response validation using Pydantic
- Type-safe data structures
- Automatic API documentation generation (visit `/docs` while the server is running)

## Auth & Chat History — how it actually works

This was added by a teammate on the `maja` branch and merged via PR #1. Summary for anyone who didn't build it:

- **Passwords**: hashed with bcrypt (`passlib`) in `backend/utils/security.py` before being stored — never stored or logged in plaintext.
- **Login tokens**: a single stateless JWT (HS256, signed with `JWT_SECRET_KEY`), returned as `access_token` on register/login, sent back by the client as `Authorization: Bearer <token>` on every authenticated request. Tokens expire after **1 day** and there is **no refresh token and no server-side revocation** — "logout" is purely a client-side action (the endpoint exists but doesn't invalidate anything server-side). This is a deliberate MVP trade-off, not a bug, but worth knowing: a token keeps working until it naturally expires even after "logging out."
- **Auth guard**: `backend/middleware/auth.py`'s `get_current_user` dependency decodes the JWT and loads the `User` row. It's applied to `/api/chat`, `/api/quiz`, `/api/summary`, `/api/explore`, `/api/ask-more`, and every `/api/conversations/*` route — consistently now across all of them.
- **Rate limiting**: `/api/auth/register`, `/api/auth/login`, and `/api/auth/forgot-password` are limited to 5 requests/minute per IP (`slowapi`, in-memory store — fine for a single-process deployment; swap in a Redis storage backend if this ever runs with multiple workers).
- **Email verification / password reset**: `backend/utils/email.py::send_email()` sends via the Resend API if `RESEND_API_KEY` is set; otherwise it falls back to **printing the link to the server console** (`[DEV] ... link: ...`). Fine for local dev/demo without a Resend account configured.
- **Chat history**: every chat lives in a `Conversation` (id, owner, title, subject, timestamps) which owns an ordered list of `ChatMessage` rows (role, content, author, timestamp). Deleting a conversation cascades and deletes its messages. A conversation is visible only to its owner and any invited members (see "Group chat" below) — `conversationRoute.py`'s `_get_member_conversation` helper returns a 404 (not a 403) if you try to access a conversation you don't own or belong to, so you can't even tell whether a given conversation ID belongs to someone else.
- **Permanent conversation numbering**: the frontend's masthead shows each conversation as "No. NN" (magazine-issue style) — `Conversation.issue_no`, stamped once at creation from `User.conversation_seq` (migration `b1e4a7c92d05`), the owner's Nth-ever conversation. Both are plain integer columns, not something recomputed from the live conversation list, specifically so deleting an earlier conversation never renumbers the ones that came after it. Assigned via an atomic `UPDATE ... RETURNING` (`conversationRoute.py::create_conversation` and `chat_service.py::resolve_conversation` — there are two conversation-creation paths, since sending a first message with no `conversation_id` yet auto-creates one) so two concurrent creates for the same user can't collide on the same number.
- **Streaming + persistence**: `/api/chat` streams the AI's reply via SSE. Because the database session tied to the HTTP request closes as soon as the streaming response starts, the code opens a **second, fresh database session** partway through the stream just to save the assistant's final reply once it's fully generated.
- **Graceful failure mid-stream**: if Groq errors out partway through a response (rate limit, timeout, etc.), the backend catches it, sends the client a proper `event: error` SSE frame with a readable message (e.g. "You're sending messages too fast"), and still saves whatever partial answer had already been generated instead of losing it. The frontend shows the error alongside the partial answer rather than replacing it. Covered by `backend/tests/test_chat_route.py` — verified the tests actually catch a regression here, not just pass regardless, by temporarily reverting the fix and confirming they failed.
- **Stop generating**: the composer's send button turns into a stop button while a response is streaming (`useChatStream`'s `abort()`, backed by a real `AbortController`). Clicking it always stops the client from receiving/showing more text. **Known limitation**: unlike the server-error case above, a client-initiated disconnect doesn't reliably trigger the same save-partial-reply path — Starlette/anyio can raise `RuntimeError: aclose(): asynchronous generator is already running` when cleaning up the stream generator on a client disconnect, which is a deeper async cleanup issue than this fix addresses. So stopping generation is instant and reliable; the partial answer being saved to that conversation's history on a *user-initiated* stop is not guaranteed (it is guaranteed on a *server-side* error).

## Frontend (frontend/)

A Vite + React + TypeScript SPA that replaces `backend/static/learnwise-2.html` entirely — `backend/main.py` no longer serves that file. It talks to the exact REST API documented in this README (nothing frontend-specific exists on the backend beyond CORS/`ALLOWED_ORIGINS`).

- **Routing**: `react-router-dom` — `/login`, `/register`, `/forgot-password`, `/reset-password`, `/verify-email`, and `/blog` are public (`/blog` matches the backend's public `GET /api/blog` - its admin-only add/delete controls are hidden client-side via `user?.role === 'admin'`, same pattern as the rest of the app); everything else requires auth (a `ProtectedRoute` wrapper redirects to `/login` otherwise): `/chat`, `/chat/:conversationId`, `/courses`, `/courses/:courseId`, `/progress`, `/admin`, `/marketplace`, `/marketplace/submit`, `/marketplace/:courseId`, `/my-courses`, `/subscribe`, `/billing/success`, `/billing/cancel`. All of these are real pages now, not stubs.
- **Courses section**: `CoursesPage` lists ingested courses grouped by semester with a search box; `CourseDetailPage` shows a course's metadata pills, description, materials list, and recordings grouped by category (Предавања/Аудиториски вежби/etc.), each linking out to its source. A left-sidebar nav (`NavTabs`, shared with the chat page) switches between Chat and Courses.
- **Auth**: JWT kept in `localStorage` (same trade-off the old HTML app had — the backend only issues bearer tokens, not httpOnly cookies, so this wasn't "fixed" here, just carried forward knowingly). `AuthContext` calls `GET /api/auth/me` on load to restore a session; a central API client clears the token and redirects to `/login` on any `401`.
- **Theme**: `ThemeContext` (`frontend/src/context/ThemeContext.tsx`) toggles a `data-theme` attribute on `<html>` between `"light"`/`"dark"`, driving every color via CSS custom properties in `globals.css` — no per-component dark-mode logic. Defaults to the OS's `prefers-color-scheme` on first visit, then remembers the explicit choice in `localStorage` (`lw_theme`) from then on. Toggled from the account menu in the sidebar footer (`UserFooter.tsx`), not a floating button.
- **Collapsible sidebars**: both the left (nav/chat history) and right (sources/study tools) sidebars can be collapsed to an icon-only rail via `useCollapsed` (`frontend/src/hooks/useCollapsed.ts`), a small localStorage-backed boolean hook (`lw_sidebar_left` / passed down for the right sidebar) - state persists across reloads, independent of the existing responsive breakpoints that hard-hide the right sidebar on narrow screens. The collapsed left sidebar keeps one action reachable (start a new conversation) rather than going fully icon-free.
- **Help / onboarding tour**: `HelpTourContext` + `HelpTourModal` (`frontend/src/context/HelpTourContext.tsx`, `frontend/src/components/onboarding/HelpTourModal.tsx`) show a short skippable slideshow the first time a user logs in (tracked via a `lw_help_seen` localStorage flag, not a backend column - it's purely a "have they seen the tour in this browser" flag), covering the sidebar, course/subject context, code blocks, the Study tools panel, and every other page the user has access to (My courses/Admin slides only appear for users who'd actually see those nav items). Replayable any time via "Help & quick tour" in the account menu.
- **Streaming chat**: `useChatStream` replicates the backend's exact SSE framing via `fetch` + `ReadableStream` (native `EventSource` can't send the required `Authorization` header) — same approach the old vanilla-JS app used, just ported into a hook. It also exposes `abort()` (backed by a real `AbortController`) for the composer's stop-generating button, and treats a connection that ends without a `[DONE]` sentinel as its own error state instead of leaving the message stuck showing "typing" forever.
- **New-conversation shortcut**: pressing a bare `N` anywhere outside a text field, a `<select>`, an open dropdown/menu, or a modal starts a new conversation (`ChatPage.tsx`). Deliberately not a modifier combo — `Cmd/Ctrl+N` is reserved by every browser for "new window", and `Cmd/Ctrl+Shift+O` (an earlier attempt, matching ChatGPT's own binding) turned out to be reserved too, for the browser's own bookmark manager. Matched via `e.code` (physical key position), not `e.key`, so it fires correctly regardless of keyboard layout - `e.key` alone would silently never match on a Macedonian Cyrillic layout.
- **Markdown rendering is sanitized**: AI responses and summaries render through `frontend/src/utils/markdown.ts`, which pipes `marked`'s output through DOMPurify before it hits `dangerouslySetInnerHTML`. `marked` alone does not sanitize — since responses can embed live web-search content, unsanitized output would be a real XSS vector.
- **Code blocks**: fenced code in AI responses is syntax-highlighted via `highlight.js` (a custom `marked.Renderer().code` in `markdown.ts`, capped with a small in-memory cache so an unchanged block isn't re-highlighted on every streamed token) and wrapped in a `.code-block` with its own header bar - a language label plus a one-click Copy button (falls back to a no-op if `navigator.clipboard` is unavailable, e.g. a non-HTTPS deployment). Colors are on dedicated fixed CSS tokens (`--code-bg`/`--code-text`/`--code-border`), not the theme-swapping ones, so a code block looks the same in light and dark mode instead of inverting.
- **State/data**: no react-query or similar — plain `fetch` wrapped in a small typed API client (`frontend/src/api/`) plus React Context/hooks. Deliberate: there are only ~6 REST resources, and a query library would fight the raw SSE code path more than it would help.
- **Study tools**: Quiz/Summary/Explore/Ask More render as modals over the chat page (not separate routes), matching the original app's UX.
- **Course picker in the chat masthead**: `ChatMasthead` fetches `GET /api/courses` once on load and shows a course dropdown (a bordered "pill" with a book icon, next to the existing free-text Subject dropdown, separated by a divider since they're different things — course ties you to a specific FINKI course's real data, subject just nudges the live web search). Selecting one threads `course_id` through every chat/quiz/summary/explore/ask-more call. Hidden entirely if no courses are ingested yet, so it degrades gracefully. Both dropdowns are width-capped with ellipsis truncation — course names can run 60+ characters in Cyrillic, and without a cap it would balloon and shove everything else in the masthead out of place.
- **Custom `Dropdown` component** (`frontend/src/components/Dropdown.tsx`): both pickers above (and other selects in the app) use this instead of a native `<select>`, since a native select's open menu can't be restyled at all in any browser - it's what made the old pickers look out of place next to the rest of the custom UI. Reimplements what a native select gives for free: Arrow Up/Down + Home/End move between options, `aria-expanded`/`aria-haspopup` on the trigger, Escape or an outside click closes it, and focus returns to the trigger after a selection instead of being dropped.
- **Dev vs prod**: in dev, Vite proxies `/api` to `:8000` (see `frontend/vite.config.ts`) — no CORS needed. In prod, `npm run build` produces `frontend/dist`, which `backend/main.py` mounts directly at `/` if present, so the whole app can ship as a single FastAPI process.

## Course Data (courses / course_materials / recordings)

Ingested from the public, non-login-gated subdomains of **finki-hub.com** — an independent student-run open-source project (`github.com/finki-hub`), *not* the official university site, and explicitly not the login-gated Moodle at `courses.finki.ukim.mk` (out of scope — scraping that would need real student credentials).

- **predmeti.finki-hub.com** turned out to be a React SPA whose own data comes from a single public JSON asset (`assets.finki-hub.com/courses.json`) — `predmeti_scraper.py` fetches that directly, no HTML parsing needed.
- **snimki.finki-hub.com** is a static VitePress site built from Markdown in `github.com/finki-hub/recordings-listing` — `snimki_scraper.py` fetches the raw Markdown from GitHub and parses it (headers → categories/presenter+year groups, links → recordings or materials).
- **Important limitation, read before relying on this for real studying**: neither source publishes an actual course **syllabus**. `Course.description` is a synthesized blurb from metadata (course code, semester, credits, professors, prerequisites, tags) — FINKI's real syllabi live only behind the gated Moodle. `services/course_context.py` supplements this with the course's actual lecture-recording **topic titles** (e.g. "Циклуси (дел 1)", "Покажувачи") and its ingested **materials** (solved exercises, past-exercise sites, source repos — with real links) as the closest available stand-in for real course content, since those come from real lecture titles and real linked resources. This is disclosed in that file's docstring — don't oversell this feature as "the AI has read the syllabus."
- **The tutor is instructed not to fabricate resources**: early testing of the materials context showed the AI padding a real 3-item materials list with two invented, non-existent ones (a "FINKI portal" page and a fake GitHub search link) to seem more thorough. Fixed with an explicit system-prompt rule (`backend/ai/chat.py`) forbidding invented URLs/resources — re-verified afterward that it lists only what's actually provided. `backend/tests/test_ai_chat.py` guards the prompt text itself (that the rule can't be silently deleted) and that `course_context` actually reaches every prompt-builder function, though "the model doesn't hallucinate" isn't something a unit test can fully cover — that part stays on live verification.
- Ingestion is a standalone, manual/cron-able script (`python -m backend.services.ingestion.cli`), never triggered by live API traffic. It's a well-behaved client: real User-Agent, `robots.txt` check, ~1.5s delay between requests. Re-running it is safe (idempotent upserts, no duplicates).
- 67 courses have been ingested so far — run the CLI yourself to pull more or refresh existing ones.

## Lesson Content (lessons / course_sources)

A separate, deeper layer on top of Course Data: instead of just metadata + lecture topic titles, each lesson gets real AI-generated study documentation (and an on-demand quiz). By default this is grounded in an actual textbook/course-material excerpt — not the model's general knowledge — but for courses with no usable source, an admin can explicitly opt into general-knowledge generation instead (`--generate-without-source` / `--force-general-knowledge` below); every such lesson is disclaimed in its own text *and* flagged via `Lesson.generation_method` (`"source"` vs `"general_knowledge"`), so it's distinguishable from real source-grounded content at the data/API level too, not just by a markdown sentence a future edit could drop.

**This is not a self-contained scraper** — it's a content-*generation* pipeline driven by a hand-curated input file, `courses_db.json` (course → source textbook → lesson topic titles), exported from a shared "LearnWise - база извори" spreadsheet. It now lives in the repo at `backend/services/ingestion/courses_db.json`. There's no `.example.json`/schema file yet, so if you need to hand-edit it, coordinate with whoever maintains it rather than trying to reconstruct it from the code.

**How it works** (`backend/services/ingestion/`):
1. `courses_db.py` loads `courses_db.json` and looks up the requested `--course-codes`.
2. `source_discovery.py` (optional, Gemini + Google Search grounding) finds the real chapter/page URLs for a source whose stored URL is just a catalog page (e.g. OpenStax).
3. `source_text.py` fetches (and disk-caches) the source — HTML split by real heading tags, PDFs split heuristically by a regex over title-like lines, or local `.docx`/`.pdf` files for the handful of courses with no public source at all.
4. `title_translation.py` translates each Macedonian lesson title to English (cached), since most sources are English-language — needed for fair matching.
5. `lesson_matching.py` scores every extracted section against each lesson title and picks the best excerpt, skipping (not fabricating) anything below a confidence threshold.
6. `gemini_generator.py` generates the documentation from that excerpt *only* (explicit prompt rule against adding outside knowledge — the same lesson learned the hard way with course materials, see above), then the quiz from the documentation.
7. `lesson_upsert.py` writes it all to the `lessons`/`course_sources` tables (migration `bc6e93a07557`), resumable by default — a lesson that already has documentation is skipped unless `--force-regenerate` is passed, so a crashed batch just picks up where it left off without re-spending API calls.

**No usable source for a course?** By default such a course only gets topic-title-only `Lesson` rows (no Gemini calls, nothing to review). Two explicit, opt-in flags bypass that:
- `--generate-without-source` — for a course with genuinely no source in `courses_db.json`, generates real documentation from the model's own general knowledge instead of leaving topic-only rows.
- `--force-general-knowledge` — ignores a course's source even when one exists (e.g. it technically has a book, but matching/coverage was poor in practice), always generating from general knowledge instead.

Either path (`seed_lessons.py`'s `_generate_lessons_no_source`) always prepends `gemini_generator.NO_SOURCE_DISCLAIMER_MK` to the generated text *and* sets that lesson's `generation_method` column to `"general_knowledge"` (regular source-grounded lessons get `"source"`, also the default for existing/topic-only rows — migration `d8f3a1c9b274`) — so these lessons are never silently indistinguishable from real source-grounded ones, at the database/API level or in the run report (`Report.generated_no_source`). `full_audit.sql` also breaks out a `bez_izvor_ai_znaenje` count per course for exactly this.

**Quiz difficulty (Medium/Hard)**: each lesson can hold two independent, on-demand-generated quizzes — the original `quiz` column (Medium, `POST /{lesson_id}/quiz?difficulty=medium`, the default) and a separate `quiz_hard` column (migration `f7a2c9d14e6b`), generated only when a student explicitly asks for it via the Hard tab in `LessonDetail.tsx`. Regenerating one tier never touches the other. Hard uses the same Gemini pipeline (`gemini_generator.py`'s `build_quiz_prompt(..., difficulty="hard")`) but asks for application/analysis questions instead of fact recall.

**To run it**, you need a `GEMINI_API_KEY` in `.env` (get one free at https://aistudio.google.com/apikey) — `courses_db.json` ships in the repo, so `--courses-db-path` can just point at it:
```bash
python -m backend.services.ingestion.cli --source lessons \
    --courses-db-path backend/services/ingestion/courses_db.json \
    --course-codes F23L1W005,F23L1W020,F23L2W002
```
Useful flags: `--skip-quiz` (documentation-only pass, halves the Gemini calls per lesson), `--force-regenerate`, `--threshold <float>`, `--report-path <file>` (defaults to a timestamped markdown file listing what happened to every lesson touched — matched/skipped/errored with reasons), `--generate-without-source` / `--force-general-knowledge` (see above — review lessons generated this way before trusting them like sourced ones).

**Frontend**: `CourseDetailPage` shows a Lessons section per course; opening one (`LessonDetail.tsx`) shows the documentation and lets you generate/take the quiz. Fetched independently from materials/recordings, so a lessons-specific issue can't take down the rest of an otherwise-working course page.

**Security note, already fixed**: an early version of `LessonDetail.tsx` rendered AI-generated documentation via raw `dangerouslySetInnerHTML` instead of the sanitized `renderMarkdown()` helper every other AI-output view uses — a real stored-XSS vector, since that text is ultimately derived from fetched external content. Fixed - it now goes through `renderMarkdown()` like everything else.

**Note**: the Lessons section only ever has content for courses the pipeline has actually been run on (needs a `GEMINI_API_KEY` - see Setup above). Until then (or for courses never covered by `courses_db.json`), it correctly shows "No lessons generated for this course yet".

## Marketplace Study Guides (course_materials)

The Marketplace equivalent of Lesson Content above, but generated on demand from a single course material's own URL instead of a curated textbook source — no `courses_db.json` entry needed, works for any course (official catalog or Marketplace) that has materials.

- **On demand, not pre-seeded**: a student opens a material and clicks "Study Guide" (`frontend/src/components/courses/MaterialStudyGuide.tsx`) — nothing is generated until then. `GET /api/courses/{course_id}/materials/{material_id}/study-guide` returns whatever's already cached; `POST` (same path) generates documentation + a quiz the first time, or just the missing tier if documentation already exists. Rate-limited 5/minute per IP, same as the Lessons quiz endpoint.
- **Text extraction from the material itself**: `services/material_study_guide.py` fetches (disk-cached under `backend/services/material_study_guide_cache/`) and extracts readable text from the material's own URL — PDF via the same `pypdf` path `ingestion/source_text.py` uses, anything else via a plain BeautifulSoup text extraction (no heading-based section splitting like the curated-textbook pipeline needs, since this is one ad-hoc material, not a whole book to navigate). Video materials are rejected outright (`is_generatable_category`) — there's no text to work from, and the frontend hides the toggle for these too.
- **Same Medium/Hard quiz split as Lessons**: `CourseMaterial.quiz`/`quiz_hard` (migration `9d4c1a2f7e6b`) reuse the exact same `gemini_generator.generate_quiz(difficulty=...)` Lessons already use — documentation is generated once and shared by both tiers.
- **Gating**: same rule as Materials/Recordings generally — free courses open to anyone, priced courses need the submitter, an admin, or a `CoursePurchase` row. Any logged-in user can trigger generation (not restricted to the submitter/admin), since it's read access to something they can already view, just computed lazily.

## Current Status

| Component | Status   |
|-----------|----------|
| AI Chat with Streaming | Complete |
| Web Search Integration | Complete, now cache-backed (see below) |
| Frontend | Complete — React + TypeScript SPA (`frontend/`), replaces the old static HTML |
| User Authentication | Complete (register, login, logout, JWT, email verify, password reset — see caveats above) |
| Chat History | Complete (conversations saved to DB, list/search/rename/delete/export, sidebar wired up) |
| Group chat | Complete — up to 3 members per conversation, shareable invite links, polling-based sync (see "Group chat" under API Endpoints) |
| Quiz Generator | Complete (auth required, optional `course_id` context) |
| Summary Service | Complete (auth required, optional `course_id` context) |
| Explore Feature | Complete (auth required, cache-backed, optional `course_id` context) |
| Database Layer | Complete (PostgreSQL + SQLAlchemy + Alembic) |
| Search-Result Caching | Complete (`cached_searches` table, exact + pg_trgm fuzzy match) |
| Dual-source answer verification | Complete — cross-checks a live-search draft against a course-materials draft (+ an optional third, cheaply-found cached-search draft) before merging into one answer; gated on both sources being genuinely available, with a size-based fallback for oversized requests. Kill switch: `ENABLE_ANSWER_VERIFICATION` (see "Answer Verification" above) |
| Middleware | Complete (JWT auth guard on all endpoints, CORS origin allowlist, rate limiting on auth routes) |
| Tests | Backend: covers search cache, course context, AI prompt construction, SSE error handling, Marketplace/admin/billing/uploads (Stripe and Supabase calls mocked), lesson-content generation, quiz progress, and FINKI announcement sync (see "Run the tests" and the tests/ tree above). Frontend: none yet — no test framework configured |
| Course data / study content | Complete for 67 ingested courses (see "Course Data" above) — metadata + lecture topics + materials, no real syllabus text available from any public source |
| Course-aware chat (frontend) | Complete — course picker in the chat masthead, threads `course_id` through every chat/study-tool call |
| Quiz from lecture video | Not started — R&D idea only, see Roadmap |
| Courses browsing (frontend) | Complete — catalog + detail pages, listing materials/recordings per course |
| Marketplace / course submission | Complete — submit → admin approve/reject → public listing, free or priced |
| Admin panel | Complete — pending/approved/rejected/all filters, approve/reject/delete |
| Billing (Stripe) | Complete, test-mode only — submission subscription + per-course one-time purchase |
| Progress frontend page | Complete — real UI, quiz attempts tracked and low-scoring subjects recommended for revisiting |
| Lesson content (AI-generated docs + quizzes) | Complete — pipeline + UI built; needs a `GEMINI_API_KEY` to actually generate anything (see "Lesson Content" above) |
| Marketplace material study guides | Complete — on-demand per-material AI docs + Medium/Hard quiz, same `GEMINI_API_KEY` requirement (see "Marketplace Study Guides" above) |
| Community study notes | Complete — any logged-in user can attach a note to any course, no subscription needed, never locked even on a priced course |
| News & Recommendations (Blog) | Complete — FINKI + MON (Ministry of Education) announcement auto-sync, admin article submission by URL, category filtering, job postings feed |
| Onboarding tour & theme | Complete — skippable first-visit help tour (replayable from the account menu), light/dark theme remembered per browser |

### Notes for the team

- **Frontend stack**: now a real React + TypeScript SPA in `frontend/` (see "Frontend" above) — `backend/static/learnwise-2.html` is no longer served, though it's still on disk for reference.
- **Email sending**: uses Resend if `RESEND_API_KEY` is set, otherwise falls back to console logging (see above) — set the key before this goes anywhere near production.
- **Auth is now required everywhere that touches the tutor or your data**: `/api/chat`, `/api/quiz`, `/api/summary`, `/api/explore`, `/api/ask-more`, and all `/api/conversations/*` endpoints all require a valid `Authorization: Bearer <token>` header.
- **Search provider**: this app uses **Tavily**, not Brave (an earlier version of this README said Brave — that was a documentation-only typo, the code has always called Tavily).
- **CORS**: `ALLOWED_ORIGINS` in `.env` controls which frontend origins may call the API (defaults to the Vite dev server + FastAPI's own port) — update it once the React app has a real deployed URL.
- **`FRONTEND_URL` controls what invite links (and Stripe redirect links) look like**: group-chat invite URLs are built server-side as `f"{FRONTEND_URL}/chat/join/{token}"` (`conversationRoute.py`'s `create_invite`). Locally this defaults to `http://localhost:5173`, so a link looks like `http://localhost:5173/chat/join/2oW1mpU4uDtLlX1BJjZL5AuCyLq3mEl4ThQuCeOCnZI`. **Before deploying, set `FRONTEND_URL` in the backend's `.env` to the real deployed frontend origin** (e.g. `https://learnwise.example.com`), same as you'd do for `ALLOWED_ORIGINS` above — otherwise every invite link generated in production will point at `localhost` and be unusable for anyone but the person who created it. The token itself (`secrets.token_urlsafe`) is already opaque and long enough to be safely shared over chat/email/etc.

## API Endpoints

### Auth (`/api/auth`) - public unless noted
- `POST /register` - `{email, password, full_name?}` → `{access_token, token_type}`
- `POST /login` - `{email, password}` → `{access_token, token_type}`
- `POST /logout` - stateless, just returns a confirmation message
- `GET /me` - **requires auth** - returns the logged-in user's profile
- `GET /verify-email?token=...` - confirms the email (token is logged to console at registration, not emailed)
- `POST /forgot-password` - `{email}` → always returns a generic success message (doesn't leak which emails exist)
- `POST /reset-password` - `{token, new_password}`

### Conversations (`/api/conversations`) - all require auth
Up to 3 people can share one conversation (see "Group chat" below) - every endpoint here accepts the owner or an invited member unless noted, and 404s (not 403) for anyone else so conversation IDs aren't enumerable.
- `POST /` - create a conversation - `{title?, subject?}`
- `GET /?search=...` - list conversations you own or are a member of, optionally filtered by title
- `GET /{id}` - get a conversation with its full message history, member list, `is_owner`, `generating` (whether a reply is currently streaming for anyone in it), and `max_members` (the server-side cap, currently 3 — the frontend reads this instead of hardcoding it)
- `GET /{id}/status` - a cheap `{message_count, generating}` poll target, used by `useConversationPolling` instead of re-fetching the full conversation every tick (see "Group chat" below)
- `PATCH /{id}` - rename - `{title}` - any member
- `DELETE /{id}` - **owner only** - a member who wants out uses `DELETE /{id}/members/{their own user_id}` (leave) instead
- `GET /{id}/export?format=markdown|json` - download the conversation
- `POST /{id}/invites` - **owner only** - creates a shareable join link, returns `{token, url, expires_at}` (7-day default lifetime); multi-use until the conversation hits 3 members
- `DELETE /{id}/invites/{invite_id}` - **owner only** - revoke a link without removing anyone already invited through it
- `POST /conversations/invites/{token}/accept` - any logged-in user - joins the conversation, `410` if expired/revoked, `409` if already at 3 members, a no-op if already a member
- `GET /{id}/members` - list everyone (owner + members)
- `DELETE /{id}/members/{user_id}` - your own `user_id` to leave, or (owner only) someone else's to remove them; the owner can't be removed by anyone, including themselves - they delete the conversation instead

**Group chat, end to end**: the owner opens the Invite modal, which calls `POST /{id}/invites` and shows back a copyable `http://<FRONTEND_URL>/chat/join/{token}` link (see the `FRONTEND_URL` note above for what this looks like once deployed). Whoever opens that link either logs in/registers first (the app remembers the pending invite and resumes the join automatically right after auth — see `JoinConversationPage` and `LoginPage`/`RegisterPage`'s `location.state.from` handling) or, if already logged in, joins immediately via `POST /conversations/invites/{token}/accept`. From then on everyone in the conversation sees the same message history and the same AI replies.

Real-time sync is deliberately polling-based, not push/WebSocket - see `frontend/src/hooks/useConversationPolling.ts`. At up to 3 people, short-interval polling (every 2.5s, or every 1s while a reply is generating; paused while your own tab is streaming or the tab isn't focused) is simple and sufficient — it hits the cheap `GET /{id}/status` endpoint each tick and only fetches the full `GET /{id}` conversation when the message count actually changed, so an idle conversation with a long history isn't re-transferred every tick just to discover nothing happened. The backend still rebuilds each prompt from the database (not the calling tab's local message array) so two members typing near-simultaneously can't produce a reply built from a stale transcript. `ChatMessage.author_user_id` (null for assistant messages and for messages sent before this feature existed) is what lets the UI show "Alice: ..." instead of "You" for another member's messages. The `generating` flag (`services/chat_state.py`) is a plain in-memory, self-expiring dict keyed by conversation id — advisory only, and correct only within a single backend process (consistent with the rate limiter's existing single-process assumption; see "Auth & Chat History" above).

### Chat & study tools (`/api/chat`, `/api/quiz`, `/api/summary`, `/api/explore`, `/api/ask-more`) - all require auth
All five accept an optional `course_id?: number` — if given and it matches a row in `courses`, that course's metadata + lecture topics are folded into the prompt context (see "Course Data" above for what this context actually contains).
- `POST /api/chat` - `{messages, subject?, search?, conversation_id?, course_id?}` — omit `conversation_id` to start a new conversation, or pass an existing one to keep appending to it. Returns a `text/event-stream`, in this order when present:
  - `event: conversation` - `{id, title, issue_no}`, always first (so the frontend knows which conversation was created/used, and its permanent "No." — see "Permanent conversation numbering" above)
  - `event: sources` - the search results, if `search` was on and any came back
  - `event: searchMeta` - `{fromCache: bool}`, alongside `sources` - whether *this turn's own* search was served from `cached_searches` or fetched live from Tavily (shown as a small "From cached search" pill in the sources sidebar). Independent of the third-source cross-check described below.
  - `event: thinking` - `{status}`, zero or more live status updates while the answer-verification pipeline (see "Answer Verification" above) is working - only emitted when that pipeline actually runs
  - `event: reasoning` - the dual/triple-source drafts + comparison note, only when the verification pipeline ran and its drafts succeeded (see "Answer Verification" above) - powers the "Thought for Xs" panel
  - a stream of `data: <chunk>` events - the actual answer text
  - `event: error` - `{message}`, only on a mid-stream failure (partial text already sent is preserved, not replaced)
  - `data: [DONE]` - always last
- `POST /api/quiz` - `{messages, subject?, course_id?}` → a generated quiz
- `POST /api/summary` - `{messages, subject?, course_id?}` → a study summary
- `POST /api/explore` - `{messages, subject?, course_id?}` → related links (cache-backed, same as `/api/chat`)
- `POST /api/ask-more` - `{messages, subject?, course_id?}` → suggested follow-up questions

### Courses (`/api/courses`) - public, no auth needed (read-only catalog data, not user-specific) unless noted
- `GET /?semester=&search=&source=official|community|all&price_filter=free|purchased` - list courses; `source` splits the scraped catalog from Marketplace; `price_filter=purchased` requires auth
- `GET /{id}` - course detail, including `material_count`/`recording_count`
- `GET /{id}/materials` - non-recording resources (notes, external links, etc.) - `402` if the course is priced and locked
- `GET /{id}/recordings?category=` - lecture/exercise recording links - `402` if the course is priced and locked
- `GET /mine` - **requires auth** - every course the current user has submitted, any status
- `POST /submit` - **requires a premium subscription** - `{name, materials, price, ...}`, creates a course with status `"pending"`
- `POST /upload-material` - **requires auth, rate-limited to 10/minute per IP** (no subscription needed - uploading a file is free) - `multipart/form-data` with `file` + optional `context` (`material` default or `note`), returns `{url, resource_type, original_filename}` (Supabase Storage-backed). Type is verified from the file's actual bytes (magic numbers), not the client-supplied Content-Type header, which is otherwise trivially spoofable - `415` if unrecognized. Allowed: PDF, images (jpeg/png/webp/gif), video (mp4/webm/mov), Word (.doc/.docx), PowerPoint (.pptx). Size cap depends on `context` - 50 MB for `material` (Supabase free-tier limit), 10 MB for `note` (the fully open, unmoderated community-notes path gets a much smaller budget) - `413` over the cap, `400` for an unrecognized `context` value.
- `DELETE /{id}` - **requires auth** - the course's own submitter or an admin only; refuses to touch the scraped catalog
- `GET /{course_id}/materials/{material_id}/study-guide` - `402` if the course is priced and locked (same rule as Materials/Recordings) - returns whatever's already generated (see "Marketplace Study Guides" above)
- `POST /{course_id}/materials/{material_id}/study-guide?difficulty=medium|hard` - **requires auth, rate-limited to 5/minute per IP** - generates (or regenerates just the missing tier of) a material's AI study guide + quiz on demand. `400` for a video material (nothing to extract text from) or an invalid `difficulty`, `502` if fetching/extracting the material's own content or the Gemini call fails.

### Admin (`/api/admin`) - all require an admin account
- `GET /courses/pending` - pending submissions (Admin panel's default view)
- `GET /courses?status=pending|approved|rejected|all` - all user-submitted courses by status
- `POST /courses/{id}/approve`
- `POST /courses/{id}/reject` - `{reason}` (required, shown back to the submitter)
- `GET /notes?limit=` - every community-contributed note across every course, newest first (default 200, max 1000) - notes have no pending/approval workflow like course submissions, so this read-only, cross-course view is the only way to discover abuse without querying the database directly; deletion still goes through the existing `DELETE /api/courses/{course_id}/notes/{note_id}`

### Blog / News & Recommendations (`/api/blog`)
- `GET /` - public, no auth - every curated article, newest first
- `POST /` - **requires an admin account, rate-limited to 10/minute per IP** - `{url, category?}`; scrapes title/excerpt/image straight from the pasted page's own `<title>`/meta tags (`services/blog_fetcher.py`), nothing from the article body is stored. The fetch itself is SSRF-guarded: the URL (and every redirect hop it follows) is resolved and rejected if it points at a loopback/private/link-local/reserved address (this blocks cloud metadata endpoints like `169.254.169.254` too), and only `http`/`https` are allowed. `409` if that `url` was already added, `422` if the page can't be reached/parsed or is blocked by the SSRF guard.
- `DELETE /{post_id}` - **requires an admin account** - removes a bad or mis-scraped card

### Billing (`/api/billing`)
- `GET /plans` - public - live Stripe price/name/interval for the submission subscription
- `POST /checkout` - **requires auth** - starts the submission-subscription Checkout, returns `{checkout_url}`
- `POST /cancel` - **requires auth** - cancels the subscription immediately, not at period end
- `POST /courses/{id}/checkout` - **requires auth** - one-time Checkout to unlock a priced course
- `POST /webhook` - Stripe-only (signature-verified), not for direct use

### Lessons (`/api/courses/{course_id}/lessons`)
- `GET /` - list a course's lessons (topic title + whether documentation/a quiz already exist) - public, no auth
- `GET /{lesson_id}` - full lesson content (documentation + quiz, if generated) - public, no auth
- `POST /{lesson_id}/quiz?difficulty=medium|hard` - **requires auth, rate-limited to 5/minute per IP** - generates (or regenerates) the quiz for a lesson on demand via a real, billed Gemini call. `difficulty` defaults to `medium` (the original `quiz` column); `hard` writes to the separate `quiz_hard` column instead, leaving `medium` untouched. 400s if the lesson has no documentation yet, or if `difficulty` isn't `medium`/`hard`.

### Notes (`/api/courses/{course_id}/notes`)
Community-contributed study notes - deliberately separate from Materials above: any logged-in user can add one to any course (no premium subscription, unlike `POST /submit`), and unlike Materials/Recordings they're **never locked** even on a priced course - they're contributed by students, not part of what the course's submitter is selling.
- `GET /` - list a course's notes, newest first - public, no auth, never `402`s
- `POST /` - **requires auth** - `{title, url, description?}` (`url` can be a pasted link or a `POST /upload-material` result). `title`/`url` are trimmed and rejected if blank; `url` must be `http://`/`https://` - `422` otherwise (blocks a `javascript:`/`data:` URL from sitting in the DB and executing when another viewer clicks it).
- `DELETE /{note_id}` - **requires auth** - the note's own uploader or an admin only

### Quiz Progress (`/api/quiz-progress`) - all require auth
- `GET /` - list the current user's quiz attempts, most recently updated first
- `POST /` - start a new attempt - `{topic, subject?, total_questions}`
- `PATCH /{id}` - update progress - `{answered_count, correct_count}` (auto-marks `completed` once `answered_count >= total_questions`)
- `GET /recommendations` - up to 5 subjects where the user's average completed-quiz score is below 70%, sorted lowest-first

## How It Works

1. User sends a question
2. Backend builds a search query from the question + selected subject, served from `cached_searches` on a repeat/near-duplicate or fetched live from Tavily otherwise (see "Search Cache" above)
3. If a course is selected, that course's metadata/topics/materials are folded in too (see "Course Data" above)
4. **If both a live search and real course content are available**, the answer-verification pipeline cross-checks them instead of just concatenating the two into one prompt — see "Answer Verification" above for the full flow (isolated drafts → comparison note → verify/merge). Otherwise, the single context block goes straight to Groq as before
5. Groq streams a tutor-style answer grounded in the available context(s)
6. Sources appear in the sidebar so the user can verify; a "Thought for Xs" panel on the message shows the verification pipeline's reasoning when it ran

## Roadmap

The team has agreed on the following next steps, roughly in priority order. See the shared planning doc/Trello for full detail — this section is a living summary so nobody has to go dig for it.

1. **Backend hardening + search-result caching** ✅ done — Tavily results are now cached in `cached_searches` (exact + `pg_trgm` fuzzy match on the normalized query), so a repeated or near-duplicate question is answered from cache instead of a fresh API call. Also landed: CORS now uses an explicit `ALLOWED_ORIGINS` allowlist instead of `*`, rate limiting on `/login`/`/register`/`/forgot-password` (5/min via `slowapi`), real email sending via Resend (falls back to console logging if unconfigured), consistent auth across `/api/quiz`/`/api/summary`/`/api/explore`/`/api/ask-more`, and the `services/` layer now actually has code in it (`search_cache.py`, `chat_service.py`).
2. **React frontend** ✅ done — `backend/static/learnwise-2.html` has been replaced by a real Vite + TypeScript SPA in `frontend/`, against the exact same REST API. FastAPI is now a pure JSON API (`backend/main.py` no longer serves the old static HTML); the old files are left on disk for reference but are unreferenced. See "Frontend" above. `/courses`, `/courses/:courseId`, `/progress`, and `/admin` are all real pages now — no stubs left.
3. **Course/study data** ✅ done, 67 courses ingested — `Course`/`CourseMaterial`/`Recording` tables exist, `/api/courses/*` endpoints are live, the AI tutor accepts an optional `course_id` on chat/quiz/summary/explore/ask-more and folds in course metadata + topics + materials, and the frontend has a real Courses catalog + detail page (`/courses`, `/courses/:courseId`) *plus* a course picker right in the chat masthead so `course_id` actually gets used day-to-day, not just via the API. See "Course Data" above for the **important caveat**: no real syllabus text exists in any public source, so this is metadata + lecture topics + materials, not a full curriculum — and for the anti-hallucination fix that keeps the tutor from inventing resources that aren't actually in that data.
4. **Quiz generation from lecture recordings** (idea, not yet started) — `snimki.finki-hub.com` only lists links to recordings (almost certainly YouTube), with no transcripts, and the lectures are in Macedonian with a lot of Macedonian/English code-switching around technical terms. Plan: try YouTube's own (even auto-generated) captions first via `youtube-transcript-api`; if quality is too poor on real sample lectures, fall back to self-hosted Whisper transcription; cache whatever transcript is produced permanently, the same way search results get cached in step 1. This needs a short manual quality spike on a couple of real lectures before any pipeline gets built — Macedonian ASR quality on code-heavy lectures is the real risk here, not the engineering.
5. **Dual-source answer verification** ✅ done — prompted by a professor's suggestion to reduce hallucination by cross-checking live search against course materials, rather than concatenating both into one call as before. Isolated single-source drafts, a comparison note, and a verify/merge call now catch claims neither source actually supports; gated to only run when both sources are genuinely available, with a size-based fallback (and a kill switch, `ENABLE_ANSWER_VERIFICATION`) after a real production Groq rate-limit crash surfaced how expensive stacking several extra calls onto an already-large course/conversation context could get. See "Answer Verification" above for the full design — including the plain single-call path's own independent size safety net, added after a code review flagged that it was otherwise the one path every fallback in this pipeline ultimately depends on, unprotected.

## Extending It

### Add real email sending
Replace the `print(f"[DEV] ...")` lines in `backend/routes/auth/__init__.py` with a real provider call (Resend, SendGrid, SMTP, etc) — part of item 1 in the Roadmap above.

### Add YouTube transcript support if needed
```python
from youtube_transcript_api import YouTubeTranscriptApi
transcript = YouTubeTranscriptApi.get_transcript(video_id)
```
See item 4 in the Roadmap — validate transcript quality on real Macedonian lecture audio before building a full pipeline around this.

### Replace Tavily with other search providers
- **SerpAPI** (google results, paid)
- **DuckDuckGo** (unofficial, free, rate-limited)
