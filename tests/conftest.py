import pytest

from nmb_five.contract_map import ContractMap
from nmb_five.stores import local_stores
from nmb_five.sync import Pipeline


@pytest.fixture
def pipeline():
    return Pipeline(local_stores()).run_all()


@pytest.fixture
def cmap(pipeline):
    m = ContractMap(pipeline.gate, pipeline.stores.vectors, pipeline.stores.embedder)
    m.index_contracts()
    m.index_quarantine(pipeline.quarantine)
    return m
