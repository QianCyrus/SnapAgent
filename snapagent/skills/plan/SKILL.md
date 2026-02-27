---
name: plan
description: Structured task planning for complex multi-step requests.
always: true
---

# Plan Mode

## When to Plan

Generate a structured plan before acting when ANY of these apply:
- The message contains `[Plan Mode]` (always plan)
- The request requires 3+ distinct steps or tool calls
- The request involves research, comparison, or synthesis
- The request combines multiple independent sub-tasks

Do NOT plan for simple questions, greetings, single-tool tasks, or casual conversation.

## Plan Workflow

### Step 1: Clarify Requirements
Before creating a plan, briefly confirm your understanding of the request:
- Restate the goal in one sentence
- List any assumptions you are making
- Ask clarifying questions if the request is ambiguous

### Step 2: Present the Plan
Output a plan block and **stop — do NOT execute any tools yet**:

```
**Plan:**
1. [ ] Step description (tool: tool_name)
2. [ ] Step description (tool: tool_name)
3. [ ] Step description
```

Then ask: "Does this plan look good? You can approve, modify, or reject it."

Rules:
- Each step is a single, concrete action
- Include the primary tool in parentheses when applicable
- Keep to 3–7 steps; collapse trivial sub-steps

### Step 3: Wait for User Approval
- If the user approves (e.g. "ok", "go", "approved", "yes", "do it"): execute the plan step by step
- If the user suggests changes: revise the plan and present it again
- If the user rejects: abandon the plan and ask what they'd like instead

### Step 4: Execute
Once approved:
- State which step you are working on before each tool call
- After each step, evaluate whether the remaining plan still makes sense
- Skip steps that become unnecessary based on new information
- Add steps if gaps are discovered
- When all steps are complete, synthesize and deliver the final answer
