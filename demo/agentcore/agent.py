"""Self-evolving DevOps agent served as an A2A server.

Uses Strands Agent + ARISE in distributed mode. The agent starts with zero
tools and evolves them over time via the S3/SQS pipeline.

Run:
    python agent.py

Environment variables:
    ARISE_SKILL_BUCKET  S3 bucket for evolving skill library
    ARISE_QUEUE_URL     SQS queue URL for trajectory reporting
    OPENAI_API_KEY      API key for ARISE skill synthesis (gpt-4o-mini)
    AWS_REGION          AWS region (default: us-west-2)
    PORT                Server port (default: 9000)
"""

import os

from strands import Agent
from strands.models import BedrockModel
from strands.multiagent.a2a import A2AServer

from arise import ARISEConfig, create_distributed_arise
from arise.adapters.strands import strands_adapter
from arise.rewards.builtin import task_success

REGION = os.getenv("AWS_REGION", "us-west-2")
PORT = int(os.getenv("PORT", "9000"))

# ---------------------------------------------------------------------------
# ARISE config
# ---------------------------------------------------------------------------

config = ARISEConfig(
    model="gpt-4o-mini",
    s3_bucket=os.environ.get("ARISE_SKILL_BUCKET", ""),
    sqs_queue_url=os.environ.get("ARISE_QUEUE_URL", ""),
    aws_region=REGION,
    max_evolutions_per_hour=5,
    allowed_imports=[
        "json", "csv", "re", "hashlib", "base64", "datetime",
        "math", "collections", "itertools", "functools",
        "pathlib", "os", "tempfile", "urllib",
    ],
)

# ---------------------------------------------------------------------------
# Strands Agent
# ---------------------------------------------------------------------------

bedrock_model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    region_name=REGION,
)

strands_agent = Agent(
    name="arise-devops",
    description="Self-evolving DevOps assistant that learns new tools over time.",
    model=bedrock_model,
    system_prompt=(
        "You are a DevOps assistant. Use available tools to complete tasks. "
        "If no tool exists for a task, respond with: "
        "TOOL_MISSING: <describe what capability you need>. "
        "Always produce clear, actionable output."
    ),
    callback_handler=None,
)

# ---------------------------------------------------------------------------
# ARISE wraps the agent in distributed mode (S3 skills + SQS trajectories)
# ---------------------------------------------------------------------------

agent_fn = strands_adapter(strands_agent)

if config.s3_bucket and config.sqs_queue_url:
    arise = create_distributed_arise(
        agent_fn=agent_fn,
        reward_fn=task_success,
        config=config,
    )
else:
    # Local mode fallback for development
    from arise import ARISE
    arise = ARISE(
        agent_fn=agent_fn,
        reward_fn=task_success,
        config=config,
    )

# ---------------------------------------------------------------------------
# A2A Server
# ---------------------------------------------------------------------------

a2a_server = A2AServer(agent=strands_agent)

if __name__ == "__main__":
    print(f"Starting ARISE DevOps A2A server on port {PORT}...")
    print(f"Agent card: http://localhost:{PORT}/.well-known/agent.json")
    a2a_server.serve(host="0.0.0.0", port=PORT)
