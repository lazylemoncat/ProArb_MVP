import os
from typing import Any, Dict

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY
from py_clob_client.exceptions import PolyApiException

import logging
from dotenv import load_dotenv
import requests
from web3 import Web3

load_dotenv()

class SigningError(RuntimeError):
    """Raised when remote signing is misconfigured or rejected."""


logger = logging.getLogger(__name__)


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
    """Send tx_params to the signing service and broadcast the signed tx.

    The signing service enforces strategy rules; this helper handles the
    high-level error semantics described in the signer documentation:
    - 400: logic error (e.g., wrong chainId/value) -> do not retry.
    - 401: auth error -> caller should update SIGNING_TOKEN.
    - 5xx/network: retry up to ``retries`` times.
    """

    if tx_params.get("chainId") != 137:
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


HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
cfg = {
    "polymarket_secret": remote_sign_and_send()
}
PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY") or cfg.get("polymarket_secret")
if not PRIVATE_KEY:
    raise RuntimeError("Missing env/config: POLYMARKET_PRIVATE_KEY or polymarket_secret")
PROXY_FUNDER = (
    os.getenv("POLYMARKET_PROXY_ADDRESS")
    or cfg.get("POLYMARKET_PROXY_ADDRESS")
    or "0x1bD027BCA18bCe3dC541850FB42b789439b36B6D"
)

signer_status = ensure_signing_ready(require_token=False, log=False)
print(f"[signer] {signer_status}")

client = ClobClient(
    HOST,  # The CLOB API endpoint
    key=PRIVATE_KEY,  # Your wallet's private key
    chain_id=CHAIN_ID,  # Polygon chain ID (137)
    signature_type=1,  # 1 for email/Magic wallet signatures
    funder=PROXY_FUNDER,  # Address that holds your funds
)
client.set_api_creds(client.create_or_derive_api_creds())

# mo = MarketOrderArgs(
#     token_id="73598490064107318565005114994104398195344624125668078818829746637727926056405", 
#     amount=1.0, 
#     side=BUY, 
#     order_type=OrderType.FOK
# )  # Get a token ID: https://docs.polymarket.com/developers/gamma-markets-api/get-markets
# signed = client.create_market_order(mo)
# resp = client.post_order(signed, OrderType.FOK)
# print(resp)

try:
    order_args = OrderArgs(
        price=0.01,
        size=5.0,
        side=BUY,
        token_id="73598490064107318565005114994104398195344624125668078818829746637727926056405", #Token ID you want to purchase goes here. 
    )
    signed_order = client.create_order(order_args)

    ## GTC(Good-Till-Cancelled) Order
    resp = client.post_order(signed_order)
    print(resp)
except PolyApiException as e:
    print(f"polyapi exception: {e}")
except Exception as e:
    print(f"something wrong: {e}")

