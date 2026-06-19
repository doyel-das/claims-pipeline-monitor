# Data Dictionary

What every column means, in plain language, across the input file, the outputs, and the run history.

## Input: `sample_claims.csv`

| Column | Meaning |
|---|---|
| `claim_id` | Unique ID for the claim (e.g., `CLM-3007`). |
| `provider_name` | The therapist or provider who delivered the session. |
| `payor_name` | The insurance payor the claim was submitted to (e.g., `Aetna`, `Medicaid`, `Cascade Behavioral Health Network`). |
| `payor_type` | `commercial`, `medicaid`, or `regional`. Regional payors are smaller, local plans that often lack the API/835 integrations larger payors have. |
| `service_date` | The date the therapy session was provided. |
| `submission_date` | The date the claim was submitted to the payor. `days_outstanding` is calculated from this date. |
| `amount` | The dollar amount billed on the claim. |
| `status` | `outstanding` (awaiting payor response), `denied`, `partial_payment` (payor paid part of the claim), or `resubmitted_pending` (a previously denied claim was corrected and resubmitted, now awaiting a new response). |
| `denial_code` | The payor's denial reason code (e.g., `CO-4`, `PR-1`), if the claim was denied. Blank otherwise. |
| `denial_date` | The date the payor denied the claim. Blank if not denied. |
| `partial_payment_amount` | The dollar amount the payor actually paid, if a partial payment was made. Blank otherwise. |
| `outreach_count` | How many follow-up messages have already been sent to the payor about this specific claim. |
| `last_outreach_date` | The date of the most recent follow-up message. Blank if none has been sent yet. |
| `notes` | Free-text context — CPT code, why a claim is in its current state, or operational flags like a payor having no API/835 feed. |

## Output: `claim_status.csv`

Includes every column above, plus:

| Column | Meaning |
|---|---|
| `days_outstanding` | How many days have passed since `submission_date`. |
| `priority_score` | A single number combining age and dollar amount, used to sort the output so the most urgent claims appear first. See "Priority scoring logic" below. |
| `follow-up_stage` | One of `no_action_needed`, `first_followup`, `second_followup`, `third_followup`, `escalation`, or `denied`. See "Follow-up threshold logic" below. |
| `message_subject` / `message_body` | The AI-generated payor follow-up message, if one was generated this run. Blank for claims not yet due for outreach, already contacted today, or denied (denied claims get a denial draft instead). |
| `template_used` | Which follow-up template category was applied (e.g. `template_2_firm_followup_10_business_days`). Blank if no message was generated. |
| `urgency_level` | 1, 2, or 3, matching the template tone. Blank if no message was generated. |
| `denial_category` | The plain-language category of the denial (e.g. `coding_error`, `missing_documentation`), if the claim has a `denial_code`. See "Denial classification system" below. |
| `resolution_path` | The automated path this denial was routed to (e.g. `corrected_claim`, `appeal_review`). |
| `denial_draft_subject` / `denial_draft_body` | The AI-generated resolution draft for the denial — a corrected claim letter, documentation request, appeal framework, or patient billing notice, depending on `resolution_path`. |
| `denial_confidence` | `high`, `medium`, or `low` — how clear-cut the classification is. Always `low` for unrecognized denial codes. |
| `requires_human_review` | `True` if this case needs a person to look at it before anything proceeds. See "What `requires_human_review` means" below. |
| `review_reason` | A short, specific explanation of why human review is required. Empty if `requires_human_review` is `False`. |

## Output: `escalations.csv`

The exact same columns as `claim_status.csv`, but filtered to only the rows where `requires_human_review` is `True`, sorted by `amount` descending instead of by `priority_score`. See "Why escalations.csv is separate" below.

## Run history: `metrics_log.csv`

One row is appended every time the tool runs, so trends can be tracked over time.

| Column | Meaning |
|---|---|
| `timestamp` | When this run happened (UTC). |
| `total_claims` | How many claims were processed in this run. |
| `total_value_outstanding` | The total dollar amount across all outstanding/denied/partial claims processed this run. |
| `followups_generated` | How many payor follow-up messages were generated this run. |
| `denials_classified` | How many denials were classified this run. |
| `denials_auto_routed` | How many of those denials were routed automatically with no human review needed. |
| `denials_requiring_human` | How many of those denials were flagged for human review. |
| `escalations_count` | How many claims required human review this run, for any reason (escalation threshold, denial classification, or partial payment). |
| `high_dollar_escalations` | How many of those escalations were also above `HIGH_DOLLAR_THRESHOLD`. |
| `avg_days_outstanding` | The average `days_outstanding` across all claims processed this run. |
| `dollars_in_escalation` | The total dollar amount tied up in claims that required human review this run. |

## Priority scoring logic — why days and dollars both matter

`priority_score` is calculated as `days_outstanding + (amount * 0.15)`. A claim that has been outstanding a long time represents money that is increasingly unlikely to be collected the longer it sits; a claim with a large dollar amount represents more revenue at stake per claim regardless of age. Sorting by age alone would bury a $720 claim at 45 days behind a $140 claim at 65 days, even though the $720 claim has far more revenue riding on it. Sorting by dollar amount alone would do the opposite — ignore claims that are quietly aging toward write-off. Combining both into one score means a young, high-dollar claim can and should outrank an older, low-dollar one, which is exactly the behavior a billing team wants from a triage queue.

## Follow-up threshold logic — why tone escalates across three templates

A claim's `follow-up_stage` is driven entirely by `days_outstanding` relative to three thresholds (`FIRST_FOLLOWUP_THRESHOLD`, `SECOND_FOLLOWUP_THRESHOLD`, `THIRD_FOLLOWUP_THRESHOLD` — 30, 45, and 60 days by default):

- **first_followup (30+ days)** — Template 1: neutral, informational, simply requesting a status update. Most claims resolve on their own within this window, so there's no reason to escalate tone yet.
- **second_followup (45+ days)** — Template 2: firmer, explicitly requesting a response within 10 business days. A claim still unresolved at this point needs a concrete deadline, not just a nudge.
- **third_followup (60+ days)** — Template 3: direct, referencing the prior outreach attempts that went unanswered, noting that the applicable state prompt payment statute may apply, and signaling that the team will escalate internally if there's still no response.
- **escalation (90+ days)** — past `ESCALATION_THRESHOLD`, a claim is automatically flagged for human review regardless of anything else. By this point, automated outreach alone has clearly not worked.

Tone escalates rather than staying flat because a payor that ignores a polite status request needs a different message than one that's about to get an internal escalation. Sending the same neutral message indefinitely wastes the leverage that a firmer, deadline-bound, statute-referencing message can apply once a claim has genuinely overstayed normal processing time.

## Denial classification system

When a claim has a `denial_code`, it's looked up in the `DENIAL_CODES` table in `config.py`, which maps each code to a category and a resolution path:

| Code | Category | Resolution path | What happens |
|---|---|---|---|
| `CO-4` | coding_error | corrected_claim | A corrected claim cover letter is drafted addressing the specific coding issue. |
| `CO-16` | missing_documentation | documentation_request | A documentation submission letter is drafted listing what needs to be attached. |
| `CO-22` | coordination_of_benefits | patient_followup | An internal note is drafted for the billing team to follow up with the patient about other coverage. |
| `CO-50` | non_covered_service | appeal_review | An appeal letter framework is drafted, with the clinical rationale section left for a human to complete. |
| `CO-97` | bundling_issue | billing_review | An internal billing review note is drafted summarizing the bundling conflict to check. |
| `PR-1` | patient_deductible | patient_billing | A plain-language patient notification draft is generated explaining the deductible amount owed. |
| `PR-2` | patient_coinsurance | patient_billing | Same as above, for coinsurance amounts owed. |
| `OA-23` | timely_filing | appeal_review | An appeal letter framework is drafted, same human-completion requirement as `CO-50`. |

Any code not in this table maps to `unknown` / `human_review`. No resolution draft is generated for unknown codes — the system explicitly states the code wasn't recognized and routes the claim to a person to research and classify manually, rather than guessing at a resolution path that might be wrong.

Appeal drafts (`appeal_review` resolution path) always require human review before submission, regardless of how confident the classification is. The system can produce a structurally correct appeal framework, but it cannot fabricate the clinical rationale that makes an appeal persuasive — that section is explicitly left blank and marked for a human to complete and approve.

## What `requires_human_review` means and every condition that triggers it

`requires_human_review = True` means this case cannot be resolved by automation alone. It is set to `True` whenever any of the following is true:

- The claim has been outstanding more than `ESCALATION_THRESHOLD` (90) days, regardless of anything else.
- The claim's amount is over `HIGH_DOLLAR_THRESHOLD` (500) and it has reached `third_followup` with no response.
- The claim has a `partial_payment_amount` — the disposition of a partial payment (write off the remainder, bill the patient, dispute with the payor) always requires human judgment.
- The claim's denial code is `unknown` (not in `DENIAL_CODES`).
- The claim's denial resolution path is `appeal_review` (every appeal draft requires human completion of the clinical rationale and approval before it can be submitted).

Everything else is handled by automated outreach or automated denial routing, with no human review required.

## Why `escalations.csv` is separate from `claim_status.csv`

`claim_status.csv` is the complete picture — every claim, every stage, useful for trend analysis and revenue forecasting. `escalations.csv` is the action list: only the handful of claims that genuinely need a person's judgment right now, sorted by dollar amount so the billing team sees the highest-revenue cases first. Keeping them separate means a billing team member can open one small file each morning and know they've seen everything that needs their attention, without scrolling past dozens of routine outstanding and auto-routed claims.

## What the metrics log tracks, and why follow-up trigger rate is a better signal than recovery rate

`metrics_log.csv` tracks volume, follow-up activity, denial routing outcomes, and escalation activity over time. The most informative single number in it is `followups_generated` relative to `total_claims` — the **follow-up trigger rate**. This number reflects whether the system is doing its core job: catching outstanding claims at the right moment and acting on them, every run, without anything slipping through.

`Recovery rate` (dollars actually collected divided by dollars billed) sounds like the more obvious success metric, but it's a poor signal for *this specific tool* because it's confounded by factors entirely outside the tool's control — payor-side processing delays, plan-level coverage decisions, patient ability to pay, even seasonal claim volume. A month with a low recovery rate could mean the monitoring and outreach layer failed, or it could simply mean a slow payor quarter that has nothing to do with whether claims were tracked and followed up on correctly. Follow-up trigger rate isolates the one thing this tool actually controls: did every claim that needed action get it, on time. That's why `metrics_log_MOCK.csv` is built to show trigger rate climbing steadily even while escalation count stays flat and the dollar value outstanding per claim shrinks — that combination is the signature of a monitoring system working as intended, independent of how payors happen to behave in any given month.
