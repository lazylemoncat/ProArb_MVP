import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType, OrderArgs
from py_clob_client.order_builder.constants import BUY
from py_clob_client.exceptions import PolyApiException

from src.utils.auth import ensure_signing_ready
from src.utils.dataloader import load_all_configs


HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
cfg = load_all_configs()
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

