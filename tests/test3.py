from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, TradeParams
from py_clob_client.order_builder.constants import BUY, SELL
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

trades = client.get_trades(TradeParams(asset_id="88131829552274957112139728426016493105408110485466156054905686742341012893447"))
# trades = client.get_trades()
print(trades)
# trade_size = trades[0]["size"]
# token_id = trades[0]["asset_id"]
# sell_order = client.create_and_post_order(
#     OrderArgs(
#         token_id=token_id,
#         price=0.89,
#         size=float(trade_size),
#         side=SELL,
#     )
# )
# print(sell_order)
# resp = client.cancel_all()
# print(resp)