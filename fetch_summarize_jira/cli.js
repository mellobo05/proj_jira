const API_BASE_URL = process.env.API_BASE_URL || "http://localhost:8000"
const INTERNAL_API_TOKEN = process.env.INTERNAL_API_TOKEN || "";

async function run() {
    const [, , command, jiraKey] = process.argv;

    const supportedCommands = ["fetch_jira", "fetch_and_summarize"];
    if (!supportedCommands.includes(command) || !jiraKey) {
        console.log("Usage:");
        console.log("  node cli.js fetch_jira <JIRA_KEY>");
        console.log("  node cli.js fetch_and_summarize <JIRA_KEY>");
        process.exit(1);
    }

    const response = await fetch(`${API_BASE_URL}/v1/tools/call`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            ...(INTERNAL_API_TOKEN ? { "X-Internal-Token": INTERNAL_API_TOKEN } : {})
        },
        body: JSON.stringify({
            tool_name: command,
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
    if (command === "fetch_jira") {
        const issue = out.result ?? {};
        console.log("Issue Key:", issue.key || "N/A");
        console.log("Summary:", issue.summary || "N/A");
        console.log("Status:", issue.status || "N/A");
        console.log("Priority:", issue.priority || "N/A");
        console.log("Assignee:", issue.assignee || "N/A");
        console.log("Reporter:", issue.reporter || "N/A");
        console.log("Updated:", issue.updated || "N/A");
        console.log("URL:", issue.url || "N/A");
        return;
    }

    const data = out.result?.analysis ?? out.result ?? {};
    console.log("Summary:", data.summary || "N/A");
    console.log("Root Cause:", data.root_cause || "N/A");

}

run().catch(err => {
    console.error("Unexpected error:", err);
    process.exit(1);
});