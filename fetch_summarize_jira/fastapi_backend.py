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
    
async def llm_summarize_issue(issue_data: Dict[str, Any]) -> Dict[str, Any]:
    #Generates a summary of a Jira issue using an LLM. It constructs a prompt based on the issue data and optional context 
    # configuration, then sends this prompt to the OpenAI API to obtain a summary. The function returns the generated summary 
    # as a string.
    if not openai_client:
        return {
                "summary": f"{issue_data['key']} is {issue_data['status']} with priority {issue_data['priority']}.",
                "root_cause": "OpenAI key not configured; LLM analysis unavailable.",
                "confidence": "low",
                "evidence": [issue_data["key"]]
            }
        
    payload = {
            "key" : issue_data["key"],
            "summary": issue_data["summary"],
            "status": issue_data["status"],
            "priority": issue_data["priority"],
            "description": issue_data["description"],
            "comments": issue_data["comments"],
        }

    prompt = (
            "You are a senior triage engineer.\n"
            "Analyze this Jira issues and comments\n"
            "Return strict JSON with keys: summary, root_cause, confidence, evidence\n"
            "Confidence must be one of low, medium, high based on how certain you are about the root cause\n"
            "evidence short list of concrete clues from description and comments \n"
            f"DATA: \n{json.dumps(payload, ensure_ascii=False)}\n"
        )

    response = await with_retry(
            lambda: openai_client.responses.create(
                model=OPENAI_MODEL,
                input=prompt,
                max_output_tokens=700
            )
        )

    text = (response.output_text or "").strip()
    try:
        cleaned = text.replace("```json", "").replace("```", "").strip()
        obj = json.loads(cleaned)
        return {
                "summary": obj.get("summary", ""),
                "root_cause": obj.get("root_cause", ""),
                "confidence": obj.get("confidence", "low"),
                "evidence": obj.get("evidence", [])
            }
    except Exception:
        return {
                "summary": text or "LLM parse failed.",
                "root_cause": "Unable to parse structured root cause from model output.",
                "confidence": "low",
                "evidence": [issue_data["key"]]
            }
        
#-----------------------------
# API Endpoints
#-----------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("v1/tools")
async def list_tools():
    return {
        "success": True,
        "tools": [
            {
                "name": "fetch_jira",
                "description": "Fetches one JIRA issue with comments.",
                "parameters": {
                    "issue_key": "string(e.g., SYSCROS-156171)"
                }
            },
            {
                "name": "fetch_and_summarize",
                "description": "Fetches a Jira issue and generates a summary/root cause using an LLM.",
                "parameters": {
                    "issue_key": "string(e.g., SYSCROS-156171)"
                }
            }
        ]
    }
        
@app.post("/v1/tools/call", response_model=ToolCallResponse)
async def call_tool(request: ToolCallRequest, x_internal_token: Optional[str] = Header(default=None)):
    start = datetime.now().timestamp()

    if INTERNAL_API_TOKEN and x_internal_token != INTERNAL_API_TOKEN:
        return ToolCallResponse(
            success=False, 
            tool_name=request.tool_name, 
            error="Unauthorized",
            execution_time = datetime.now().timestamp() - start
        )
    
    try:
        issue_key = request.parameters.get("issue_key")
        if not issue_key:
            raise ValueError("Missing required parameter: issue_key")
        if request.tool_name == "fetch_jira":
            issue = await fetch_jira_issue(issue_key)
            return ToolCallResponse(
                success=True, 
                tool_name= request.tool_name,
                result=issue,
                execution_time = datetime.now().timestamp() - start
            )
        
        if request.tool_name == "fetch_and_summarize":
            issue = await fetch_jira_issue(issue_key)
            summary = await llm_summarize_issue(issue)
            result = {
                "fetched_at" : datetime.now(timezone.utc).isoformat(),
                "issue": issue,
                "analysis": summary
            }
            return ToolCallResponse(
                success=True, 
                tool_name= request.tool_name,
                result=result,
                execution_time = datetime.now().timestamp() - start
            )
        
        raise ValueError(f"Unknown tool: {request.tool_name}")
    
    except Exception as e:
        return ToolCallResponse(
            success=False, 
            tool_name=request.tool_name, 
            error=str(e),
            execution_time = datetime.now().timestamp() - start
        )