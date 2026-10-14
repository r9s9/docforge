"""The Postgres driver must not depend on which SQLAlchemy version got installed.

SQLAlchemy 2.1 changed the driver a bare postgresql:// URL selects (psycopg2 ->
psycopg 3). The deployment installs psycopg2-binary, so a fresh build pulling
2.1 crashed on import and took every request down with it.
"""

from docforge.db.session import database_url_with_driver


def test_a_bare_postgres_url_names_psycopg2():
    url = "postgresql://user:pw@host:6543/postgres"
    assert database_url_with_driver(url) == "postgresql+psycopg2://user:pw@host:6543/postgres"


def test_the_heroku_style_scheme_is_accepted():
    assert database_url_with_driver("postgres://u@h/db") == "postgresql+psycopg2://u@h/db"


def test_an_explicit_driver_and_sqlite_are_left_alone():
    assert database_url_with_driver("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert database_url_with_driver("sqlite:///./data/docforge.db") == "sqlite:///./data/docforge.db"
