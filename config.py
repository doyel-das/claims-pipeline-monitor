# Central configuration: model name, file paths, follow-up/escalation thresholds, and the
# denial code lookup table. ANTHROPIC_API_KEY is read automatically from the environment by
# anthropic.Anthropic().
MODEL = "claude-sonnet-4-6"

INPUT_CSV = "sample_claims.csv"
OUTPUT_CSV = "claim_status.csv"
ESCALATIONS_CSV = "escalations.csv"
METRICS_LOG_CSV = "metrics_log.csv"

# Days outstanding (from submission_date) before each follow-up stage applies.
FIRST_FOLLOWUP_THRESHOLD = 30
SECOND_FOLLOWUP_THRESHOLD = 45
THIRD_FOLLOWUP_THRESHOLD = 60

# Days outstanding after which a claim is automatically escalated to a human, regardless
# of dollar amount, follow-up history, or any other factor.
ESCALATION_THRESHOLD = 90

# Claims above this dollar amount get priority handling — a larger weight in the priority
# score and a human-review trigger if a high-dollar claim hits the third follow-up with
# no response.
HIGH_DOLLAR_THRESHOLD = 500

# Maps each denial reason code to its plain-language category and the automated resolution
# path it should be routed to. Any code not in this dictionary maps to "unknown" /
# "human_review" and is always flagged for a person.
DENIAL_CODES = {
    "CO-4": {"category": "coding_error", "resolution_path": "corrected_claim"},
    "CO-16": {"category": "missing_documentation", "resolution_path": "documentation_request"},
    "CO-22": {"category": "coordination_of_benefits", "resolution_path": "patient_followup"},
    "CO-50": {"category": "non_covered_service", "resolution_path": "appeal_review"},
    "CO-97": {"category": "bundling_issue", "resolution_path": "billing_review"},
    "PR-1": {"category": "patient_deductible", "resolution_path": "patient_billing"},
    "PR-2": {"category": "patient_coinsurance", "resolution_path": "patient_billing"},
    "OA-23": {"category": "timely_filing", "resolution_path": "appeal_review"},
}

UNKNOWN_DENIAL = {"category": "unknown", "resolution_path": "human_review"}
