# ETAIR — Industrial Knowledge Intelligence Platform

> **Document-first, governance-first industrial workspace with AI retrieval.**

## Quick Start

### Prerequisites
- Docker & Docker Compose
- An OpenAI API key (for embeddings + AI query answering)

### 1. Configure environment

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — add your OPENAI_API_KEY
```

### 2. Start the full stack

```bash
docker compose up --build
```

This starts:
| Service | URL |
|---|---|
| Frontend (Next.js) | http://localhost:3000 |
| Backend API (FastAPI) | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |
| PostgreSQL | localhost:5432 |

### 3. Open the app

Navigate to **http://localhost:3000** → Register → Create Workspace → Upload documents.

---

## Architecture Overview

```
frontend/          Next.js 14 (TypeScript)
backend/
  app/
    main.py        FastAPI entrypoint
    models.py      SQLAlchemy ORM (PostgreSQL + pgvector)
    auth.py        JWT auth + role enforcement
    storage.py     MinIO S3-compatible object storage
    config.py      Pydantic settings
    routers/       API endpoints (auth, workspaces, files, query)
    services/      Retrieval engine + LLM service
    workers/       Celery tasks + file parsers (PDF, DOCX, PPTX, XLSX, Image, Audio, CAD)
    utils/         File family detection
docker-compose.yml Full stack: PostgreSQL, Redis, MinIO, Backend, Workers, Frontend
```

## File Families Supported

| Family | Formats | Parser |
|---|---|---|
| Text/Office | PDF, DOCX, PPTX, TXT | PyMuPDF, python-docx, python-pptx |
| Tables | XLSX, CSV, TSV, ODS | pandas, openpyxl |
| Images/Scans | JPG, PNG, TIFF, BMP | Tesseract OCR |
| Audio | MP3, WAV, M4A | OpenAI Whisper API |
| CAD | DXF, DWG (title-block) | ezdxf |
| Operational | JSON, XML, logs | Custom parsers |

## Key Design Decisions

- **Store once, derive many**: Original in MinIO → text/chunks in PostgreSQL → embeddings in pgvector → graph in PostgreSQL graph tables
- **Permission-first retrieval**: User role filter applied before ANY search step
- **Hybrid retrieval**: Metadata keyword + pgvector cosine + graph traversal, fused and ranked
- **Source-cited answers**: Every AI answer lists file ID, version, and page/chunk
- **Linear versioning**: Stable `document_id` + incremental `version_number`, no branching complexity

## Adding an OpenAI Key

Without an OpenAI key:
- File upload and metadata search work normally
- Vector search and AI query answering are disabled (graceful fallback)

With an OpenAI key:
- Full hybrid retrieval (embeddings generated on upload)
- AI query answering with source citations

## Scaling Path

| When | Action |
|---|---|
| > 5M chunks | Migrate pgvector → Qdrant |
| Complex graph queries | Migrate PostgreSQL graph tables → Neo4j |
| Production workloads | MinIO → AWS S3 (config change only) |
| Enterprise auth | Add SAML/OIDC SSO |
