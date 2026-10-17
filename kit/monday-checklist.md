# The Monday morning checklist

From the Raygency webinar, 6 November 2026. About thirty minutes of setup. Next month you have a baseline to beat.

## 1. A GA4 channel for AI assistants (10 minutes)

In GA4: **Admin, Data display, Channel groups**. Copy the default group, then **Add new channel**:

- Name: `AI assistants`
- Condition: **Session source** **matches regex**:

```
.*(chatgpt\.com|chat\.openai\.com|openai\.com|perplexity\.ai|gemini\.google\.com|bard\.google\.com|claude\.ai|copilot\.microsoft\.com|edgeservices\.bing\.com|chat\.deepseek\.com|meta\.ai|chat\.mistral\.ai|you\.com).*
```

- **Drag it above Referral** in the channel order. GA4 assigns the first match, so below Referral it never fires.
- Save, then check Reports, Acquisition, Traffic acquisition with your new group selected. It applies to historical data too.

What it will not see: visits where the app strips the referrer. Those land in Direct. That is why step 3 exists.

## 2. Search Console's generative AI report (5 minutes)

In Search Console, open **Performance** and find the generative AI report Google launched on 3 June 2026. Bookmark it.

What it shows: impressions in Google's AI features. What it does not show: clicks or queries. Record the monthly impressions in the same sheet as your presence score.

## 3. One option on your form (15 minutes)

On your sign up, demo request or checkout form, add the question **"How did you hear about us?"** with these options:

- Google search
- **ChatGPT or another AI assistant**
- Social media
- A friend or colleague
- Other (please say)

This is the one measure that sees what analytics cannot.

## 4. Your first presence baseline (do it this week)

Use the prompt pack in this kit: twenty questions, logged out, five runs, the engines your buyers use. Write down the date and the score.

## 5. Put it in the calendar

Same week every month: rerun the twenty, read the three numbers (presence, AI channel visits, form answers) side by side. Change one thing at a time between runs.
