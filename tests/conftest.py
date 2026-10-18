from pathlib import Path
import pytest
from src.config import load
from src.portfolio import generate

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def config():
    c,_=load(ROOT/'tests/fixtures/config/experiments/experiment.yaml')
    for site in c['sites']['sites']:
        site['recovery']=dict(verified=True,rto_minutes=30.0,rpo_minutes=5.0,scaling_verified=True)
    return c

@pytest.fixture
def app(config):
    return config['applications']['applications'][0]

@pytest.fixture
def portfolio(config):
    return generate(config)
