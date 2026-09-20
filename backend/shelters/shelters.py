import json

from ..models import Household, Shelter
from ..routing.roads import DATA_DIR


def find_shelters(household: Household | None = None):
    household = household or Household()
    shelters = [Shelter.model_validate(item) for item in
                json.loads((DATA_DIR / 'shelters.json').read_text(encoding='utf-8'))]
    return [s for s in shelters if s.capacity >= household.occupants
            and (not household.accepts_pets or s.accepts_pets)
            and (not household.wheelchair_accessible or s.accessible)]
