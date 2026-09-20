"""The evacuation assistant behind `POST /chat`.

The model talks; it never decides. Every route, time, distance and shelter in
an answer comes back from the same `/plan` the map calls, through the tool
below -- so the assistant cannot invent one, and cannot route around an
evacuation order the deterministic path would refuse.
"""

import json

import anthropic
from anthropic import beta_tool
from fastapi import HTTPException, Response

from ..fire.firms import env_value
from ..models import Household, Origin, PlanRequest

MODEL = 'claude-opus-5'
# A household waiting to evacuate is not the place for a long think. Routing,
# hazards and orders are all decided deterministically before the model sees
# them; its job is to explain the result, which low effort does well and fast.
EFFORT = 'low'
# An answer to a frightened person should be a few sentences. 1000 tokens is
# roughly three times the longest useful reply, so it caps runaway cost without
# ever truncating a real one.
MAX_TOKENS = 1000
# Resent in full every turn, so this bounds the worst case rather than the
# typical one -- a demo conversation is five or six turns.
HISTORY = 20

SYSTEM = """You are the evacuation assistant for Ignis, an experimental wildfire
decision-support demo. You are talking to a household that may be deciding
whether and how to leave.

How you work:

- You have one tool, `plan_evacuation`. It runs the real routing engine over a
  real road network with the modelled fire regions and any evacuation orders
  applied. Call it once you know where they are and who is with them.
- Every route, travel time, distance, shelter name and exposure figure you state
  MUST come from a `plan_evacuation` result in this conversation. Never estimate,
  interpolate, round differently, or describe a road the tool did not return.
  If you have not called the tool, you do not have a route.
- Always repeat the `warnings` from the result. They are not boilerplate: they
  say what the model does not account for.
- If the tool returns an error, say plainly what failed and that you have no
  route. Do not offer a guessed alternative. "The model cannot find a way out"
  is a real and important answer -- give it, and tell them to follow official
  instructions and call 911 if they are in immediate danger.

What you need before calling the tool: their location (address or coordinates)
and the number of people. Ask for a vehicle, pets, wheelchair access and whether
anyone has a respiratory condition -- each one changes which shelters and roads
are eligible. Ask for what is missing in one short question at a time; do not
interrogate. If they are in danger right now, tell them to call 911 first.

Tone: brief, calm, concrete. Short paragraphs, no bullet-point walls, no
reassurance you cannot back up. This is a demonstration built on modelled and
historical data -- say so if they seem to be treating it as an official source.
Official evacuation orders always win over anything you say."""


def _client():
    """Fail loudly and early rather than at the first token.

    Read through `env_value` so the key can live in the repo's .env beside the
    FIRMS one, which is where anyone running this locally will put it.
    """
    key = env_value('ANTHROPIC_API_KEY')
    if not key or key == 'your_key_here':
        raise HTTPException(503, 'Chat is unavailable: no Anthropic credentials are '
                                 'configured on the server. Set ANTHROPIC_API_KEY.')
    return anthropic.Anthropic(api_key=key)


def conversation(messages):
    """Validate the client turns before they reach a model prompt.

    A trust boundary: these arrive from the browser, so the shape is checked
    rather than assumed.
    """
    clean = []
    for turn in messages:
        role, content = turn.get('role'), (turn.get('content') or '').strip()
        if role not in ('user', 'assistant'):
            raise HTTPException(422, "Each message needs a role of 'user' or 'assistant'")
        if not content:
            raise HTTPException(422, 'Each message needs non-empty content')
        if len(content) > 4000:
            raise HTTPException(422, 'Message is too long; keep it under 4000 characters')
        clean.append({'role': role, 'content': content})
    # Oldest turns drop first; the last one must still be the user's.
    clean = clean[-HISTORY:]
    if not clean or clean[0]['role'] != 'user' or clean[-1]['role'] != 'user':
        raise HTTPException(422, 'The conversation must start and end with a user message')
    return clean


def reply(request, planner):
    """Answer the conversation, planning a route through `planner` if asked.

    `planner` is the `/plan` endpoint function itself, so the chat inherits
    every gate it has -- live staleness, the bbox check, the 503/422 mapping --
    instead of a second copy that drifts from it.
    """
    client = _client()
    plans = []

    @beta_tool
    def plan_evacuation(lat: float, lon: float, occupants: int = 1,
                        has_vehicle: bool = True, accepts_pets: bool = False,
                        wheelchair_accessible: bool = False,
                        respiratory_sensitive: bool = False) -> str:
        """Plan an evacuation route from the household's location to a shelter.

        Runs the routing engine over the real road network with the current
        modelled fire regions and any evacuation orders applied. Returns the
        routes, the destination, and warnings that must be passed on to the
        household. Call this before stating any route, time or distance.

        Args:
            lat: Latitude of the household, in decimal degrees (WGS84).
            lon: Longitude of the household, in decimal degrees (WGS84).
            occupants: How many people are evacuating together.
            has_vehicle: Whether the household has a vehicle. Only driving is modelled.
            accepts_pets: True if the destination must accept pets.
            wheelchair_accessible: True if the destination must be wheelchair accessible.
            respiratory_sensitive: True if anyone has a respiratory condition, is
                pregnant, or is an infant. Prefers routes out of the modelled
                downwind smoke plume; never overrides an evacuation order.
        """
        try:
            plan = planner(PlanRequest(
                origin=Origin(lat=lat, lon=lon),
                household=Household(occupants=occupants, has_vehicle=has_vehicle,
                                    accepts_pets=accepts_pets,
                                    wheelchair_accessible=wheelchair_accessible,
                                    respiratory_sensitive=respiratory_sensitive),
                mode=request.mode), Response())
        except HTTPException as exc:
            # Handed to the model as a result, not raised: a refusal to route is
            # something the household needs explained, not a 500.
            return json.dumps({'error': exc.detail, 'status': exc.status_code,
                               'routes': []})
        plans.append(plan)
        # The model is given the plan without route geometry. 185 coordinate
        # pairs is ~77% of the payload and none of it is readable -- it cannot
        # say anything about a polyline that `named_roads` does not already
        # say, and every token of it is resent on each later turn. The full
        # geometry still goes to the caller for the map to draw.
        summary = plan.model_dump(exclude={'routes': {'__all__': {'geometry'}}})
        return json.dumps(summary, default=str)

    try:
        message = client.beta.messages.tool_runner(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            output_config={'effort': EFFORT},
            tools=[plan_evacuation], messages=conversation(request.messages),
        ).until_done()
    except anthropic.AuthenticationError as exc:
        raise HTTPException(503, "Chat is unavailable: the server's Anthropic "
                                 'credentials were rejected') from exc
    except anthropic.RateLimitError as exc:
        raise HTTPException(503, 'Chat is rate limited right now; try again shortly') from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(503, 'Chat is unavailable: cannot reach the model') from exc
    except anthropic.APIStatusError as exc:
        raise HTTPException(503, f'Chat is unavailable: model error {exc.status_code}') from exc

    if message.stop_reason == 'refusal':
        raise HTTPException(422, 'The assistant declined to answer that.')
    text = '\n\n'.join(block.text for block in message.content if block.type == 'text').strip()
    if not text:
        raise HTTPException(503, 'The assistant returned no answer; please retry.')
    # The last plan, so the map can draw exactly the route being talked about.
    return {'reply': text, 'plan': plans[-1] if plans else None}
