"""Read-only, bounded numeric subset; never substitute for the game's resolver.

Fabric AND/OR, numeric operators, ^/~ and X-ranges:
https://wiki.fabricmc.net/documentation:fabric_mod_json_spec#versionrange
Maven hard ranges (bare soft versions and qualifiers intentionally unknown):
https://maven.apache.org/pom.html#Dependency_Version_Requirement_Specification
"""
import json
import re

NUMBER = r'(?:0|[1-9][0-9]{0,8})'
NUMERIC = re.compile(NUMBER + r'(?:\.' + NUMBER + r'){0,7}\Z')


def numeric(value, *, fabric=False):
    if not isinstance(value, str) or len(value) > 256:
        return None
    if fabric and '+' in value:
        value, suffix = value.split('+', 1)
        if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*', suffix):
            return None
    if not NUMERIC.fullmatch(value):
        return None
    parts = tuple(int(x) for x in value.split('.'))
    return parts + (0,) * (8-len(parts))


def _fabric_term(actual, term):
    if term == '*':
        return True
    wildcard = re.fullmatch(r'(' + NUMBER + r'(?:\.' + NUMBER + r')?)(?:\.[xX*])+', term)
    if wildcard:
        prefix = tuple(int(x) for x in wildcard[1].split('.'))
        return actual[:len(prefix)] == prefix
    match = re.fullmatch(r'(>=|<=|>|<|=|\^|~)?(.+)', term)
    if not match:
        return None
    op, text = match[1] or '=', match[2]
    expected = numeric(text, fabric=True)
    if expected is None:
        return None
    if op == '^':
        # Fabric explicitly does NOT apply npm's special rules for zero majors.
        return expected <= actual < (expected[0]+1,) + (0,)*7
    if op == '~':
        if len(text.split('+')[0].split('.')) < 2:
            return None
        return expected <= actual < (expected[0], expected[1]+1) + (0,)*6
    return {'=': actual == expected, '>=': actual >= expected, '>': actual > expected,
            '<=': actual <= expected, '<': actual < expected}[op]


def _fabric(actual, expression):
    try:
        ranges = json.loads(expression)
    except (ValueError, TypeError, RecursionError):
        return None
    if isinstance(ranges, str):
        ranges = [ranges]
    if not isinstance(ranges, list) or not 1 <= len(ranges) <= 32:
        return None
    alternatives = []
    for value in ranges:
        if not isinstance(value, str) or not 0 < len(value) <= 512:
            return None
        terms = value.split()
        if not 1 <= len(terms) <= 16:
            return None
        result = [_fabric_term(actual, term) for term in terms]
        # Malformed/unsupported branches cannot be hidden by a matching branch.
        if any(x is None for x in result):
            return None
        alternatives.append(all(result))
    return any(alternatives)


def _maven(actual, expression):
    position, results = 0, []
    expression = expression.strip()
    while position < len(expression) and len(results) < 32:
        match = re.compile(r'([\[(])([^\[\]()]*)([\])])').match(expression, position)
        if not match:
            return None
        left, body, right = match.groups()
        if ',' not in body:
            expected = numeric(body.strip())
            if left != '[' or right != ']' or expected is None:
                return None
            result = actual == expected
        else:
            if body.count(',') != 1:
                return None
            lo_text, hi_text = (x.strip() for x in body.split(','))
            lo, hi = numeric(lo_text), numeric(hi_text)
            if ((not lo_text and left != '(') or (not hi_text and right != ')')
                    or (lo_text and lo is None) or (hi_text and hi is None)
                    or not (lo_text or hi_text)):
                return None
            if lo is not None and hi is not None and (lo > hi or (lo == hi and (left != '[' or right != ']'))):
                return None
            result = ((lo is None or (actual >= lo if left == '[' else actual > lo))
                      and (hi is None or (actual <= hi if right == ']' else actual < hi)))
        results.append(result)
        position = match.end()
        if position == len(expression):
            return any(results)
        if expression[position] != ',':
            return None
        position += 1
        while position < len(expression) and expression[position].isspace():
            position += 1
    return None


def check_version(actual, expression, syntax):
    """MATCH/MISMATCH apply only to the supported declared version condition."""
    if not isinstance(expression, str) or len(expression) > 4096:
        return 'UNKNOWN'
    value = numeric(actual, fabric=syntax == 'fabric')
    if value is None:
        return 'UNKNOWN'
    result = _fabric(value, expression) if syntax == 'fabric' else _maven(value, expression) if syntax == 'maven' else None
    return 'UNKNOWN' if result is None else 'MATCH' if result else 'MISMATCH'
