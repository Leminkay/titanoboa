import os

import pytest

import boa
from boa.deployments import DeploymentsDB, set_deployments_db
from boa.network import NetworkEnv
from boa.rpc import to_bytes
from boa.util.abi import Address
from boa.verifiers import Blockscout

# boa.env.anchor() does not work in prod environment
pytestmark = pytest.mark.ignore_isolation

code = """
totalSupply: public(uint256)
balances: HashMap[address, uint256]

@deploy
def __init__(t: uint256):
    self.totalSupply = t
    self.balances[self] = t

@external
def update_total_supply(t: uint16):
    self.totalSupply += convert(t, uint256)

@external
def raise_exception(t: uint256):
    raise "oh no!"
"""

STARTING_SUPPLY = 100


@pytest.fixture(scope="module")
def simple_contract():
    return boa.loads(code, STARTING_SUPPLY)


def test_verify(simple_contract):
    api_key = os.getenv("BLOCKSCOUT_API_KEY")
    blockscout = Blockscout("https://eth-sepolia.blockscout.com", api_key)
    with boa.set_verifier(blockscout):
        result = boa.verify(simple_contract, blockscout)
        result.wait_for_verification()
        assert result.is_verified()


def test_env_type():
    # sanity check
    assert isinstance(boa.env, NetworkEnv)


def test_total_supply(simple_contract):
    assert simple_contract.totalSupply() == STARTING_SUPPLY


@pytest.mark.parametrize("amount", [0, 1, 100])
def test_update_total_supply(simple_contract, amount):
    orig_supply = simple_contract.totalSupply()
    simple_contract.update_total_supply(amount)
    assert simple_contract.totalSupply() == orig_supply + amount


@pytest.mark.parametrize("amount", [0, 1, 100])
def test_raise_exception(simple_contract, amount):
    with boa.reverts("oh no!"):
        simple_contract.raise_exception(amount)


# XXX: probably want to test deployment revert behavior


def test_deployment_db():
    with set_deployments_db(DeploymentsDB(":memory:")) as db:
        arg = 5

        # contract is written to deployments db
        contract = boa.loads(code, arg)

        # test get_deployments()
        deployment = next(db.get_deployments())

        initcode = contract.compiler_data.bytecode + arg.to_bytes(32, "big")

        # sanity check all the fields
        assert deployment.contract_address == contract.address
        assert deployment.contract_name == contract.contract_name
        assert deployment.deployer == boa.env.eoa
        assert deployment.rpc == boa.env._rpc.name
        assert deployment.source_code == contract.deployer.solc_json

        # some sanity checks on tx_dict and rx_dict fields
        assert to_bytes(deployment.tx_dict["data"]) == initcode
        assert deployment.tx_dict["chainId"] == hex(boa.env.get_chain_id())
        assert Address(deployment.receipt_dict["contractAddress"]) == contract.address
