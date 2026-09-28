from laya import Router

router = Router(preload=True)

state = {
    "body": "I was charged twice. Please refund the duplicate."
}

questions = {
    "department": {
        "type": "choice",
        "instructions": "Which department should handle this?",
        "criteria": {
            "billing": "payments and refunds",
            "technical": "bugs and outages"
        }
    },
    "refund_requested": {
        "type": "noul",
        "instructions": "Does the user explicitly request a refund?"
    }
}

result = router.predict(state, questions)
print(result)