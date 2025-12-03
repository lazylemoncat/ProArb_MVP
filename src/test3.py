from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY
import os
from dotenv import load_dotenv

load_dotenv()

host: str = "https://clob.polymarket.com"
key: str = str(os.getenv("polymarket_secret"))
chain_id: int = 137 #No need to adjust this
POLYMARKET_PROXY_ADDRESS: str = '0xD5ADA6ec52b09778c83022549b2121AdC2Cf9981'

### Initialization of a client using a Polymarket Proxy associated with an Email/Magic account. If you login with your email use this example.
client = ClobClient(host, key=key, chain_id=chain_id, signature_type=2, funder=POLYMARKET_PROXY_ADDRESS)

client.set_api_creds(client.create_or_derive_api_creds()) 

order_args = OrderArgs(
    price=0.01,
    size=5.0,
    side=BUY,
    token_id="66604715064313675033536808011849390570102921362707254216904866359860317631372",
)
signed_order = client.create_order(order_args)

## GTC(Good-Till-Cancelled) Order
resp = client.post_order(signed_order, OrderType.GTC)
print(resp)