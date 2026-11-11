"""Root pytest config. Test fixtures live in tests/conftest.py."""

# Pytest walks the rootdir during collection and stats every entry. Skip local
# secrets files so the suite runs where reading them is denied (agent sandboxes).
collect_ignore_glob = [".env*"]
