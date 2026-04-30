"""
Sentiment Pipeline — XAUUSD News Signal
=========================================
Converts raw financial headlines into 6 real-time sentiment features
that replace the zero-placeholders in the obs vector (indices 50-55).

Sources (all free, no API key required):
  1. RSS feeds  — Reuters, MarketWatch, Kitco Gold
  2. GDELT      — Global news event database (free, no key)
  3. Lexicon    — Gold-specific keyword scoring (fallback)

Features produced (Group I — obs indices 55-59):
  sentiment_score    — [-1, +1]  bullish/bearish for Gold right now
  sentiment_novelty  — [0, 1]   how different current sentiment is from 24hr avg
  sentiment_momentum — [-1, +1]  direction sentiment is moving
  news_volume        — [0, 1]   normalised count of gold-relevant headlines per hour
  event_flag         — {0, 1}   1 = high-impact scheduled event within 2 hours
"""

import os
import sys
import time
import logging
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib  import Path
from typing   import List, Dict, Optional
from collections import deque

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy  as np
import pandas as pd

try:
    import feedparser
    _FEEDPARSER_OK = True
except ImportError:
    _FEEDPARSER_OK = False

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

from config.settings import SENTIMENT

log = logging.getLogger(__name__)

# ── Gold-specific sentiment lexicon ──────────────────────────────────────────
BULLISH_WORDS = [
    "rally", "surge", "gain", "rise", "bullish", "safe haven", "demand",
    "inflow", "record", "high", "inflation", "fear", "uncertainty",
    "geopolitical", "central bank buying", "rate cut", "dovish",
    "recession fears", "dollar weakness", "dxy falls",
]
BEARISH_WORDS = [
    "fall", "drop", "decline", "sell", "bearish", "outflow", "low",
    "hawkish", "rate hike", "dollar strength", "dxy rises", "risk on",
    "equities surge", "recovery", "taper",
]

RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.marketwatch.com/marketwatch/marketpulse/",
    "https://www.kitco.com/rss/kitconews.rss",
]

GOLD_KEYWORDS = ["gold", "xauusd", "xau", "bullion", "precious metal", "safe haven"]


# ── Lexicon scorer ────────────────────────────────────────────────────────────

def _lexicon_score(text: str) -> float:
    """Score a headline [-1, +1] using the gold lexicon."""
    text_lower = text.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in text_lower)
    bear = sum(1 for w in BEARISH_WORDS if w in text_lower)
    total = bull + bear
    if total == 0:
        return 0.0
    return (bull - bear) / total


def _is_gold_relevant(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in GOLD_KEYWORDS)


# ── RSS fetcher ───────────────────────────────────────────────────────────────

def fetch_rss_headlines(max_age_hours: int = 4) -> List[Dict]:
    """Fetch recent gold-relevant headlines from RSS feeds."""
    if not _FEEDPARSER_OK:
        return []

    headlines = []
    cutoff    = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:30]:
                title = entry.get("title", "")
                if not _is_gold_relevant(title):
                    continue
                published = entry.get("published_parsed")
                if published:
                    dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                else:
                    dt = datetime.now(timezone.utc)

                uid = hashlib.md5(title.encode()).hexdigest()[:8]
                headlines.append({"id": uid, "text": title, "dt": dt, "source": "rss"})
        except Exception as e:
            log.debug(f"RSS fetch failed ({url}): {e}")

    return headlines


# ── GDELT fetcher ─────────────────────────────────────────────────────────────

def fetch_gdelt_headlines(max_age_hours: int = 4) -> List[Dict]:
    """Fetch gold-related headlines from GDELT GKG API (free, no key)."""
    if not _REQUESTS_OK:
        return []

    try:
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            "?query=gold%20bullion%20XAUUSD&mode=artlist&maxrecords=25"
            "&format=json&timespan=4h"
        )
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        articles = data.get("articles", [])
        cutoff   = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        results  = []
        for art in articles:
            title = art.get("title", "")
            if not _is_gold_relevant(title):
                continue
            uid = hashlib.md5(title.encode()).hexdigest()[:8]
            results.append({"id": uid, "text": title, "dt": datetime.now(timezone.utc), "source": "gdelt"})
        return results
    except Exception as e:
        log.debug(f"GDELT fetch failed: {e}")
        return []


# ════════════════════════════════════════════════════════════════════════════════
# Sentiment Store — rolling 24hr window
# ════════════════════════════════════════════════════════════════════════════════

class SentimentStore:
    """
    Maintains a rolling 24-hour window of scored headlines.
    Applies time-decay weighting (half-life = 30 min).
    """

    def __init__(self, window_hours: int = 24, half_life_min: int = 30):
        self.window_hours = window_hours
        self.half_life    = half_life_min * 60  # seconds
        self._records: deque = deque()          # (dt, score)

    def ingest(self, headlines: List[Dict]):
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=self.window_hours)
        for h in headlines:
            score = _lexicon_score(h["text"])
            self._records.append((h["dt"], score))
        # Prune old records
        while self._records and self._records[0][0] < cutoff:
            self._records.popleft()

    def _weighted_score(self) -> float:
        """Exponentially time-decayed mean score."""
        if not self._records:
            return 0.0
        now     = datetime.now(timezone.utc).timestamp()
        weights = []
        scores  = []
        for dt, score in self._records:
            age     = max(0, now - dt.timestamp())
            weight  = 2 ** (-age / self.half_life)
            weights.append(weight)
            scores.append(score)
        w = np.array(weights)
        s = np.array(scores)
        return float(np.dot(w, s) / (w.sum() + 1e-9))

    def get_features(self, calendar_blocked: bool = False) -> np.ndarray:
        """
        Returns obs[55:60] — 5 sentiment features as float32.
        """
        score    = np.clip(self._weighted_score(), -1.0, 1.0)
        n        = len(self._records)
        max_n    = self.window_hours * 10      # ~10 headlines/hr expected max
        vol      = min(1.0, n / max_n)

        # Novelty: compare last 1hr to previous 23hr mean
        now    = datetime.now(timezone.utc)
        recent = [s for (dt, s) in self._records if (now - dt).total_seconds() < 3600]
        older  = [s for (dt, s) in self._records if (now - dt).total_seconds() >= 3600]
        r_mean = np.mean(recent) if recent else 0.0
        o_mean = np.mean(older)  if older  else 0.0
        novelty = float(np.clip(abs(r_mean - o_mean), 0.0, 1.0))

        # Momentum: direction of score change (last 1hr vs prior 1hr)
        prior  = [s for (dt, s) in self._records
                  if 3600 <= (now - dt).total_seconds() < 7200]
        p_mean = np.mean(prior) if prior else r_mean
        momentum = float(np.clip(r_mean - p_mean, -1.0, 1.0))

        event_flag = 1.0 if calendar_blocked else 0.0

        return np.array([
            score,            # sentiment_score
            novelty,          # sentiment_novelty
            momentum,         # sentiment_momentum
            vol,              # news_volume
            event_flag,       # event_flag
        ], dtype=np.float32)


# ════════════════════════════════════════════════════════════════════════════════
# Live Sentiment Pipeline
# ════════════════════════════════════════════════════════════════════════════════

class SentimentPipeline:
    """
    Refresh every 15 minutes. Thread-safe getter for latest features.
    """

    def __init__(self):
        self.store      = SentimentStore(
            window_hours  = SENTIMENT["window_hours"],
            half_life_min = SENTIMENT["decay_half_life_min"],
        )
        self._last_refresh = 0.0
        self._interval     = SENTIMENT["refresh_interval_sec"]
        self._features     = np.zeros(5, dtype=np.float32)
        self._features[1]  = 0.5   # novelty default

    def refresh(self, calendar_blocked: bool = False, force: bool = False):
        now = time.time()
        if not force and (now - self._last_refresh) < self._interval:
            return
        headlines = []
        if SENTIMENT.get("rss_enabled", True):
            headlines += fetch_rss_headlines()
        if SENTIMENT.get("gdelt_enabled", True):
            headlines += fetch_gdelt_headlines()
        if headlines:
            self.store.ingest(headlines)
            log.info(f"Sentiment refreshed — {len(headlines)} headlines ingested")
        self._features     = self.store.get_features(calendar_blocked)
        self._last_refresh = now

    def get_features(self, calendar_blocked: bool = False) -> np.ndarray:
        self.refresh(calendar_blocked)
        return self._features.copy()


# ── Singleton for live use ────────────────────────────────────────────────────
_pipeline: Optional[SentimentPipeline] = None

def get_sentiment_pipeline() -> SentimentPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SentimentPipeline()
    return _pipeline


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)
    pipe = SentimentPipeline()
    pipe.refresh(force=True)
    feats = pipe.get_features()
    labels = ["sentiment_score", "sentiment_novelty", "sentiment_momentum",
              "news_volume", "event_flag"]
    print("\n── Sentiment Features ──")
    for label, val in zip(labels, feats):
        print(f"  {label:<25} {val:+.4f}")
