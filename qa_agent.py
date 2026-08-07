import json
import uuid
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

class TestCaseOutput(BaseModel):
    title: str = Field(description="Short descriptive title of the test case")
    description: str = Field(description="Detailed explanation of what is being tested")
    type: str = Field(description="Type of test (e.g., Unit, Integration, E2E, Security, Database)")
    test_steps: str = Field(description="Numbered list of steps to execute the test")
    expected_result: str = Field(description="The exact expected outcome of the test")
    requirement_id: str = Field(description="The sourceReq ID of the task this test applies to")

class QASuiteOutput(BaseModel):
    test_cases: List[TestCaseOutput]

async def generate_test_cases(tasks: List[Dict[str, Any]], hld_content: str, lld_content: str) -> QASuiteOutput:
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)

    # Format tasks for the prompt
    task_context = ""
    for idx, t in enumerate(tasks, 1):
        task_context += f"Task {idx}:\n"
        task_context += f"- ID: {t.get('id')}\n"
        task_context += f"- Title: {t.get('title')}\n"
        task_context += f"- Description: {t.get('description')}\n"
        task_context += f"- User Story: {t.get('user_story')}\n"
        task_context += f"- Requirement ID: {t.get('requirement_id')}\n\n"

    system_prompt = """You are an expert QA Automation Architect.
Your job is to generate rigorous, high-fidelity test cases for a set of tasks that have just been moved to the "Review" stage.
You must use the provided High-Level Design (HLD) and Low-Level Design (LLD) to perform "White-Box" and "Integration" testing.
Do not just write basic black-box UI tests. Write tests that verify database schemas, API contracts, security hashing, and component interactions as defined in the architecture.

Return the output EXACTLY matching the requested JSON schema.
"""

    human_prompt = f"""
We have the following tasks in the "Review" stage that need test cases generated:
--- TASKS ---
{task_context}
--- END TASKS ---

Here is the High-Level Design (HLD) context:
{hld_content}

Here is the Low-Level Design (LLD) context:
{lld_content}

Generate a comprehensive test suite for these tasks. Include Unit, Integration, and Database tests where applicable based on the LLD.
Ensure each test case has a clear title, description, step-by-step instructions, and expected result.
Map each test case to the 'requirement_id' of the task it belongs to.
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    response = llm.with_structured_output(QASuiteOutput).invoke(messages)
    return response
