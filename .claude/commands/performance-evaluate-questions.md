---
name: performance-evaluate-questions
description: "Run AI evaluation on quarterly performance questions."
arguments:
  - name: question_id
---
# Evaluate Questions

Run AI evaluation on quarterly performance questions.

## Instructions

```text
skill_run("performance/evaluate_questions", '{"question_id": ""}')
```

## What It Does

Run AI evaluation on quarterly performance questions.

For each question (or a specific one):
1. Gathers auto-evidence from daily events
2. Includes manual notes
3. Builds a prompt with competency context
4. Generates a summary using Claude
5. Saves the summary to the question

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `question_id` | Specific question ID to evaluate (empty for all) | No |
