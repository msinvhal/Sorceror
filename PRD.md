# Sorceror PRD

## High-Level Product Description

Sorceror is an **AI-native sourcing engine that identifies high-relevance connections using shared context and generates personalized outreach — going beyond firmographic filters to enable high-conversion outbound.**

---

## ✨ Context

Outbound sourcing today is fragmented and inefficient.

Existing tools optimize for:

* contact retrieval
* email enrichment

But they do NOT solve:

* expressing nuanced intent (e.g., “AI founders in SF Berkeley grads”)
* identifying who is actually worth reaching out to
* explaining why someone is relevant
* generating personalized outreach

Users rely on:

* manual Google searches
* LinkedIn browsing
* intuition-based filtering

This leads to:

* inconsistent results
* low-quality outreach
* high effort

LLMs now enable:

* natural language intent understanding
* contextual reasoning
* structured generation

This creates an opportunity for an **AI-native sourcing + personalization workflow**.

---

## ✨ Problem

Users need to convert vague intent into a **shortlist of high-quality, real, contactable people**.

Current limitations:

* rigid filters (cannot express nuanced intent)
* unranked results
* no reasoning
* manual candidate selection

Current workflow:

1. Search manually
2. Click through multiple pages
3. Compile candidates
4. Guess relevance

→ Slow, manual, inconsistent

---

## ✨ User Profile

* Early-career operators (PMs, founders, event organizers)
* Running outbound workflows (e.g., sourcing conference speakers)
* Need **real, contactable people**, not large lists
* Limited time → high need for precision

Key insight:
👉 Success depends on **relevance + shared context**, not just title

---

## ✨ Solution

Sorceror converts:

> natural language query → real candidate discovery → ranking → user selection → (optional) outreach generation

---

## ✨ Northstar / Objective

Given a natural language query, return **10–20 real, relevant, contactable candidates with clear reasoning in under 2 minutes.**

---

## ✨ Design Requirements

* Clean, minimal UI
* Single input box (primary interaction)
* Button: “Find Candidates”

### Output UI:

Each result includes:

* name
* role
* company
* LinkedIn URL (required for inclusion if identifiable)
* fit_score
* why_relevant

### Interaction (V2+):

* Accept / Reject toggle per candidate

### States:

* loading
* no results
* error

---

# ✨ V1 Solution (Discovery Only)

### Input

Natural language query

Example:
“AI founders in SF Berkeley grads”

---

### Output (UI + CSV)

* First Name
* Last Name
* Company
* Title
* LinkedIn URL
* Fit Score (1–10)
* Why Relevant

---

### Core Features

### 1. LLM-Guided Candidate Discovery (CORE)

Pipeline:

Query
→ LLM generates search queries
→ system retrieves search results (titles, snippets, links)
→ extract candidate mentions
→ LLM structures candidate profiles

Constraints:

* use only publicly available data
* no login-based sources
* no deep scraping

Fallback:

* expand search queries
* relax constraints if needed

---

### 2. Candidate Structuring

LLM converts raw search results into:

* name
* role
* company
* LinkedIn (if identifiable)

Only include candidates with sufficient identifiable information.

---

### 3. Deterministic Ranking Engine (CORE)

Score candidates using:

* +4 → role match
* +3 → domain match
* +2 → location match
* +2 → shared context (e.g., university)

Normalize to 1–10

Rules:

* deterministic
* consistent
* explainable

---

### 4. LLM Enrichment

Generate:

* **why_relevant**

  * 1–2 sentences
  * grounded in real attributes

---

### 5. Result Filtering

* prioritize candidates with LinkedIn
* return top 10–20 candidates only

---

### 6. CSV Export

Export includes:

* First Name
* Last Name
* Company
* Title
* LinkedIn URL
* Fit Score
* Why Relevant

Designed for upload into tools like Apollo or Hunter for email enrichment.

---

## ✨ Engineering Requirements (V1)

* Accept natural language query input
* Generate search queries using LLM
* Retrieve search results (titles, snippets, links)
* Extract candidate mentions
* Structure candidates using LLM
* Implement deterministic scoring function
* Rank candidates
* Select top 10–20 candidates
* Generate why_relevant
* Return structured response
* Export CSV
* Build minimal UI

---

# ✨ V2 Solution (Selection Layer)

* Add Accept / Reject interaction per candidate
* Allow user to curate shortlist
* Export only accepted candidates

Goal:
Improve precision and reduce noise before outreach

---

# ✨ V3 Solution (Outreach)

* Add user profile input:

  * name
  * role
  * goal

* Generate personalized outreach messages using:

  * candidate info
  * query
  * user profile

Triggered only after user selection.

---

## ✨ Product Constraints

* Personal portfolio project (not production-scale)
* Must work independently without explanation
* Must be low-cost (target: ~$0–$5 total usage)
* Will not be deployed at scale

### Cost Strategy

* Minimize LLM calls:

  * only generate why_relevant for top results
  * generate outreach only in V3 and only on demand

* Avoid:

  * paid data sources
  * heavy scraping
  * large pipelines

Design implications:

* prioritize simplicity
* limit results to 10–20
* optimize for output quality over scale

---

## ✨ QA Checklist

* Query returns real, identifiable candidates
* Results are relevant and ranked correctly
* why_relevant is specific and accurate
* CSV export works
* system handles weak/no results gracefully

---

## ✨ Success Criteria

* User can input a query and receive usable candidates in <2 minutes
* Results include real, contactable people
* Output is immediately usable for outreach workflows
* Tool works without explanation


