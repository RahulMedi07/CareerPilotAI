"""Root-level pytest configuration.

The scripts at ``backend/`` root -- ``test_complete_workflow.py``,
``test_week1.py``, ``test_api.py`` -- are demos and smoke checks, not unit tests.
They start real services, load the real model and print reports; they are meant
to be run directly with ``python``.

Two reasons they are excluded from collection:

1. ``test_complete_workflow.py`` shares a basename with
   ``tests/test_complete_workflow.py``. With no ``__init__.py`` in ``tests/``,
   pytest identifies modules by basename, so collecting both raises
   ``import file mismatch`` and aborts the run -- ``pytest .`` collected *zero*
   tests before this file existed.
2. Even without the clash, they are slow and have side effects. A test run
   should not open a socket or download a model.

``pytest.ini`` sets ``testpaths = tests``, so a bare ``pytest`` never saw these
anyway. This makes ``pytest .`` and ``pytest backend`` behave the same way.
"""

collect_ignore = [
    "test_complete_workflow.py",
    "test_week1.py",
    "test_api.py",
    "run_test.py",
]
