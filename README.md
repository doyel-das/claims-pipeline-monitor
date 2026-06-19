# Claims Pipeline Monitor

## What this is

This is a tool that monitors outstanding insurance claims across a mental healthcare platform's billing pipeline. The platform connects patients, therapists, and insurance payors — a three-sided marketplace where the platform submits claims to insurance payors on behalf of therapy sessions. Claims go unpaid for all kinds of reasons: slow payors, denials, missing documentation, coding errors. Every uncollected claim is direct revenue sitting on the table. This tool identifies which claims need action and when, generates payor follow-up outreach calibrated to how long a claim has been outstanding, classifies denial reason codes and routes each denied claim to the correct automated resolution path, and surfaces only the genuinely complex cases to a human billing team. Built as a portfolio project to demonstrate AI operations and revenue cycle management thinking for healthcare platforms.

## Why it exists

At scale, a billing team cannot manually track thousands of outstanding claims, chase each one at exactly the right moment, and know what to do with every denial. Claims that should be followed up at 30 days quietly slide to 60, then 90, while a team is busy with whatever is loudest that day. Denials pile up in a shared inbox waiting for someone to figure out, case by case, what each reason code actually means. This tool automates that repetitive monitoring and triage layer so a human only has to step in for the cases that genuinely require judgment — complex denials, high-dollar escalations, and partial payments where the right next step isn't obvious.

## How it works

1. Reads outstanding claim records from `sample_claims.csv`
2. Calculates `days_outstanding` for each claim and a `priority_score` that combines age and dollar amount
3. Generates an AI follow-up message for any claim due for outreach, with tone calibrated to how long the claim has been outstanding
4. Classifies any denied claim's reason code and routes it to the correct automated resolution path — or flags it for a human if the code is unrecognized or the path requires one
5. Writes the full results to `claim_status.csv`, sorted by priority, and a filtered list of cases needing a human to `escalations.csv`, sorted by dollar amount
6. Appends a run summary to `metrics_log.csv` for trend tracking over time

## Project structure

```
claims-pipeline-monitor/
├── main.py                     # Entry point — orchestrates reading, scoring, outreach, denial classification, and output
├── followup.py                 # Calls the Claude API to generate a structured payor follow-up message per claim
├── denial_classifier.py        # Calls the Claude API to classify a denial code and generate a resolution draft
├── config.py                   # Model name, file paths, follow-up/escalation thresholds, and the denial code lookup table
├── requirements.txt            # Python dependencies
├── .env.example                # Template for the required API key environment variable
├── sample_claims.csv           # Input: 14 fictional claim records covering all key scenarios
├── claim_status_MOCK.csv       # Example of what claim_status.csv looks like after running the tool
├── escalations_MOCK.csv        # Example of what escalations.csv looks like — only cases needing human review
├── metrics_log_MOCK.csv        # Example of six months of run history showing the program maturing over time
└── DATA_DICTIONARY.md          # Column-by-column documentation for every input and output field
```

## How to run it

1. Clone the repo:
   ```
   git clone https://github.com/doyel-das/claims-pipeline-monitor.git
   cd claims-pipeline-monitor
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and add your Anthropic API key:
   ```
   cp .env.example .env
   ```
   Then open `.env` and replace `your_api_key_here` with your actual key from [console.anthropic.com](https://console.anthropic.com).

4. Run the tool:
   ```
   python main.py
   ```

5. Check the output:
   - `claim_status.csv` — every claim, with days outstanding, priority score, follow-up message, and denial classification
   - `escalations.csv` — only the claims that need a human to review them
   - `metrics_log.csv` — a one-row summary of this run, appended each time you run

## Sample output

A few rows from `claim_status_MOCK.csv` to show the range of outcomes:

| claim_id | payor_name | days_outstanding | priority_score | follow-up_stage | denial_category | requires_human_review |
|---|---|---|---|---|---|---|
| CLM-3001 | Aetna | 10 | 32.5 | no_action_needed | | False |
| CLM-3003 | United Healthcare | 32 | 56.0 | first_followup | | False |
| CLM-3006 | BCBS | 95 | 141.5 | escalation | | True |
| CLM-3008 | BCBS | 27 | 54.0 | denied | coding_error | False |
| CLM-3012 | Cascade Behavioral Health Network | 46 | 75.2 | denied | unknown | True |

CLM-3001 needs no action at all — it's only 10 days old, well within normal processing time. CLM-3006 is the clearest case for human review: it's been outstanding 95 days, past the automatic escalation threshold, regardless of anything else about it. CLM-3008 shows the system working without a human at all — a `CO-4` coding error denial gets a corrected claim cover letter drafted automatically. CLM-3012 shows the opposite: an unrecognized denial code gets no auto-generated resolution draft, because guessing at a resolution path the system doesn't actually know is worse than admitting it doesn't know and asking a person.

## Denial classification

Each denial code is looked up in a table (`config.py`) mapping it to a category and an automated resolution path:

- **`CO-4` (coding_error)** → drafts a corrected claim cover letter
- **`CO-16` (missing_documentation)** → drafts a documentation submission letter
- **`CO-22` (coordination_of_benefits)** → drafts an internal note to follow up with the patient about other coverage
- **`CO-50` (non_covered_service)** → drafts an appeal letter framework
- **`CO-97` (bundling_issue)** → drafts an internal billing review note
- **`PR-1` (patient_deductible)** → drafts a patient billing notification
- **`PR-2` (patient_coinsurance)** → drafts a patient billing notification
- **`OA-23` (timely_filing)** → drafts an appeal letter framework

Any code not in this table is classified as `unknown`. No resolution draft is generated for unknown codes — the system states plainly that the code isn't recognized and routes the claim to the billing team to research and classify manually, rather than guessing at a path that could be wrong.

Appeal drafts (`CO-50` and `OA-23`) always require human review before submission. The system can produce a structurally correct appeal framework, but it cannot fabricate the clinical rationale that actually makes an appeal persuasive — that section is explicitly left for a human to write and approve.

## Design decisions

**Priority scoring combines days and dollars rather than sorting by one dimension.** Sorting purely by age would bury a young, high-dollar claim behind an old, low-dollar one, even though the high-dollar claim represents far more revenue at risk. Sorting purely by dollar amount would let claims quietly age toward write-off. Combining both into `priority_score = days_outstanding + (amount * 0.15)` means a $720 claim at 45 days can and does outrank a $140 claim at 65 days — exactly the triage behavior a billing team actually wants.

**Three escalating templates rather than one generic message.** A payor that ignores a polite status request needs a different message than one that's about to get escalated internally. Flat, unescalating outreach wastes the leverage a firmer, deadline-bound message can apply once a claim has genuinely overstayed normal processing time.

**Denial classification routes automatically for known codes and flags unknown codes rather than trying to guess.** A wrong guess at a resolution path wastes a billing team's time worse than an honest "I don't know" — chasing a fabricated resolution path is more costly than a flagged claim sitting in a queue for a few extra hours.

**Partial payments always flag for human disposition rather than auto-closing.** Whether to write off the remainder, bill the patient, or dispute the partial amount with the payor depends on plan details and account history the system doesn't have visibility into. Auto-closing a partial payment risks writing off money that should have been collected, or billing a patient for an amount they don't actually owe.

**Follow-up trigger rate is tracked because it's a better signal of system performance than recovery rate.** Recovery rate (dollars collected divided by dollars billed) is confounded by factors entirely outside this tool's control — payor processing speed, plan coverage decisions, patient ability to pay. Follow-up trigger rate (the share of claims that get timely outreach) isolates the one thing the tool actually controls: whether every claim that needed action got it, on time.

## Revenue cycle and mental health context

This problem is specific to mental health platforms in a few important ways:

- **High volume, lower dollar value per claim.** Therapy sessions are billed far more frequently than many medical procedures, but each individual claim is worth less than, say, a surgical procedure. That means claim volume is high relative to average claim value, which is exactly the regime where manual, per-claim tracking breaks down fastest.
- **Behavioral health claims face higher denial rates.** Payor behavior toward behavioral health claims has historically differed from medical claims, with behavioral health facing higher denial rates and more inconsistent adjudication. That makes denial classification and resolution routing more load-bearing here than in specialties where denials are rarer.
- **Session-level billing means one issue can cascade.** A single credentialing lapse or coding error for one provider can simultaneously affect hundreds of claims, since every session that provider delivers gets billed individually. A monitoring system that catches this pattern early is worth far more here than in lower-volume specialties where a single coding mistake might only touch a handful of claims.

These factors compound to make automation more valuable in this specific corner of revenue cycle management than in most other specialties.

## What this would look like in production

This prototype runs on a static CSV, read and processed once per invocation. In production, the input would come from a live connection to the billing system instead of a file. Structured denial data would arrive through 835 file ingestion rather than a manually entered `denial_code` column, which would let denial classification run the moment a denial posts rather than waiting for the next batch run. Claim status for payors with API access would be checked via direct payor portal API queries; for the payors that don't have one (like the regional payor flagged in this dataset), RPA would run the same manual portal check the notes field currently just flags for a person. High-dollar escalations would push real-time Slack alerts to the billing team instead of sitting in a CSV someone has to remember to open, and a dashboard would replace `claim_status.csv` as the system of record for tracking priority queue movement and denial trends over time.
