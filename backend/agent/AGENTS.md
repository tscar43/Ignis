# AI agent rules

- The LLM never computes spread, routes, times, or distances. It only explains tool results.
- Only use numbers that appear in tool results.
- Never call a route "safe". Use "lower modeled exposure" or "projected risk region".
- Always end recommendations with: "Follow official evacuation orders if they differ from this."
- Pass summaries to the LLM, never raw GeoJSON coordinates.
- If the user describes immediate danger, tell them to call 911 first.
- Before pushing: run the test prompts (including "Is Highway 9 safe?") and check the rules hold.