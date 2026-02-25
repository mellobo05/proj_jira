const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000"
const INTERNAL_API_TOKEN = process.env.INTERNAL_API_TOKEN || "";

async function run() {
    const [, , command, jiraKey] = process.argv;

    if (command !== "fetch_and_summarize" || !jiraKey) {
        console.log("Usage: node cli.js fetch_and_summarize <JIRA_KEY>");
        process.exit(1);
    }
    // Add your fetch and summarize logic here

    const response = await fetch(`${API_BASE_URL}/v1/fetch_and_summarize`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...(INTERNAL_API_TOKEN ? { "X-Internal-Token": INTERNAL_API_TOKEN } : {})
        },
        body: JSON.stringify({
            tool_name: "fetch_and_summarize",
            parameters: {
                issue_key: jiraKey}
        })
    });

    const text = await response.text();
    if (!response.ok) {
        console.error(`Error ${response.status}: ${text}`);
        process.exit(1);
    }

    const out = JSON.parse(text);
    const data = out.result?.analysis ?? out.result ?? {};
    console.log("Summary:", data.summary || "N/A");
    console.log("Root Cause:", data.root_cause || "N/A");

}

run().catch(err => {
    console.error("Unexpected error:", err);
    process.exit(1);
});