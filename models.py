"""
Models Module for Tech News AI Scraper.

This module defines the structured Pydantic data schemas used to validate and 
shape the scraped news items extracted from various technology sources. It maps 
unstructured web text into strongly-typed objects required for subsequent 
scoring, deduplication, and transformation steps.
"""

# pyrefly: ignore [missing-import]
from pydantic import BaseModel,Field
from typing import List

class ArticleInfo(BaseModel):
    """
    Pydantic structure representing a single harvested technology article.
    
    Attributes:
        title (str): The primary headline captured from the target site.
        url (str): The verified absolute web link resolving to the source article.
        source (str): The publisher or platform name (e.g., Hacker News).
        summary (str): An LLM-generated 1-2 sentence contextual overview.
    """
    title: str = Field(description="The main headline or title of the news article")
    url: str = Field(description="The absolute URL destination link to the full article")
    source: str = Field(description="The name of the website/platform (e.g., TechCrunch, Hacker News)")
    summary: str = Field(description="A brief 1-2 sentence overview summarizing what the article covers")

class TechNewsExtraction(BaseModel):
    """
    Container object acting as a collection schema for array-based LLM extractions.
    
    Attributes:
        articles (List[ArticleInfo]): A sequence containing all parsed ArticleInfo entities.
    """
    articles: List[ArticleInfo] = Field(description="List of tech news articles extracted from the webpage")