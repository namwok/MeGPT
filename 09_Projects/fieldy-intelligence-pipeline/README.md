# Fieldy Meeting Intelligence Pipeline

Automatic pipe:

```text
Fieldy Public API → GitHub Actions → GitHub Models AI → Notion
```

It runs at 8:00 a.m., 12:30 p.m., and 8:00 p.m. Newfoundland time, deduplicates by Fieldy conversation ID, stores the full returned transcript inside the Notion meeting page, and populates Meeting Records, Actions and Open Loops, Strategic Signals, and Daily Briefs.

It does not use Gmail, does not require ChatGPT Business, does not need a separate OpenAI API key, and never commits transcripts or credentials to GitHub.

## Required repository secrets

Add these under **Repository Settings → Secrets and variables → Actions**:

- `FIELDY_API_KEY` — from Fieldy **Settings → Developer Settings**
- `NOTION_API_KEY` — from an internal Notion integration with read, insert, and update-content capabilities

Share the **Fieldy Meeting Intelligence OS** Notion page with the Notion integration. Do not paste either key into a file, issue, commit, pull request, or chat.

## First run

Open **Actions → Fieldy Meeting Intelligence → Run workflow**. Leave `force` enabled. The first run checks the previous 72 hours. Scheduled runs use a 36-hour lookback and deduplicate existing meetings.

## Notion data sources

- Meeting Records: `96e3ccdd-ece1-4b30-a159-db860c4d4a76`
- Actions and Open Loops: `9be2b7c6-6bcc-4a72-b0b1-1460a76535d3`
- Strategic Signals: `1e4fb2a3-12af-4386-a2ef-635269d97f8c`
- Daily Briefs: `12da2525-6d9d-4496-a585-25bda3b26686`

## Safety and reliability

- Transcript/summary content is never printed in Actions logs.
- API calls retry temporary failures and rate limits.
- The AI receives Fieldy summary/tasks plus an 8,000-character transcript excerpt; the full returned transcript is stored in Notion.
- If GitHub Models is unavailable, the pipeline still imports Fieldy's summary and tasks and flags the record for review.
- No secret or transcript is written to the repository.
