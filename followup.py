# Sends each claim that needs outreach today to the Claude API with the claim record and
# the follow-up stage that applies, and returns a structured payor follow-up message plus a
# human-review flag.
import anthropic
from pydantic import BaseModel

from config import ESCALATION_THRESHOLD, HIGH_DOLLAR_THRESHOLD, MODEL

client = anthropic.Anthropic()

FOLLOWUP_PROMPT = """You are an AI assistant for the billing team at a mental healthcare \
platform that connects patients, therapists, and insurance payors. Generate a professional \
follow-up message to an insurance payor about an outstanding claim. The message must be \
factual, professional, and reference the specific claim details provided. Never fabricate \
policy details. Never make legal threats.

Claim ID: {claim_id}
Provider: {provider_name}
Payor: {payor_name} ({payor_type})
Service date: {service_date}
Submission date: {submission_date}
Amount: ${amount}
Days outstanding: {days_outstanding}
Follow-up stage: {follow_up_stage}
Prior outreach attempts: {outreach_count}
Notes: {notes}

Tone escalates across three templates depending on follow-up stage:
- Template 1 (first_followup): neutral and informational, simply requesting a status update.
- Template 2 (second_followup): firmer, explicitly requesting a response within 10 business \
days.
- Template 3 (third_followup): direct, referencing the prior outreach attempts that went \
unanswered and signaling escalation. On third follow-up only, reference that the applicable \
state prompt payment statute may apply and that the team will be escalating internally if no \
response is received. Do not cite a specific statute number or state — refer to it generally \
as "the applicable state prompt payment statute."

Set template_used to a short string identifying which template category was applied (e.g. \
"template_1_initial_status_request", "template_2_firm_followup_10_business_days", \
"template_3_final_notice_escalation_reference"). Set urgency_level to 1 for template 1, 2 for \
template 2, or 3 for template 3.

Decide if this case requires human review before the message is sent, and if so, give a short \
reason in review_reason. Set requires_human_review to true if any of these apply: the claim's \
amount is over ${high_dollar_threshold} and this is the third follow-up with no response, the \
claim has been outstanding more than {escalation_threshold} days, or there is a partial \
payment on this claim where the disposition is unclear. Otherwise set requires_human_review to \
false and leave review_reason empty.
"""


class FollowupMessage(BaseModel):
    message_subject: str
    message_body: str
    template_used: str
    urgency_level: int
    requires_human_review: bool
    review_reason: str


def generate_followup(claim: dict) -> FollowupMessage:
    prompt = FOLLOWUP_PROMPT.format(
        **claim,
        high_dollar_threshold=HIGH_DOLLAR_THRESHOLD,
        escalation_threshold=ESCALATION_THRESHOLD,
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        output_format=FollowupMessage,
    )
    message = response.parsed_output

    # Enforce the deterministic human-review rules in code rather than trusting the model
    # alone — the escalation threshold and high-dollar third-follow-up rule must always
    # trigger, no exceptions.
    amount = float(claim["amount"])
    days_outstanding = int(claim["days_outstanding"])
    partial_payment = str(claim.get("partial_payment_amount", "")).strip()

    if (
        days_outstanding > ESCALATION_THRESHOLD
        or (amount > HIGH_DOLLAR_THRESHOLD and claim["follow_up_stage"] == "third_followup")
        or partial_payment
    ):
        message.requires_human_review = True
        if not message.review_reason:
            if days_outstanding > ESCALATION_THRESHOLD:
                message.review_reason = f"Outstanding more than {ESCALATION_THRESHOLD} days."
            elif partial_payment:
                message.review_reason = "Partial payment received; disposition unclear."
            else:
                message.review_reason = "High-dollar claim at third follow-up with no response."

    return message
