---
name: plan
description: Structured task planning for complex multi-step requests.
always: true
---

# Plan Mode

## When to Plan

Generate a structured plan before acting when ANY of these apply:
- The user explicitly uses `/plan` or sends `[Plan Mode]` (always plan)
- The request requires 3+ distinct steps or tool calls
- The request involves research, comparison, or synthesis
- The request combines multiple independent sub-tasks

Do NOT plan for simple questions, greetings, single-tool tasks, or casual conversation.

## Plan Format

Output a plan block BEFORE making any tool calls:

```
**Plan:**
1. [ ] Step description (tool: tool_name)
2. [ ] Step description (tool: tool_name)
3. [ ] Step description
```

Rules:
- Each step is a single, concrete action
- Include the primary tool in parentheses when applicable
- Keep to 3–7 steps; collapse trivial sub-steps
- After outputting the plan, execute it step by step
- Do NOT re-output the entire plan after each step

## Execution

- State which step you are working on before each tool call
- After each step, evaluate whether the remaining plan still makes sense
- Skip steps that become unnecessary based on new information
- Add steps if gaps are discovered
- When all steps are complete, synthesize and deliver the final answer
