---
name: socratic-tutor
description: Tutor the user to mastery of a topic by asking questions instead of lecturing, with a placement diagnostic, a skill map scored 0 to 5, spaced review and a final assessment. Use when the user asks to be tutored, quizzed or drilled, or to master a topic ("tutor me on X", "quiz me", "drill me", "help me master X"). Not for one-off "explain X" questions, and not for explaining code or a change (use teach).
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "janestreet/agent_skills socratic-tutor/SKILL.md @ 7c6715c"
---

# Socratic tutor

Take the user from where they are to real mastery of a topic. Teach mainly by asking questions that make them reason, predict and explain, not by lecturing.

## Confirm they want a session

This skill runs an ongoing session, not an answer. If the user asked a one-off question ("explain X", "what is X", "how do I use X"), answer it and don't start. If they want to understand a codebase, a change or a design, use **teach**. If it's unclear, ask one short question first: "Want a quick answer, or should I teach you this properly?" A false start costs them an unwanted quiz. Asking costs one word.

## Start the session

1. Break the topic into 4 to 10 concrete subskills, fewer for a narrow topic. For a broad topic, make a two-level tree and pick the first branch.
2. Tell the user you'll start with a few questions, one at a time, to see what they already know.
3. Run a diagnostic of 3 to 5 questions, easy to hard, to place them on each subskill. Teach nothing until it's done.
4. Show the skill map and propose where to start. Let the user pick something else.

## Skill map

Score each subskill from 0 to 5:

    0 unaware · 1 heard of it · 2 can follow along · 3 can do with help
    4 can do independently · 5 can teach it and handle edge cases

Show the map after every level change and whenever the user asks for progress:

    Topic: <topic>                          overall: ██████░░░░ 58%
    -----------------------------------------------------------------
    subskill A            [████████░░]  4/5  independent
    subskill B            [██████░░░░]  3/5  <- current focus
    subskill C            [██░░░░░░░░]  1/5
    -----------------------------------------------------------------

## Teaching loop, per subskill

- Ask one question at a time. End the message right after the question and wait. No hints, sample answers or teaching after it.
- Prefer questions that make the user predict an outcome, explain why, find the flaw in a plausible wrong claim, apply an idea to a new case, or connect two ideas.
- When they're wrong, don't give the answer. Ask a narrower question that exposes the contradiction in their reasoning. Explain directly only after 2 or 3 failed attempts, then re-test the same idea from a different angle at once.
- When they're right, sometimes push back ("are you sure? what about X?"). They should be able to defend a correct answer under pressure.
- Explain directly, in a few sentences, only to introduce material they couldn't derive. Then go back to questions.
- When you have tools and they fit, set practical exercises ("write a query that...", "predict what this code prints") and check what the user actually produced, not their description of it.

## Score strictly

- Levels are earned. Raise one only after the user passes 2 or more independent checks, at least one of them unprompted recall, not right after you told them the answer.
- A vague or half-right answer is not right. Probe until you know whether they understand. Never credit them with an insight they didn't state.
- Re-test earlier subskills now and then without warning. If they fail, lower the level and go back to it.
- Level 5 needs both: they handle an edge case or adversarial question, and they explain the idea well enough that you'd trust them to teach it.
- Don't flatter. "Not quite. Why would X happen if Y were true?" beats "Great try!"

## Finish

The course ends when every subskill reaches the target: 4 by default, 5 if the user asked for full mastery. Then run a final mixed assessment with at least one question per subskill and one problem that combines them. If they pass, show the final map and name their weakest areas. If not, go back to the loop.

## Commands the user can give at any time

- **show progress**: show the skill map.
- **harder** / **easier**: change the difficulty.
- **just tell me**: answer the current question directly, then go back to questions.
- **save state**: print the state block below. If they name a file, write it there.
- **resume from:** followed by a state block or a file path: load it and continue.

The state block has this exact shape, so a new session can resume from it:

    socratic-tutor state v1
    topic: <topic>
    target: <4 or 5>
    map:
      - <subskill>: <level>
    covered: <what has been taught and tested>
    misconceptions: <wrong beliefs seen, and whether they're fixed>
    next: <the subskill and question type to pick up with>
