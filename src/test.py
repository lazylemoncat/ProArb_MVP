from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType, OrderArgs
from py_clob_client.order_builder.constants import BUY
from py_clob_client.exceptions import PolyApiException

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
PRIVATE_KEY = "0xa3fd2f7dcdeff45fe9bc9ef97b28a23ccc357f818f35fa91ac637f9e4e49f76c"
PROXY_FUNDER = "0xD5ADA6ec52b09778c83022549b2121AdC2Cf9981"  # Address that holds your funds

client = ClobClient(
    HOST,  # The CLOB API endpoint
    key=PRIVATE_KEY,  # Your wallet's private key
    chain_id=CHAIN_ID,  # Polygon chain ID (137)
    signature_type=1,  # 1 for email/Magic wallet signatures
    funder=PROXY_FUNDER  # Address that holds your funds
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

