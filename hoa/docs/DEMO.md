# HOA Scripted Demo

This document outlines the 10-step demo script for the Healthcare Operations Assistant (HOA). The data for this demo is deterministically seeded by `make demo-reset` (or `make demo-data`).

## Setup

Before presenting:
1. Run `make demo-reset` to get a clean slate (takes < 20 seconds).
2. Open the frontend at `http://localhost:5173`.
3. Keep the Admin Dashboard open in another window (`http://localhost:5173/admin`, login as `admin@demo`).

## Demo Script

### Step 1: Grounded Answer
**Role:** Billing (`billing@demo`)
**Action:** Ask a routine policy question.
**Input:** "What is the policy for out-of-network insurers?"
**Expected:** The AI answers accurately (Outcome: `ANSWER`), citing the specific policy document from the knowledge base.

### Step 2: Guided MRI Workflow
**Role:** Radiology (`radiology@demo`)
**Action:** Start a pre-authorization workflow.
**Input:** "I need to check pre-authorization requirements for an MRI scan."
**Expected:** The AI recognizes the intent and initiates the `W-001` workflow (Outcome: `GUIDE`), prompting the user for missing required fields (e.g., patient MRN, insurer).

### Step 3: Honest Uncertainty & Gap Capture
**Role:** Insurance/TPA (`insurance@demo`)
**Action:** Ask about a highly specific, undocumented scenario.
**Input:** "Does our specific TPA contract cover experimental gene therapies?"
**Expected:** The AI's confidence falls below the medium band (Outcome: `ROUTE`). It admits it doesn't know and routes the query to a human, automatically tagging it as a knowledge gap (`is_gap=True`).

### Step 4: Gap Closes & Answered
**Role:** Admin (`admin@demo`) / Insurance/TPA (`insurance@demo`)
**Action:** In the Admin Dashboard, go to Knowledge > Gaps. Resolve the gap from Step 3 into a new article. Then, re-ask the question as the Insurance user.
**Input:** (Same question as Step 3)
**Expected:** The FSM now has the knowledge. It provides a confident `ANSWER` using the newly approved article.

### Step 5: Specimen Rejection Route
**Role:** Lab (`lab@demo`)
**Action:** Report a critical operational issue that requires human intervention.
**Input:** "Lab rejected blood specimen due to hemolysis, what is the protocol?"
**Expected:** The AI identifies the `lab_rejection` intent and applies a routing rule (Outcome: `ROUTE`), creating a high-urgency ticket for the Lab team.

### Step 6: Clinical Refusal
**Role:** Discharge (`discharge@demo`)
**Action:** Ask a clinical/medical question.
**Input:** "Should I increase the patient's digoxin dosage from 125mcg to 250mcg daily?"
**Expected:** The Guard rail triggers (Outcome: `REFUSE`). The AI refuses to answer clinical questions and advises consulting a physician.

### Step 7: Persona / Role-Based Access
**Role:** Billing (`billing@demo`) and Billing Supervisor (`billing.super@demo`)
**Action:** Ask a question that requires supervisor privileges.
**Input:** "Can I approve a $5000 discharge billing write-off?"
**Expected:**
- **As Billing:** The AI provides general guidance or routes it.
- **As Billing Supervisor:** The AI answers based on the supervisor-specific knowledge (which is only retrievable if `active_dept_role` includes supervisor).

### Step 8: Change Impact Analysis
**Role:** Admin (`admin@demo`)
**Action:** In the Admin Dashboard, view the graph impact for a specific node (e.g., a policy document).
**Expected:** The system shows all workflows and articles affected by changes to this node via graph backlinks.

### Step 9: Kill the LLM (Template Fallback)
**Role:** Front Office (`frontoffice@demo`)
**Action:** Simulate an LLM outage. (Stop the LLM service or set `LLM_PROVIDER=template` in `.env`). Ask a routine question.
**Input:** "How do I process a visitor pass?"
**Expected:** The system gracefully falls back to the deterministic FSM (`mode="template"`). It still provides a correct `ANSWER` (or `ROUTE` if uncertain), ensuring 100% uptime for core flows.

### Step 10: Audit Tampering Verification
**Role:** Admin (`admin@demo`)
**Action:** Tamper with an audit row in the database directly (e.g., via `psql` or a script), modifying the `outcome` or `text`. Then check the Admin Audit view.
**Expected:** The Audit module detects the HMAC mismatch and highlights the tampered row as invalid.
