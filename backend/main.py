import asyncio
import csv
import io
import json
import logging
import os

from google import genai
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
MODEL = "gemini-2.5-flash"

# In-memory cache for last search result (single-user portfolio tool)
last_results: list[dict] = []


# ---------- Pydantic models ----------

class UserProfile(BaseModel):
    name: str = ""
    company: str = ""
    role: str = ""
    school: str = ""
    location: str = ""
    hiring_context: str = ""


class SearchRequest(BaseModel):
    query: str
    user_profile: UserProfile | None = None


class MessageRequest(BaseModel):
    candidate: dict
    query: str
    user_profile: UserProfile | None = None


class Candidate(BaseModel):
    first_name: str
    last_name: str
    company: str
    role: str
    location: str
    linkedin_url: str | None = None
    fit_score: int
    about: str
    why_relevant: str


class SearchResponse(BaseModel):
    candidates: list[Candidate]
    count: int


# ---------- LLM helpers ----------

def llm(prompt: str, label: str = "LLM") -> str:
    log.info("=== %s PROMPT ===\n%s\n=== END PROMPT ===", label, prompt)
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(model=MODEL, contents=prompt)
    result = response.text.strip()
    log.info("=== %s RESPONSE ===\n%s\n=== END RESPONSE ===", label, result)
    return result


def parse_json(text: str) -> any:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        inner = text[start + 3:end]
        if inner.startswith("json"):
            inner = inner[4:]
        text = inner.strip()
    return json.loads(text)


# ---------- Pipeline steps ----------

def parse_intent_and_queries(query: str, user_profile: dict | None = None) -> tuple[dict, list[str]]:
    """Single LLM call: parse search intent AND generate 5 targeted queries."""
    profile_context = ""
    if user_profile:
        profile_context = f"""
Searcher profile (use to bias queries toward shared context):
- Name: {user_profile.get('name', '')}
- Company: {user_profile.get('company', '')}
- Role: {user_profile.get('role', '')}
- School: {user_profile.get('school', '')}
- Location: {user_profile.get('location', '')}
- Looking for: {user_profile.get('hiring_context', '')}
"""

    prompt = f"""Analyze this people-search query and return a JSON object.

Query: "{query}"
{profile_context}
Extract the key criteria from the query (company, role, school, location, etc.) and generate 5 highly targeted search queries to find real LinkedIn profiles matching ALL criteria.

Return exactly this structure:
{{
  "intent": {{
    "company": ["Mercor"],
    "role_keywords": ["product manager", "program manager"],
    "education": ["UC Berkeley", "University of California Berkeley"],
    "location": []
  }},
  "search_queries": [
    "site:linkedin.com/in Mercor \\"product manager\\" \\"UC Berkeley\\"",
    "site:linkedin.com/in Mercor \\"program manager\\" Berkeley",
    "site:linkedin.com/in Mercor \\"UC Berkeley\\" PM",
    "Mercor product manager UC Berkeley linkedin",
    "Mercor program manager Berkeley alumni linkedin"
  ]
}}

Rules for search_queries:
- Generate exactly 5 queries
- At least 3 must use site:linkedin.com/in
- Each query must include ALL key criteria from the original query (company name, role, school, etc.)
- Use exact company name and role terms as they would appear on a LinkedIn profile
- Do NOT generate generic queries — every query must be specific to this exact search

Return only valid JSON, no explanation."""
    result = parse_json(llm(prompt, "INTENT+QUERIES"))
    log.info("Generated queries: %s", result.get("search_queries", []))
    return result.get("intent", {}), result.get("search_queries", [])


async def fetch_results(queries: list[str]) -> list[dict]:
    async def fetch_one(query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": 10},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("organic", []):
                link = r.get("link", "")
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "link": link,
                    "is_linkedin_profile": "linkedin.com/in/" in link,
                })
            return results

    all_results = await asyncio.gather(*[fetch_one(q) for q in queries])
    seen = set()
    flat = []
    for batch in all_results:
        for r in batch:
            if r["link"] not in seen:
                seen.add(r["link"])
                flat.append(r)
    linkedin_results = [r for r in flat if r["is_linkedin_profile"]]
    other_results = [r for r in flat if not r["is_linkedin_profile"]]
    combined = (linkedin_results + other_results)[:60]
    log.info("Fetched %d total results (%d LinkedIn profiles, %d other)", len(combined), len(linkedin_results), len(other_results))
    for r in combined:
        log.info("  [%s] %s | %s", "LI" if r["is_linkedin_profile"] else "--", r["title"], r["link"])
    return combined


def extract_candidates(results: list[dict], query: str) -> list[dict]:
    snippets = "\n".join(
        f"[{i+1}] {'[LINKEDIN PROFILE] ' if r['is_linkedin_profile'] else ''}{r['title']} | {r['snippet']} | {r['link']}"
        for i, r in enumerate(results)
    )
    prompt = f"""Extract real, named individuals from these search results who match: "{query}"

Search results:
{snippets}

For each person, return a JSON array with:
{{
  "first_name": "Jane",
  "last_name": "Smith",
  "role": "Product Manager",
  "company": "Mercor",
  "linkedin_url": "https://linkedin.com/in/janesmith or null",
  "location": "San Francisco, CA",
  "background_notes": "UC Berkeley grad, PM at Mercor since 2022"
}}

Critical rules:
- If the query names a specific company, only include people at that company. If no company is specified, extract anyone who matches the other criteria (role, education, location, domain).
- Be INCLUSIVE — extract anyone who plausibly matches. The scoring step will rank and filter. Aim for at least 15 raw candidates so the final step can pick the best 10.
- For results marked [LINKEDIN PROFILE]:
  * The link IS the linkedin_url — always set it
  * Parse "Full Name - Current Title at Current Company | LinkedIn" from the title
  * Extract school, current role, company from the snippet into background_notes
- If a person appears in multiple results, merge into one entry with the most complete info
- Return between 15 and 30 candidates — never fewer than 15 if the results contain that many people
- Return only a valid JSON array, no explanation"""
    raw = parse_json(llm(prompt, "EXTRACT_CANDIDATES"))
    if not isinstance(raw, list):
        return []
    log.info("Extracted %d raw candidates", len(raw))
    return raw[:30]  # enrich step will score and pick top 10


def enrich_candidates(candidates: list[dict], query: str, intent: dict, user_profile: dict | None = None) -> list[dict]:
    """Single LLM call: score each candidate, write about, write why_relevant."""
    candidates_text = json.dumps(
        [{"name": f"{c['first_name']} {c['last_name']}", "role": c.get("role", ""),
          "company": c.get("company", ""), "location": c.get("location", ""),
          "background": c.get("background_notes", ""), "linkedin": bool(c.get("linkedin_url"))}
         for c in candidates],
        indent=2,
    )
    profile_context = ""
    if user_profile:
        profile_context = f"""
Searcher profile (boost candidates who share background with the searcher):
- School: {user_profile.get('school', '')}
- Company: {user_profile.get('company', '')}
- Looking for: {user_profile.get('hiring_context', '')}
"""

    prompt = f"""Evaluate these candidates against the search query and criteria.

Query: "{query}"
Criteria: {json.dumps(intent)}
{profile_context}

Candidates:
{candidates_text}

For each candidate return a JSON array (same order) with:
{{
  "fit_score": 8,
  "about": "Co-Founder & CEO of Acme AI (2021), UC Berkeley CS grad, prev. Google Brain.",
  "why_relevant": "Founded an AI startup in 2021 as a UC Berkeley alumnus, directly matching the query criteria."
}}

Scoring (1-10):
- 8-10: Clearly matches all major criteria in the query
- 5-7: Matches most criteria; some uncertainty or missing info
- 1-4: Weak match, wrong field, or missing key criteria

about: one sentence — their current role + company + the most relevant background fact.
why_relevant: 1-2 sentences — specific to why THEY match THIS query.

IMPORTANT: You MUST return one entry for every single candidate in the list, in the same order. Do not skip any candidates.

Return only a valid JSON array, no explanation."""
    enrichments = parse_json(llm(prompt, "ENRICH_CANDIDATES"))

    for i, c in enumerate(candidates):
        if i < len(enrichments):
            c["fit_score"] = max(1, min(10, int(enrichments[i].get("fit_score", 1))))
            c["about"] = enrichments[i].get("about", "")
            c["why_relevant"] = enrichments[i].get("why_relevant", "")
        else:
            c["fit_score"] = 1
            c["about"] = ""
            c["why_relevant"] = ""
    return candidates


# ---------- Endpoints ----------

@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    global last_results

    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    if not SERPER_API_KEY or SERPER_API_KEY == "your_serper_api_key_here":
        raise HTTPException(status_code=500, detail="SERPER_API_KEY not configured")

    profile_dict = req.user_profile.model_dump() if req.user_profile else None

    # Step 1: parse intent + generate queries (1 LLM call)
    intent, queries = parse_intent_and_queries(req.query, profile_dict)

    # Step 2: fetch results in parallel
    results = await fetch_results(queries)

    if not results:
        return SearchResponse(candidates=[], count=0)

    # Step 3: extract candidates
    raw_candidates = extract_candidates(results, req.query)

    if not raw_candidates:
        return SearchResponse(candidates=[], count=0)

    # Step 4: score + enrich all candidates (1 LLM call)
    enriched = enrich_candidates(raw_candidates, req.query, intent, profile_dict)

    # Sort by score, drop below 4, cap at 10
    ranked = sorted(enriched, key=lambda c: c.get("fit_score", 1), reverse=True)
    ranked = [c for c in ranked if c.get("fit_score", 1) >= 4][:10]
    log.info("Final ranked candidates: %s", [(f"{c.get('first_name')} {c.get('last_name')}", c.get('fit_score')) for c in ranked])

    candidates = []
    for c in ranked:
        candidates.append(Candidate(
            first_name=c.get("first_name") or "",
            last_name=c.get("last_name") or "",
            company=c.get("company") or "",
            role=c.get("role") or "",
            location=c.get("location") or "",
            linkedin_url=c.get("linkedin_url") or None,
            fit_score=c.get("fit_score") or 1,
            about=c.get("about") or "",
            why_relevant=c.get("why_relevant") or "",
        ))

    last_results = [c.model_dump() for c in candidates]
    return SearchResponse(candidates=candidates, count=len(candidates))


@app.post("/generate-message")
async def generate_message(req: MessageRequest):
    c = req.candidate
    p = req.user_profile or UserProfile()
    prompt = f"""Write a short, personalized LinkedIn DM from {p.name or 'the sender'} to {c.get('first_name', '')} {c.get('last_name', '')}.

Sender profile:
- Name: {p.name}
- Role: {p.role} at {p.company}
- School: {p.school}
- Location: {p.location}
- Why reaching out: {p.hiring_context}

Recipient profile:
- Name: {c.get('first_name', '')} {c.get('last_name', '')}
- Role: {c.get('role', '')} at {c.get('company', '')}
- Location: {c.get('location', '')}
- Background: {c.get('about', '')}

Original search context: "{req.query}"

Write a LinkedIn DM that:
- Opens with a genuine, specific hook (shared school, mutual background, or specific thing about their work) — NOT a generic opener
- Is warm and human, not recruiter-speak
- Mentions who the sender is and why they're reaching out in 1 sentence
- Ends with a simple, low-pressure ask (quick chat, 15 min call)
- Is 80-100 words total — short enough to actually get read

Return only the message text, no subject line, no explanation."""

    message = llm(prompt, "GENERATE_MESSAGE")
    return {"message": message}


@app.get("/export")
def export_csv():
    if not last_results:
        raise HTTPException(status_code=404, detail="No results to export. Run a search first.")

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["first_name", "last_name", "company", "role", "location", "linkedin_url", "fit_score", "about", "why_relevant"],
    )
    writer.writeheader()
    writer.writerows(last_results)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sorceror_candidates.csv"},
    )
