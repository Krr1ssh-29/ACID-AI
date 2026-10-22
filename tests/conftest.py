"""Global pytest configuration and test session fixtures."""
# Pre-warm third-party libraries so cold import times do not delay individual test calls
try:
    import anthropic  # noqa: F401
except ImportError:
    pass
