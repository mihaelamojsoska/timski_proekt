import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


from backend.middleware.rate_limit import limiter
from backend.routes import (
    health,
    chatRoute,
    auth,
    conversationRoute,
    courseRoute,
    quizProgressRoute,
    adminRoute,
    billingRoute,
    uploadRoute,
    blogRoute,
)
from config import ALLOWED_ORIGINS

app = FastAPI(title="LearnWise AI Tutor")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Dev (Vite on :5173) proxies /api straight to this server, so no CORS is
# needed there. ALLOWED_ORIGINS still matters for any other client hitting
# the API directly (e.g. a separately-hosted frontend, or tools like Postman).
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chatRoute.router)
app.include_router(auth.router)
app.include_router(conversationRoute.router)
app.include_router(courseRoute.router)
app.include_router(quizProgressRoute.router)
app.include_router(adminRoute.router)
app.include_router(billingRoute.router)
app.include_router(uploadRoute.router)
app.include_router(blogRoute.router)

# Production build: serve the compiled React app for anything that isn't
# /api/*. Registered after the routers above so it never shadows them.
#
# StaticFiles(html=True) alone only serves real files on disk - it 404s on
# client-side routes like /login or /chat/join/<token> that only exist inside
# React Router. The catch-all route below fixes that: it serves a real
# static asset (JS/CSS/images) if the path matches one, otherwise falls
# back to index.html so React Router can take over and render the route.
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        candidate = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(frontend_dist, "index.html"))