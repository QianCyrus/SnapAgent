---
name: secure-rag-reader
description: Fact-checked document reader with citation verification. Use for accurate information extraction from text sources.
always: false
---

# Secure RAG Reader

High-precision document analysis engine with built-in hallucination prevention.

## When to use

Invoke the `rag_query` tool when:
- Summarizing or extracting facts from fetched web pages or files
- The user needs verified, citation-backed answers
- Accuracy is critical and claims must be traceable to source text

## Workflow

1. Obtain source material using `web_fetch` or `read_file`.
2. Call `rag_query` with your question and the source text as context.
3. The tool returns a fact-checked answer with exact verbatim citations.
4. Report the tool's answer and citations to the user without modification.

## Strict rules

- NEVER modify, rephrase, or embellish the answer returned by `rag_query`.
- NEVER supplement the answer with your internal knowledge.
- If the tool reports "Insufficient information", tell the user honestly.
- If confidence is below 50%, warn the user about low certainty.
