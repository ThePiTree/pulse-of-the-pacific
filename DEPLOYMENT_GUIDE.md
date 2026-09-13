# Deployment Guide — every step, nothing skipped

This is the exhaustive companion to `README.md`. It assumes **no prior experience** with Git,
GitHub, the command line, or web hosting. If you've deployed sites before, the README's shorter
version is probably enough. Here, every command and every click is spelled out, with what you
should see after each one and what to do if it goes wrong.

Total time for a first-timer: about **30–45 minutes**. You will end with a live, auto-updating
website on a free `https://` address.

> **Status note:** this guide's Part 4 walks through Cloudflare Pages, but the site as actually
> deployed today runs on **GitHub Pages** (via `.github/workflows/pages.yml`), with
> `elninotracker.org` attached as a custom domain under this repo's Settings → Pages. The
> Cloudflare instructions below remain valid if hosting ever moves, but skip to README Section 2
> / GitHub Pages if you're setting this project up as it currently runs. One consequence: the
> `public/_headers` file (Part 4's "authoritative" CSP/security headers) only takes effect on
> Cloudflare/Netlify — GitHub Pages ignores it entirely, so the `<meta http-equiv="Content-
> Security-Policy">` tag in each HTML file is the only CSP actually enforced in production.

**The plan, in plain words:**
1. Install two free tools (Git and a code editor) — *skip if you already have them*.
2. Preview the site on your own machine.
3. Put the project on GitHub (a free code host).
4. Connect Cloudflare Pages to it so it goes live and re-deploys itself.
5. Switch on the robot that refreshes the data.
6. (Optional) attach your own domain name.

---

## Part 0 — Vocabulary (30-second read)

- **Terminal / command line** — a text window where you type commands. On **Mac**: open
  *Applications → Utilities → Terminal*. On **Windows**: after installing Git (Part 1) use
  *Git Bash* from the Start menu. On **Linux**: your usual terminal.
- **Git** — a tool that tracks versions of files and uploads them to GitHub.
- **Repository ("repo")** — a project folder that Git and GitHub manage.
- **Commit** — a saved snapshot of your files.
- **Push** — uploading your commits to GitHub.
- **Static site** — a website made of plain files (HTML/CSS/JS) with no server to run. Yours
  is one of these, which is why hosting is free and simple.

When this guide shows a box like the one below, type (or paste) each line into your terminal and
press Enter. `# lines starting with a hash are comments — you don't type them.`

```bash
# example
echo "hello"
```

---

## Part 1 — Install the tools (skip anything you already have)

### 1.1 Git

Check if you already have it:
```bash
git --version
```
- If you see something like `git version 2.42.0`, you're done — go to 1.2.
- If you see "command not found":
  - **Mac:** the easiest path is to run `xcode-select --install` and click through the popup.
    Or install [Homebrew](https://brew.sh) then `brew install git`.
  - **Windows:** download and run the installer from <https://git-scm.com/download/win>. Accept
    all the defaults. This also gives you **Git Bash**, which you'll use as your terminal.
  - **Linux (Debian/Ubuntu):** `sudo apt update && sudo apt install git`.

### 1.2 A code editor (recommended, not required)

Install **Visual Studio Code** (free): <https://code.visualstudio.com>. You'll use it to open
the project folder and, if you like, to make edits. Any text editor works.

### 1.3 Python (only needed if you want to run the data pipeline locally)

You do **not** need Python to deploy — GitHub runs the pipeline for you in the cloud. But to test
it on your machine:
```bash
python3 --version
```
If missing: Mac users get it with Homebrew (`brew install python`); Windows users can install
from <https://python.org/downloads> (tick "Add Python to PATH" during setup).

---

## Part 2 — Get the project and preview it locally

### 2.1 Put the project folder somewhere you'll find it

Unzip/copy the `pulse-of-the-pacific/` folder to, say, your Desktop. Then point your terminal at
it. The `cd` ("change directory") command does that:

```bash
# Mac/Linux example — adjust the path to where your folder actually is
cd ~/Desktop/pulse-of-the-pacific

# Windows (Git Bash) example
cd ~/Desktop/pulse-of-the-pacific
```

Confirm you're in the right place — you should see the project files listed:
```bash
ls
# expected: README.md  DEPLOYMENT_GUIDE.md  public  scripts  .github
```
> On Windows, if `ls` doesn't work, you're in Command Prompt, not Git Bash. Open **Git Bash**
> instead (Start menu) and `cd` again.

### 2.2 Preview it

The page loads its data files with `fetch()`, which browsers block when you open an HTML file
directly (you'll get a blank page). So serve it over a tiny local web server instead:

```bash
cd public
python3 -m http.server 8000
```
You'll see `Serving HTTP on ... port 8000`. Now open **http://localhost:8000** in your browser.

You should see the breathing ocean, the timeline heartbeat, the world map, and the forecast.
Press **F12** to open the browser console — it should be free of red errors (a note about
external fonts/CDN is fine).

To stop the server, return to the terminal and press **Ctrl + C**.

> **No Python?** Use Node instead: `npx serve .` (from inside `public/`), then open the URL it
> prints. Or drag `index.html` onto a running local server of your choice.

**Checkpoint:** the site works on your machine. Now we make it public.

---

## Part 3 — Put the project on GitHub

### 3.1 Create a GitHub account

Go to <https://github.com> and sign up (free). Verify your email.

### 3.2 Create an empty repository

1. Click the **+** in the top-right → **New repository**.
2. **Repository name:** `pulse-of-the-pacific` (or anything you like).
3. Leave it **Public** (required for free GitHub Pages; fine for the others too).
4. **Do NOT** tick "Add a README" — your folder already has one.
5. Click **Create repository**.
6. Leave that page open. It shows commands under "…or push an existing repository." You'll use
   those in 3.4.

### 3.3 Tell Git who you are (first time only)

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### 3.4 Upload the project

From inside the `pulse-of-the-pacific/` folder (the top level, **not** `public/`):

```bash
git init                       # start tracking this folder
git add .                      # stage every file
git commit -m "Initial commit: Pulse of the Pacific"
git branch -M main             # name the main branch
git remote add origin https://github.com/YOUR-USERNAME/pulse-of-the-pacific.git
git push -u origin main        # upload
```
Replace `YOUR-USERNAME`. Copy the exact `git remote add …` line from the GitHub page in 3.2 to
avoid typos.

### 3.5 Authenticate when Git asks

On `git push`, GitHub will ask you to log in. Modern GitHub **does not accept your account
password** here. Two easy options:

- **Personal Access Token (quickest):**
  1. Go to <https://github.com/settings/tokens> → **Generate new token → Fine-grained token**.
  2. Give it a name, set expiration, under **Repository access** pick "Only select repositories"
     → your repo, and under **Permissions → Contents** choose **Read and write**.
  3. Generate it and **copy the token** (you won't see it again).
  4. When `git push` prompts for a password, paste the **token** as the password.
- **GitHub CLI (nicer long-term):** install from <https://cli.github.com>, run `gh auth login`,
  and follow the browser prompts. Then `git push` just works.

**Checkpoint:** refresh your repo page on GitHub — you should see all your files (`public/`,
`scripts/`, `README.md`, etc.).

---

## Part 4 — Go live with Cloudflare Pages (recommended host)

Cloudflare Pages is free, fast, gives you HTTPS automatically, and — crucially — re-deploys
every time the data robot pushes an update.

### 4.1 Create a Cloudflare account
Sign up at <https://dash.cloudflare.com> (free). Verify your email.

### 4.2 Create the Pages project
1. In the left sidebar: **Workers & Pages**.
2. Click **Create** → the **Pages** tab → **Connect to Git**.
3. Click **Connect GitHub**, authorize Cloudflare, and (recommended) grant access to just your
   `pulse-of-the-pacific` repo.
4. Back in Cloudflare, select that repo and click **Begin setup**.

### 4.3 The build settings (the one screen that matters)
Set these exactly:

| Field | Value |
|---|---|
| **Project name** | `pulse-of-the-pacific` (this becomes part of your URL) |
| **Production branch** | `main` |
| **Framework preset** | `None` |
| **Build command** | *(leave completely empty)* |
| **Build output directory** | `public` |

> Why these? There's nothing to compile — the site is ready-made files inside `public/`. So we
> tell Cloudflare "no build step, just publish the `public` folder."

### 4.4 Deploy
Click **Save and Deploy**. Cloudflare copies your files and, in roughly 30–60 seconds, shows
**Success!** with a live link like:

```
https://pulse-of-the-pacific.pages.dev
```

Open it. Your site is on the internet. 🎉

Two things happened silently that are worth knowing:
- Cloudflare read **`public/_headers`** and is now serving the site with its full
  security-header set (strict CSP, no-frame, nosniff, etc.). Verify with
  `curl -I https://YOUR-SITE/` — you should see `content-security-policy` in the reply.
- The **status dashboard** is live too: open `https://YOUR-SITE/admin.html`. On a fresh
  deploy it will say *"Pipeline has not run yet"* — that's expected until Part 5.

### 4.5 How updates work from now on
Any push to `main` — whether from you editing files or from the data robot (Part 5) — triggers
an automatic redeploy. You never touch the deploy step again.

> **Prefer Vercel or GitHub Pages?** See README Section 2 (Options 2 and 3). For GitHub Pages
> specifically, because Pages can't serve a `public/` subfolder directly, use the ready-made
> `pages.yml` workflow in README Appendix B — copy it to `.github/workflows/pages.yml`, commit,
> push, and enable Pages with the **GitHub Actions** source.

---

## Part 5 — Switch on the auto-updating robot

Your repo already contains `.github/workflows/update-data.yml`. It's the scheduled job that
fetches fresh ENSO numbers from NOAA and commits them. Two quick settings make it work.

### 5.1 Allow the robot to write to your repo
1. On GitHub, open your repo → **Settings** (top tab).
2. Left sidebar → **Actions** → **General**.
3. Scroll to **Workflow permissions** → select **Read and write permissions** → **Save**.
   *(Without this, the robot can fetch data but can't commit it back.)*
4. Higher up on the same page, under **Actions permissions**, make sure actions are allowed
   (the default "Allow all actions and reusable workflows" is fine).

### 5.2 Run it once by hand to prove it works
1. Repo → **Actions** tab.
2. In the left list, click **Refresh ENSO data**.
3. Click **Run workflow** (right side) → keep branch `main` → **Run workflow**.
4. A run appears; click it to watch the log. Green check = success. (The job runs the
   parser test-suite first — if a test is red, the refresh is blocked by design.)
5. Now reload `https://YOUR-SITE/admin.html`: the banner should turn green
   ("All systems normal") with five OK source cards. That page is your ongoing
   health check — see `OPERATIONS_RUNBOOK.md` for the 2-minute weekly routine.
   - If the log ends with new files under `public/data/`, the robot fetched fresh data and
     committed it — and Cloudflare will redeploy within a minute.
   - If it says "No data changes — nothing to commit," that's also success; NOAA simply had
     nothing new since the shipped baseline.

### 5.3 What it will do on its own
It runs **Mondays and Thursdays at 16:10 UTC** (set in the workflow's `cron` lines). Mondays
catch NOAA's new weekly Niño-3.4 reading; the monthly indices refresh around the 1st–5th and the
Thursday run is a safety net. To change the schedule, edit the two `cron:` lines in
`.github/workflows/update-data.yml` (times are UTC; use <https://crontab.guru> to compose one).

### 5.4 What it fetches
| File it writes | NOAA source | Cadence |
|---|---|---|
| `oni.json` | Oceanic Niño Index | monthly |
| `roni.json` | Relative ONI (NOAA's 2026 operational index) | monthly |
| `wksst.json` | weekly Niño-3.4 SST anomaly | **weekly** |
| `soi.json` | Southern Oscillation Index | monthly |
| `heat.json` | equatorial upper-300 m heat content | monthly |

The site automatically lights up the extra features (real RONI line, weekly "live" reading)
once these files appear. Until then it runs on the embedded baseline it shipped with. If any
NOAA source is temporarily unreachable, the robot keeps the last good file and the site never
breaks.

**Checkpoint:** you have a live site that updates itself. Everything below is optional.

---

## Part 6 — Attach your own domain (optional)

If you own a domain (e.g. from Cloudflare Registrar, Namecheap, Google Domains):

**Cloudflare Pages:**
1. Your Pages project → **Custom domains** → **Set up a domain**.
2. Enter your domain (e.g. `enso.example.com`).
3. If the domain's DNS is already on Cloudflare, it's added automatically. Otherwise Cloudflare
   shows a **CNAME** record to add at your registrar; add it and wait a few minutes.
4. HTTPS is provisioned for you.

**Vercel / GitHub Pages:** both have a **Settings → Domains / Custom domain** field that walks
you through the same CNAME step.

---

## Part 6.5 — (Optional) Make the status dashboard private

`/admin.html` is read-only telemetry about public data, so leaving it open is safe and
even a nice transparency feature (it's linked in the site footer, and `robots.txt` asks
crawlers to skip it). If you'd still prefer it private, do **not** build a login into the
site — gate it at the edge with **Cloudflare Zero Trust Access** (free tier):

1. Cloudflare dashboard → **Zero Trust** → complete the one-time team-name setup.
2. **Access → Applications → Add an application → Self-hosted.**
3. Application domain: your site's domain, path **`/admin.html`**.
4. Add a policy: *Allow* → *Emails* → your email address. Save.
5. Visiting `/admin.html` now shows Cloudflare's login (emailed one-time PIN); everything
   else on the site stays public. Also remove the footer link in `public/index.html` if
   you want it unadvertised.

## Part 7 — Making changes later

The everyday loop once everything is set up:

```bash
# 1. edit files (e.g. open the folder in VS Code and change something)
# 2. preview locally
cd public && python3 -m http.server 8000     # look at http://localhost:8000, then Ctrl+C
cd ..
# 3. publish
git add .
git commit -m "describe what you changed"
git push
```
Cloudflare/Vercel redeploys automatically within a minute.

Before pushing code changes, run the fast checks:
```bash
python3 tests/test_parsers.py            # pipeline suite (also gates CI)
node --check public/assets/app.js        # JS syntax
```
To regenerate the offline single-file demo after edits:
```bash
python3 scripts/build_standalone.py      # writes dist/el-nino-tracker-standalone.html
```

To rebuild the ONE-TIME baseline data files from scratch (rarely needed):
```bash
python3 scripts/build_oni.py       # regenerates public/data/oni.json
python3 scripts/build_context.py   # regenerates events / impacts / roni_compare
```

---

## Part 8 — Troubleshooting (expanded)

| What you see | Why | Fix |
|---|---|---|
| Blank page locally | You opened `index.html` directly (`file://`) | Serve it: `cd public && python3 -m http.server 8000`. |
| `git: command not found` | Git not installed | Part 1.1. |
| `git push` rejected / asks for password repeatedly | Password auth is disabled on GitHub | Use a Personal Access Token or `gh auth login` (Part 3.5). |
| `fatal: remote origin already exists` | You ran `git remote add` twice | Run `git remote set-url origin <your-repo-url>` instead. |
| Cloudflare build "succeeds" but site is blank | Wrong output directory | Set **Build output directory** to `public` (Part 4.3), redeploy. |
| Action fails: "Permission denied" / can't push | Workflow can't write | Settings → Actions → General → **Read and write permissions** (Part 5.1). |
| Action green, but data never changes | NOAA had no new release | Normal between updates; the weekly file changes on Mondays. |
| A NOAA URL 404s in the Action log | NOAA moved a file | Edit the URL in `scripts/update_data.py` (the `URLS` dictionary near the top). The script is written to keep the last good data if a source fails, so the site stays up meanwhile. |
| Charts missing only on your machine | Your network blocks the CDN | Do the offline build in README Appendix C. |
| Horizontal scrolling on phone | (Fixed in this version) | If you edited the map/CSS, keep `min-width:0` on grid children and `overflow-x:hidden` on `body`. |
| `admin.html` stuck on "Pipeline has not run yet" | Workflow never ran or can't commit | Part 5.1–5.2; check Actions tab for red runs. |
| CSP violation in console after your edit | An inline `<script>` was added | Move the code into `public/assets/*.js` — inline scripts are forbidden by design (see DEVELOPER_GUIDE §6). |

---

## Part 9 — Cost

Everything here is **free** at this project's scale:
- GitHub: free for public repos, and GitHub Actions includes a generous free monthly minute
  allowance — this job uses a minute or two, twice a week.
- Cloudflare Pages / Vercel / GitHub Pages: free static hosting with HTTPS.
- NOAA data: public and free, no API key.

The only thing you might ever pay for is a custom domain name (typically ~$10/year), which is
optional.

---

*If you get stuck on a specific step, note the exact command or screen and the exact message you
saw — that's almost always enough to pinpoint the fix in Part 8.*
