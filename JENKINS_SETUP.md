# Jenkins CI setup for HackDox

Why this exists: to have a real, working Jenkins/Groovy pipeline to point to
and discuss for CI/CD-focused interviews (e.g. an SDET role listing
"Jenkins / Github Actions" pipeline experience). The pipeline itself lives
in `Jenkinsfile` at the repo root; this doc is the one-time setup to get a
green build.

## Prerequisites

- Java 11+ (Jenkins requires it). Check with `java -version`.
- A shell that can run `sh` steps — Linux, macOS, or **WSL2 on Windows**.
  The Jenkinsfile uses `sh`, so run the Jenkins controller from WSL2 rather
  than native Windows (or swap `sh` → `bat` in the Jenkinsfile if you'd
  rather stay native).
- No Docker required for this path — Jenkins runs standalone as a `.war`.
  (Optional Docker variant at the bottom, since Docker is also on the
  SDET job's required-tools list.)

## 1. Install and start Jenkins

```bash
# From WSL2 (or any Linux shell)
curl -fsSL https://get.jenkins.io/war-stable/latest/jenkins.war -o jenkins.war
java -jar jenkins.war --httpPort=8080
```

Leave this running in its own terminal. First boot prints an initial admin
password and the path it's stored at — copy it.

## 2. Unlock and configure

1. Browse to `http://localhost:8080`.
2. Paste the initial admin password from the console output.
3. Choose **Install suggested plugins** (this covers Git, Pipeline,
   Timestamper, and JUnit already). If you skip the wizard defaults, install
   at minimum: **Git**, **Pipeline**, **JUnit**.
4. Create your first admin user.

## 3. Create the pipeline job

1. **New Item** → name it `HackDox CI` → type **Pipeline** → OK.
2. Under **Build Triggers**, check **Poll SCM** and set schedule to
   `H/5 * * * *` (matches the `pollSCM` trigger already declared in the
   Jenkinsfile — you can actually leave this section blank in the UI since
   the trigger is defined in code, but ticking it here makes it visible
   without opening the file).
3. Under **Pipeline**, set:
   - Definition: **Pipeline script from SCM**
   - SCM: **Git**
   - Repository URL: `https://github.com/hobbes144/HackDox.git`
   - Branch Specifier: `*/main` (or `*/batch-3-UserFeedback-ContentGeneration`
     while that branch is where active work lives)
   - Script Path: `Jenkinsfile` (default, already correct)
4. Save.

## 4. Run it

Click **Build Now**. First run will be slower (building the venv from
scratch). Watch the **Stage View** — you should see Checkout → Set Up
Python → Install Dependencies → Lint → Foundation Tests → Pytest Suite all
go green (Lint may go yellow/"unstable" — that's by design, see the comment
in the Jenkinsfile).

On success you get:
- A **Stage View** with per-stage timing.
- A **Test Result Trend** graph (from the JUnit XML) tracking the pytest
  suite pass count build over build.
- `reports/junit.xml` and `reports/coverage.xml` archived as build
  artifacts, downloadable from the build page.

## What to say about it in an interview

- **Why Groovy/declarative syntax**: the pipeline is code, versioned in the
  repo alongside the tests it runs — no manual "configure a job in the UI"
  step to keep in sync by hand.
- **Why a throwaway venv per build**: reproducibility — the build doesn't
  depend on whatever's installed on the agent; every run starts clean from
  `requirements.txt`.
- **Why Lint is `catchError`'d to UNSTABLE instead of failing**: a
  judgment call about gate severity — style findings shouldn't block a
  merge on a solo project with existing debt, but they should be visible
  and trending, not silently ignored. On a team repo I'd flip that to a
  hard failure once the current findings are cleared.
- **Why Poll SCM instead of a GitHub webhook**: this Jenkins instance runs
  on a local machine that isn't internet-reachable, so GitHub can't push a
  webhook to it. In a real deployment (or with a tunnel like ngrok/Cloudflare
  Tunnel) I'd switch the trigger to `githubPush()` and add the GitHub
  plugin's webhook instead — lower latency, no polling overhead.
- **Two independent test layers**: `run_foundation_tests.py` is a
  stdlib-only runner (no pytest dependency) kept from before pytest was
  wired in, and the pipeline runs both — a nice concrete example of legacy
  test-infra decisions and how CI can carry them forward without deleting
  history.

## Optional: run Jenkins in Docker instead

Since Docker is also on the SDET job's tool list, this is worth doing once
Docker Desktop (or Docker in WSL2) is available:

```bash
docker run -d --name hackdox-jenkins \
  -p 8080:8080 -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  jenkins/jenkins:lts-jdk11
```

Same setup steps from here — the container serves the same UI on
`localhost:8080`. This also gives you a second, equally real talking point:
"I ran the Jenkins controller itself in a container" is a fine answer to a
Docker question in the same interview.

## Natural next step: a GitHub Actions companion

The job posting lists "Jenkins / Github Actions" together. A minimal
`.github/workflows/ci.yml` mirroring the same stages (venv → deps → ruff →
foundation tests → pytest) would run on every push with no local server to
keep alive, giving an always-on green badge to point to. Not built yet —
flagged here as the logical next piece if you want both tools represented.
