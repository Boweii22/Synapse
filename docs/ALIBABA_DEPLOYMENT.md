# Deploying Synapse to Alibaba Cloud

This is the step-by-step path to a real, verifiable Alibaba Cloud deployment
for the submission's "Proof of Alibaba Cloud Deployment" requirement
(CLAUDE.md section 2 / section 10). It covers the simpler self-hosted-Postgres
path first, then the ApsaraDB RDS upgrade if time allows.

## Option A: ECS + self-hosted Postgres (recommended for time-boxed hackathon use)

### 1. Create an Alibaba Cloud account

Sign up at https://www.alibabacloud.com/. New accounts get a free-tier trial
that comfortably covers an ECS instance for the hackathon window.

### 2. Launch an ECS instance

In the console: **Elastic Compute Service (ECS) -> Instances -> Create Instance**.

- Region: whichever is closest to you / your judges
- Instance spec: 2 vCPU / 4 GB RAM is enough (e.g. `ecs.t6-c1m2.large` or similar burstable type)
- Image: Ubuntu 22.04 LTS
- Storage: 40 GB system disk is plenty
- Network: enable a public IP (or bind an elastic IP after creation)
- Security group: create/attach one allowing inbound TCP on:
  - `22` (SSH) -- restrict to your IP if possible
  - `80` (frontend)
  - `8000` (backend API)

Note the instance's public IP once it's running -- you'll need it below as `<ECS_IP>`.

### 3. SSH in and install Docker

```bash
ssh root@<ECS_IP>

curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version   # confirm the compose plugin is present
```

### 4. Clone the repo and configure environment

```bash
git clone <your-repo-url> synapse
cd synapse
cp .env.example .env
nano .env   # fill in QWEN_API_KEY (real DashScope key) and set:
            #   VITE_API_BASE_URL=http://<ECS_IP>:8000
            #   CORS_ORIGINS=http://<ECS_IP>
```

### 5. Bring the stack up

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

This starts three containers: `synapse-postgres` (pgvector-enabled Postgres,
schema auto-applied from `backend/app/db/schema.sql`), `synapse-backend`
(FastAPI on port 8000), and `synapse-frontend` (the built React app served by
nginx on port 80).

### 6. Verify the live deployment

```bash
curl http://<ECS_IP>:8000/health
# -> {"status": "ok"}
```

Then open `http://<ECS_IP>` in a browser -- you should see the Synapse chat UI
talking to the backend running on the same instance.

### 7. What to link as "proof of deployment"

For the submission, link:
- This file (`docs/ALIBABA_DEPLOYMENT.md`)
- `docker-compose.prod.yml` and `frontend/Dockerfile` (the actual deploy config)
- A screenshot of the ECS console showing the running instance
- The live `http://<ECS_IP>:8000/health` and `http://<ECS_IP>` URLs, if you're
  keeping the instance up through judging

## Option B: ApsaraDB RDS for PostgreSQL (upgrade path, if time allows)

More impressive per CLAUDE.md section 2, but more setup:

1. **ApsaraDB RDS console -> Create Instance -> PostgreSQL** (version 15+, which
   supports the `vector` extension in Alibaba Cloud's managed offering).
2. Create a database and account, note the connection endpoint.
3. Under the instance's **Database Connection**, add the ECS instance's private
   IP (or security group) to the RDS whitelist so the backend container can reach it.
4. Enable the `vector` extension: connect via `psql` (or the RDS console's SQL
   window) and run the same `CREATE EXTENSION IF NOT EXISTS vector;` statement
   from `backend/app/db/schema.sql`, then apply the rest of that schema file.
5. Update `.env`'s `DATABASE_URL` to point at the RDS endpoint instead of the
   local `postgres` container, e.g.:
   ```
   DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/synapse
   ```
6. Start only the backend and frontend containers (skip the local Postgres
   service since RDS replaces it):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build backend frontend
   ```
7. For "proof of deployment," link the RDS instance's console page/ID alongside the ECS one.

## Notes

- The backend's `qwen_client.py` calls DashScope's public API directly, so
  network egress from the ECS instance to `dashscope-intl.aliyuncs.com` must be
  allowed (it is, by default, on a standard ECS security group -- egress isn't
  restricted unless you've locked it down).
- Rotate the `QWEN_API_KEY` in `.env` if this repo or its `.env` file is ever
  made public; `.env` is gitignored and should never be committed.
