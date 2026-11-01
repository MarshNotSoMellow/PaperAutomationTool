# CVD Si/C Daily Paper Digest

Daily, Chinese-language research brief for:

> CVD Si/C anode material and microstructure of Si/C anode

The workflow runs for free on GitHub Actions:

1. Searches recent papers through the free OpenAlex API.
2. Requires silicon, carbon, and anode/negative-electrode concepts.
3. Favors CVD, Si/C composites, porosity, interfaces, and microstructure.
4. Runs a small Qwen model locally on the GitHub runner to write Chinese titles and summaries.
5. Emails a responsive HTML brief through QQ SMTP.
6. Commits a deduplication state so the same paper is not sent twice.

## Schedule

The digest runs at **08:30 Asia/Shanghai every day**:

```yaml
- cron: "30 0 * * *"
```

GitHub may start scheduled jobs several minutes late during busy periods.

## One-time setup

Use a public GitHub repository for free unlimited GitHub-hosted Actions minutes.
Repository secrets remain encrypted and are not exposed by making the code public.

1. Create a new GitHub repository and upload the contents of this folder.
2. Open **Settings → Actions → General** and make sure workflows are enabled.
3. Create a QQ Mail SMTP authorization code:
   **QQ Mail → Settings → Account → POP3/IMAP/SMTP service → Generate authorization code**.
   Use the authorization code, not your normal QQ password.
4. Open **Settings → Secrets and variables → Actions → New repository secret** and add:

   | Name | Value |
   |---|---|
   | `MAIL_TO` | The QQ address that should receive the brief |
   | `SMTP_USER` | The sending QQ address |
   | `SMTP_PASSWORD` | The QQ SMTP authorization code |

   If the digest is sent and received by the same QQ address, `SMTP_USER` can be
   omitted; the workflow then reuses `MAIL_TO`.

5. Open **Actions → CVD Si/C daily paper digest → Run workflow**.
   Leave `dry_run` enabled for the first test.
6. Download the run artifact and inspect the HTML report.
7. Run again with `dry_run` disabled to verify the email.

## Tuning the topic

Edit `config.json`:

- `queries`: OpenAlex search phrases.
- `concept_groups`: all three groups must match.
- `preference_terms`: terms that raise relevance.
- `minimum_score`: raise it for fewer, more focused papers.
- `max_papers`: maximum papers per email.
- `lookback_days`: indexing delay window used for first-run/backfill retrieval.

`state/seen.json` prevents duplicates. Leave it in the repository and let the
workflow update it.

## Cost and limitations

- OpenAlex is used through its free API.
- Qwen runs locally on the GitHub-hosted runner, so no paid LLM API is needed.
- A public repository gets free GitHub-hosted Actions minutes under GitHub's
  standard public-repository policy.
- The first run downloads/caches the model and takes longer.
- OpenAlex indexes metadata and abstracts, not necessarily every publisher's
  full text. The brief is a screening aid, not a substitute for the paper.
- QQ Mail may delay or classify automated email; add the sender to contacts if
  the brief does not appear in the inbox.
