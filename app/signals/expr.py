"""True / false expressions for signal rules and strategies: (A OR B) AND NOT (X OR (S AND H)), and
("Rule 1" AND !"Rule 3") OR Rule5. Text in, a tree out, and back; evaluated by rules.py.

The language:
    A ... Z                  a condition of the rule, by its letter (rules only)
    Rule5, "Rule 1"          a saved rule, by name (in quotes when it has spaces, or is one capital letter)
    NOT x, !x                not
    x AND y, x && y, x & y   and
    x OR y, x || y, x | y    or
    WITHIN n x               x was true on one of the last n bars (this one included), n from 1 to 50
    ( ... )                  grouping
NOT and WITHIN bind tightest, then AND, then OR. Words are not case-sensitive (and, Or, not...).

The tree: {"cond": "A"} | {"rule": "Rule 1"} | {"not": x} | {"and": [x, y, ...]} | {"or": [...]}
          | {"within": n, "of": x}
"""
from __future__ import annotations

import re

MAX_TEXT = 4000
MAX_NODES = 300
MAX_DEPTH = 24
MAX_WITHIN = 50
KEYWORDS = {"and", "or", "not", "within"}
_WORD = re.compile(r"[A-Za-z0-9_.\-]+")
_BARE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")


class ExprError(ValueError):
    """What's wrong with an expression, and where (pos: 0-based index into the text, or None)."""

    def __init__(self, message: str, pos: int | None = None):
        super().__init__(message if pos is None else f"{message} (at character {pos + 1})")
        self.pos = pos


# ---------------------------------------------------------------- text to tokens
def _tokens(text: str) -> list[tuple[str, str, int]]:
    """(kind, value, position): kind is ( ) not and or within num cond name end."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c in "()":
            out.append((c, c, i))
            i += 1
        elif c == "!":
            out.append(("not", "!", i))
            i += 1
        elif text.startswith("&&", i) or text.startswith("||", i):
            out.append(("and" if c == "&" else "or", text[i:i + 2], i))
            i += 2
        elif c in "&|":
            out.append(("and" if c == "&" else "or", c, i))
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 1
                buf.append(text[j])
                j += 1
            if j >= n:
                raise ExprError("A name in quotes isn't closed", i)
            name = "".join(buf).strip()
            if not name:
                raise ExprError("An empty name in quotes", i)
            out.append(("name", name, i))
            i = j + 1
        else:
            m = _WORD.match(text, i)
            if not m:
                raise ExprError(f"'{c}' isn't part of an expression", i)
            w = m.group(0)
            low = w.lower()
            if low in KEYWORDS:
                out.append((low, w, i))
            elif w.isdigit():
                out.append(("num", w, i))
            elif len(w) == 1 and "A" <= w <= "Z":
                out.append(("cond", w, i))
            else:
                out.append(("name", w, i))
            i = m.end()
    out.append(("end", "", n))
    return out


# ---------------------------------------------------------------- tokens to a tree
class _Parser:
    def __init__(self, text: str):
        self.toks, self.k = _tokens(text), 0

    def peek(self):
        return self.toks[self.k]

    def take(self, kind: str):
        t = self.toks[self.k]
        if t[0] != kind:
            want = {")": "')'", "num": "a number of bars"}.get(kind, kind)
            raise ExprError(f"Expected {want}, found {self._say(t)}", t[2])
        self.k += 1
        return t

    @staticmethod
    def _say(t):
        return "the end" if t[0] == "end" else f"'{t[1]}'"

    def expr(self, depth=0):
        if depth > MAX_DEPTH:
            raise ExprError(f"Brackets more than {MAX_DEPTH} deep", self.peek()[2])
        parts = [self.conj(depth)]
        while self.peek()[0] == "or":
            self.k += 1
            parts.append(self.conj(depth))
        return _flat("or", parts)

    def conj(self, depth):
        parts = [self.unary(depth)]
        while self.peek()[0] == "and":
            self.k += 1
            parts.append(self.unary(depth))
        return _flat("and", parts)

    def unary(self, depth):
        t = self.peek()
        if t[0] == "not":
            self.k += 1
            return {"not": self.unary(depth + 1)}
        if t[0] == "within":
            self.k += 1
            n = self.take("num")
            bars = int(n[1])
            if not 1 <= bars <= MAX_WITHIN:
                raise ExprError(f"WITHIN takes 1 to {MAX_WITHIN} bars", n[2])
            return {"within": bars, "of": self.unary(depth + 1)}
        return self.atom(depth)

    def atom(self, depth):
        t = self.peek()
        if t[0] == "(":
            self.k += 1
            x = self.expr(depth + 1)
            self.take(")")
            return x
        if t[0] == "cond":
            self.k += 1
            return {"cond": t[1]}
        if t[0] == "name":
            self.k += 1
            return {"rule": t[1]}
        if t[0] == "end":
            raise ExprError("The expression ends too soon: a condition or rule is missing", t[2])
        raise ExprError(f"Expected a condition, a rule or '(', found {self._say(t)}", t[2])


def _flat(op: str, parts: list) -> dict:
    if len(parts) == 1:
        return parts[0]
    out = []
    for p in parts:
        out.extend(p.get(op, [p]))
    return {op: out}


def parse(text: str) -> dict:
    """The tree of an expression; ExprError says what's wrong and where."""
    if not isinstance(text, str) or not text.strip():
        raise ExprError("The expression is empty")
    if len(text) > MAX_TEXT:
        raise ExprError(f"At most {MAX_TEXT} characters")
    p = _Parser(text)
    tree = p.expr()
    t = p.peek()
    if t[0] != "end":
        raise ExprError(f"Unexpected {p._say(t)}: join conditions with AND or OR" if t[0] in ("cond", "name", "(", "not")
                        else f"Unexpected {p._say(t)}", t[2])
    if count(tree) > MAX_NODES:
        raise ExprError(f"At most {MAX_NODES} parts in one expression")
    return tree


# ---------------------------------------------------------------- a tree back to text, and what it refers to
def _name(n: str) -> str:
    bare = _BARE.fullmatch(n) and n.lower() not in KEYWORDS and not (len(n) == 1 and "A" <= n <= "Z")
    return n if bare else '"' + n.replace("\\", "\\\\").replace('"', '\\"') + '"'


def text(tree: dict) -> str:
    """The expression as text, a group inside another always in brackets ((A AND B) OR C): parse(text(t)) == t."""
    def go(x, outer):
        if "cond" in x:
            return x["cond"]
        if "rule" in x:
            return _name(x["rule"])
        if "not" in x:
            return "NOT " + go(x["not"], "unary")
        if "within" in x:
            return f"WITHIN {x['within']} " + go(x["of"], "unary")
        op = "and" if "and" in x else "or"
        s = f" {op.upper()} ".join(go(y, op) for y in x[op])
        return f"({s})" if outer != "top" else s
    return go(tree, "top")


def count(tree: dict) -> int:
    if "not" in tree:
        return 1 + count(tree["not"])
    if "within" in tree:
        return 1 + count(tree["of"])
    for op in ("and", "or"):
        if op in tree:
            return 1 + sum(count(y) for y in tree[op])
    return 1


def refs(tree: dict) -> tuple[list[str], list[str]]:
    """The condition letters and the rule names an expression uses, each once, in order."""
    letters, names = [], []

    def go(x):
        if "cond" in x:
            if x["cond"] not in letters:
                letters.append(x["cond"])
        elif "rule" in x:
            if x["rule"] not in names:
                names.append(x["rule"])
        elif "not" in x:
            go(x["not"])
        elif "within" in x:
            go(x["of"])
        else:
            for y in x.get("and") or x.get("or") or []:
                go(y)
    go(tree)
    return letters, names


def rename(tree: dict, old: str, new: str) -> dict:
    """The same tree with rule `old` called `new`."""
    if "rule" in tree:
        return {"rule": new} if tree["rule"] == old else tree
    if "not" in tree:
        return {"not": rename(tree["not"], old, new)}
    if "within" in tree:
        return {"within": tree["within"], "of": rename(tree["of"], old, new)}
    if "cond" in tree:
        return tree
    op = "and" if "and" in tree else "or"
    return {op: [rename(y, old, new) for y in tree[op]]}


def valid_tree(tree) -> dict:
    """A tree from the browser (the group editor) checked by turning it into text and back."""
    if not isinstance(tree, dict):
        raise ExprError("An expression is an object")
    try:
        return parse(text(tree))
    except (KeyError, TypeError, AttributeError):
        raise ExprError("That isn't an expression tree") from None
