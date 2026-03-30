import asyncio
import csv
import io
import json
import os

from google import genai
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

class SearchRequest(BaseModel):
    query: str


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

def llm(prompt: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(model=MODEL, contents=prompt)
    return response.text.strip()


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

def parse_intent_and_queries(query: str) -> tuple[dict, list[str]]:
    """Single LLM call: parse search intent AND generate 5 targeted queries."""
    prompt = f"""Analyze this people-search query and return a JSON object.

Query: "{query}"

Return exactly this structure:
{{
  "intent": {{
    "role_keywords": ["founder", "co-founder", "CEO"],
    "domain": ["AI", "machine learning", "artificial intelligence"],
    "location": ["San Francisco", "Bay Area"],
    "shared_context": ["UC Berkeley", "Berkeley", "Cal"]
  }},
  "search_queries": [
    "site:linkedin.com/in UC Berkeley founder AI startup",
    "site:linkedin.com/in Berkeley grad co-founder artificial intelligence",
    "site:linkedin.com/in Berkeley alumni AI company founder CEO",
    "UC Berkeley graduate founded AI startup Forbes 30 under 30",
    "Berkeley alum AI startup founder TechCrunch"
  ]
}}

For search_queries:
- Generate exactly 5 queries
- At least 3 must use site:linkedin.com to find LinkedIn profiles
- Focus on finding real, named individuals (not companies or articles)
- Be specific to the search criteria in the query
- For queries with site:linkedin.com, use keywords that appear in LinkedIn bio/headline

Return only valid JSON, no explanation."""
    result = parse_json(llm(prompt))
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
    # Prioritize LinkedIn profile results
    linkedin_results = [r for r in flat if r["is_linkedin_profile"]]
    other_results = [r for r in flat if not r["is_linkedin_profile"]]
    return (linkedin_results + other_results)[:60]


def extract_candidates(results: list[dict], query: str) -> list[dict]:
    snippets = "\n".join(
        f"[{i+1}] {'[LINKEDIN PROFILE] ' if r['is_linkedin_profile'] else ''}{r['title']} | {r['snippet']} | {r['link']}"
        for i, r in enumerate(results)
    )
    prompt = f"""Extract real, named individuals from these search results who could match: "{query}"

Search results:
{snippets}

For every person you can identify by name, return a JSON array with:
{{
  "first_name": "Jane",
  "last_name": "Smith",
  "role": "Co-Founder & CEO",
  "company": "Acme AI",
  "linkedin_url": "https://linkedin.com/in/janesmith or null",
  "location": "San Francisco, CA",
  "background_notes": "UC Berkeley grad, founded AI company in 2021, background in ML"
}}

Critical rules:
- Be INCLUSIVE — extract anyone who might be relevant. Include partial matches.
- For results marked [LINKEDIN PROFILE]:
  * The link IS the linkedin_url — always set it
  * The title format is usually "Full Name - Current Title at Current Company | LinkedIn" — parse this to get role and company
  * The snippet often contains their bio, school, previous experience — extract all of it into background_notes
- For non-LinkedIn results, still extract the person if named
- If a person appears in multiple results, merge into one entry with the most complete info
- Return up to 30 candidates
- Return only a valid JSON array, no explanation"""
    raw = parse_json(llm(prompt))
    if not isinstance(raw, list):
        return []
    return raw[:30]


def enrich_candidates(candidates: list[dict], query: str, intent: dict) -> list[dict]:
    """Single LLM call: score each candidate, write about, write why_relevant."""
    candidates_text = json.dumps(
        [{"name": f"{c['first_name']} {c['last_name']}", "role": c.get("role", ""),
          "company": c.get("company", ""), "location": c.get("location", ""),
          "background": c.get("background_notes", ""), "linkedin": bool(c.get("linkedin_url"))}
         for c in candidates],
        indent=2,
    )
    prompt = f"""Evaluate these candidates against the search query and criteria.

Query: "{query}"
Criteria: {json.dumps(intent)}

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

Return only a valid JSON array, no explanation."""
    enrichments = parse_json(llm(prompt))

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

    # Step 1: parse intent + generate queries (1 LLM call)
    intent, queries = parse_intent_and_queries(req.query)

    # Step 2: fetch results in parallel
    results = await fetch_results(queries)

    if not results:
        return SearchResponse(candidates=[], count=0)

    # Step 3: extract candidates
    raw_candidates = extract_candidates(results, req.query)

    if not raw_candidates:
        return SearchResponse(candidates=[], count=0)

    # Step 4: score + enrich all candidates (1 LLM call)
    enriched = enrich_candidates(raw_candidates, req.query, intent)

    # Sort by score, return top 15
    ranked = sorted(enriched, key=lambda c: c.get("fit_score", 1), reverse=True)[:15]

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
