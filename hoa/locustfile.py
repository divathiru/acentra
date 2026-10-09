"""
Locust load test file for Healthcare Operations Assistant.
"""

from locust import HttpUser, task, between
import random

QUERIES = [
    "What is the policy for patient admission?",
    "I need prior authorization for an MRI scan for patient MRN-998877.",
    "Should I increase the patient's digoxin dosage from 125mcg to 250mcg daily?",
    "How long do we have to submit a claim after discharge?",
    "What is the visiting hours policy?",
]

class HOAUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def ask_chat(self):
        query = random.choice(QUERIES)
        self.client.post("/chat", json={
            "query": query,
            "user_id": f"locust-user-{random.randint(1, 1000)}",
            "dept_role": "ALL",
        })
