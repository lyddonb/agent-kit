---
name: explainer-video
description: Make a finished, narrated explainer video (MP4) about a subject, from concept and script through voiceover, animation and render, and check the frames before delivering. Use when asked to make an explainer, promo, product or walkthrough video, or "a video about X".
license: MIT
compatibility: Renders with Remotion. Needs Node.js and the Remotion agent skills (remotion-best-practices). Voiceover needs a TTS API key or a local TTS model.
metadata:
  author: lyddonb
  version: "0.1.0"
  upstream: "h14h/explainers .agents/skills/promo/SKILL.md @ 314eb13"
---

# Explainer video

You own the whole video: concept, script, narration, visuals, render and the check. Work autonomously until it's done.

**Engine: Remotion.** Load the `remotion-best-practices` skill and follow it for project setup, markup, voiceover, captions and rendering. If it isn't installed, stop and give the user the install command (`npx skills add remotion-dev/skills`, or `npx remotion skills add` inside a Remotion project). Don't build your own pipeline instead.

## Before you start

- **Subject.** If the request doesn't name one, ask. That is the only question to ask.
- **Style.** Use the style the request names: [whiteboard](references/whiteboard.md) or [collage](references/collage.md), or the user's own description. Read only that file. If none is named, pick the one that suits the subject and say which.
- **Rendering is requested.** Remotion's skill says to show a preview and render only when asked. This skill's job is a finished MP4, so the render is asked for. Still open Studio while you build, if you can, so the user can watch.

## Steps

1. **Concept and script.** Write one sentence saying what a viewer should understand and feel by the end. Then a scene list: each scene's purpose, its narration, and what's on screen. Aim for 60 to 120 seconds unless asked otherwise. Save it as `script.md` in the source folder.
2. **Voiceover.** Generate one audio file per scene, following Remotion's voiceover reference. Use the first TTS key you find in the environment or the project's `.env`: `ELEVENLABS_API_KEY`, then `OPENROUTER_API_KEY`. With neither, use a local TTS model, or ask the user to configure a key. Never print a key or write it into source.
3. **Size scenes from the audio.** Use `calculateMetadata` so each scene lasts as long as its narration plus a short beat. Don't hard-code durations.
4. **Build the scenes** in the chosen style. Every on-screen element should support the line being spoken at that moment.
5. **Check frames before the full render.** Render stills at the start, middle and end of every scene in one call: `npx remotion render <id> <source>/check --frames=<list> --image-format=png --is-production=false`. List the folder and look at every image. Fix and re-render until each one passes:
   - Text is readable and inside the frame, with nothing clipped or overlapping by accident.
   - The style matches the reference, and no frame is blank or half-built.
   - What's on screen matches that scene's narration.
   - The last frame is a deliberate ending, not a cut.
6. **Render** to `videos/<name>.mp4`, passing a license key as Remotion's render reference says.
7. **Check the file.** Run `npx remotion ffprobe videos/<name>.mp4`. Confirm the duration matches the composition and that there is an audio stream. Pull a frame from the start, middle and end of the MP4 and look at them: `npx remotion ffmpeg -ss <seconds> -i videos/<name>.mp4 -frames:v 1 <source>/check/final-<seconds>.png`.

## Output

- The MP4 goes in `videos/` in the user's project, with a short name that says the subject. Its source, assets and check frames go in `videos/<name>/`. Never write into this skill's folder.
- In a Git project, make sure `videos/` and any `.env` holding keys are ignored, adding to existing ignore rules without replacing them.

## Quality bar

Aim for professional production value. Pace it to hold attention for the whole length. A viewer should come away wanting to learn more, without being told to.

## Report

Give the MP4 path and duration, the style, the TTS provider, and how many frames you checked and what you fixed. If the user may work at a company of more than 3 people, mention that Remotion needs a company license there (see Remotion's license reference).
