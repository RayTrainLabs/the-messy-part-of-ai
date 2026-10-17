# The messy part of AI: Production, ROI, and Your Visibility

Raygency webinar, 6 November 2026. Speaker Varun Tyagi, host Renuka Adnani.

**Your customers already asked. You weren't in the answer.** This is the kit from the talk: everything you need to check whether your brand is on the AI shortlist, measure it every month, and put a number on it.

- **The deck:** https://raytrainlabs.github.io/the-messy-part-of-ai/
- **The deck as a PDF:** https://raytrainlabs.github.io/the-messy-part-of-ai/deck.pdf

## Start here, no code

| File | What it is | Download |
|---|---|---|
| Monday checklist | GA4 channel for AI (regex included), Search Console's AI report, one form field. Thirty minutes. | https://raytrainlabs.github.io/the-messy-part-of-ai/kit/monday-checklist.md |
| Prompt pack | Write your twenty buyer questions, run the shortlist test, find out why a rival wins, rewrite your five pages. | https://raytrainlabs.github.io/the-messy-part-of-ai/kit/prompt-pack.md |
| ROI worksheet | A model on your own numbers, plus a monthly tracker. Excel or Google Sheets. | https://raytrainlabs.github.io/the-messy-part-of-ai/kit/roi-worksheet.xlsx |
| Questions for your team | Twelve questions for your next meeting, each with what a good answer sounds like. | https://raytrainlabs.github.io/the-messy-part-of-ai/kit/questions-for-your-team.md |
| The Gymshark rerun | The agent output from the talk, in full, with how it was run. | https://raytrainlabs.github.io/the-messy-part-of-ai/kit/gymshark-rerun.md |

## For your technical team: the AEO skills

The agent from slide 14, as Claude Code skills in [`kit/aeo-skills/`](kit/aeo-skills):

| # | Skill | What it does |
|---|---|---|
| 01 | aeo-brand-visibility-analysis | Writes the buyer questions, runs them across ChatGPT, Claude, Gemini, Perplexity and Google, scores every answer, finds the gaps, and writes a scorecard and PDF report |
| 02 | aeo-content-recommendations | Turns the scorecard into a page by page content plan for your site |
| 04 | aeo-content-attribution | Links content you shipped to changes in AI visibility over time |

**First run:** copy a skill folder into `~/.claude/skills/`, run `pip install -r requirements.txt`, put your own API keys in a local `.env` file (never commit it), then ask Claude Code to "run an AEO brand visibility analysis for [your brand]". Each skill's `SKILL.md` lists the keys it needs.

## Free AI visibility snapshot

We run twenty buyer questions about your category across five assistants and send you your presence score, who is named instead of you, and the biggest gaps. Book before 27 November 2026 at https://www.raygency.com.

## Who made this

[Raygency](https://www.raygency.com), an AI native product studio. Varun Tyagi and Renuka Adnani.

The figures in the deck carry their sources on the slides. The ROI worksheet is a model, not a case study.
