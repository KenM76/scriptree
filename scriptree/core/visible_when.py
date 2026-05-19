"""
visible_when.py — tiny expression evaluator for ``ParamDef``'s
``visible_when`` and ``required_when`` fields (V0.4.0+).

## For humans

Design constraint: this is a **declarative** language for tool
authors writing JSON, not an embedded scripting language.  It only
expresses the few logical patterns that actually arise in real
tool forms:

  * "field X is set to value V"
  * "field X is one of (V1, V2)"
  * Boolean AND / OR / NOT combinations of the above.

Anything more complex (arithmetic, function calls, lambdas)
belongs in the tool's executable, not in the schema.

Grammar (BNF-ish)::

    <expr>       := <or_expr>
    <or_expr>    := <and_expr> ( 'OR' <and_expr> )*
    <and_expr>   := <unary> ( 'AND' <unary> )*
    <unary>      := 'NOT' <unary> | <atom>
    <atom>       := '(' <expr> ')' | <comparison>
    <comparison> := <ident> <op> <literal>
                  | <ident> 'in' '(' <literal_list> ')'
    <op>         := '==' | '!='
    <literal>    := <quoted> | <bare_token>
    <quoted>     := '...' | "..."
    <bare_token> := letters, digits, _ (no whitespace, no commas)
    <ident>      := Python-style identifier (matches ParamDef.id)

Operators are case-insensitive (``AND`` / ``and`` / ``And``).
Identifiers are case-sensitive (they match ``ParamDef.id``
verbatim).

Comparisons use **string equality** because that's what's in the
form's values dict.  Numeric / boolean fields compare against
their stringified value: ``checked=True`` is ``"True"``,
``count=5`` is ``"5"``.  This keeps the evaluator dead-simple —
authors writing ``visible_when: "use_advanced == 'true'"`` get
sensible behaviour even though the underlying type is bool.

Public API::

    evaluate(expression: str, values: dict[str, Any]) -> bool

  expression: the ``visible_when`` / ``required_when`` string.
              Empty string ⇒ ``True`` (always visible / required).
  values:     ``{param_id: current_value, ...}``.  Unknown
              identifiers in the expression evaluate to the empty
              string — so ``foo == 'bar'`` is ``False`` when there
              is no ``foo`` param, NOT a hard error.

  return:     True if the expression evaluates truthy, False if
              falsy, **True** on any parse error (fail-open — a
              broken expression in a tool def must not hide the
              field forever).

The evaluator is allocation-light and pure; safe to call on every
form-value change.  No regex, no eval, no AST module — a 60-line
recursive-descent parser walks the token stream once.

## For maintainers / LLMs

* FAIL-OPEN is a hard invariant: ``evaluate`` catches BOTH
  ``ValueError`` (parse errors) and any other ``Exception`` and
  returns ``True``. A broken expression must never make a field
  invisible AND unfixable from the UI. ``runner.resolve`` relies on
  this: it uses ``visible_when`` to EXEMPT hidden fields from the
  required check — a fail-CLOSED change here would make hidden
  required fields un-runnable.
* String-equality only. The LHS is ``str(values.get(ident, ""))`` —
  bool/number params compare via their Python ``str()`` form
  (``True``→``"True"``, ``5``→``"5"``). Authors commonly write
  ``== 'true'`` (lowercase); that compares against ``str(True)`` ==
  ``"True"`` and is FALSE. This quirk is documented above as
  "sensible" but is a real footgun — don't add type coercion to
  paper over it without revisiting all existing tool defs.
* Unknown identifiers resolve to ``""`` (not an error) by design —
  preserves fail-soft when a referenced param was renamed/removed.
* Tokenizer accepts ``_ - .`` inside bare tokens/identifiers so
  values like ``v1.2`` / ``off-line`` work; quoted strings have NO
  escape sequences (intentional — paths/values don't carry quotes
  in practice). Widening either is a grammar change that ripples to
  the editor's expression UI.
* Parser is a single-pass combined parse+evaluate (no AST node
  objects) with standard precedence NOT < AND < OR and parenthesised
  override. ``parse_expr`` rejects trailing tokens. Keep the
  recursive-descent shape — ``eval``/``ast`` are explicitly banned
  here for safety (this string comes from tool-def JSON).
* ``_log`` writes to stderr only; this module never raises to the
  caller and never touches Qt. Keep it dependency-free (stdlib
  ``sys`` only) so it stays callable on every keystroke and on the
  headless path.
"""
from __future__ import annotations

import sys
from typing import Any


def _log(msg: str) -> None:
    print(f"[visible_when] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class _Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r})"


def _tokenize(text: str) -> list[_Token]:
    """Return a list of tokens.  Raises ``ValueError`` on
    malformed input (unterminated string, stray character)."""
    tokens: list[_Token] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            tokens.append(_Token("LPAREN", "("))
            i += 1
            continue
        if c == ")":
            tokens.append(_Token("RPAREN", ")"))
            i += 1
            continue
        if c == ",":
            tokens.append(_Token("COMMA", ","))
            i += 1
            continue
        if c == "=" and i + 1 < n and text[i + 1] == "=":
            tokens.append(_Token("EQ", "=="))
            i += 2
            continue
        if c == "!" and i + 1 < n and text[i + 1] == "=":
            tokens.append(_Token("NE", "!="))
            i += 2
            continue
        if c in ("'", '"'):
            # Quoted string literal.  No escape sequences (kept
            # simple — paths and values don't carry quotes in
            # practice).
            quote = c
            i += 1
            start = i
            while i < n and text[i] != quote:
                i += 1
            if i >= n:
                raise ValueError(
                    f"unterminated string literal at column {start - 1}"
                )
            tokens.append(_Token("STRING", text[start:i]))
            i += 1  # closing quote
            continue
        # Identifier / keyword / bare value.  Allow letters, digits,
        # underscore, hyphen, dot — covers param IDs and most
        # bare-token values (e.g. "3", "v1.2", "off-line").
        start = i
        while i < n and (text[i].isalnum() or text[i] in "_-."):
            i += 1
        if i == start:
            raise ValueError(
                f"unexpected character {c!r} at column {start}"
            )
        word = text[start:i]
        upper = word.upper()
        if upper in ("AND", "OR", "NOT", "IN"):
            tokens.append(_Token(upper, word))
        else:
            tokens.append(_Token("IDENT", word))
    return tokens


# ---------------------------------------------------------------------------
# Parser + evaluator (combined — single pass)
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens: list[_Token], values: dict[str, Any]) -> None:
        self._t = tokens
        self._i = 0
        self._values = values

    def _peek(self) -> _Token | None:
        return self._t[self._i] if self._i < len(self._t) else None

    def _take(self) -> _Token:
        tok = self._t[self._i]
        self._i += 1
        return tok

    def _expect(self, kind: str) -> _Token:
        tok = self._peek()
        if tok is None or tok.kind != kind:
            got = "EOF" if tok is None else tok.kind
            raise ValueError(f"expected {kind}, got {got}")
        return self._take()

    # Grammar production: expression ::= or_expr
    def parse_expr(self) -> bool:
        result = self._or_expr()
        # Trailing junk?
        if self._peek() is not None:
            raise ValueError(f"unexpected trailing token {self._peek()!r}")
        return result

    def _or_expr(self) -> bool:
        left = self._and_expr()
        while self._peek() is not None and self._peek().kind == "OR":
            self._take()
            right = self._and_expr()
            left = left or right
        return left

    def _and_expr(self) -> bool:
        left = self._unary()
        while self._peek() is not None and self._peek().kind == "AND":
            self._take()
            right = self._unary()
            left = left and right
        return left

    def _unary(self) -> bool:
        if self._peek() is not None and self._peek().kind == "NOT":
            self._take()
            return not self._unary()
        return self._atom()

    def _atom(self) -> bool:
        tok = self._peek()
        if tok is None:
            raise ValueError("unexpected EOF — expected comparison")
        if tok.kind == "LPAREN":
            self._take()
            inner = self._or_expr()
            self._expect("RPAREN")
            return inner
        return self._comparison()

    def _comparison(self) -> bool:
        ident_tok = self._expect("IDENT")
        lhs = str(self._values.get(ident_tok.value, ""))
        op_tok = self._peek()
        if op_tok is None:
            raise ValueError(
                f"expected operator after {ident_tok.value!r}, got EOF"
            )
        if op_tok.kind == "EQ":
            self._take()
            rhs = self._read_literal()
            return lhs == rhs
        if op_tok.kind == "NE":
            self._take()
            rhs = self._read_literal()
            return lhs != rhs
        if op_tok.kind == "IN":
            self._take()
            self._expect("LPAREN")
            options: list[str] = []
            while True:
                options.append(self._read_literal())
                nxt = self._peek()
                if nxt is None:
                    raise ValueError("unterminated 'in (...)' list")
                if nxt.kind == "COMMA":
                    self._take()
                    continue
                if nxt.kind == "RPAREN":
                    self._take()
                    break
                raise ValueError(
                    f"expected ',' or ')' in 'in' list, got {nxt.kind}"
                )
            return lhs in options
        raise ValueError(
            f"expected '==' / '!=' / 'in', got {op_tok.kind!r}"
        )

    def _read_literal(self) -> str:
        tok = self._peek()
        if tok is None:
            raise ValueError("expected literal, got EOF")
        if tok.kind in ("STRING", "IDENT"):
            self._take()
            return tok.value
        raise ValueError(f"expected literal, got {tok.kind}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def evaluate(expression: str, values: dict[str, Any]) -> bool:
    """Evaluate ``expression`` against ``values``.

    Empty / whitespace-only expression returns True (i.e. "always"
    semantics — useful as the default for both ``visible_when``
    and ``required_when``).

    Parse / runtime errors fail OPEN — log a warning and return
    True so the tool stays usable.  A broken expression should
    never make a field invisible AND impossible to fix from the
    UI.
    """
    if not expression or not expression.strip():
        return True
    try:
        tokens = _tokenize(expression)
        if not tokens:
            return True
        parser = _Parser(tokens, values)
        return parser.parse_expr()
    except ValueError as exc:
        _log(f"evaluate({expression!r}): {exc!r} — failing open")
        return True
    except Exception as exc:  # noqa: BLE001
        _log(f"evaluate({expression!r}): unexpected {exc!r} — failing open")
        return True
