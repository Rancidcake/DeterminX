# What Is This Project? (The Simple Version)

**No jargon. No code. Just what this thing is and why it exists.**
*(For the technical deep-dive, see `KT_V2_FinancialIntelligence.md` and `KT_AMD_and_ShelfCompany.md`.)*

---

## In one sentence

**FinVeritas reads a company's financial statements and tells you, in plain English, whether the
company looks financially healthy — and it shows its work, so you can check the math yourself.**

---

## The problem it solves

Imagine you're trying to decide: *"Should I lend money to this company? Invest in it? Do business
with it?"*

Normally you'd either:
1. Hire an expensive analyst to read the financial statements and write you a report, or
2. Ask an AI chatbot to read the numbers and tell you what it thinks.

Option 1 is slow and costly. Option 2 is fast and cheap — but AI chatbots have a bad habit of
**making up numbers that sound right but aren't real**. Ask a chatbot "what's this company's profit
margin?" and it might just guess a plausible-looking number instead of actually calculating it. In
finance, a confidently wrong number is worse than no number at all.

**FinVeritas is built specifically to never do that.**

---

## The one rule everything is built around

> **A calculator does the math. A writer explains what the math means. They are never the same
> person.**

In this app:
- **Python (plain, boring, predictable computer code) does every single calculation.** Revenue
  growth, profit margins, debt ratios, cash flow — all of it is arithmetic done by code that
  behaves the exact same way every single time, like a calculator.
- **The AI (the LLM — "the chatbot part") is only ever allowed to explain, in words, what the
  numbers that Python already calculated actually mean.** It is never allowed to do the math
  itself, and it's technically prevented from even seeing the raw financial statements — it only
  ever sees a list of already-computed numbers, like `{"revenue_growth": "12%"}`.

So the AI physically cannot invent a number, because it's never in a position to produce one in the
first place. It can only talk about numbers someone else (Python) already worked out.

---

## What it actually does, step by step

1. **You give it a company's financials** — upload a PDF, type in a stock ticker, or paste in a
   spreadsheet.
2. **It reads and organizes the numbers** — revenue, profit, debt, assets, cash, etc.
3. **It calculates everything a financial analyst would calculate** — growth rates, profit margins,
   debt levels, liquidity, efficiency, and more (currently **over 100 different metrics**).
4. **For anything it CAN'T calculate**, it says so honestly instead of guessing — e.g. "we don't have
   enough data to calculate this" rather than making something up.
5. **The AI then writes a plain-English summary** of what those calculated numbers mean — like
   "this company's profit margin has been shrinking for two years, which is a warning sign."
6. **You get a dashboard** showing both the raw numbers AND the plain-English explanation, so you can
   trust the numbers because you can see exactly how they were calculated.

---

## What's new in this version (V2) — in plain terms

Version 1 could answer: *"How has this company performed historically?"*

Version 2 adds seven new things on top, so it can also answer:

| New feature | What it means in plain English |
|---|---|
| **Way more metrics** | Went from a handful of financial ratios to 100+, covering every angle a real analyst would check |
| **Forecasting** | You type "I think this company will grow 15% next year" and it tells you, based on real historical data, whether that's a *realistic* guess or a *wildly optimistic* one — and explains why |
| **Competitor comparison** | Automatically pulls a competitor's numbers and shows you side-by-side: is this company doing better or worse than its rivals? |
| **Early-warning alerts** | Flags things that suddenly look "off" compared to the company's own past — like a smoke detector for financial trouble |
| **Loan/credit check** | Estimates how much working capital a business needs and roughly how much a bank might lend it — clearly labeled as an *estimate*, never pretending to be an official bank decision |
| **Geography breakdown** | If a company reports revenue by region (US, Europe, India, etc.), it shows which regions are growing or shrinking, and can suggest — cautiously — why, based on recent news |
| **Leadership background check** | Pulls out the names of company directors and does a basic "has this person been in any concerning news recently" scan |
| **Industry-specific metrics** | If you tell it "this is a SaaS company," it adds software-industry metrics like Customer Acquisition Cost and Customer Lifetime Value — the kind of numbers that don't show up on a normal balance sheet but investors specifically want for that kind of business |

---

## What it deliberately does NOT do

This matters just as much as what it does do:

- **It never invents a number it doesn't have enough information to calculate.** If the data isn't
  there, it says so — it doesn't guess.
- **It never makes a "should you lend/invest/hire this company" decision.** It shows you the
  evidence; you make the call.
- **It doesn't have access to official government/regulatory databases** (like corporate registries
  or court records) in this setup — so anywhere it would need that, it says plainly "this
  information isn't available here" instead of pretending to have checked something it hasn't.

---

## The two-word summary

**Calculator, then writer.** Never the other way around. That's the whole trick — and it's why you
can actually trust what this app tells you, instead of just hoping the AI got it right.
