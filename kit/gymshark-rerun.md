# The Gymshark rerun, in full

The agent output shown in the webinar on 6 November 2026. Gymshark is a public brand picked as a worked example. It is not a Raygency client, and no client data was used.

## How it was run

- 18 buyer questions, written by the agent from the brand profile, never naming the brand.
- Run 1 on 7 May 2026. Run 2 on 17 October 2026, the same 18 questions.
- The same models both times, through the API with web search on: gpt-5.4-nano (ChatGPT), claude-opus-4-7 (Claude), gemini-3-flash-preview (Gemini), plus Google's top results through SerpApi. Perplexity (sonar-pro) was added in October.
- Scored by plain text match: does the answer name Gymshark? No model in between.
- API answers are not the consumer app with a logged in history. Expect the app to differ in detail.

## What came back

| Engine | May | October | Same questions both times |
|---|---|---|---|
| ChatGPT | 1 of 18 | 1 of 18 | none: May was the limited drops question, October the long flights question |
| Claude | 5 of 18 | 5 of 18 | 4 |
| Gemini | 5 of 18 | 4 of 17 (one call failed) | 4 |
| Google top results | 4 of 18 | 3 of 18 | 2 |
| Perplexity | not run | 1 of 18 | n/a |

- Answers naming each brand across ChatGPT, Claude and Gemini: Lululemon 14 then 13, Gymshark 11 then 10, Nike 11 then 9, out of 54 and 53 answers.
- Most answers named no brand at all: 30 of 54 in May, 32 of 53 in October.
- Gymshark by question type, both runs together: trend 6 of 12 (50%), problem 10 of 35 (29%), decision 3 of 18 (17%), how to 2 of 42 (5%).
- In October, 4 of 232 citations pointed at Gymshark's own site.
- Sites those three assistants cited: 84 in May, 69 in October, 16 in both. **77% of October's cited sites were not cited in May.**
- On "I'm in the UK and want one outfit for HIIT, then errands after, what pieces should I pick together?", ChatGPT named no brand at all in either run. Claude and Gemini named Gymshark both times.

## What it means

The score held still while the ground moved under it. A single check is a coin toss: measure the same questions, five runs, every month.

## Run it yourself

Skill 01 in `aeo-skills/` is the agent that produced this. See the README in this kit for the first run.
