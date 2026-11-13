"""Minimal lexical lint for MQL5 sources (bracket balance outside strings/chars/comments).
This is NOT a compiler: it only catches gross structural slips. MetaEditor remains the
only authority on whether the EA compiles."""
import glob
import os
import sys


def lex_brackets(src: str):
    out, i, n, line = [], 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
        if src.startswith("//", i):
            i = src.find("\n", i)
            if i < 0:
                break
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i)
            line += src.count("\n", i, j)
            i = j + 2
            continue
        if c in "\"'":
            q, i = c, i + 1
            while i < n and src[i] != q:
                if src[i] == "\n":
                    return None, f"unterminated literal at line {line}"
                i += 2 if src[i] == "\\" else 1
            i += 1
            continue
        if c in "{}()[]":
            out.append((c, line))
        i += 1
    return out, None


def check(path: str):
    toks, err = lex_brackets(open(path, encoding="utf-8").read())
    if err:
        return err
    stack, pair = [], {")": "(", "]": "[", "}": "{"}
    for c, line in toks:
        if c in "({[":
            stack.append((c, line))
        elif not stack or stack.pop()[0] != pair[c]:
            return f"unbalanced '{c}' at line {line}"
    return f"unclosed '{stack[-1][0]}' from line {stack[-1][1]}" if stack else None


if __name__ == "__main__":
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EA")
    bad = 0
    for f in sorted(glob.glob(os.path.join(root, "**", "*.mq*"), recursive=True)):
        e = check(f)
        print(("FAIL " if e else "ok   ") + os.path.relpath(f, root) + (f": {e}" if e else ""))
        bad += bool(e)
    sys.exit(1 if bad else 0)
