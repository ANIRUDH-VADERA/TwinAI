"""Two-layer deduplication: a Bloom filter for exact repeats, Jaccard similarity for near-repeats."""
from __future__ import annotations

import hashlib
import math
import re
from collections import deque


class BloomFilter:
    def __init__(self, capacity: int = 100_000, error_rate: float = 0.001) -> None:
        self.size = max(8, int(-capacity * math.log(error_rate) / math.log(2) ** 2))
        self.hashes = max(1, round(self.size / capacity * math.log(2)))
        self.bits = bytearray((self.size + 7) // 8)

    def _positions(self, item: str):
        digest = hashlib.sha256(item.encode()).digest()
        h1, h2 = int.from_bytes(digest[:8], "big"), int.from_bytes(digest[8:16], "big")
        for i in range(self.hashes):  # double hashing gives k independent-enough positions
            yield (h1 + i * h2) % self.size

    def add(self, item: str) -> bool:
        """Adds the item. Returns True if it was (probably) already present."""
        present = True
        for p in self._positions(item):
            byte, bit = divmod(p, 8)
            if not self.bits[byte] >> bit & 1:
                present = False
                self.bits[byte] |= 1 << bit
        return present


_WORD = re.compile(r"[a-z0-9_./-]+")


def shingles(text: str, n: int = 3) -> set[str]:
    words = _WORD.findall(text.lower())
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))} if words else set()


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class Deduplicator:
    def __init__(self, threshold: float = 0.85, window: int = 200) -> None:
        self.exact = BloomFilter()
        self.recent: deque[set[str]] = deque(maxlen=window)
        self.threshold = threshold

    def is_duplicate(self, source: str, content: str) -> bool:
        normalized = " ".join(content.split()).lower()
        if self.exact.add(f"{source}\x00{normalized}"):
            return True
        sh = shingles(normalized)
        if any(jaccard(sh, prev) >= self.threshold for prev in self.recent):
            return True
        self.recent.append(sh)
        return False
