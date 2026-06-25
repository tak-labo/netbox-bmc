"""
Normalize component names to a consistent format.

All components of the same kind are numbered sequentially starting from 0,
regardless of their original naming scheme. This allows consistent InventoryItem
names across different vendors and Redfish implementations.

Examples:
    "CPU.Socket.1" → "CPU 0"
    "CPU.Socket.2" → "CPU 1"
    "DIMM.A1" → "Memory 0"
    "DIMM.B1" → "Memory 1"
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .inventory import Component

KIND_LABELS = {
    "cpu": "CPU",
    "memory": "Memory",
    "drive": "Drive",
    "psu": "PSU",
    "fan": "Fan",
    "pci": "PCI",
    "firmware": "Firmware",
}

MODULE_KINDS = frozenset(KIND_LABELS)


@dataclass
class NormalizedComponent:
    """A component with its normalized name."""
    normalized_name: str  # e.g. "CPU 0"
    component: Component


def normalize(components: list[Component]) -> list[NormalizedComponent]:
    """
    Normalize component names per kind.

    Components are grouped by kind, sorted naturally within each group,
    and assigned sequential numbers (0, 1, 2, ...). NICs and other
    non-module kinds are filtered out.

    Args:
        components: List of raw components from drivers.

    Returns:
        List of NormalizedComponent with consistent names.
    """
    grouped: dict[str, list[Component]] = defaultdict(list)
    for c in components:
        if c.kind in MODULE_KINDS:
            grouped[c.kind].append(c)

    result = []
    for kind in sorted(grouped):
        label = KIND_LABELS[kind]
        sorted_comps = sorted(grouped[kind], key=lambda c: _sort_key(c.name))
        for i, comp in enumerate(sorted_comps):
            result.append(NormalizedComponent(
                normalized_name=f"{label} {i}",
                component=comp,
            ))
    return result


def _sort_key(name: str) -> tuple[int | str, ...]:
    """
    Generate a sort key for natural (alphanumeric) sorting.

    Splits the name on digit boundaries and converts digit sequences to ints,
    allowing "DIMM.A1" < "DIMM.A2" < "DIMM.B1".

    Examples:
        "CPU.Socket.1" → ("cpu.socket.", 1)
        "DIMM.A2" → ("dimm.", "a", 2)
        "DIMM.A1" → ("dimm.", "a", 1)
    """
    parts = re.split(r"(\d+)", name)
    return tuple(p.zfill(10) if p.isdigit() else p.lower() for p in parts if p != "")
