# Workspace

## Overview

pnpm workspace monorepo using TypeScript and Python. Each package manages its own dependencies.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)
- **Python version**: 3.11 (for MK AI)

## Key Commands

- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `pnpm --filter @workspace/api-server run dev` — run API server locally

See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details.

## Artifacts

### MK AI (`artifacts/mk-ai/`)
- **Type**: Python Flask web application
- **Preview path**: `/mk-ai/`
- **Port**: 18330
- **Stack**: Python 3.11, Flask, Groq API, Pillow, SQLite
- **Features**:
  - Multi-turn AI chat with session history (in-memory per user)
  - Auto model switching: code→llama-3.3-70b, vision→llama-4-scout, chat→llama-3.1-8b
  - Smart intent detection (English + Hinglish)
  - Image generation via Pollinations AI with Pillow watermarking (MK + MOHTASHIM KHAN)
  - Image analysis via Groq Vision
  - SQLite user authentication (register/login/logout, Werkzeug password hashing)
  - ChatGPT-style dark UI (#0a0a0a) with conversation sidebar
  - Mobile-responsive with hamburger menu
  - "About MK AI" modal with features grid
  - REST API: GET/POST /conversations, DELETE /conversations/<id>, GET /conversations/<id>/messages
- **Entry point**: `artifacts/mk-ai/app.py`
- **Templates**: `artifacts/mk-ai/templates/` (base.html, login.html, register.html, chat.html)
- **Generated images**: `artifacts/mk-ai/static/generated/`
- **Run**: `bash /home/runner/workspace/artifacts/mk-ai/run.sh`
- **Required secrets**: `GROQ_API_KEY`, `SESSION_SECRET`
