# Complete Step-by-Step Guide: Deploying ETAIR2 on Supabase + Vercel ($0 Free Tier)

This guide walks you through deploying your **ETAIR2 Industrial Knowledge Platform** to **Vercel** and **Supabase** directly from your GitHub repository (`https://github.com/BURNFIR3/ETAIR2_Umiamkesher`) for **$0/month**.

---

## Architecture Summary

1. **Frontend**: Hosted on **Vercel** (`frontend/` folder). Automatically deploys whenever code is pushed to your GitHub `main` branch.
2. **Database**: Hosted on **Supabase Postgres** (Free Tier: 500MB DB with `pgvector` pre-installed).
3. **File Storage**: Hosted on **Supabase Storage** (Free Tier: 1GB S3-compatible object storage).
4. **RAC Agent Backend**: Hosted on **Render / Railway / Fly.io** (`backend/` folder). Acts as the high-performance AI document parsing, graph extraction, and query engine.

---

## Step 1: Set Up Supabase (Database + File Storage)

1. Go to [supabase.com](https://supabase.com) and create a free account & project (e.g. `etair-prod`).
2. **Enable pgvector & Create Tables**:
   In your Supabase Dashboard, go to **SQL Editor** and run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
   *(Note: When your backend starts for the first time, `database.py` automatically runs `Base.metadata.create_all` to create all required tables with `workspace_id` isolation).*

3. **Create S3 Storage Buckets**:
   In your Supabase Dashboard, go to **Storage** and create two **Public or Private** buckets:
   - `etair-files` (for raw industrial PDFs/documents)
   - `etair-thumbnails` (for generated cover images)

4. **Get Your Connection Credentials (Where to find them in the Supabase UI)**:
   - **Database Connection String (`DATABASE_URL`)**:
     - Click the green **`Connect`** button at the top-center header of your dashboard (next to your project name `etair-prod`).
     - Or, go to the left icon bar → click **Database** → **Connection string** → **URI** tab.
     - Copy the `postgresql://...` URI and replace `[YOUR-PASSWORD]` with your project database password.
   - **API Keys (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`)**:
     - In the left sidebar under **Settings** (where you see *Infrastructure*), click on **`API Keys`**.
     - Copy your **Project URL** (`https://xxxx.supabase.co`) and your **`service_role` secret key**.
   - **Storage S3 Credentials (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`)**:
     - In the far-left icon bar, click the **Storage** icon (folder icon).
     - Inside Storage, look at the left sub-menu and click **Configuration** → **S3 Connection** (or **Settings**).
     - Copy the **Endpoint** (`xxxx.supabase.co/storage/v1/s3`), and click **Generate new access key** to copy your **Access Key ID** and **Secret Access Key**.

---

## Step 2: Deploy the RAC Agent Backend Service (`backend/`) on Render (Free Web Service)

To process heavy industrial PDFs (`tesseract-ocr`, `poppler-utils`, `spacy` NLP models) and vector embeddings (`BAAI/bge-base-en-v1.5`) for $0/month, deploy the `backend/` folder on **Render Free Web Service** using our Docker container:

1. Go to [render.com](https://render.com), log in, and click **New + → Web Service**.
2. Select **Build and deploy from a Git repository** and connect your GitHub repo: `https://github.com/BURNFIR3/ETAIR2_Umiamkesher`.
3. Fill out the exact configuration fields on Render:
   - **Name**: `etair-backend`
   - **Region**: Choose any region (e.g. Frankfurt or Oregon)
   - **Root Directory**: **`backend`** *(IMPORTANT: Type `backend` so Render looks inside the backend folder)*
   - **Runtime**: **Docker** *(Render will automatically detect `backend/Dockerfile` and install all system tools like Tesseract & Poppler)*
   - **Instance Type**: Select **Free** ($0/month, 512MB RAM)
4. Under **Environment Variables**, click **Add Environment Variable** (or click *Secret Files / Environment*) and add these exact keys:

   | Key | Value to Enter |
   | :--- | :--- |
   | `ENVIRONMENT` | `production` |
   | `DEBUG` | `False` |
   | `DATABASE_URL` | `postgresql+asyncpg://postgres:[YOUR_PASSWORD]@db.rebgfdpqrdjsadcjyemx.supabase.co:5432/postgres?ssl=require` |
   | `CELERY_DATABASE_URL` | `postgresql+psycopg2://postgres:[YOUR_PASSWORD]@db.rebgfdpqrdjsadcjyemx.supabase.co:5432/postgres?sslmode=require` |
   | `STORAGE_PROVIDER` | `supabase_s3` |
   | `MINIO_ENDPOINT` | `rebgfdpqrdjsadcjyemx.supabase.co/storage/v1/s3` |
   | `MINIO_ACCESS_KEY` | *(Paste your Supabase Storage S3 Access Key ID)* |
   | `MINIO_SECRET_KEY` | *(Paste your Supabase Storage S3 Secret Access Key)* |
   | `MINIO_BUCKET_FILES` | `etair-files` |
   | `MINIO_BUCKET_THUMBS` | `etair-thumbnails` |
   | `MINIO_SECURE` | `True` |
   | `MINIO_REGION` | `us-east-1` |
   | `SUPABASE_URL` | `https://rebgfdpqrdjsadcjyemx.supabase.co` |
   | `SUPABASE_SERVICE_KEY` | *(Paste your Supabase `service_role` secret key)* |
   | `GROQ_API_KEY` | *(Your 100% Free Groq API key: `gsk_...`)* |
   | `LOCAL_EMBEDDING_MODEL` | `BAAI/bge-base-en-v1.5` |
   | `JWT_SECRET` | `etair_super_secret_jwt_token_key_2026` |
   | `REDIS_URL` | *(Optional for Celery queues: e.g. Free Upstash Redis URL or `redis://localhost:6379/0`)* |

5. Click **Create Web Service**.
   Render will now build the Docker container (takes ~3-4 minutes) and provide a live URL like **`https://etair-backend.onrender.com`**. *(Copy this URL for Step 3 on Vercel!)*

---

## Step 3: Deploy the Next.js Frontend to Vercel (`frontend/`)

1. Go to [vercel.com](https://vercel.com) and click **Add New -> Project**.
2. Import your GitHub repository: `https://github.com/BURNFIR3/ETAIR2_Umiamkesher`.
3. In the **Configure Project** screen:
   - **Root Directory**: Click *Edit* and select **`frontend`**.
   - **Framework Preset**: Next.js (automatically detected via `vercel.json`).
4. Under **Environment Variables**, add:
   - `NEXT_PUBLIC_API_URL`: Set to the URL of your deployed RAC Agent backend from Step 2 (for example, `https://etair-backend.onrender.com`).
5. Click **Deploy**.

Because we configured `export const dynamic = 'force-dynamic'` and `vercel.json`, your frontend will build and deploy cleanly in ~45 seconds!

---

## Step 4: Verification & Continuous Deployment

- **Automated Git Pulls**: Whenever you run `git push origin main` to `https://github.com/BURNFIR3/ETAIR2_Umiamkesher`, Vercel and your RAC Agent backend will automatically pull the latest code and re-deploy without downtime.
- **Data Isolation & Security**: Every user session attaches `workspace_id` and JWT credentials, ensuring full compliance with Supabase Row-Level Security principles.
