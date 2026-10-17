# Phase 1, Brand validation

**Goal:** the user reads `output/brand_profile.md`, edits anything wrong, and explicitly approves before any query work starts. Five minutes here saves an hour of rerunning the audit on the wrong premise.

## Why this phase exists

Phase 2 generates 20 queries derived from the brand profile. If the profile says the category is "project management" but the brand actually sells "client onboarding workflows for agencies", every single query will be off-target and the entire audit is wasted. Validation is non-negotiable.

## Steps

1. **Show the user `output/brand_profile.md`** in the chat. Do not just say "I wrote it to disk", actually paste the key sections inline so the user can react immediately.

2. **Highlight what was inferred vs. taken verbatim**:
 - "From your docs: [verbatim]"
 - "Inferred from the website: [paraphrase]"
 - "Best guess (please confirm): [field]"

3. **Lead with the "Open questions" list.** These are the items the skill flagged as uncertain. The user's answers here are the highest-leverage edits.

4. **Ask a single, focused question**, not seven. Example:
 > Here is the brand profile I synthesized. Three things I want to confirm before I generate the AEO test queries:
 >
 > 1. Is the **category** I'm using ("product feedback / experience analytics") the one a buyer would actually search for, or would they use something narrower like "in-app survey tools"?
 > 2. Your **direct competitor list** is Sprig, Pendo, FullStory, should Hotjar or Survicate be on there too?
 > 3. The **geographic focus** I have is US/EU. Is APAC in scope for this audit or not?
 >
 > If anything else looks off, just point at it. Otherwise, reply "looks good" and I'll generate the query set.

5. **Apply edits to BOTH** `brand_profile.md` and `brand_profile.json`. Keep them in sync. Re-show the diff if changes are non-trivial.

6. **Loop until the user says "looks good", "approved", "go ahead", or equivalent.** Do not infer approval from silence. Do not proceed if the user only acknowledged part of the questions.

7. **Stamp the JSON** when approved:
 ```json
 "validated_at": "2026-04-27",
 "validated_by": "user"
 ```
 This stamp is what Phase 2 checks before it runs.

## What NOT to ask the user

- Do not ask the user to confirm trivial verbatim quotes ("Is your tagline really 'real-time feedback for product teams'?"). They wrote it.
- Do not ask leading questions ("Don't you think Pendo is a competitor?"). Ask open: "Who else should be on this list?"
- Do not bury the questions in a wall of text. Three questions max per validation round.

## Edge cases

- **User pushes back on competitor list with no replacement** ("Pendo isn't really a competitor"): ask what they consider the closest 2 to 3 alternatives a buyer evaluates. AEO audits are useless without a competitor set.
- **User says "I don't know my ICP"**: walk them through the four-question version: who paid you last, what title were they, what company size, what problem brought them in.
- **User wants to add 20 competitors**: trim to the 5 to 8 most-mentioned in their actual sales conversations. Too many dilutes the share-of-voice math.
- **User changes the brand name** ("we're rebranding next month"): use the **current** name for this audit and note in `brand_profile.json` that a re-run is planned post-rebrand.

## Output contract

- `output/brand_profile.json` updated with `validated_at` + `validated_by` keys
- `output/brand_profile.md` updated to match
- A one-line confirmation in the chat: `Brand profile validated. Generating 50 to 60 AEO queries next.`

Then proceed to Phase 2.
