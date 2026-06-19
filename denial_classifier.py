# Sends each newly-denied claim to the Claude API with its denial code and the category /
# resolution path looked up from config.DENIAL_CODES, and returns a structured classification
# plus a draft resolution message.
import anthropic
from pydantic import BaseModel

from config import DENIAL_CODES, MODEL, UNKNOWN_DENIAL

client = anthropic.Anthropic()

CLASSIFIER_PROMPT = """You are an AI assistant for the billing team at a mental healthcare \
platform. A claim has been denied by an insurance payor. Classify the denial and generate an \
appropriate resolution draft. Use the denial code to determine the category and resolution \
path. Never fabricate clinical details.

Claim ID: {claim_id}
Provider: {provider_name}
Payor: {payor_name} ({payor_type})
Service date: {service_date}
Amount: ${amount}
Denial code: {denial_code}
Denial date: {denial_date}
Looked-up category: {category}
Looked-up resolution path: {resolution_path}
Notes: {notes}

Generate the draft according to the resolution path:
- corrected_claim: generate a corrected claim cover letter addressing the specific coding \
issue.
- documentation_request: generate a documentation submission letter listing what supporting \
documentation should be attached.
- appeal_review: generate an appeal letter framework. Clearly mark in the draft body that a \
human must complete the clinical rationale section before this can be submitted — do not \
fabricate clinical rationale yourself.
- patient_billing: generate a patient notification draft explaining the patient responsibility \
amount, written in plain, non-alarming language.
- billing_review or patient_followup: generate a short internal billing review note \
summarizing what needs to be checked or who needs to be contacted.
- human_review (unknown/unrecognized denial code): do not attempt to generate a resolution \
draft. Set draft_message_subject and draft_message_body to short strings stating that this \
denial code is not recognized and requires manual classification by the billing team.

Set confidence to "high", "medium", or "low" based on how clear-cut this denial is. Set \
confidence to "low" and requires_human_review to true for any unknown or complex denial code. \
Appeal drafts (appeal_review resolution path) always require human review before submission — \
set requires_human_review to true and explain in review_reason that a human must complete the \
clinical rationale and approve before sending. For all other resolution paths, set \
requires_human_review to false unless something about this specific claim makes it genuinely \
ambiguous, in which case explain why in review_reason.
"""


class DenialClassification(BaseModel):
    denial_category: str
    resolution_path: str
    draft_message_subject: str
    draft_message_body: str
    confidence: str
    requires_human_review: bool
    review_reason: str


def classify_denial(claim: dict) -> DenialClassification:
    lookup = DENIAL_CODES.get(claim["denial_code"], UNKNOWN_DENIAL)
    prompt = CLASSIFIER_PROMPT.format(
        **claim,
        category=lookup["category"],
        resolution_path=lookup["resolution_path"],
    )
    response = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
        output_format=DenialClassification,
    )
    classification = response.parsed_output

    # Enforce the deterministic rules in code rather than trusting the model alone — unknown
    # codes and appeal drafts must always route to a human, no exceptions.
    if lookup is UNKNOWN_DENIAL:
        classification.denial_category = "unknown"
        classification.resolution_path = "human_review"
        classification.confidence = "low"
        classification.requires_human_review = True
        if not classification.review_reason:
            classification.review_reason = (
                f"Denial code {claim['denial_code']} is not recognized and requires manual "
                "classification by the billing team."
            )
    elif lookup["resolution_path"] == "appeal_review":
        classification.requires_human_review = True
        if not classification.review_reason:
            classification.review_reason = (
                "Appeal draft requires human completion of the clinical rationale section "
                "and approval before submission."
            )

    return classification
