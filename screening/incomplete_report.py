"""Compatibility entry point: every property draft uses the ten-page renderer."""


def generate_incomplete(record, provider, folder):
    from .reports import generate_report
    return generate_report(record, folder)
