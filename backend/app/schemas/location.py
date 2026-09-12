from pydantic import BaseModel, ConfigDict


class LocationCreate(BaseModel):
    name: str
    address: str = ""
    latitude: float
    longitude: float
    site_type: str = "site"
    access_notes: str = ""
    operating_hours: dict = {}


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    address: str
    latitude: float
    longitude: float
    site_type: str
    access_notes: str
    operating_hours: dict
