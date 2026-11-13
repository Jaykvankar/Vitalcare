"""Synthetic but physiologically plausible vital-sign streams.

Used for training/evaluating the model and by the device simulator.
Episode types: hypoxia, tachycardia, hypotension, fever (deterioration, label 1)
and activity (harmless heart-rate rise, label 0, to teach the model what *not* to flag).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .rules import VITALS

EPISODES: dict[str, dict[str, tuple[float, float]]] = {
    # vital: (min shift, max shift) at full severity
    "hypoxia": {"spo2": (-12, -6), "rr": (6, 10), "hr": (15, 25)},
    "tachycardia": {"hr": (38, 60), "rr": (2, 5)},
    "hypotension": {"sbp": (-45, -30), "dbp": (-25, -15), "hr": (20, 30)},
    "fever": {"temp": (1.7, 2.6), "hr": (15, 25), "rr": (3, 6)},
    "activity": {"hr": (12, 28), "rr": (2, 4)},
}
DETERIORATION = ("hypoxia", "tachycardia", "hypotension", "fever")
NOISE = {"hr": 2.5, "spo2": 0.5, "sbp": 4.0, "dbp": 3.0, "temp": 0.06, "rr": 0.8}


def random_baseline(rng: random.Random) -> dict:
    return {
        "hr": min(92.0, rng.gauss(74, 7)), "spo2": min(99.5, max(96.5, rng.gauss(97.8, 0.8))),
        "sbp": rng.gauss(121, 9), "dbp": rng.gauss(77, 6),
        "temp": rng.gauss(36.75, 0.18), "rr": rng.gauss(15, 1.8),
    }


@dataclass
class Episode:
    kind: str
    shifts: dict
    onset: int       # steps to reach full severity
    plateau: int
    recovery: int
    t: int = 0

    @property
    def length(self) -> int:
        return self.onset + self.plateau + self.recovery

    def severity(self) -> float:
        if self.t < self.onset:
            return (self.t + 1) / self.onset
        if self.t < self.onset + self.plateau:
            return 1.0
        return max(0.0, 1 - (self.t - self.onset - self.plateau + 1) / self.recovery)


def make_episode(kind: str, rng: random.Random, scale: float = 1.0) -> Episode:
    shifts = {k: rng.uniform(*rng_range) for k, rng_range in EPISODES[kind].items()}
    if kind == "activity":
        return Episode(kind, shifts, onset=rng.randint(2, 5), plateau=rng.randint(5, 20), recovery=rng.randint(3, 8))
    return Episode(
        kind, shifts,
        onset=max(3, int(rng.randint(15, 40) * scale)),
        plateau=max(3, int(rng.randint(20, 60) * scale)),
        recovery=max(3, int(rng.randint(15, 40) * scale)),
    )


@dataclass
class PatientStream:
    """One simulated patient. Call step() once per reading."""
    rng: random.Random
    baseline: dict = field(default_factory=dict)
    episode: Episode | None = None
    episode_rate: float = 0.0015      # chance per step of a spontaneous deterioration
    activity_rate: float = 0.004
    drift: dict = field(default_factory=lambda: {k: 0.0 for k in VITALS})

    def __post_init__(self) -> None:
        if not self.baseline:
            self.baseline = random_baseline(self.rng)

    def start(self, kind: str, scale: float = 1.0) -> None:
        self.episode = make_episode(kind, self.rng, scale)

    def step(self) -> tuple[dict, int, str]:
        """Return (vitals, label, episode_kind)."""
        if self.episode is None:
            r = self.rng.random()
            if r < self.episode_rate:
                self.start(self.rng.choice(DETERIORATION))
            elif r < self.episode_rate + self.activity_rate:
                self.start("activity")

        # slow random-walk drift so baselines are not perfectly flat
        for k in VITALS:
            self.drift[k] = 0.98 * self.drift[k] + self.rng.gauss(0, NOISE[k] * 0.15)

        v = {k: self.baseline[k] + self.drift[k] + self.rng.gauss(0, NOISE[k]) for k in VITALS}
        label, kind = 0, "stable"
        if self.episode is not None:
            sev = self.episode.severity()
            for k, shift in self.episode.shifts.items():
                v[k] += shift * sev
            kind = self.episode.kind
            if kind in DETERIORATION and sev >= 0.3:
                label = 1
            self.episode.t += 1
            if self.episode.t >= self.episode.length:
                self.episode = None

        v["spo2"] = min(100.0, v["spo2"])
        v["dbp"] = min(v["dbp"], v["sbp"] - 15)
        return {k: round(v[k], 1 if k != "temp" else 2) for k in VITALS}, label, kind
