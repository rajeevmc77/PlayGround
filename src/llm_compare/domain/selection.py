"""Which route a scored pair takes."""

from llm_compare.domain.models import Route


def route_for(score: float, threshold: float) -> Route:
    return Route.MATCH_PHASH if score >= threshold else Route.TO_LLM
