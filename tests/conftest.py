import pytest

from careeros.correlate.project import ensure_self, project_activities
from careeros.fixtures import demo
from careeros.ingest.importer import import_envelope
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import ConnectorInstance


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        for cid, (stype, ns) in demo.CONNECTORS.items():
            s.add(ConnectorInstance(id=cid, source_type=stype, namespace=ns, is_fixture=True))
        s.commit()
        ensure_self(s, demo.SELF_EMAIL)
        s.commit()
        yield s


@pytest.fixture
def demo_session(session):
    ap = demo.approvals()
    for env in demo.initial_envelopes():
        import_envelope(session, env, ap, now=demo.T0)
    project_activities(session)
    return session
