# -*- coding: utf-8 -*-
"""
Lumberjack Workbench - naming.py

Compact, human readable names for a set of object labels. Pure Python, no FreeCAD imports.

Labels are split into tokens (separators, camelCase and letter/digit boundaries), the
common suffix is factored out, and the remaining token sequences are arranged in a trie
which is rendered compactly:

    Kitchen_Left_Top, Kitchen_Left_Bottom, Kitchen_Right_Top -> "Kitchen Left Top/Bottom, Right Top"
    Left_Drawer, Right_Drawer                                -> "Left/Right Drawer"
    Drawer001, Drawer002, Drawer003                          -> "Drawer 001-003"
    Drawer, Drawer001, Drawer002                             -> "Drawer x3"
"""

import re

MAX_LENGTH = 60
TIMES = "×"  # multiplication sign used for counts
_SEPARATORS = re.compile(r"[\s_\-\.,;:/\\|()\[\]{}]+")


def tokenize(label):
    """Split a label into tokens at separators, camelCase and letter/digit boundaries."""
    tokens = []
    for chunk in _SEPARATORS.split(label):
        if not chunk:
            continue
        current = ""
        for ch in chunk:
            if current:
                prev = current[-1]
                boundary = (
                    prev.isdigit() != ch.isdigit()
                    or (prev.islower() and ch.isupper())
                    or (prev.isalpha() != ch.isalpha() and not ch.isdigit() and not prev.isdigit())
                )
                if boundary:
                    tokens.append(current)
                    current = ""
            current += ch
        if current:
            tokens.append(current)
    return tokens


def _natural_key(label):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", label)]


class _Node:
    def __init__(self, token):
        self.token = token
        self.children = []  # insertion order
        self.terminal = False
        self.count = 0

    def child(self, token):
        for c in self.children:
            if c.token == token:
                return c
        c = _Node(token)
        self.children.append(c)
        return c


def _common_suffix(sequences):
    if len(sequences) < 2:
        return []
    suffix = []
    shortest = min(len(s) for s in sequences)
    for i in range(1, shortest):  # keep at least one token per label
        tokens = {tuple(s[-i:]) for s in sequences}
        if len(tokens) != 1:
            break
        suffix = list(sequences[0][-i:])
    return suffix


def _compress_numeric(tokens):
    """Join leaf tokens with '/', collapsing runs of consecutive numbers into ranges."""
    if len(tokens) > 1 and all(t.isdigit() for t in tokens):
        nums = sorted(tokens, key=int)
        runs = [[nums[0]]]
        for t in nums[1:]:
            if int(t) == int(runs[-1][-1]) + 1:
                runs[-1].append(t)
            else:
                runs.append([t])
        parts = []
        for run in runs:
            if len(run) >= 3:
                parts.append("{}-{}".format(run[0], run[-1]))
            else:
                parts.extend(run)
        return "/".join(parts)
    return "/".join(tokens)


def _render(node):
    if not node.children:
        return node.token
    if node.terminal:  # a label ends here while others continue: just count them
        return "{} {}{}".format(node.token, TIMES, node.count).strip()
    if all(not c.children for c in node.children):
        inner = _compress_numeric([c.token for c in node.children])
    else:
        inner = ", ".join(_render(c) for c in node.children)
    return "{} {}".format(node.token, inner).strip()


def group_name(labels, max_length=MAX_LENGTH):
    """
    A compact name describing a collection of labels without repeating shared parts.

    Falls back to "<common prefix> xN" (or "N items") when the compact form gets too long.
    """
    labels = sorted({str(l) for l in labels if str(l).strip()}, key=_natural_key)
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    sequences = [tokenize(l) or [l] for l in labels]
    suffix = _common_suffix(sequences)
    if suffix:
        sequences = [s[: len(s) - len(suffix)] for s in sequences]
    root = _Node("")
    for seq in sequences:
        node = root
        node.count += 1
        for token in seq:
            node = node.child(token)
            node.count += 1
        node.terminal = True
    name = _render(root)
    if suffix:
        name = "{} {}".format(name, " ".join(suffix))
    if len(name) > max_length:
        prefix = []
        node = root
        while len(node.children) == 1 and not node.terminal:
            node = node.children[0]
            prefix.append(node.token)
        if prefix or suffix:
            name = "{} {}{}".format(" ".join(prefix + suffix), TIMES, len(labels)).strip()
        else:
            name = "{} items".format(len(labels))
    return name


if __name__ == "__main__":  # quick self-check: python3 naming.py
    cases = [
        (["Drawer"], "Drawer"),
        (["Drawer", "Captured"], "Captured/Drawer"),
        (["Drawer", "Drawer001", "Drawer002"], "Drawer " + TIMES + "3"),
        (["Drawer001", "Drawer002", "Drawer003"], "Drawer 001-003"),
        (["Drawer001", "Drawer003"], "Drawer 001/003"),
        (["Kitchen_Left_Top", "Kitchen_Left_Bottom", "Kitchen_Right_Top"], "Kitchen Left Bottom/Top, Right Top"),
        (["Left_Drawer", "Right_Drawer"], "Left/Right Drawer"),
        (["Küche_Oben", "Küche_Unten"], "Küche Oben/Unten"),
        (["Bad_Schublade", "Küche_Schublade"], "Bad/Küche Schublade"),
        (["KitchenLeft", "KitchenRight"], "Kitchen Left/Right"),
    ]
    for labels, expected in cases:
        got = group_name(labels)
        print("ok " if got == expected else "BAD", labels, "->", got)
        assert got == expected, (got, expected)
