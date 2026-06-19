# Entry point: reads outstanding claims from sample_claims.csv, calculates days outstanding
# and a priority score for each, generates AI follow-up outreach for claims due for it,
# classifies denied claims and routes them to a resolution path, writes claim_status.csv and
# escalations.csv, and appends a run summary to metrics_log.csv.
import csv
import os
from datetime import date, datetime, timezone

from config import (
    ESCALATIONS_CSV,
    ESCALATION_THRESHOLD,
    FIRST_FOLLOWUP_THRESHOLD,
    HIGH_DOLLAR_THRESHOLD,
    INPUT_CSV,
    METRICS_LOG_CSV,
    OUTPUT_CSV,
    SECOND_FOLLOWUP_THRESHOLD,
    THIRD_FOLLOWUP_THRESHOLD,
)
from denial_classifier import classify_denial
from followup import generate_followup

TRUTHY = {"true", "1", "yes"}


def is_true(value):
    return str(value).strip().lower() in TRUTHY


def load_claims(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_metrics_log(path, summary):
    file_exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=summary.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(summary)


def days_outstanding_for(submission_date_str, today):
    submitted = datetime.strptime(submission_date_str, "%Y-%m-%d").date()
    return (today - submitted).days


def priority_score_for(days_outstanding, amount):
    # Both age and dollar amount increase priority. The dollar weight is large enough that
    # a young, high-dollar claim can outrank an older, low-dollar one — high-dollar claims
    # are meant to get priority handling, not just wait their turn in the queue.
    return round(days_outstanding + amount * 0.15, 1)


def follow_up_stage_for(row, days_outstanding):
    if row["status"] in ("denied", "partial_payment"):
        return "denied"
    if days_outstanding >= ESCALATION_THRESHOLD:
        return "escalation"
    if days_outstanding >= THIRD_FOLLOWUP_THRESHOLD:
        return "third_followup"
    if days_outstanding >= SECOND_FOLLOWUP_THRESHOLD:
        return "second_followup"
    if days_outstanding >= FIRST_FOLLOWUP_THRESHOLD:
        return "first_followup"
    return "no_action_needed"


def already_contacted_today(row, today):
    last_outreach_date = row.get("last_outreach_date", "").strip()
    if not last_outreach_date:
        return False
    return datetime.strptime(last_outreach_date, "%Y-%m-%d").date() == today


def main():
    today = date.today()
    rows = load_claims(INPUT_CSV)

    output_rows = []
    followups_generated = 0
    denials_classified = 0
    denials_auto_routed = 0
    denials_requiring_human = 0
    total_value_outstanding = 0.0
    days_outstanding_sum = 0

    for row in rows:
        days_outstanding = days_outstanding_for(row["submission_date"], today)
        amount = float(row["amount"])
        priority_score = priority_score_for(days_outstanding, amount)
        follow_up_stage = follow_up_stage_for(row, days_outstanding)

        days_outstanding_sum += days_outstanding
        total_value_outstanding += amount

        message_subject = ""
        message_body = ""
        template_used = ""
        urgency_level = ""
        requires_human_review = False
        review_reason = ""

        needs_outreach = follow_up_stage in (
            "first_followup",
            "second_followup",
            "third_followup",
            "escalation",
        )
        if needs_outreach and not already_contacted_today(row, today):
            claim = {**row, "days_outstanding": days_outstanding, "follow_up_stage": follow_up_stage}
            followup = generate_followup(claim)
            message_subject = followup.message_subject
            message_body = followup.message_body
            template_used = followup.template_used
            urgency_level = followup.urgency_level
            requires_human_review = followup.requires_human_review
            review_reason = followup.review_reason
            followups_generated += 1

        # Automatic escalation past ESCALATION_THRESHOLD applies regardless of any other
        # factor, including whether outreach was already sent today.
        if days_outstanding >= ESCALATION_THRESHOLD:
            requires_human_review = True
            if not review_reason:
                review_reason = f"Outstanding more than {ESCALATION_THRESHOLD} days."

        denial_category = ""
        resolution_path = ""
        denial_draft_subject = ""
        denial_draft_body = ""
        denial_confidence = ""

        denial_code = row.get("denial_code", "").strip()
        if denial_code:
            classification = classify_denial({**row, "denial_code": denial_code})
            denial_category = classification.denial_category
            resolution_path = classification.resolution_path
            denial_draft_subject = classification.draft_message_subject
            denial_draft_body = classification.draft_message_body
            denial_confidence = classification.confidence
            denials_classified += 1
            if classification.requires_human_review:
                requires_human_review = True
                if not review_reason:
                    review_reason = classification.review_reason
                denials_requiring_human += 1
            else:
                denials_auto_routed += 1

        # A partial payment with an unclear disposition always needs a human, independent
        # of what the denial classifier or follow-up generator decided.
        if row.get("partial_payment_amount", "").strip():
            requires_human_review = True
            if not review_reason:
                review_reason = "Partial payment received; disposition unclear."

        output_rows.append({
            **row,
            "days_outstanding": days_outstanding,
            "priority_score": priority_score,
            "follow-up_stage": follow_up_stage,
            "message_subject": message_subject,
            "message_body": message_body,
            "template_used": template_used,
            "urgency_level": urgency_level,
            "denial_category": denial_category,
            "resolution_path": resolution_path,
            "denial_draft_subject": denial_draft_subject,
            "denial_draft_body": denial_draft_body,
            "denial_confidence": denial_confidence,
            "requires_human_review": requires_human_review,
            "review_reason": review_reason,
        })

    output_rows.sort(key=lambda r: r["priority_score"], reverse=True)

    fieldnames = list(rows[0].keys()) + [
        "days_outstanding",
        "priority_score",
        "follow-up_stage",
        "message_subject",
        "message_body",
        "template_used",
        "urgency_level",
        "denial_category",
        "resolution_path",
        "denial_draft_subject",
        "denial_draft_body",
        "denial_confidence",
        "requires_human_review",
        "review_reason",
    ]
    write_csv(OUTPUT_CSV, output_rows, fieldnames)

    escalation_rows = [r for r in output_rows if is_true(r["requires_human_review"])]
    escalation_rows.sort(key=lambda r: float(r["amount"]), reverse=True)
    write_csv(ESCALATIONS_CSV, escalation_rows, fieldnames)

    high_dollar_escalations = sum(
        1 for r in escalation_rows if float(r["amount"]) > HIGH_DOLLAR_THRESHOLD
    )
    dollars_in_escalation = sum(float(r["amount"]) for r in escalation_rows)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_claims": len(output_rows),
        "total_value_outstanding": round(total_value_outstanding, 2),
        "followups_generated": followups_generated,
        "denials_classified": denials_classified,
        "denials_auto_routed": denials_auto_routed,
        "denials_requiring_human": denials_requiring_human,
        "escalations_count": len(escalation_rows),
        "high_dollar_escalations": high_dollar_escalations,
        "avg_days_outstanding": round(days_outstanding_sum / len(output_rows), 1),
        "dollars_in_escalation": round(dollars_in_escalation, 2),
    }
    append_metrics_log(METRICS_LOG_CSV, summary)

    print(f"Processed {summary['total_claims']} claims -> {OUTPUT_CSV}")
    print(f"Total value outstanding: ${summary['total_value_outstanding']:.2f}")
    print(f"Follow-up messages generated: {summary['followups_generated']}")
    print(
        f"Denials classified: {summary['denials_classified']} "
        f"(auto-routed: {summary['denials_auto_routed']}, "
        f"requiring human: {summary['denials_requiring_human']})"
    )
    print(
        f"Escalations requiring human review: {summary['escalations_count']} -> {ESCALATIONS_CSV} "
        f"(${summary['dollars_in_escalation']:.2f}, "
        f"{summary['high_dollar_escalations']} high-dollar)"
    )
    print(f"Average days outstanding: {summary['avg_days_outstanding']}")


if __name__ == "__main__":
    main()
