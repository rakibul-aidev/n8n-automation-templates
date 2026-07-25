"""
Shared tool definitions used across sub-agents.
Uses LangChain tool format for LangGraph compatibility.
"""

from __future__ import annotations
import os
import requests
from langchain_core.tools import tool


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information on a topic. Returns a list of results with titles and snippets."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return f"[web_search disabled — TAVILY_API_KEY not set. Query was: {query}]"
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": max_results},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return "\n\n".join(
        f"**{r['title']}**\n{r['content'][:500]}\nURL: {r['url']}" for r in results
    )


@tool
def read_url(url: str) -> str:
    """Fetch and return the text content of a URL (up to 5000 chars)."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # Strip HTML tags crudely
        import re
        text = re.sub(r'<[^>]+>', ' ', resp.text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:5000]
    except Exception as e:
        return f"Error reading {url}: {e}"


@tool
def check_word_count(text: str) -> str:
    """Return the word count of a piece of text."""
    count = len(text.split())
    return f"Word count: {count}"


@tool
def format_markdown(text: str) -> str:
    """Return the text formatted as clean markdown (pass-through — model does the work)."""
    return text


# Tool lists by agent role
RESEARCHER_TOOLS = [web_search, read_url]
WRITER_TOOLS     = [check_word_count, format_markdown]
REVIEWER_TOOLS   = [check_word_count]
