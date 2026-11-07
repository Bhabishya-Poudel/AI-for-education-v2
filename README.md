# AI for Education

Scores educational blog posts against a 14-criterion evaluation framework using Gemini, driven through a Playwright-controlled browser, then tests whether the criteria are statistically independent of each other.

The framework is meant to be *orthogonal*: each criterion should measure a distinct property of the material (for example accuracy vs. completeness vs. clarity). This project checks that claim empirically. If two criteria always move together across blogs, they may be measuring the same thing.

```
blogs/*.txt ─────┐
criteria.txt ────┼─► score_blogs.py ─► scores.csv ─► analyze.py ─► correlation matrices
reference.txt ───┘   (Playwright)                    (Pearson, Spearman, dCor)
```

## Repository contents

Only code and documentation are published. The inputs (blogs, criteria, reference text, prompts) and all outputs (CSVs, PDFs) are git-ignored; you supply your own.

| File | Purpose |
|---|---|
| `save_login.py` | One-time Google sign-in; saves the browser session to `state/auth.json` |
| `score_blogs.py` | Scores blogs through the Gemini web UI and writes `scores.csv` |
| `run_batches.py` | Runs `score_blogs.py` over ranges of blogs, each in a fresh browser |
| `analyze.py` | Computes Pearson, Spearman and distance correlation matrices from `scores.csv` |
| `requirements.txt` | Python dependencies |

Expected local (unpublished) inputs:

| Path | Contents |
|---|---|
| `blogs/` | One blog per file, named `Blog<N>.txt` (e.g. `Blog1.txt`) |
| `criteria.txt` | The full 14-criterion framework, including each criterion's boundary |
| `LawsOfMotionWiki.txt` | Trusted reference text used to judge accuracy and completeness (optional; change `REFERENCE_FILE` in `score_blogs.py` for other subjects) |

## Setup

Requires Python 3.9+, Google Chrome, and a Google account with access to Gemini.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
python save_login.py              # once: sign in, creates state/auth.json
python score_blogs.py             # score every blog in blogs/ -> scores.csv
python score_blogs.py 3-7         # score only Blog3 ... Blog7
python score_blogs.py Blog5.txt   # test mode: one blog -> test_scores.csv
python run_batches.py 1 5 100     # blogs 1-100 in batches of 5
python analyze.py                 # scores.csv -> *_matrix.csv + report
```

`state/auth.json` holds your login session. Never commit it (it is git-ignored).

## How the Playwright script works

There is no Gemini API call. The scripts drive the real Gemini website the way a person would, which is what `save_login.py` and `score_blogs.py` automate.

### 1. Login (`save_login.py`, run once)

1. Launches your installed Chrome (`channel="chrome"`) in a visible window, with the `AutomationControlled` flag disabled so Google is less likely to reject the sign-in.
2. Opens `https://gemini.google.com/app`.
3. You sign in by hand, then press Enter in the terminal.
4. `context.storage_state()` writes cookies and local storage to `state/auth.json`.

Every later run loads that file, so no password is ever handled by the code. If the session expires, run `save_login.py` again.

### 2. Scoring (`score_blogs.py`)

**Startup**

1. Reads the reference file (if present) and lists `blogs/*.txt`, sorted by the number in the file name (so `Blog2` comes before `Blog10`).
2. Picks the blogs to score from the command line: none = all, `3-7` = a range, `Blog5.txt` = a single test file.
3. Loads `scores.csv` if it exists and skips every blog already in it, so a run can be stopped and resumed.

**For each blog**

1. **Browser.** On the first blog only, Chrome is launched (headed, `slow_mo=50`) with a context restored from `state/auth.json`. The same page is reused for all blogs.
2. **Fresh chat.** The page navigates to the Gemini app URL, so every blog is scored in a new conversation with no memory of earlier blogs. If Google redirects to `accounts.google.com`, the session has expired and the script stops.
3. **Find the input box.** `_first_visible` tries each selector in `INPUT_SELECTORS` in turn and returns the first visible match. Candidate lists exist because Gemini's markup changes; if the script breaks after a UI change, these lists (and `SEND_SELECTORS`, `STOP_SELECTORS`, `REPLY_SELECTORS`) are what to update.
4. **Attach files.** It opens the "Upload and tools" menu, clicks "Upload files", and uses Playwright's file chooser to attach three files: `criteria.txt`, the reference text and the blog. It then waits until a "close <name>" chip appears for every file, plus a short pause so uploads finish. Files are attached rather than pasted because the texts are too long for the input box.
5. **Prompt.** `build_prompt` produces a short instruction naming the three files, the 1-5 scale (`null` when a criterion does not apply or cannot be evaluated), and a request to return only a JSON object with one key per criterion. The prompt is typed into the box.
6. **Send.** It clicks the send button, or presses Enter if the button is not found.
7. **Wait for the reply.** First it waits for a response element to appear. Then it polls once a second until the "Stop" button is gone *and* the reply text has been identical for three consecutive polls. This avoids reading a half-written answer. The overall limit is `REPLY_TIMEOUT_S` (240 s).
8. **Parse.** `parse_json` takes the first `{...}` block in the reply and loads it as JSON, discarding any surrounding prose. If parsing fails or the browser step errors, the blog is retried up to `RETRIES_PER_BLOG` (2) extra times. A blog that still fails is not saved, so the next run picks it up.
9. **Save.** The scores for the 14 criteria are appended as a row and `scores.csv` is rewritten immediately, so nothing is lost if the run stops.
10. **Pause.** A random 15-30 s delay before the next blog avoids hammering the site.

If the run is interrupted (Ctrl-C) or the session expires, current results are saved before exit, and the browser is always closed at the end.

### 3. Batching (`run_batches.py`)

Runs `score_blogs.py <lo>-<hi>` as a separate process for each batch, e.g. `python run_batches.py 3 5 30` scores blogs 3-7, 8-12, and so on up to 30. Each batch gets a fresh browser, which keeps long runs stable, with a 60 s pause between batches. It stops at the first failed batch; finished blogs are skipped on the next run.

## Analysis (`analyze.py`)

Reads `scores.csv` and drops criteria that were scored for fewer than `MIN_BLOGS` (4) blogs or that never vary. For every remaining pair of criteria it computes:

| Measure | What it detects |
|---|---|
| Pearson | Straight-line relationships |
| Spearman | Any consistent rise-and-fall together (rank-based, suited to 1-5 scales) |
| Distance correlation (dCor) | Any kind of dependence; 0 only when truly independent |

The matrices are written to `pearson_matrix.csv`, `spearman_matrix.csv` and `dcor_matrix.csv`, and two reports are printed:

- **Possibly non-independent pairs**: any measure at or above `FLAG_AT` (0.7).
- **Hidden links**: dCor exceeds |Pearson| by `GAP_AT` (0.25) or more, meaning a real relationship that a linear test understates.

## The 14 criteria

accuracy, completeness, linguistic accessibility, organization/coherence, explanation/conceptual development, learning-objective alignment, practice/application, cognitive engagement, learner appropriateness/inclusivity, visual/multimodal representation, usability/accessibility, credibility/provenance, assessment/feedback, interactivity/collaboration.

## Limitations

- **Small samples.** With fewer than 10 blogs, results are only a smoke test. dCor is biased upward below about 30 blogs; prefer Spearman.
- **LLM scoring is noisy.** Each blog is scored by a single model response, and results may vary across models and prompt wording.
- **Fragile to UI changes.** The script depends on Gemini's page structure and on a browser session; it is not a supported API.
- **Reference-dependent.** Accuracy and completeness are judged against the reference file, so the blogs must cover that topic.
