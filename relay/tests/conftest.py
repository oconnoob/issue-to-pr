"""PostgreSQL tests require an explicitly selected, disposable local database."""

import os
from uuid import uuid4

import psycopg
from psycopg import sql
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, quote
import pytest


@pytest.fixture
def postgres_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL tests")
    schema = "test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            parts = urlsplit(url)
            query = dict(parse_qsl(parts.query)) | {"options": f"-c search_path={schema}"}
            yield urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))
        finally:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
