# EN → ES Subtitle Translation (K-pop variety)

Translate English SRT subtitles into Latin American Spanish, preserving casual
register, slang, and comedic timing.

Translation happens **in this session** — you translate the text directly. There
is no API script and no external service. `srtkit.py` only handles plumbing.

## Workflow

```bash
python srtkit.py extract ./subs --out ./work     # 1. SRT -> text
#  2. you translate partNN.txt -> partNN.es.txt  (see below)
python srtkit.py merge ./work --out ./subs_es    # 3. text -> SRT
python srtkit.py check ./subs ./subs_es          # 4. verify
```

### Step 2 in detail — your job

For each `work/<episode>/partNN.txt`:

1. Read the file. Every line looks like `[142] English text here`.
2. Read `glossary.json` before you start. It is authoritative.
3. Write `work/<episode>/partNN.es.txt` in the **exact same format**, same ids,
   same order, one line per entry.
4. Do one part file at a time and write it out before starting the next. Do not
   hold several files in your head at once — that is where cues get dropped.

**Format rules, non-negotiable:**

- Every `[id]` from the input must appear in the output. Same count, same order.
- Never merge two cues into one, never split one into two. Timing is already
  locked to these ids and there is no way to re-sync afterwards.
- `\n` (literal backslash-n) inside a line means a line break within that
  subtitle. Preserve it. Don't add new ones casually.
- Preserve inline formatting tags exactly as they appear: `<i>`, `</i>`,
  `{\an8}`, `♪`. These are markup — never translate them.
- **Brackets and parentheses are delimiters, not markup.** Keep the `[ ]` and
  `( )` characters, but translate the text inside them. `[THE GAME BEGINS]`
  becomes `[EMPIEZA EL JUEGO]`, never left in English.
- Never write timestamps or cue numbers other than the `[id]` prefix.

If a cue is genuinely untranslatable, still emit its id with your best attempt.
Never skip a line to "come back to it."

## Tone — the actual point of this project

The failure mode is not mistranslation. It's **over-formalization**. Variety
show banter rendered as neutral business Spanish is a failed run even when every
word is technically correct.

- Latin American / Mexican register. `tú` and `ustedes`. Never `vosotros`.
- Translate how people actually talk. `That's so dumb lol` is not
  `Eso es sumamente absurdo` — it's `jajaja qué tontería` or similar.
- Laughter is `jaja` / `jajaja`, never `haha`.
- Reactions get localized, not transliterated: `Huh?` → `¿Eh?`, `Ugh` → `Ay`.
- Keep fandom vocabulary that Spanish-speaking fans already use in English.
  Honorifics stay untranslated. See `glossary.json`.
- **Parenthetical and bracketed text is production-team commentary or sound
  description.** It comes in three flavours, handled differently:
  - *Sound/action captions* — `(laughs)`, `(everyone screaming)`, `(silence)`.
    Spanish subtitle convention is lowercase and short: `(risas)`, `(gritos)`,
    `(silencio)`. Prefer a noun over a conjugated verb — `(risas)` not
    `(se ríe)` — unless the subject genuinely matters.
  - *Producer/editor asides* — the snarky running commentary the edit adds on
    top of the footage. These are **jokes** and are often the funniest text on
    screen. Translate them with full attitude. Never neutralise them into flat
    description.
  - *On-screen text being transcribed* — signs, captions, chyrons. Translate
    plainly and keep it short.
- ALL-CAPS and `{\an8}` cues are also production-team captions. Keep them punchy
  and caption-like, not descriptive.
- Keep the delimiter style the source used. If the show puts commentary in
  parentheses, your translation uses parentheses too — don't switch to brackets
  or drop them. Consistency across an episode matters more than your preference.
- Untranslatable wordplay gets **adapted** to a joke landing on the same
  emotional beat. Never explained, never flattened.
- Members roast each other constantly. Preserve the teasing.

## Length discipline

Spanish runs roughly 20% longer than English. These are subtitles read in under
two seconds — **tighten the wording rather than padding it.** Brevity beats
literalness. `merge` will rewrap lines over 42 characters, but a rewrap that
produces two cramped lines is worse than a tighter translation.

## The glossary is the highest-leverage file

`glossary.json` is what makes output sound like *this specific show* rather than
generic Spanish. Before a full season, populate:

- Every member's name and nickname (stops `Wonyoung` becoming `Won Young`)
- Recurring segment names
- Running gags needing a consistent Spanish rendering

Suggested loop: translate one episode, watch it, add terms, then batch the rest.

## If `merge` fails

It refuses to write a broken SRT rather than corrupting output — that's
intended. The error names the problem:

| Error | Fix |
|---|---|
| `N cues missing` | Add the listed ids to the `.es.txt` file |
| `malformed line` | Every line must start with `[id] ` |
| `duplicate cue id` | Remove the repeat |
| `no part*.es.txt files` | That episode isn't translated yet |

Never "fix" a failure by editing `skeleton.json`. It is the source of truth for
timing and must stay untouched.

## Tuning

| Constant | Default | Notes |
|---|---|---|
| `CUES_PER_PART` | 120 | Lower via `--chunk` if part files feel unwieldy |
| `MAX_LINE_CHARS` | 42 | Drop to ~38 if lines feel long on screen |

`check` also flags cues over 20 characters/second, which are technically valid
but hard to actually read. Worth a manual look.
