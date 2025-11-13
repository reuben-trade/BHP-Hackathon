from pydantic import BaseModel

# Request models
class ShipResponse(BaseModel):
    location: str
    berths: list
