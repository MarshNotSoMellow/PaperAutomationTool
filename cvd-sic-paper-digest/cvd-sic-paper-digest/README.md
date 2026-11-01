# CVD Si/C Daily Paper Digest

Daily, Chinese-language research brief for:

> CVD Si/C anode material and microstructure of Si/C anode

The workflow runs for free on GitHub Actions. Email is optional; the default
setup publishes a webpage that can be opened in any browser:

1. Searches recent papers through the free OpenAlex API.
2. Requires silicon, carbon, and anode/negative-electrode concepts.
3. Favors CVD, Si/C composites, porosity, interfaces, and microstructure.
4. Runs a small Qwen model locally on the GitHub runner to write Chinese titles and summaries.
5. Publishes a responsive HTML brief through GitHub Pages.
6. Optionally emails the same brief through QQ Mail or Gmail SMTP.
7. Commits a deduplication state so the same paper is not shown twice.

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
3. Open **Settings → Pages**, select **Deploy from a branch**, choose `main` and
   `/docs`, then save. The report will appear at
   `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/`.
4. Open **Actions → CVD Si/C daily paper digest → Run workflow**.

No email credentials are required for this default setup.

## Optional email

Create a provider-specific app credential:

- **QQ Mail:** Settings → Account → POP3/IMAP/SMTP service → Generate
  authorization code.
- **Gmail:** enable 2-Step Verification, then use the Google app-password page.
- Never use either account's normal login password.

Open **Settings → Secrets and variables → Actions → New repository secret** and
add the QQ secrets below, or the Gmail secrets in the following table.

| Name | Value |
|---|---|
| `MAIL_TO` | The QQ address that should receive the brief |
| `SMTP_USER` | The sending QQ address |
| `SMTP_PASSWORD` | The QQ SMTP authorization code |

If the digest is sent and received by the same QQ address, `SMTP_USER` can be
omitted; the workflow then reuses `MAIL_TO`.

To use Gmail instead of QQ Mail:

| Name | Value |
|---|---|
| `MAIL_TO` | Recipient Gmail address |
| `SMTP_USER` | Complete sending Gmail address |
| `SMTP_PASSWORD` | Google app password |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |

Gmail requires 2-Step Verification before Google will generate an app password.
Use the 16-character app password, not the normal Google password. Advanced
Protection or a work/school account policy may disable app passwords.

For manual runs, enable `send_email` in the Run workflow dialog. For the daily
schedule, create a repository variable named `SEND_EMAIL` with value `true`
under **Settings → Secrets and variables → Actions → Variables**.

## Tuning the topic

Edit `config.json`:

- `queries`: OpenAlex search phrases.
- `concept_groups`: all three groups must match.
- `preference_terms`: terms that raise relevance.
- `minimum_score`: raise it for fewer, more focused papers.
- `max_papers`: maximum papers per report.
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
- Email providers may delay or classify automated messages; add the sender to
  contacts if the brief does not appear in the inbox.
