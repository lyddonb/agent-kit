---
name: interview-kit
description: Build a structured interview kit for an engineering role - competencies, an interview loop, questions with follow-ups, and a scoring rubric with behavioral anchors. Use when planning hiring for a role, designing an interview loop, writing interview questions, or creating a scorecard or rubric.
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
---

# Interview kit

Produce a kit that lets different interviewers evaluate candidates consistently and fairly.

## Inputs to gather

Ask for whatever is missing, in one message:
- Role, level, and team (e.g. "Senior Backend Engineer, payments team")
- What this person must accomplish in their first 6-12 months
- Must-have vs. nice-to-have skills; the tech stack
- Loop constraints: number of interviews, total time, take-home allowed or not
- Company values or engineering principles to assess, if any

If the user says "just draft it", make reasonable assumptions and list them at the top.

## Steps

1. **Define 4-6 competencies** derived from the 6-12 month outcomes, not from a generic list. Each gets a one-line definition of what "good" looks like at this level.
2. **Design the loop.** Map each competency to exactly one or two interviews so every competency is covered and nothing is assessed five times. Include a short candidate-facing description of each interview.
3. **Write questions** for each interview: a main prompt, 2-4 follow-up probes that go deeper, and what strong and weak answers sound like. Prefer realistic work samples and past-behavior questions ("tell me about a time...") over trivia and brainteasers.
4. **Build the scorecard** using [assets/scorecard-template.md](assets/scorecard-template.md): a 1-4 scale per competency with behavioral anchors, plus an overall hire/no-hire recommendation and evidence fields.
5. **Add interviewer guidance:** how to take notes as evidence (quotes and observations, not adjectives), submit scores before the debrief, and avoid discussing candidates before scoring.

## Guardrails

- Every question must map to a competency. Drop any that do not.
- Keep it job-related and consistent across candidates. Never include questions about age, family, health, religion, national origin, or other protected characteristics, and flag any such question the user proposes.
- Calibrate to level: a senior loop assesses scope, ambiguity, and influence, not just coding speed.
- Note accommodations: offer alternatives (e.g. take-home instead of live coding) where they do not change what is measured.
- This is a planning aid, not legal advice; point the user to their recruiting or legal partner for jurisdiction-specific rules.
