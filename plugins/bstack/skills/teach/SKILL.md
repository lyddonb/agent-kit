---
name: teach
description: Explain a body of work plainly so a person actually understands it, by running the how and why skills and weaving what they find into one clear, layered explanation with diagrams that build up step by step. Use for "teach me this", "help me really understand X", "explain this change or subsystem to me", or "prove to me this approach is better".
license: MIT
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "pstack teach @ 11713c6 (MIT, Lauren Tan)"
---

# Teach

Explain what a thing is, how it works, and why it's built that way, in one plain account at the person's pace. The goal is that they understand it and can trust the work, not that you change anything.

Teaching sits on top of **how** and **why**. Get your bearings, run them, then blend what they find into one explanation. Reword freely, with one exception: keep **why**'s confidence language intact. Its hedges are findings, not style.

1. **Decide what they should walk away with.** Pick a few things from why they're asking (about to change it, reviewing it, debugging it, new to it) and what they already know. Read both from the conversation; don't quiz them. Skip what they plainly know and put the depth where their question is.
2. **Let how and why do the digging.** Read the code yourself to get oriented, then run **how** for how it works and **why** for why it's that way, in parallel. Size them to the question: both for a subsystem, maybe one for a small change. Keep **why** narrow by default, since its full sweep is slow. Put the narrowing in the request itself (a scoped question, git plus a source or two) so **why** records what it skipped, and widen it only when the reasons are the point.
3. **Start with a plain definition.** Name the thing and say what it is in general terms, the way a senior engineer would say it out loud, with its common name if it has one. Then tie it to this case ("here we use it to...") and build from there: how it works, the deeper reasons, the edge cases. For each part, give the problem it solves and how it works. Walking through what happens as a user does the thing often makes it click. Listing functions and constants is reference, not teaching.
4. **Give the smallest complete answer first.** A sentence or two, then stop. Add layers when they ask. Never a wall of text.
5. **Keep it a conversation.** Offer to go deeper or move on, and follow their lead. No quizzes, no "pause here", no asking them to say it back, and no flagging a part as important or tricky. Just say it. Running one-shot with no one live, deliver it cleanly and put the offer to go deeper at the end.
6. **Show, and build the picture up.** Open the diff, the code or the output when that's the fastest way to land it. For anything with three or more moving parts, don't draw one diagram with everything in it. Draw a short series where each diagram redraws the last and adds one part, so the reader watches the system assemble: A to B, then A to B to C, then the return edge. Use Mermaid when labels carry the meaning. When the idea is spatial (layout, overlap, scroll position, before and after) and you can make images, draw a simple whiteboard-style picture with a few short labels. A single simple point needs no figure.

Write every response through the **unslop** skill, in plain spoken English, the way you'd explain it to a colleague. Tight, not terse: cut filler and hedging, keep the part that makes it click. State the mechanism, not a metaphor or a preview of what's coming. Target density: "Virtualization runs in two parts, one for rendering and one for loading from disk. When an item scrolls out past the buffer, both its DOM node and its in-memory data are evicted." Normal sentence case. Prefer periods to commas. Give each concept one name and keep it. Don't print the structure of these steps as headers or stock phrases ("the key insight", "TL;DR", "at its core").

**Reply:** the explanation itself, never a report about what you did. Lead with the main point, then the plain account of what it is, how it works and why, then the threads worth chasing with **how** or **why**.
