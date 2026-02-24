import os
import time 
import asyncio
from datetime import datetime, timezone
from typing import List, Literal, Optional, Dict, Any

import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field 
from openai import AsyncOpenAI

# -----------------------------
# Config
# -----------------------------
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")

app = FastAPI(title="Jira Summarizer API", version="1.0")
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

#-----------------------------
#Models (tool calls)
#-----------------------------
class ToolCallRequest(BaseModel):
    tool_name: Literal["fetch_jira", "fetch_and_summarize"]
    parameters: Dict[str, Any] = Field(default_factory=dict)
    context_config: Optional[Dict[str, Any]] = None

class ToolCallResponse(BaseModel):
    success: bool
    tool_name: str
    result:Optional[Any] = None
    error: Optional[str] = None

#-----------------------------
#Helpers
#-----------------------------
def ensure_env():
    missing = [k for k, v in {
        "JIRA_BASE_URL": JIRA_BASE_URL,
        "JIRA_EMAIL": JIRA_EMAIL,
        "JIRA_API_TOKEN": JIRA_API_TOKEN}.items() if not v]
    if missing:
        raise HTTPException(status_code=500, detail = f"Missing environment variables: {', '.join(missing)}")

def adf_to_text(node: Any) -> str:
    #Converts an Atlassian Document Format (ADF) node or structure to plain text by recursively 
    # processing strings, lists, and node dictionaries, handling paragraphs, text, and hard breaks.
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(item) for item in node)
    node_type = node.get("type")
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"
    child = adf_to_text(node.get("content", []))
    return f"{child}\n" if node_type == "paragraph" else child

async def with_retry(coro_factory, retries: int = 3, base_sleep: float = 0.5):
    #A helper function that executes an asynchronous coroutine factory with retry logic. It attempts to run the provided 
    # coroutine factory up to a specified number of retries, with an exponential backoff delay between attempts. If all 
    # attempts fail, it raises the last encountered exception.
    last_err = None
    for i in range(retries):
        try:
            return await coro_factory()
        except Exception as e:
            last_err = e
            if i < retries - 1:
                await asyncio.sleep(base_sleep * (2 ** i))
    raise last_err

async def fetch_jira_issue(issue_key: str) -> Dict[str, Any]:
    #Fetches a Jira issue by its key using the Jira REST API. It constructs the appropriate URL, sets up authentication 
    # and headers, and makes an asynchronous GET request to retrieve the issue data. If the request is successful, it returns 
    # the issue data as a dictionary; otherwise, it raises an HTTPException with details about the failure.
    ensure_env()
    auth = httpx.BasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    timeout = httpx.Timeout(10.0, connect=5.0)

    async with httpx.AsyncClient(base_url=JIRA_BASE_URL, auth=auth, timeout=timeout) as client:
        async def get_issue():
            return await client.get(f"/rest/api/3/issue/{issue_key}",
                                    params= {"fields" : "summary,status,priority,assignee,reporter,created,updated,labels,description"}
                                    )
        
        async def get_comments():
            return await client.get(f"/rest/api/3/issue/{issue_key}/comment", params = {"maxResults": 50})
        
        issue_response = await with_retry(get_issue)
        comment_response = await with_retry(get_comments)
        if issue_response.status_code != 200:
            raise HTTPException(status_code=issue_response.status_code, detail=f"Failed to fetch issue: {issue_response.text}")
        if comment_response.status_code != 200:
            raise HTTPException(status_code=comment_response.status_code, detail=f"Failed to fetch comments: {comment_response.text}")

        issue = issue_response.json()
        comments = comment_response.json()

        f = issue.get("fields", {})
        return {
            "key": issue.get("key"),
            "summary": f.get("summary"),
            "status": f.get("status", {}).get("name"),
            "priority": f.get("priority", {}).get("name"),
            "assignee": f.get("assignee", {}).get("displayName"),
            "reporter": f.get("reporter", {}).get("displayName"),
            "created": f.get("created"),
            "updated": f.get("updated"),
            "labels": f.get("labels", []),
            "description": adf_to_text(f.get("description", {})),
            "comments": [
                {
                    "author": c.get("author", {}).get("displayName"),
                    "created": c.get("created"),
                    "body": adf_to_text(c.get("body", {}))
                }
                for c in comments
            ],
            "url": f"{JIRA_BASE_URL}/browse/{issue_key}"
        }
        
