# GitHub Actions: build the container image on every PR to `main`

This walks through setting up a pipeline that builds the Docker image for
the nightly Azure Container Apps Job every time you open a PR against
`main` (as a build-check), and actually publishes it to GitHub Container
Registry (GHCR) once that PR merges. Written for someone who hasn't set up
GitHub Actions before.

**Why split it that way (build-on-PR, publish-on-merge)** rather than
publishing on every PR: publishing an image tags it as something Azure
could pull and run. You don't want that happening from a branch that
hasn't been reviewed/merged yet — you just want to know the Dockerfile
still builds. Only a push to `main` (which is what a merge does) should
produce a real, pullable image.

Recall from earlier in this project: there's only **one** image here — the
Job image (Python + `requirements.txt` + the app code). There's no
always-on serving container in this design (the dashboard gets published
to Blob static website hosting instead), so nothing else needs building.

## Step 1 — add a Dockerfile

Create `Dockerfile` at the repo root:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py .
COPY smart_meter/ smart_meter/

# Placeholder default -- once the nightly script that chains SMT ingest ->
# dashboard rebuild -> Blob upload exists, this CMD should run that script
# instead. For now this at least gives the image something runnable so we
# can confirm the build pipeline itself works end to end.
CMD ["python3", "-m", "smart_meter.ingest", "--from-smt", "14"]
```

Note what's deliberately **not** copied in: `.env`, `data/`, `meter_data.db`,
`dashboard.html`, `.venv/`, `.git/`. None of that belongs inside the image —
credentials come in as environment variables at run time (see the `.env`
guidance in the README), and the DB/HTML are things the container
produces/fetches at run time, not something baked in at build time.

## Step 2 — add a `.dockerignore`

Even though the Dockerfile above only `COPY`s specific paths, add this as a
second line of defense so a future broader `COPY . .` can't accidentally
pull in something it shouldn't:

```
.git
.venv
venv
.env
.env.example
__pycache__
*.pyc
data/
meter_data.db
dashboard.html
.vscode
docs
```

## Step 3 — add the workflow file

Create `.github/workflows/build-image.yml`:

```yaml
name: Build container image

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read
  packages: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      # GHCR requires the image name to be all-lowercase. GitHub usernames
      # and repo names can contain uppercase letters, so this normalizes it
      # rather than letting the push step fail on a naming rule you'd have
      # no reason to expect.
      - name: Compute lowercase image name
        id: image
        run: |
          echo "name=$(echo ghcr.io/${{ github.repository }} | tr '[:upper:]' '[:lower:]')" >> "$GITHUB_OUTPUT"

      - name: Log in to GHCR
        if: github.event_name == 'push'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build (and push only on merge to main)
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          push: ${{ github.event_name == 'push' }}
          tags: |
            ${{ steps.image.outputs.name }}:latest
            ${{ steps.image.outputs.name }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

What this does on each trigger:
- **On a PR into `main`**: checks out the code and runs the build, `platforms: linux/amd64` (so it's a real test of the same architecture Azure will run, not your Mac's arm64) — but `push` evaluates to `false`, so nothing is published and no registry login even happens. A green check shows up on the PR either way.
- **On merge to `main`** (a push event): logs into GHCR using the repo's own built-in `GITHUB_TOKEN` (no secret to create yourself), builds again, and pushes two tags — `:latest` and `:<commit-sha>` (the SHA tag matters later for pointing the Azure Job at a specific known-good build instead of a floating `latest`).

`docker/build-push-action` using GitHub's own amd64 runners is what sidesteps the Apple Silicon cross-build problem entirely — nothing builds on your Mac, so there's no local Docker install needed for this pipeline at all.

## Step 4 — one repo setting to check

GitHub Actions' default token permissions are sometimes locked to
read-only at the repo level, which would make the push step fail with a
permissions error even though the YAML above requests `packages: write`.
Check it once:

**Settings → Actions → General → Workflow permissions** → make sure
**"Read and write permissions"** is selected, then Save.

## Step 5 — try it

1. Create a branch, make a trivial change (e.g. a comment), push it, open a PR into `main`.
2. On the PR, you should see a check named "Build container image / build" — click it to watch the build run. It should go green without pushing anything (check the log — you'll see no "Log in to GHCR" step ran).
3. Merge the PR. The workflow runs again, this time as a push event — now it logs in and pushes.

## Step 6 — confirm the image landed

Go to the repo's main page → right sidebar → **Packages** (or your GitHub
profile → Packages). You should see a new container package with `latest`
and a commit-SHA tag.

## Step 7 — set the package visibility

Container packages pushed this way typically default to **private**. Open
the package → **Package settings** → **Change visibility**. For this
project, **public** is the simpler choice: nothing secret is ever baked
into the image (SMT credentials only ever arrive as environment variables
at run time), and a public package means the Azure Container Apps Job can
pull it with zero registry credentials configured. Private is fine too if
you'd rather keep it that way — it just means an extra registry-credential
step when we wire up the Container Apps Job later.

## What's not done yet

This pipeline only builds and publishes the image — it doesn't touch
Azure. Two things still ahead, from the broader plan:
- The Dockerfile's `CMD` is a placeholder; it needs to become the real
  "pull from SMT → rebuild dashboard.html → upload to Blob" script once
  that's written (the Blob upload piece doesn't exist yet).
- Creating the actual Azure resources (Resource Group, Storage Account,
  Container Apps Environment + Job) and pointing the Job at this GHCR
  image is a separate step, covered when we get to it.
