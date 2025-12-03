from __future__ import annotations

import logging
import os
from typing import Any, Dict

import requests
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY
from py_clob_client.exceptions import PolyApiException
from web3 import Web3

load_dotenv()

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
DEFAULT_PROXY_FUNDER = "0x1bD027BCA18bCe3dC541850FB42b789439b36B6D"
DEFAULT_TOKEN_ID = "73598490064107318565005114994104398195344624125668078818829746637727926056405"
DEFAULT_PRICE = 0.01
DEFAULT_SIZE = 5.0

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

class SigningError(RuntimeError):
    """Raised when remote signing is misconfigured or rejected."""


def get_signer_url() -> str:
    return os.getenv("SIGNER_URL", "")


def get_signing_token(*, required: bool = True) -> str | None:
    token = os.getenv("SIGNING_TOKEN")
    if required and not token:
        raise SigningError("SIGNING_TOKEN is required for remote signing")
    return token


def ensure_signing_ready(*, require_token: bool = True, log: bool = True) -> str:
    """Validate signer env and return a human readable status string."""

    signer_url = get_signer_url()
    token = get_signing_token(required=require_token)
    status = f"signer_url={signer_url}; token={'set' if token else 'missing'}"
    if log:
        logger.info("remote signer config: %s", status)
    return status


def remote_sign_and_send(w3: Web3, tx_params: Dict[str, Any], *, retries: int = 2, timeout: float = 3.0) -> str:
    """Send tx_params to the signing service and broadcast the signed tx."""

    if tx_params.get("chainId") != CHAIN_ID:
        raise SigningError("chainId must be 137 for Polygon mainnet")
    if int(tx_params.get("value", 0)) != 0:
        raise SigningError("value must be 0 for the current signing strategy")

    signer_url = get_signer_url()
    headers = {"Authorization": f"Bearer {get_signing_token()}"}

    attempt = 0
    last_error: Exception | None = None
    while attempt <= retries:
        attempt += 1
        try:
            resp = requests.post(signer_url, json=tx_params, headers=headers, timeout=timeout)
            if resp.status_code == 400:
                raise SigningError(f"signer rejected tx (400): {resp.text}")
            if resp.status_code == 401:
                raise SigningError("signer auth failed; check SIGNING_TOKEN")
            resp.raise_for_status()
            data = resp.json()
            raw = str(data["raw"])
            raw_bytes = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
            tx_hash = w3.eth.send_raw_transaction(raw_bytes)
            return tx_hash.hex()
        except requests.RequestException as exc:  # network / 5xx
            last_error = exc
            if attempt > retries:
                break
            logger.warning("signer request failed (attempt %s/%s): %s", attempt, retries, exc)
            continue
    raise SigningError(f"failed to reach signer after {retries + 1} attempts: {last_error}")


def build_client() -> ClobClient:
    """Create a configured ``ClobClient`` using environment defaults."""

    # Use remote signing to get the private key
    w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))  # Ensure Web3 is connected
    from_addr = "0x1bD027BCA18bCe3dC541850FB42b789439b36B6D"

    # Define contract ABI for the setPrice function (example)
    contract_abi = [
        {
            "constant": False,
            "inputs": [
                {"name": "price", "type": "uint256"}
            ],
            "name": "setPrice",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]

    # Get contract instance
    contract_address = "0x91430CaD2d3975766499717fA0D66A78D814E5c5"  # Polymarket contract address
    contract = w3.eth.contract(address=contract_address, abi=contract_abi)

    # Example parameter for setPrice function
    price = 1000

    # Encode calldata for the setPrice function using the contract's functions
    # Correct way to get calldata with web3.py
    encoded_data = contract.encodeABI(fn_name="setPrice", args=[price])

    # Get nonce and create transaction parameters
    nonce = w3.eth.get_transaction_count(from_addr, "pending")
    tx_params = {
        "nonce": nonce,
        "gas": 250000,
        "gasPrice": w3.to_wei("30", "gwei"),
        "to": contract_address,
        "value": 0,
        "data": encoded_data,  # Use the encoded calldata here
        "chainId": CHAIN_ID,
    }

    # Use remote signing to sign the transaction and get the transaction hash
    signed_tx_hash = remote_sign_and_send(w3, tx_params)
    logger.info(f"Signed transaction hash: {signed_tx_hash}")

    private_key = signed_tx_hash  # In practice, you'd get the private key from the remote signing service

    proxy_funder = os.getenv("POLYMARKET_PROXY_ADDRESS") or DEFAULT_PROXY_FUNDER

    signer_status = ensure_signing_ready(require_token=False, log=False)

    client = ClobClient(
        HOST,
        key=private_key,  # Now using the signed transaction as the key
        chain_id=CHAIN_ID,
        signature_type=1,
        funder=proxy_funder,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def place_gtc_order(client: ClobClient, token_id: str, price: float, size: float) -> dict[str, Any]:
    """Create and post a Good-Till-Cancelled order."""

    order_args = OrderArgs(price=price, size=size, side=BUY, token_id=token_id)
    signed_order = client.create_order(order_args)
    return client.post_order(signed_order)


def main() -> None:
    token_id = os.getenv("POLYMARKET_TEST_TOKEN_ID", DEFAULT_TOKEN_ID)
    price = float(os.getenv("POLYMARKET_TEST_PRICE", str(DEFAULT_PRICE)))
    size = float(os.getenv("POLYMARKET_TEST_SIZE", str(DEFAULT_SIZE)))

    client = build_client()
    logger.info("Attempting order: token_id=%s price=%s size=%s", token_id, price, size)

    try:
        response = place_gtc_order(client, token_id=token_id, price=price, size=size)
        print(response)
    except PolyApiException as exc:
        logger.error("polyapi exception: %s", exc)
    except Exception as exc:  # noqa: BLE001 - top-level testing script
        logger.error("something wrong: %s", exc)


if __name__ == "__main__":
    main()
