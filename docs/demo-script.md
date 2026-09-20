# Demo video — shot list (2:50)

Judges watch three minutes and read nothing. The film has one job: make the spoiler fence
*visible*, twice, before minute two.

**Setup:** emulator (or Fire TV Stick) at 1080p, backend running, `sintel` timeline ingested.
Record the screen at 1080p60, capture the voice-over separately and lay it over the picture.
Keep every answer on screen long enough to read (~4 s).

---

## 0:00–0:20 · The problem, in the viewer's words

**Picture:** *Sintel* playing, someone reaching for the remote and pausing.

> "Who's that again?" — the question every person on a sofa has asked. Today you either pause
> and search the plot, which spoils the film, or you shrug and keep watching.

## 0:20–0:50 · The answer, spoiler-free

**Picture:** at **5:49**, press ☰ → *Who's that?* → the card appears.

**On screen:** headline **"Red-haired woman"**, "first seen at 2:40", the answer about caring for
the winged creature.

> Press one button. The answer comes from the film itself — but only from the part you have
> already watched.

**Hold on the knowledge bar for 3 seconds.** Point at it with a cursor or a highlight.

> Everything left of the line is what the companion knows. Everything right of it is hatched out:
> the model is never given it.

## 0:50–1:20 · The proof: the same button, later ⭐

**Picture:** jump to **10:12**, press ☰ → *Who's that?* again.

**On screen:** headline **"Sintel"**.

> Same button, same film, four minutes later. Now it knows her name — because by now, so do you.
> At 5:49 the film had not said it yet, so neither did the companion.

**Cut the two cards side by side for 2 seconds.** This is the shot people remember.

## 1:20–1:45 · Skipping ahead

**Picture:** fast-forward from ~4:30 to ~9:45; the hint *"⏩ Skipped 5:15 · ☰ for a recap"* appears.
Press ☰ — *What did I miss?* is already focused — press OK.

> Skip five minutes and it offers to catch you up on exactly what you skipped. Not the last five
> minutes. The five minutes you jumped over.

**On screen:** the orange range on the knowledge bar covering exactly the skipped part.

## 1:45–2:05 · Going back

**Picture:** ☰ → *Take me back…* → type "she found the winged creature" → the card shows
**"▶ Jump to 4:00"** → press OK → the player jumps and plays.

> It can also drive the player. "Take me back to when she found the creature" — and you are there.
> Ask it to take you to the ending and it refuses: that part hasn't happened for you yet.

**Optional, if the pacing allows:** show that refusal for 2 seconds.

## 2:05–2:35 · Why it holds: the number

**Picture:** a plain slide with the table.

| | leaks | questions |
|---|---|---|
| **with the fence** | **0** | 30 |
| a normal assistant, asked not to spoil | **9** | 30 |

> Most AI companions are handed the whole plot and asked politely not to spoil it. We measured
> that: they leak. Ours never receives the future, so it cannot leak it — and when the model does
> slip a name it learned elsewhere, the backend catches it, because it knows exactly which names
> the viewer has not heard yet.

## 2:35–2:50 · What it is

**Picture:** the architecture diagram from the README, then the app icon.

> Fire TV app, AWS Lambda, Amazon Bedrock. The fence itself is forty lines of Python that any
> streaming app can put in front of its own player.

---

## Checklist before recording

- [ ] `data/titles/sintel/timeline.json` present (23 scenes)
- [ ] backend up, one warm-up question asked (first call is slower)
- [ ] `adb shell settings put global window_animation_scale 0.5` — snappier transitions
- [ ] quota headroom: every question is one model call
- [ ] numbers in the slide match `eval/leak_report.md`
- [ ] under 3:00, public on YouTube, English audio
