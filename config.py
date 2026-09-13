from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GROQ_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    DATABASE_URL: str = ""
    JWT_SECRET_KEY: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:8000"
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "LearnWise <onboarding@resend.dev>"

    # Stripe: lets a user pay for the "submit courses" subscription (see
    # routes/billingRoute.py). Get test-mode keys from
    # https://dashboard.stripe.com/test/apikeys after creating a (free,
    # no-verification-required-for-test-mode) Stripe account. STRIPE_PRICE_ID
    # is the id of a recurring Price you create in the dashboard for the
    # subscription product. STRIPE_WEBHOOK_SECRET comes from `stripe listen`
    # (see README) during local dev, or the dashboard's webhook endpoint once deployed.
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID: str = ""
    # Used to build the Stripe Checkout success/cancel redirect URLs.
    FRONTEND_URL: str = "http://localhost:5173"

    # Supabase Storage: stores course materials (books/PDFs/videos) uploaded
    # via POST /api/courses/upload-material (see routes/uploadRoute.py). Free
    # project at https://supabase.com (no card required). SUPABASE_URL and
    # SUPABASE_SERVICE_ROLE_KEY are on the project's Settings > API page - use
    # the service_role key (not anon) since uploads happen server-side and
    # need to bypass bucket RLS policies. SUPABASE_STORAGE_BUCKET is the name
    # of a *public* bucket you create under Storage in the dashboard.
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "course-materials"

    # Kill switch for the dual-source answer-verification pipeline (see
    # services/answer_verification.py) - it triples the LLM calls made for a
    # chat question when both live search and course context are available
    # (two isolated drafts + one verify/merge call), so this can turn it off
    # instantly without a deploy if cost/latency doesn't pan out in practice.
    # Set to "false" to disable; anything else (including unset) means enabled.
    ENABLE_ANSWER_VERIFICATION: str = "true"

    # extra="ignore": don't crash on stray/leftover .env keys (e.g. from a
    # since-removed integration) - just ignore anything we don't declare above.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
GROQ_API_KEY = settings.GROQ_API_KEY
TAVILY_API_KEY = settings.TAVILY_API_KEY
GEMINI_API_KEY = settings.GEMINI_API_KEY
DATABASE_URL = settings.DATABASE_URL
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
ALLOWED_ORIGINS = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]
RESEND_API_KEY = settings.RESEND_API_KEY
ENABLE_ANSWER_VERIFICATION = settings.ENABLE_ANSWER_VERIFICATION.strip().lower() != "false"
EMAIL_FROM = settings.EMAIL_FROM
STRIPE_SECRET_KEY = settings.STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET = settings.STRIPE_WEBHOOK_SECRET
STRIPE_PRICE_ID = settings.STRIPE_PRICE_ID
FRONTEND_URL = settings.FRONTEND_URL
SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY = settings.SUPABASE_SERVICE_ROLE_KEY
SUPABASE_STORAGE_BUCKET = settings.SUPABASE_STORAGE_BUCKET