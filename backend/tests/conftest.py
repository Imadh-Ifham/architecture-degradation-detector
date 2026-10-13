"""Shared pytest configuration for the backend test suite.

Author: Imadh Ifham
Date: 2026-10-13
Description:
    Keeps the fixture repositories out of test collection. The multi-service
    fixture deliberately contains files named like tests (for example
    `services/checkout/tests/test_service.py`) so the inventory can be checked
    against a realistic layout; those files must not be collected or imported
    as part of this suite.
"""

collect_ignore_glob = ["fixtures/*"]
