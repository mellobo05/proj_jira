# Jira Fetch & Summarize Tool

This project provides a FastAPI backend and Node.js CLI to fetch Jira issues and summarize them using an LLM, following ADA's workflow style.

## Features
- Fetch Jira issue details and comments
- Summarize issues and extract root cause using OpenAI LLM
- ADA-style tool-call API (`/v1/tools/call`)
- Node.js CLI for easy tool invocation

## Setup

### 1. Clone the Repository
```
git clone <your-repo-url>
cd <repo-folder>
```

### 2. Python Backend
- Install dependencies:
  ```
  pip install -r requirements.txt
  ```
- Configure Jira and OpenAI credentials in `.env` or `credentials.json` (see below).
- Start the backend:
  ```
  python -m uvicorn fetch_summarize_jira.fastapi_backend:app --reload
  ```

### 3. Node.js CLI
- Install dependencies:
  ```
  cd fetch_summarize_jira
  npm install
  ```
- Usage:
  ```
  node cli.js fetch_jira <JIRA_KEY>
  node cli.js fetch_and_summarize <JIRA_KEY>
  ```

## Configuration

- **.env** or **credentials.json** (never commit these!):
  - `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` (or password)
  - `OPENAI_API_KEY` (optional, for LLM summarization)

## Security
- `.env` and `credentials.json` are git-ignored by default.
- If you accidentally committed secrets, rotate them and remove from git history.

## Troubleshooting
- If you get only N/A fields, check Jira credentials and API access.
- For SSO-protected Jira, basic auth may not work—contact your Jira admin.

## License
MIT
