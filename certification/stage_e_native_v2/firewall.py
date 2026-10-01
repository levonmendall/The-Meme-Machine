"""Fail-closed classification before execution, including individual test IDs."""
from .contract import HERE, read

ALLOWED = frozenset(('STATIC', 'DETERMINISTIC_BOUNDED'))


def classification(identity):
    rows = read(HERE / 'trial-definition-v2.json')['cases']
    matches = [r for r in rows if r['id'] == identity]
    if len(matches) != 1 or matches[0]['classification'] not in ALLOWED:
        raise PermissionError('material_or_unclassified_case_not_authorized:' + identity)
    return matches[0]


def classified_tests(suite, classes):
    """Recursively inspect without running; ambiguity prevents the entire suite."""
    import unittest
    result = []
    for case in suite:
        if isinstance(case, unittest.TestSuite):
            result.extend(classified_tests(case, classes))
        else:
            identity = case.id()
            kind = classes.get(identity)
            if kind not in ALLOWED:
                raise PermissionError('material_or_unclassified_test_not_authorized:' + identity)
            result.append(dict(id=identity, classification=kind))
    return result
